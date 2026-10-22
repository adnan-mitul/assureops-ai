"""Risk acceptance never rewrites a failed result, needs a second person, is release-bound, expires and never covers critical failures."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from assureops_api import routes_handoffs, routes_risk
from assureops_domain import reducer, risk
from assureops_domain.db import tenant_session
from assureops_domain.models import ApplicationProfile, Finding, RiskAcceptance, TestRun, now
from assureops_domain.profile import canonical_hash
from tests.conftest import add_release, prof
from tests.integration.test_evidence_validity import _run

REASON = "Customer-facing approvals are disabled behind a feature flag until the fix ships."
COMPENSATING = "Manual approval review of every refund by the finance team."


def _denied(fn) -> str:
    with pytest.raises(HTTPException) as exc:
        fn()
    return exc.value.detail["code"]


def _allow_policy(ws: str, max_severity: str = "high"):
    with tenant_session(ws) as s:
        row = s.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == f"{ws}-app", ApplicationProfile.status == "active")).first()
        raw = copy.deepcopy(row.profile)
        raw["gate_policy"]["risk_acceptance"] = {"max_severity": max_severity}
        row.profile, row.digest = raw, canonical_hash(raw)


def _policy(max_severity: str | None) -> dict:
    p = copy.deepcopy(prof())
    if max_severity:
        p["gate_policy"]["risk_acceptance"] = {"max_severity": max_severity}
    return p


def test_eligibility_rules():
    failed_high = {"result": "failed", "failure_severity": "high", "runtime_violation": False}
    assert risk.eligible(failed_high, _policy(None)) == (False, "this application's profile does not permit risk acceptance")
    assert risk.eligible(failed_high, _policy("high"))[0]
    assert not risk.eligible(failed_high, _policy("medium"))[0]
    assert not risk.eligible({**failed_high, "failure_severity": "critical"}, _policy("critical"))[0]
    assert not risk.eligible({**failed_high, "runtime_violation": True}, _policy("high"))[0]
    assert not risk.eligible({**failed_high, "result": "supported"}, _policy("high"))[0]


def test_an_approved_acceptance_moves_the_failure_out_of_blocking_but_the_control_stays_failed(workspace):
    r1 = add_release(workspace, "R1")
    run = _run(workspace, r1, "T-C01-01", "failed")
    p = _policy("high")
    with tenant_session(workspace) as s:
        before = reducer.readiness(s, f"{workspace}-app", r1, p)
        assert "C01" in before["gate"]["blocking"]
        s.add(RiskAcceptance(workspace_id=workspace, application_id=f"{workspace}-app", release_id=r1.id, control_id="C01", severity="high",
                             reason=REASON, compensating_controls=COMPENSATING, status="active", requested_by="a", decided_by="b",
                             expires_at=now() + 3600))
    with tenant_session(workspace) as s:
        after = reducer.readiness(s, f"{workspace}-app", r1, p)
        c01 = next(c for c in after["controls"] if c["id"] == "C01")
        assert c01["result"] == "failed" and c01["risk_accepted"]
        assert "C01" not in after["gate"]["blocking"] and after["gate"]["accepted_risks"][0]["control"] == "C01"
        assert "accepted as a risk" in after["gate"]["reason"]
        assert s.get(TestRun, run.id).outcome == "failed"  # evidence untouched
        assert after["scores"] == before["scores"]  # support and coverage are not inflated
        without_policy = reducer.readiness(s, f"{workspace}-app", r1, _policy(None))
        assert "C01" in without_policy["gate"]["blocking"]  # the reviewed profile must permit it


def test_acceptance_is_bound_to_the_release_and_expires(workspace):
    r1 = add_release(workspace, "R1")
    _run(workspace, r1, "T-C01-01", "failed")
    p = _policy("high")
    with tenant_session(workspace) as s:
        s.add(RiskAcceptance(workspace_id=workspace, application_id=f"{workspace}-app", release_id=r1.id, control_id="C01", severity="high",
                             reason=REASON, compensating_controls=COMPENSATING, status="active", requested_by="a", decided_by="b",
                             expires_at=now() - 1))
    with tenant_session(workspace) as s:
        assert "C01" in reducer.readiness(s, f"{workspace}-app", r1, p)["gate"]["blocking"]  # expired
    r2 = add_release(workspace, "R2", {"policy:permission": "fp-new"})
    _run(workspace, r2, "T-C01-01", "failed")
    with tenant_session(workspace) as s:
        s.add(RiskAcceptance(workspace_id=workspace, application_id=f"{workspace}-app", release_id=r1.id, control_id="C01", severity="high",
                             reason=REASON, compensating_controls=COMPENSATING, status="active", requested_by="a", decided_by="b",
                             expires_at=now() + 3600))
    with tenant_session(workspace) as s:
        assert "C01" in reducer.readiness(s, f"{workspace}-app", r2, p)["gate"]["blocking"]  # acceptance was for R1 only


def test_api_requires_a_second_person_and_a_permitting_profile_and_refuses_critical(workspace, people):
    r1 = add_release(workspace, "R1")
    _run(workspace, r1, "T-C01-01", "failed")
    _run(workspace, r1, "T-C02-01", "failed")  # critical
    app = f"{workspace}-app"
    owner, dev, reviewer, viewer = (people[k] for k in ("owner", "developer", "reviewer", "viewer"))
    body = routes_risk.ProposeIn(control_id="C01", reason=REASON, compensating_controls=COMPENSATING, expires_in_days=14)
    assert _denied(lambda: routes_risk.propose(app, body, caller=dev)) == "not_assigned"
    assert _denied(lambda: routes_risk.propose(app, body, caller=viewer)) == "forbidden"
    assert _denied(lambda: routes_risk.propose(app, routes_risk.ProposeIn(control_id="C02", reason=REASON, compensating_controls=COMPENSATING,
                                                                          expires_in_days=14), caller=owner)) == "not_acceptable"
    routes_handoffs.assign_application_developer(app, dev.username, caller=owner)
    proposed = routes_risk.propose(app, body, caller=dev)
    assert proposed["status"] == "proposed"
    decision = routes_risk.DecideIn(approve=True, note="Compensating control verified")
    assert _denied(lambda: routes_risk.decide(proposed["id"], decision, caller=dev)) == "forbidden"
    assert _denied(lambda: routes_risk.decide(proposed["id"], decision, caller=reviewer)) == "not_acceptable"  # profile does not permit
    _allow_policy(workspace)
    approved = routes_risk.decide(proposed["id"], decision, caller=reviewer)
    assert approved["status"] == "active" and approved["decided_by"] == reviewer.username
    own = routes_risk.propose(app, body, caller=owner)
    assert _denied(lambda: routes_risk.decide(own["id"], decision, caller=owner)) == "separation_of_duties"
    listed = routes_risk.list_acceptances(app, caller=viewer)
    assert listed["policy_max_severity"] == "high" and {i["status"] for i in listed["items"]} == {"active", "proposed"}
    assert routes_risk.revoke(proposed["id"], caller=owner)["status"] == "revoked"
    with tenant_session(workspace) as s:
        assert all(f.state != "resolved" for f in s.scalars(select(Finding).where(Finding.application_id == app)))
