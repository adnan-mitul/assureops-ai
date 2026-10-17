"""Two-way assessment case workflow (plan §33.5), separate from job and control states."""

from sqlalchemy.orm import Session

from .models import Application, AssessmentCase, AuditEvent, CaseIndex, Workspace, now

TRANSITIONS = {
    "draft": {"submitted"},
    "submitted": {"triage"},
    "triage": {"assessment"},
    "assessment": {"awaiting_customer", "awaiting_review"},
    "awaiting_customer": {"assessment"},
    "awaiting_review": {"assessment", "published"},
    "published": {"monitoring"},
    "monitoring": {"reassessment"},
    "reassessment": {"assessment", "awaiting_customer", "awaiting_review"},
}


class CaseError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def transition(session: Session, case: AssessmentCase, to_state: str, *, expected_revision: int | None = None):
    if expected_revision is not None and case.revision != expected_revision:
        raise CaseError("stale_revision", "case changed since you loaded it; reload and try again")
    if to_state == case.state:
        return
    if to_state not in TRANSITIONS.get(case.state, set()):
        raise CaseError("invalid_transition", f"case cannot move from {case.state} to {to_state}")
    case.state, case.revision, case.updated_at = to_state, case.revision + 1, now()
    sync_index(session, case)


def sync_index(session: Session, case: AssessmentCase, blockers: int | None = None):
    """Keep staff queue metadata current; it carries no evidence content."""
    application = session.get(Application, case.application_id)
    workspace = session.get(Workspace, case.workspace_id)
    row = session.get(CaseIndex, case.id)
    if row is None:
        row = CaseIndex(case_id=case.id, workspace_id=case.workspace_id, workspace_name=workspace.name,
                        application_name=application.name, title=case.title, state=case.state, priority=case.priority)
        session.add(row)
    row.title, row.state, row.priority, row.updated_at = case.title, case.state, case.priority, now()
    if blockers is not None:
        row.blockers = blockers


def audit(session: Session, *, workspace_id: str, actor: str, actor_kind: str, action: str, target: str, detail: dict | None = None,
          request_id: str | None = None):
    session.add(AuditEvent(workspace_id=workspace_id, actor=actor, actor_kind=actor_kind, action=action, target=target,
                           detail=detail or {}, request_id=request_id))
