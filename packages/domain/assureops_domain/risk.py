"""Risk acceptance: a reviewed, expiring, release-bound exception that never rewrites a failed result.

Rules:
- Only a control that is failed on the exact latest release can be proposed.
- Critical failures and controls with a verified runtime violation are never acceptable.
- The application's reviewed profile decides the highest acceptable severity
  (`gate_policy.risk_acceptance.max_severity`); without it, acceptances are recorded
  but never change the gate.
- A different person (owner or reviewer) approves; the requester cannot.
- Acceptances expire (at most 90 days) and stop applying when a newer release exists.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Finding, RiskAcceptance, now
from .profile import SEVERITY_RANK

MAX_DAYS = 90


class RiskError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def allowed_severity(p: dict) -> str | None:
    return ((p.get("gate_policy") or {}).get("risk_acceptance") or {}).get("max_severity")


def eligible(control: dict, p: dict) -> tuple[bool, str]:
    severity = control.get("failure_severity")
    if control.get("result") != "failed":
        return False, "only a failed control can be accepted as a risk"
    if severity == "critical":
        return False, "critical failures always block; they cannot be accepted as a risk"
    if control.get("runtime_violation"):
        return False, "a verified runtime violation exists for this control; close the incident first"
    limit = allowed_severity(p)
    if limit is None:
        return False, "this application's profile does not permit risk acceptance"
    if SEVERITY_RANK.get(severity or "low", 1) > SEVERITY_RANK[limit]:
        return False, f"the profile permits risk acceptance up to {limit} severity; this failure is {severity}"
    return True, ""


def propose(s: Session, *, application_id: str, workspace_id: str, release, control: dict, reason: str, compensating: str,
            days: int, actor: str) -> RiskAcceptance:
    if not 1 <= days <= MAX_DAYS:
        raise RiskError("invalid_expiry", f"acceptance must expire within 1 to {MAX_DAYS} days")
    if control.get("result") != "failed":
        raise RiskError("not_failed", "only a failed control can be accepted as a risk")
    if control.get("failure_severity") == "critical":
        raise RiskError("not_acceptable", "critical failures always block; they cannot be accepted as a risk")
    if control.get("runtime_violation"):
        raise RiskError("not_acceptable", "a verified runtime violation exists for this control; close the incident first")
    row = RiskAcceptance(workspace_id=workspace_id, application_id=application_id, release_id=release.id, control_id=control["id"],
                         severity=control.get("failure_severity") or "low", reason=reason, compensating_controls=compensating,
                         requested_by=actor, expires_at=now() + days * 86400)
    s.add(row)
    s.flush()
    return row


def decide(s: Session, row: RiskAcceptance, *, approve: bool, actor: str, note: str) -> RiskAcceptance:
    if row.status != "proposed":
        raise RiskError("already_decided", f"this acceptance is {row.status}")
    if actor == row.requested_by:
        raise RiskError("separation_of_duties", "the person who requested a risk acceptance cannot approve it")
    if row.expires_at <= now():
        raise RiskError("expired", "this proposal expired; propose it again")
    row.status, row.decided_by, row.decision_note, row.decided_at = ("active" if approve else "rejected"), actor, note, now()
    return row


def revoke(row: RiskAcceptance, *, actor: str) -> RiskAcceptance:
    if row.status in ("active", "proposed"):
        row.status, row.revoked_by, row.revoked_at = "revoked", actor, now()
    return row


def active_for(s: Session, application_id: str, release_id: str) -> dict[str, RiskAcceptance]:
    rows = s.scalars(select(RiskAcceptance).where(RiskAcceptance.application_id == application_id, RiskAcceptance.release_id == release_id,
                                                  RiskAcceptance.status == "active", RiskAcceptance.expires_at > now())).all()
    return {r.control_id: r for r in rows}


def finding_ids(s: Session, application_id: str, control_id: str) -> list[str]:
    return [f.id for f in s.scalars(select(Finding).where(Finding.application_id == application_id, Finding.control_id == control_id,
                                                          Finding.state != "resolved"))]


def to_json(r: RiskAcceptance) -> dict:
    state = "expired" if r.status == "active" and r.expires_at <= now() else r.status
    return {"id": r.id, "application_id": r.application_id, "release_id": r.release_id, "control_id": r.control_id, "severity": r.severity,
            "reason": r.reason, "compensating_controls": r.compensating_controls, "status": state, "requested_by": r.requested_by,
            "decided_by": r.decided_by, "decision_note": r.decision_note, "expires_at": r.expires_at, "created_at": r.created_at,
            "decided_at": r.decided_at, "revoked_by": r.revoked_by, "revoked_at": r.revoked_at}
