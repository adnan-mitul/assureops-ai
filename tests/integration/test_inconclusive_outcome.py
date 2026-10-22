"""An agent that never makes the attempt under test yields "inconclusive": never a pass, never a failure, never reused."""

from sqlalchemy import select

from assureops_domain import reducer
from assureops_domain.db import tenant_session
from assureops_domain.findings import record_test_outcome
from assureops_domain.models import Finding
from assureops_worker import runner
from tests.conftest import add_release, prof
from tests.integration.test_evidence_validity import _run


class FakeTarget:
    def __init__(self, actions: list, steps: int):
        self.response = {"reply": "ok", "actions": actions, "citations": [], "steps": steps}

    def chat(self, message: str, **kwargs) -> dict:
        return {"request": {"message": message}, "response": self.response}


def test_unregistered_tool_check_needs_an_attempt():
    blocked = {"tool": "delete_account", "outcome": "blocked", "reason": "unknown_tool"}
    assert runner.t_c04_01(FakeTarget([blocked], 1))[0] is True
    assert runner.t_c04_01(FakeTarget([{**blocked, "outcome": "executed", "reason": None}], 1))[0] is False
    ok, record = runner.t_c04_01(FakeTarget([], 0))  # e.g. an LLM planner that can only name allowlisted tools
    assert ok is None and "never attempted" in record["inconclusive"]


def test_run_budget_check_needs_the_budget_to_be_reached():
    exhausted = {"tool": "get_action_status", "outcome": "blocked", "reason": "budget_exhausted"}
    assert runner.t_c07_01(FakeTarget([exhausted], 10))[0] is True
    ok, record = runner.t_c07_01(FakeTarget([{"tool": "get_action_status", "outcome": "executed"}], 2))
    assert ok is None and "stopped on its own" in record["inconclusive"]
    assert runner.t_c07_01(FakeTarget([{"tool": "get_action_status", "outcome": "executed"}] * 12, 12))[0] is False  # ran past it


def test_trial_record_keeps_inconclusive_apart_from_passed():
    assert runner.trial(None, {}) == {"passed": False, "inconclusive": True, "record": {}}
    assert runner.trial(True, {})["passed"] is True and "inconclusive" not in runner.trial(False, {})


def test_inconclusive_run_is_unverified_opens_no_finding_and_is_never_reused(workspace):
    r1 = add_release(workspace, "R1")
    run = _run(workspace, r1, "T-C04-01", "inconclusive")
    p = prof()
    with tenant_session(workspace) as s:
        record_test_outcome(s, run, r1, p)
        state = reducer.readiness(s, f"{workspace}-app", r1, p)
        entry = next(t for t in state["tests"] if t["test_id"] == "T-C04-01")
        assert entry["result"] == "unverified" and entry["outcome"] == "inconclusive"
        assert "C04" not in state["gate"]["blocking"]  # not a failure ...
        c04 = next(c for c in state["controls"] if c["id"] == "C04")
        assert c04["result"] == "unverified" and state["gate"]["status"] != "ready"  # ... and not support either
        assert not s.scalars(select(Finding).where(Finding.application_id == f"{workspace}-app", Finding.test_id == "T-C04-01")).all()
    r2 = add_release(workspace, "R2")  # nothing changed, yet nothing was exercised: there is no evidence to carry forward
    with tenant_session(workspace) as s:
        entry = next(t for t in reducer.readiness(s, f"{workspace}-app", r2, p)["tests"] if t["test_id"] == "T-C04-01")
        assert not entry["reused"] and entry["validity"] != "current"
