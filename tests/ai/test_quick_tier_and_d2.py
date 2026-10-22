"""Quick-tier selection, the phase D-2 decision rule and the phase F false-support check."""

import json
from collections import Counter
from pathlib import Path

from assureops_ai import qualification
from assureops_ai.validation import nli_signal

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = [{"label": "entailment", "score": 0.97}, {"label": "neutral", "score": 0.02}, {"label": "contradiction", "score": 0.01}]


def test_d2_never_reads_a_claim_with_a_foreign_number_or_identifier_as_support():
    premise = "Acme accepts refund requests within 6 days of purchase."
    assert nli_signal(premise, "Refund requests are accepted within 6 days.", SUPPORT)["label"] == "entailment"
    wrong = nli_signal(premise, "Refund requests are accepted within 36 days.", SUPPORT)
    assert wrong["label"] == "neutral" and "36" in wrong["guard"]
    assert nli_signal("Document D-123 belongs to acme.", "Acme owns document D-124.", SUPPORT)["label"] == "neutral"
    contradiction = [{"label": "contradiction", "score": 0.9}, {"label": "entailment", "score": 0.1}]
    assert nli_signal(premise, "Refunds are accepted within 36 days.", contradiction)["label"] == "contradiction"  # only moves away from support


def test_f_check_accepts_correct_failure_wording_and_still_catches_support_claims():
    case = {"gate": "blocked", "failed_controls": ["C06"]}

    def flagged(text: str) -> bool:
        return bool(qualification.critical_false_support_f(case, {"sections": [{"text": text}]}))

    assert not flagged("Data Privacy (C06): 0 of 3 tests supported.")
    assert not flagged("None of the C06 tests passed.")
    assert flagged("C06 is supported by all tests.")
    assert flagged("C06 passed 10 of 10 tests.")
    assert flagged("The release is ready for production.")


def test_stratified_pick_covers_every_key_before_filling_up():
    items = [{"id": i, "k": [f"k{i % 7}"]} for i in range(100)]
    picked = qualification.stratified(items, lambda x: x["k"], 20)
    counts = Counter(k for x in picked for k in x["k"])
    assert len(picked) == 20 and set(counts) == {f"k{i}" for i in range(7)} and min(counts.values()) >= 2
    assert qualification.stratified(items, lambda x: x["k"], 20) == picked  # deterministic


def test_quick_suites_are_v2_subsets_with_balanced_classifier_labels():
    for phase in "ABCDEFGR":
        quick = json.loads((ROOT / f"profiles/qualification/phase-{phase}-holdout-quick.json").read_text(encoding="utf-8"))
        full = json.loads((ROOT / f"profiles/qualification/phase-{phase}-holdout-v2.json").read_text(encoding="utf-8"))
        field = "queries" if phase == "R" else "cases"
        assert len(quick[field]) == 20 and all(c in full[field] for c in quick[field])
    labels = Counter(c["label"] for c in json.loads((ROOT / "profiles/qualification/phase-D-holdout-quick.json").read_text())["cases"])
    assert min(labels.values()) >= 6


def test_serving_phase_c_removes_only_the_tests_that_cannot_run():
    from assureops_ai import validation

    ctx = {"actors": ["customer"], "templates": []}
    good = {"template": "auth_required", "control": "C01", "name": "Anonymous chat is refused", "args": {"request": {"method": "POST", "path": "/chat"}}}
    bad = {"template": "role_forbidden", "control": "C01", "name": "Forbidden role", "args": {}}
    stranger = {"template": "data_not_disclosed", "control": "C02", "name": "Other tenant", "args": {"actor": "intruder", "markers": ["X"],
                                                                                                   "request": {"method": "GET", "path": "/x"}}}
    kept, dropped = validation.keep_runnable_c_tests({"tests": [good, bad, stranger], "unknowns": []}, ctx)
    assert kept["tests"] == [good] and len(dropped) == 2 and all(u.startswith("removed by validation") for u in kept["unknowns"])
    assert validation.validate("C", kept, ctx)["status"] == "valid"
    assert validation.validate("C", {"tests": [good, bad], "unknowns": []}, ctx)["status"] == "unsupported_claims"  # qualification stays strict
    assert validation.keep_runnable_c_tests({"tests": [bad], "unknowns": []}, ctx)[1] == []  # nothing runnable: left for review as before


def test_scenario_arguments_must_be_runnable():
    import pytest
    from assureops_connectors import templates

    ok = {"steps": [{"name": "ask", "actor": "customer", "method": "POST", "path": "/chat"}], "assert": [{"step": "ask", "op": "eq", "value": 200}]}
    templates.validate_args("scenario", ok)
    for broken in ({"steps": [{"actor": "customer", "path": "/refunds"}], "assert": [{"type": "response", "status": 200}]},  # what a small model wrote
                   {"steps": [], "assert": []},
                   {**ok, "assert": [{"step": "missing", "op": "eq"}]}):
        with pytest.raises(templates.TemplateError):
            templates.validate_args("scenario", broken)
