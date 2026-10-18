"""Route selection per phase and workspace. Fixed preference, no silent fallback.

Private serving is used when configured and qualified. Groq is used only for
phases approved for it, when the workspace allows external processing and the
pinned model is qualified. A failing private route never turns into an
external call: unavailability is reported as such.
"""

import os
from dataclasses import dataclass

from sqlalchemy import select

from assureops_domain.config import _dev_env, settings
from assureops_domain.db import platform_session
from assureops_domain.models import ModelQualification

from .providers.groq import GroqProvider, fits_constraint
from .providers.private import PrivateEncoder, PrivateGeneration
from .registry import PHASES


def env(name: str, default: str = "") -> str:
    return os.environ.get(name) or _dev_env().get(name) or default


@dataclass
class Route:
    phase: str
    provider: str | None
    model: str | None
    available: bool
    reason: str
    external: bool = False
    qualification: dict | None = None


def private_model(phase: str) -> str:
    return env(f"PRIVATE_MODEL_{phase}")


def qualification(phase: str, provider: str, model: str) -> dict | None:
    with platform_session() as s:
        row = s.scalars(select(ModelQualification).where(ModelQualification.phase == phase, ModelQualification.provider == provider,
                                                         ModelQualification.model == model).order_by(ModelQualification.created_at.desc())).first()
        if row is None:
            return None
        return {"id": row.id, "status": row.status, "dataset": row.dataset, "metrics": row.metrics, "prompt_version": row.prompt_version,
                "schema_version": row.schema_version, "at": row.created_at}


def groq_size_ok(model: str) -> bool:
    limit = float(env("GROQ_MAX_PARAMS_B", "3.8"))
    exception = env("GROQ_SIZE_EXCEPTION_MODEL")  # explicit operator decision, recorded with the qualification
    return fits_constraint(model, limit) or (exception and exception == model)


def resolve(phase_id: str, external_allowed: bool) -> Route:
    phase = PHASES[phase_id]
    cfg = settings()
    url_key = {"generate": "PRIVATE_INFERENCE_URL", "embed": "PRIVATE_EMBED_URL", "classify": "PRIVATE_CLASSIFY_URL"}[phase.kind]
    private_url, model = env(url_key), private_model(phase_id)
    if private_url and model:
        q = qualification(phase_id, "private", model)
        if q and q["status"] == "qualified" and q["prompt_version"] == phase.prompt_version and q["schema_version"] == phase.schema_version:
            return Route(phase_id, "private", model, True, "private route qualified", qualification=q)
        return Route(phase_id, "private", model, False, "not_qualified: private model has no current qualification record", qualification=q)
    if "groq" in phase.external_approved:
        if not cfg.groq_enabled:
            return Route(phase_id, "groq", cfg.groq_model_f or None, False, "provider_disabled: GROQ_ENABLED is false", external=True)
        if not cfg.groq_api_key:
            return Route(phase_id, "groq", cfg.groq_model_f or None, False, "key_missing: no server-side GROQ_API_KEY", external=True)
        if not cfg.groq_model_f:
            return Route(phase_id, "groq", None, False, "model_not_pinned: GROQ_MODEL_F is empty", external=True)
        if not groq_size_ok(cfg.groq_model_f):
            return Route(phase_id, "groq", cfg.groq_model_f, False, "constraint_exceeded: pinned model is larger than the project's model-size "
                                                                   "constraint and no operator exception is recorded", external=True)
        if not external_allowed:
            return Route(phase_id, "groq", cfg.groq_model_f, False, "external_processing_not_allowed: workspace is private-only", external=True)
        q = qualification(phase_id, "groq", cfg.groq_model_f)
        if not (q and q["status"] == "qualified" and q["prompt_version"] == phase.prompt_version):
            return Route(phase_id, "groq", cfg.groq_model_f, False, "not_qualified: run the phase qualification suite first", external=True, qualification=q)
        return Route(phase_id, "groq", cfg.groq_model_f, True, "groq route qualified", external=True, qualification=q)
    return Route(phase_id, None, None, False, f"no_route_configured: set {url_key} and PRIVATE_MODEL_{phase_id} on the inference host")


def generation_client(route: Route):
    cfg = settings()
    if route.provider == "groq":
        return GroqProvider(cfg.groq_base_url, cfg.groq_api_key, timeout=cfg.groq_timeout_seconds)
    return PrivateGeneration(env("PRIVATE_INFERENCE_URL"), env("PRIVATE_INFERENCE_KEY") or None, timeout=60)


def encoder_client(route: Route):
    phase = PHASES[route.phase]
    return PrivateEncoder(env("PRIVATE_EMBED_URL" if phase.kind == "embed" else "PRIVATE_CLASSIFY_URL"))
