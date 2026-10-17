"""T03/T04: one approval authorizes exactly one bound logical action."""

import threading
import time

import pytest

from assureops_domain import approvals
from assureops_domain.db import tenant_session
from assureops_domain.models import Approval

BINDING = dict(environment="staging", release="R1", tool="issue_refund", tool_schema_hash="schema-1", permission_policy_version="1.0")


def grant(ws, requester="u1", approver="m1", amount=150000, ttl=300):
    with tenant_session(ws) as s:
        return approvals.grant(s, workspace_id=ws, application_id=f"{ws}-app", payload={"order_id": "O-1", "amount_minor": amount},
                               requester=requester, approver=approver, ttl_seconds=ttl, **BINDING).id


def reserve(ws, approval_id, action_id, **changes):
    args = dict(approval_id=approval_id, action_id=action_id, application_id=f"{ws}-app", payload={"order_id": "O-1", "amount_minor": 150000},
                requester="u1", **BINDING)
    args.update(changes)
    with tenant_session(ws) as s:
        return approvals.reserve(s, **args).state


def test_self_approval_is_rejected(workspace):
    with pytest.raises(approvals.ApprovalError) as exc:
        grant(workspace, requester="same", approver="same")
    assert exc.value.code == "self_approval"


@pytest.mark.parametrize("change", [
    {"payload": {"order_id": "O-1", "amount_minor": 400000}},
    {"requester": "someone-else"},
    {"release": "R2"},
    {"permission_policy_version": "1.1"},
    {"tool_schema_hash": "schema-2"},
])
def test_binding_mismatch_is_rejected(workspace, change):
    approval = grant(workspace)
    with pytest.raises(approvals.ApprovalError):
        reserve(workspace, approval, "act-1", **change)


def test_money_must_be_integer_minor_units():
    with pytest.raises(approvals.ApprovalError):
        approvals.normalize("issue_refund", {"order_id": "O-1", "amount_minor": 1500.5})
    assert approvals.to_minor("1500.50") == 150050


def test_second_action_cannot_reuse_approval_but_retry_reconciles(workspace):
    approval = grant(workspace)
    assert reserve(workspace, approval, "act-1") == "reserved"
    assert reserve(workspace, approval, "act-1") == "reserved"  # retry of the same action
    with pytest.raises(approvals.ApprovalError):
        reserve(workspace, approval, "act-2")


def test_consumed_on_success_only(workspace):
    approval = grant(workspace)
    reserve(workspace, approval, "act-1")
    with tenant_session(workspace) as s:
        approvals.transition(s, "act-1", "dispatching")
        approvals.transition(s, "act-1", "outcome_unknown")
    with tenant_session(workspace) as s:
        assert s.get(Approval, approval).state == "reserved"  # ambiguous outcome keeps it bound, never released
        approvals.transition(s, "act-1", "succeeded", {"refund_id": "RF-1"})
    with tenant_session(workspace) as s:
        assert s.get(Approval, approval).state == "consumed"


def test_expired_approval_cannot_be_reserved(workspace):
    approval = grant(workspace, ttl=30)
    with tenant_session(workspace) as s:
        s.get(Approval, approval).expires_at = time.time() - 1
    with pytest.raises(approvals.ApprovalError):
        reserve(workspace, approval, "act-1")


def test_two_concurrent_claimers_reserve_at_most_once(workspace):
    approval = grant(workspace)
    results = []

    def claim(action_id):
        try:
            results.append(reserve(workspace, approval, action_id))
        except approvals.ApprovalError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=claim, args=(f"act-{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("reserved") == 1
