"""Model route lifecycle: development -> holdout -> shadow -> canary -> active, with one-step rollback.

- holdout -> shadow (or -> canary for external routes, which never shadow customer data)
  needs a current qualification record for the exact provider, model, prompt and schema.
- shadow -> canary needs SHADOW_MIN_RUNS shadow runs with a valid-output rate of at least MIN_VALID_RATE.
- canary -> active needs CANARY_MIN_RUNS canary runs, no invalid output, the same valid rate,
  and a different person than the one who started the canary.
- Activation retires the previous active route and remembers it; rollback restores it in one step.
- Shadow results are never reviewable or shown to customers; canary results are ordinary
  proposals and still go through review. A stage never lets a model decide an outcome.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from assureops_domain.models import ModelQualification, ModelRouteEvent, ModelRouteStage, now

from .registry import PHASES, QUICK_STATUS

STAGES = ("development", "holdout", "shadow", "canary", "active", "retired", "rolled_back")
SHADOW_MIN_RUNS = 5
CANARY_MIN_RUNS = 5
MIN_VALID_RATE = 0.75
NEXT = {"development": {"holdout", "retired"}, "holdout": {"shadow", "canary", "retired"}, "shadow": {"canary", "retired"},
        "canary": {"active", "retired"}, "retired": {"development"}, "rolled_back": {"development", "retired"}}


class LifecycleError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def current_qualification(s: Session, row: ModelRouteStage) -> ModelQualification | None:
    phase = PHASES[row.phase]
    q = s.scalars(select(ModelQualification).where(ModelQualification.phase == row.phase, ModelQualification.provider == row.provider,
                                                    ModelQualification.model == row.model, ModelQualification.status != QUICK_STATUS)
                  .order_by(ModelQualification.created_at.desc())).first()
    if q and q.status == "qualified" and q.prompt_version == phase.prompt_version and q.schema_version == phase.schema_version:
        return q
    return None


def register(s: Session, *, phase: str, provider: str, model: str, actor: str) -> ModelRouteStage:
    if phase not in PHASES:
        raise LifecycleError("invalid_route", f"unknown phase {phase}")
    if provider not in ("private", "groq") or (provider == "groq" and "groq" not in PHASES[phase].external_approved):
        raise LifecycleError("invalid_route", f"provider {provider} is not approved for phase {phase}")
    row = s.scalars(select(ModelRouteStage).where(ModelRouteStage.phase == phase, ModelRouteStage.provider == provider,
                                                  ModelRouteStage.model == model)).first()
    if row is not None:
        raise LifecycleError("exists", f"route already registered at stage {row.stage}")
    row = ModelRouteStage(phase=phase, provider=provider, model=model, stage="development", changed_by=actor)
    s.add(row)
    s.flush()
    s.add(ModelRouteEvent(route_id=row.id, from_stage=None, to_stage="development", actor=actor, note="registered"))
    return row


def _rate(valid: int, runs: int) -> float:
    return valid / runs if runs else 0.0


def transition(s: Session, row: ModelRouteStage, *, to: str, actor: str, note: str) -> ModelRouteStage:
    if to not in NEXT.get(row.stage, set()):
        raise LifecycleError("invalid_transition", f"{row.stage} cannot move to {to}")
    if to in ("shadow", "canary") and row.stage == "holdout":
        q = current_qualification(s, row)
        if q is None:
            raise LifecycleError("not_qualified", "record a current qualification for this exact model, prompt and schema first")
        if to == "shadow" and row.provider != "private":
            raise LifecycleError("no_external_shadow", "external routes never shadow customer data; go to canary for consenting workspaces")
        row.qualification_id = q.id
    if to == "canary" and row.stage == "shadow":
        if row.shadow_runs < SHADOW_MIN_RUNS or _rate(row.shadow_valid, row.shadow_runs) < MIN_VALID_RATE:
            raise LifecycleError("insufficient_evidence", f"needs {SHADOW_MIN_RUNS} shadow runs with valid rate >= {MIN_VALID_RATE} "
                                                          f"(have {row.shadow_valid}/{row.shadow_runs})")
    if to == "active":
        last_canary = s.scalars(select(ModelRouteEvent).where(ModelRouteEvent.route_id == row.id, ModelRouteEvent.to_stage == "canary")
                                .order_by(ModelRouteEvent.at.desc())).first()
        if last_canary and last_canary.actor == actor:
            raise LifecycleError("separation_of_duties", "the person who started the canary cannot activate it")
        if row.canary_runs < CANARY_MIN_RUNS or row.canary_invalid or _rate(row.canary_valid, row.canary_runs) < MIN_VALID_RATE:
            raise LifecycleError("insufficient_evidence", f"needs {CANARY_MIN_RUNS} canary runs, no invalid output and valid rate >= "
                                                          f"{MIN_VALID_RATE} (have {row.canary_valid}/{row.canary_runs}, {row.canary_invalid} invalid)")
        if current_qualification(s, row) is None:
            raise LifecycleError("not_qualified", "the qualification is no longer current for this prompt and schema")
        previous = active_route(s, row.phase)
        if previous is not None:
            _move(s, previous, "retired", actor, f"replaced by {row.provider}:{row.model}")
            row.replaces_id = previous.id
    if to == "canary":
        row.canary_runs = row.canary_valid = row.canary_invalid = 0
    if to == "shadow":
        row.shadow_runs = row.shadow_valid = 0
    return _move(s, row, to, actor, note)


def _move(s: Session, row: ModelRouteStage, to: str, actor: str, note: str) -> ModelRouteStage:
    s.add(ModelRouteEvent(route_id=row.id, from_stage=row.stage, to_stage=to, actor=actor, note=note))
    row.stage, row.changed_by, row.changed_at = to, actor, now()
    return row


def rollback(s: Session, phase: str, *, actor: str, note: str) -> dict:
    """One step back: the active route is rolled back and the route it replaced becomes active again (or the phase is unmanaged)."""
    current = active_route(s, phase)
    if current is None:
        raise LifecycleError("nothing_active", "no managed active route for this phase")
    _move(s, current, "rolled_back", actor, note)
    restored = s.get(ModelRouteStage, current.replaces_id) if current.replaces_id else None
    if restored is not None:
        _move(s, restored, "active", actor, f"restored by rollback of {current.provider}:{current.model}")
    return {"rolled_back": current.id, "restored": restored.id if restored else None}


def active_route(s: Session, phase: str) -> ModelRouteStage | None:
    return s.scalars(select(ModelRouteStage).where(ModelRouteStage.phase == phase, ModelRouteStage.stage == "active")).first()


def stage_route(s: Session, phase: str, stage: str) -> ModelRouteStage | None:
    return s.scalars(select(ModelRouteStage).where(ModelRouteStage.phase == phase, ModelRouteStage.stage == stage)
                     .order_by(ModelRouteStage.changed_at.desc())).first()


def record_outcome(s: Session, route_id: str, stage: str, valid: bool, invalid: bool):
    row = s.get(ModelRouteStage, route_id)
    if row is None or row.stage != stage:
        return
    if stage == "shadow":
        row.shadow_runs += 1
        row.shadow_valid += int(valid)
    elif stage == "canary":
        row.canary_runs += 1
        row.canary_valid += int(valid)
        row.canary_invalid += int(invalid)


def to_json(row: ModelRouteStage, events: list[ModelRouteEvent] | None = None) -> dict:
    return {"id": row.id, "phase": row.phase, "provider": row.provider, "model": row.model, "stage": row.stage,
            "canary_percent": row.canary_percent, "qualification_id": row.qualification_id, "replaces_id": row.replaces_id,
            "shadow": {"runs": row.shadow_runs, "valid": row.shadow_valid}, "changed_by": row.changed_by, "changed_at": row.changed_at,
            "canary": {"runs": row.canary_runs, "valid": row.canary_valid, "invalid": row.canary_invalid},
            "history": [{"from": e.from_stage, "to": e.to_stage, "actor": e.actor, "note": e.note, "at": e.at} for e in (events or [])]}
