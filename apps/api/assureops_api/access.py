"""Application-scoped write checks shared by the customer routes."""

from sqlalchemy.orm import Session

from assureops_domain import grants

from .auth import Caller, api_error


def require_application_writer(s: Session, caller: Caller, application_id: str, *also: str):
    """Owners change every application; developers only those assigned to them; `also` roles keep workspace-wide reach."""
    caller.require_role("owner", "developer", *also)
    if caller.role == "developer" and grants.active_grant(s, application_id, caller.user_id) is None:
        raise api_error(403, "not_assigned", "you are not assigned to this application; ask a workspace owner")
