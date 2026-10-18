"""Approval and logical-action protocol (plan §10).

One approval authorizes one logical action. Reservation is atomic (row lock),
retries reconcile the same action instead of authorizing another, and an
ambiguous outcome keeps the approval bound until reconciled.
"""

from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Approval, LogicalAction, now
from .profile import canonical_hash

APPROVAL_POLICY_VERSION = "approval-v1"
SCHEMAS = {"issue_refund": {"order_id": str, "amount_minor": int}}


class ApprovalError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def to_minor(amount) -> int:
    """Money is normalized to integer minor units before hashing."""
    try:
        value = Decimal(str(amount))
    except InvalidOperation:
        raise ApprovalError("invalid_payload", "amount is not a number")
    minor = value * 100
    if minor != minor.to_integral_value():
        raise ApprovalError("invalid_payload", "amount has more than two decimal places")
    return int(minor)


def normalize(tool: str, payload: dict) -> dict:
    schema = SCHEMAS.get(tool)
    if schema is None:
        raise ApprovalError("unsupported_tool", f"{tool} has no approval schema")
    unknown = set(payload) - set(schema)
    if unknown:
        raise ApprovalError("invalid_payload", f"unknown fields {sorted(unknown)}")
    normalized = {}
    for name, kind in schema.items():
        if name not in payload:
            raise ApprovalError("invalid_payload", f"missing {name}")
        value = payload[name]
        if kind is int and (isinstance(value, bool) or not isinstance(value, int)):
            raise ApprovalError("invalid_payload", f"{name} must be an integer of minor units")
        if kind is str and not isinstance(value, str):
            raise ApprovalError("invalid_payload", f"{name} must be a string")
        normalized[name] = value
    return normalized


def payload_hash(tool: str, payload: dict) -> str:
    return canonical_hash({"tool": tool, "payload": normalize(tool, payload)})


def grant(session: Session, *, workspace_id: str, application_id: str, environment: str, release: str, tool: str,
          tool_schema_hash: str, payload: dict, permission_policy_version: str, requester: str, approver: str,
          ttl_seconds: int, self_approval_allowed: bool = False) -> Approval:
    if not self_approval_allowed and requester == approver:
        raise ApprovalError("self_approval", "requester cannot approve their own consequential action")
    if not 30 <= ttl_seconds <= 3600:
        raise ApprovalError("invalid_ttl", "approval lifetime must be between 30 seconds and one hour")
    approval = Approval(
        workspace_id=workspace_id, application_id=application_id, environment=environment, release=release, tool=tool,
        tool_schema_hash=tool_schema_hash, payload=normalize(tool, payload), payload_hash=payload_hash(tool, payload),
        permission_policy_version=permission_policy_version, approval_policy_version=APPROVAL_POLICY_VERSION,
        requester=requester, approver=approver, expires_at=now() + ttl_seconds,
    )
    session.add(approval)
    session.flush()
    return approval


def reserve(session: Session, *, approval_id: str, action_id: str, application_id: str, environment: str, release: str,
            tool: str, tool_schema_hash: str, payload: dict, permission_policy_version: str, requester: str) -> LogicalAction:
    """Revalidate every binding, then atomically reserve the approval for exactly this action."""
    approval = session.scalars(select(Approval).where(Approval.id == approval_id).with_for_update()).first()
    if approval is None:
        raise ApprovalError("approval_invalid", "approval not found")
    existing = session.get(LogicalAction, action_id)
    if approval.action_id is not None:
        if approval.action_id == action_id and existing is not None:
            return existing  # retry of the same logical action: reconcile, never re-authorize
        raise ApprovalError("approval_invalid", "approval is already bound to another action")
    checks = [
        (approval.state == "granted", "approval is not in a grantable state"),
        (approval.expires_at > now(), "approval expired"),
        (approval.application_id == application_id and approval.environment == environment, "approval is for another application or environment"),
        (approval.release == release, "approval was granted for another release"),
        (approval.tool == tool and approval.tool_schema_hash == tool_schema_hash, "tool or tool schema changed since approval"),
        (approval.payload_hash == payload_hash(tool, payload), "approval does not match this order and amount"),
        (approval.permission_policy_version == permission_policy_version, "permission policy changed since approval"),
        (approval.requester == requester, "approval was granted for a different requester"),
    ]
    for ok, detail in checks:
        if not ok:
            if approval.expires_at <= now() and approval.state == "granted":
                approval.state = "expired"
            raise ApprovalError("approval_invalid", detail)
    if existing is not None:
        raise ApprovalError("action_conflict", "action id already used")
    approval.state, approval.action_id = "reserved", action_id
    action = LogicalAction(id=action_id, workspace_id=approval.workspace_id, application_id=application_id, approval_id=approval.id,
                           tool=tool, payload_hash=approval.payload_hash, state="reserved")
    session.add(action)
    session.flush()
    return action


def prepare_unapproved(session: Session, *, workspace_id: str, application_id: str, action_id: str, tool: str, payload: dict) -> LogicalAction:
    """Ledger entry for a write the policy lets through without approval; still idempotent."""
    existing = session.get(LogicalAction, action_id)
    if existing:
        return existing
    action = LogicalAction(id=action_id, workspace_id=workspace_id, application_id=application_id, approval_id=None, tool=tool,
                           payload_hash=payload_hash(tool, payload), state="reserved")
    session.add(action)
    session.flush()
    return action


TRANSITIONS = {
    "reserved": {"dispatching"},
    "dispatching": {"succeeded", "failed_definitive", "outcome_unknown"},
    "outcome_unknown": {"succeeded", "failed_definitive"},
}


def transition(session: Session, action_id: str, to_state: str, result: dict | None = None) -> LogicalAction:
    action = session.scalars(select(LogicalAction).where(LogicalAction.id == action_id).with_for_update()).first()
    if action is None:
        raise ApprovalError("action_unknown", "action not found")
    if action.state == to_state:
        return action
    if to_state not in TRANSITIONS.get(action.state, set()):
        raise ApprovalError("invalid_transition", f"cannot move action from {action.state} to {to_state}")
    action.state, action.updated_at, action.claim_revision = to_state, now(), action.claim_revision + 1
    if result is not None:
        action.result = result
    if action.approval_id and to_state == "succeeded":
        approval = session.get(Approval, action.approval_id)
        approval.state = "consumed"
    return action


def revoke(session: Session, approval_id: str) -> Approval:
    """Prevents new dispatch; cannot undo an action already in progress."""
    approval = session.scalars(select(Approval).where(Approval.id == approval_id).with_for_update()).first()
    if approval is None:
        raise ApprovalError("approval_invalid", "approval not found")
    if approval.state == "granted":
        approval.state = "revoked"
    return approval
