"""Reviewed applicability: exclusions need a reason, cannot hide tested controls, and only not-applicable leaves the coverage denominator."""

import copy

import pytest

from assureops_domain import reducer
from assureops_domain.db import tenant_session
from assureops_domain.profile import ProfileError, load_profile_file, normalize
from tests.conftest import add_release

REASON = "The application performs no consequential actions that this control protects."


def _profile(applicability: dict) -> dict:
    raw = copy.deepcopy(load_profile_file("refund-agent"))
    raw["tests"] = [t for t in raw["tests"] if t["control"] not in ("C08", "C09")]
    raw["coverage"] = {k: v for k, v in (raw.get("coverage") or {}).items() if k != "dependency_edges"}
    raw["applicability"] = applicability
    return raw


def test_exclusions_need_a_real_reason_and_cannot_hide_tested_controls():
    with pytest.raises(ProfileError, match="minLength|too short|is too short"):
        normalize(_profile({"C08": {"status": "not_applicable", "reason": "n/a"}}))
    with pytest.raises(ProfileError, match="has tests"):
        normalize(_profile({"C01": {"status": "not_applicable", "reason": REASON}}))
    with pytest.raises(ProfileError, match="is not one of|enum"):
        normalize(_profile({"C08": {"status": "passed", "reason": REASON}}))
    p = normalize(_profile({"C08": {"status": "not_applicable", "reason": REASON}}))
    assert p["applicability"]["C08"] == {"status": "not_applicable", "reason": REASON, "reviewed": True}
    assert p["applicability"]["C09"]["reviewed"] is False  # no reason recorded: shown as unreviewed, still not assessed
    assert p["not_applicable_controls"] == ["C08"]


def test_not_applicable_leaves_the_denominator_but_not_assessed_still_counts(workspace):
    release = add_release(workspace, "R1")
    with_na = normalize(_profile({"C08": {"status": "not_applicable", "reason": REASON}}))
    without = normalize(_profile({}))
    with tenant_session(workspace) as s:
        a = reducer.readiness(s, f"{workspace}-app", release, with_na)
        b = reducer.readiness(s, f"{workspace}-app", release, without)
    c08 = next(c for c in a["controls"] if c["id"] == "C08")
    assert c08["result"] == "not_applicable" and c08["applicability"]["reason"] == REASON
    assert a["gate"]["not_applicable"] == ["C08"] and "C08" in a["gate"]["unassessed"]
    assert "reviewed as not applicable (C08)" in a["gate"]["reason"]
    assert next(c for c in b["controls"] if c["id"] == "C08")["result"] == "unassessed"
    assert a["scores"]["controls_not_applicable"] == 1 and b["scores"]["controls_not_applicable"] == 0
    assert a["gate"]["status"] == b["gate"]["status"]  # applicability never makes an application ready by itself
