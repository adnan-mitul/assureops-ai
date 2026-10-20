"""Route selection per phase and workspace. Fixed preference, no silent fallback.

Private serving is used when configured and qualified. Groq is used only for
phases approved for it, when the workspace allows external processing and the
pinned model is qualified. A failing private route never turns into an
external call: unavailability is reported as such.
"""

import os
import re
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
    small_named = re.search(r"-(\d+)m$", model)  # sub-billion models such as llama-prompt-guard-2-86m
    return fits_constraint(model, limit) or bool(small_named) or (bool(exception) and exception == model)


def groq_model(phase_id: str) -> str:
    return settings().groq_model_f if phase_id == "F" and settings().groq_model_f else env(f"GROQ_MODEL_{phase_id}")


def resolve(phase_id: str, external_allowed: bool) -> Route:
    """Qualified private route first; an approved external route only for workspaces that allow it.

    Choosing a provider happens here, from qualification and policy. A private route that is qualified but down
    at call time fails as unavailable; it is never swapped for an external call.
    """
    phase = PHASES[phase_id]
    cfg = settings()
    url_key = {"generate": "PRIVATE_INFERENCE_URL", "embed": "PRIVATE_EMBED_URL", "classify": "PRIVATE_CLASSIFY_URL"}[phase.kind]
    private_url, model = env(url_key), private_model(phase_id)
    private = None
    if private_url and model:
        q = qualification(phase_id, "private", model)
        if q and q["status"] == "qualified" and q["prompt_version"] == phase.prompt_version and q["schema_version"] == phase.schema_version:
            return Route(phase_id, "private", model, True, "private route qualified", qualification=q)
        private = Route(phase_id, "private", model, False,
                        "not_qualified: private model failed or lacks a current qualification record" if q else
                        "not_qualified: private model has no qualification record", qualification=q)
    if "groq" in phase.external_approved:
        gm = groq_model(phase_id)
        external = None
        if not cfg.groq_enabled:
            external = Route(phase_id, "groq", gm or None, False, "provider_disabled: GROQ_ENABLED is false", external=True)
        elif not cfg.groq_api_key:
            external = Route(phase_id, "groq", gm or None, False, "key_missing: no server-side GROQ_API_KEY", external=True)
        elif not gm:
            external = Route(phase_id, "groq", None, False, f"model_not_pinned: GROQ_MODEL_{phase_id} is empty", external=True)
        elif not groq_size_ok(gm):
            external = Route(phase_id, "groq", gm, False, "constraint_exceeded: pinned model is larger than the project's model-size "
                                                         "constraint and no operator exception is recorded", external=True)
        elif not external_allowed:
            external = Route(phase_id, "groq", gm, False, "external_processing_not_allowed: workspace is private-only", external=True)
        else:
            q = qualification(phase_id, "groq", gm)
            if q and q["status"] == "qualified" and q["prompt_version"] == phase.prompt_version:
                return Route(phase_id, "groq", gm, True, "groq route qualified", external=True, qualification=q)
            external = Route(phase_id, "groq", gm, False, "not_qualified: run the phase qualification suite first", external=True, qualification=q)
        return private if private is not None else external
    if private is not None:
        return private
    return Route(phase_id, None, None, False, f"no_route_configured: set {url_key} and PRIVATE_MODEL_{phase_id} on the inference host")


def generation_client(route: Route):
    cfg = settings()
    if route.provider == "groq":
        return GroqProvider(cfg.groq_base_url, cfg.groq_api_key, timeout=cfg.groq_timeout_seconds)
    # CPU inference hosts are slow: generous timeout, no retry storms (one active request per instance).
    return PrivateGeneration(env("PRIVATE_INFERENCE_URL"), env("PRIVATE_INFERENCE_KEY") or None, timeout=float(env("PRIVATE_TIMEOUT_SECONDS", "600")),
                             max_retries=1)


def encoder_client(route: Route):
    phase = PHASES[route.phase]
    if route.provider == "groq":
        cfg = settings()
        return GroqProvider(cfg.groq_base_url, cfg.groq_api_key, timeout=cfg.groq_timeout_seconds)
    return PrivateEncoder(env("PRIVATE_EMBED_URL" if phase.kind == "embed" else "PRIVATE_CLASSIFY_URL"), timeout=120)
