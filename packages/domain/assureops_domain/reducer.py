"""Evidence validity, change impact, readiness reduction and the release gate.

Deterministic rules only. State is kept in separate dimensions (plan §6):
control_result, evidence_validity, runtime coverage and finding state are never
collapsed into one green/red field. Scores follow plan §27.

Every function takes the application's own profile. Controls the profile does
not test are reported as `unassessed`; they never count as supported and the
coverage score includes them in its denominator.
"""

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import evidence_store, risk
from .models import AnalysisRun, Artifact, DependencyEdge, EvidenceReview, Finding, Incident, Release, TestRun, now
from .profile import COMPONENT_LABELS, SEVERITY_RANK, canonical_hash, profile_version


def accepted_edges(session: Session, application_id: str, p: dict) -> dict[str, list[str]]:
    edges: dict[str, list[str]] = {t["id"]: [] for t in p["tests"]}
    rows = session.scalars(select(DependencyEdge).where(DependencyEdge.application_id == application_id, DependencyEdge.status == "accepted"))
    for edge in rows:
        if edge.test_id in edges:
            edges[edge.test_id].append(edge.component_id)
    return {k: sorted(v) for k, v in edges.items()}


def edge_revision(edges: dict[str, list[str]]) -> str:
    return canonical_hash(edges)[:16]


def components(release: Release | None) -> dict:
    return release.manifest.get("components", {}) if release else {}


def dependency_fingerprints(release: Release, components_for_test: list[str]) -> dict:
    comps = components(release)
    return {cid: comps.get(cid, {}).get("fingerprint") for cid in components_for_test}


def effective_gaps(session: Session, release: Release) -> list[str]:
    """Collection gaps plus unknown components that a completed source analysis found for this release."""
    gaps = list(release.collection_gaps or [])
    for run in session.scalars(select(AnalysisRun).where(AnalysisRun.release_id == release.id, AnalysisRun.status == "completed")):
        gaps += [f"source analysis: {u}" for u in (run.summary or {}).get("unknown_components", [])]
    return gaps


def diff_components(base: Release | None, target: Release) -> list[dict]:
    old, new = components(base), components(target)
    changes = []
    for cid in sorted(set(old) | set(new)):
        if cid not in old:
            kind = "added"
        elif cid not in new:
            kind = "removed"
        elif old[cid]["fingerprint"] != new[cid]["fingerprint"]:
            kind = "changed"
        else:
            continue
        changes.append({"component": cid, "type": (new.get(cid) or old.get(cid))["type"], "change": kind})
    return changes


def compare(session: Session, application_id: str, base: Release | None, target: Release, p: dict) -> dict:
    """Combined diff -> affected tests/controls, with conservative fallback for unmapped changes."""
    tests = p["tests"]
    edges = accepted_edges(session, application_id, p)
    mapped = {c for comps in edges.values() for c in comps}

    if base is None:
        return {
            "base": None, "target": target.version, "changes": [], "unmapped": [], "partial_collection": bool(target.collection_gaps),
            "conservative_fallback": True,
            "retest": [{"test_id": t["id"], "control": t["control"], "reasons": ["no prior assessed release"]} for t in tests],
            "reusable": [], "edge_revision": edge_revision(edges), "profile": profile_version(p),
        }

    changes = diff_components(base, target)
    changed = {c["component"] for c in changes}
    unmapped = sorted(changed - mapped)
    partial = bool(effective_gaps(session, target))
    retest, reusable = [], []
    for test in tests:
        reasons = sorted(changed & set(edges.get(test["id"], [])))
        if not edges.get(test["id"]):
            reasons.append("no reviewed dependency links: reuse not allowed")
        if unmapped:
            reasons += [f"unmapped change: {cid}" for cid in unmapped]
        if partial:
            reasons.append("partial collection: reuse not allowed")
        if test.get("mandatory"):
            reasons.append("mandatory boundary check")
        (retest.append({"test_id": test["id"], "control": test["control"], "reasons": reasons}) if reasons else reusable.append(test["id"]))

    for change in changes:
        affected = [t for t in tests if change["component"] in edges.get(t["id"], [])]
        change["impact"] = "unknown" if change["component"] in unmapped else (
            max((t["severity"] for t in affected), key=SEVERITY_RANK.get) if affected else "none")
        change["affected_tests"] = [t["id"] for t in affected]
        change["affected_controls"] = sorted({t["control"] for t in affected})
        change["label"] = COMPONENT_LABELS.get(change["component"].split(":")[0], "Change")
        change["before"] = components(base).get(change["component"], {}).get("fingerprint")
        change["after"] = components(target).get(change["component"], {}).get("fingerprint")

    return {
        "base": base.version, "target": target.version, "changes": changes, "unmapped": unmapped,
        "partial_collection": partial, "conservative_fallback": bool(unmapped or partial),
        "retest": retest, "reusable": reusable, "edge_revision": edge_revision(edges), "profile": profile_version(p),
    }


def _expired(run: TestRun, p: dict) -> bool:
    return now() - run.created_at > p["evidence_freshness_days"] * 86400


def _reusable(run: TestRun, run_release: Release, release: Release, edge_set: list[str], test: dict, mapped: set, p: dict,
              gaps: dict[str, list] | None = None) -> bool:
    """Reuse predicate (plan §6): every condition must hold, otherwise the evidence is stale."""
    if test.get("mandatory") or not edge_set:
        return False
    if run.profile_version != profile_version(p):
        return False
    if run.test_digest and run.test_digest != test["digest"]:  # the test definition itself changed
        return False
    if run.outcome == "error":
        return False
    if sorted(run.dependency_fingerprints) != edge_set:  # reviewed edges changed since collection
        return False
    if run.dependency_fingerprints != dependency_fingerprints(release, edge_set):
        return False
    gaps = gaps or {}
    if gaps.get(release.id, release.collection_gaps) or gaps.get(run_release.id, run_release.collection_gaps):
        return False
    changed = {c["component"] for c in diff_components(run_release, release)}
    return not (changed - mapped)


def readiness(session: Session, application_id: str, release: Release, p: dict) -> dict:
    edges = accepted_edges(session, application_id, p)
    mapped = {c for comps in edges.values() for c in comps}
    runs = session.scalars(select(TestRun).where(TestRun.application_id == application_id).order_by(TestRun.created_at.desc())).all()
    releases = {r.id: r for r in session.scalars(select(Release).where(Release.application_id == application_id))}
    artifacts = {a.id: a for a in session.scalars(select(Artifact).where(Artifact.id.in_([r.artifact_id for r in runs])))} if runs else {}
    reviews = {}
    for review in session.scalars(select(EvidenceReview).order_by(EvidenceReview.created_at)):
        reviews[review.run_id] = review
    open_findings = session.scalars(select(Finding).where(Finding.application_id == application_id, Finding.state != "resolved")).all()
    open_incidents = session.scalars(select(Incident).where(Incident.application_id == application_id, Incident.state == "open")).all()
    gaps = {rid: effective_gaps(session, rel) for rid, rel in releases.items()}

    tests = []
    for test in p["tests"]:
        own = [r for r in runs if r.test_id == test["id"]]
        entry = {"test_id": test["id"], "control": test["control"], "name": test["name"], "severity": test["severity"],
                 "requires_review": bool(test.get("requires_review")), "depends_on": edges.get(test["id"], []),
                 "template": test.get("template"), "expected": test.get("expected")}
        current = next((r for r in own if r.release_id == release.id and r.profile_version == profile_version(p)
                        and (not r.test_digest or r.test_digest == test["digest"])), None)
        chosen, validity, reused = None, "unavailable", False
        if current:
            chosen, validity = current, "current"
        elif reused_run := next((r for r in own if _reusable(r, releases[r.release_id], release, edges.get(test["id"], []), test, mapped, p, gaps)), None):
            chosen, validity, reused = reused_run, "current", True
        elif own:
            chosen, validity = own[0], "stale"
        if chosen is not None:
            if validity == "current" and _expired(chosen, p):
                validity = "stale"
            if not evidence_store.available(artifacts.get(chosen.artifact_id)):
                validity = "unavailable"  # deleted, missing or failed its integrity check
            result = {"passed": "supported", "failed": "failed", "error": "unverified"}[chosen.outcome]
            review = reviews.get(chosen.id)
            if test.get("requires_review") and result == "supported" and not (review and review.decision == "accept"):
                result = "review_required"
            if review and review.decision == "reject":
                result = "failed"
            entry.update(result=result, validity=validity, reused=reused, run_id=chosen.id, outcome=chosen.outcome,
                         release=releases[chosen.release_id].version, at=chosen.created_at,
                         trials=chosen.trials, passed_trials=chosen.passed_trials,
                         review=({"reviewer": review.reviewer, "decision": review.decision} if review else None))
        else:
            entry.update(result="unverified", validity="unavailable", reused=False)
        tests.append(entry)

    controls, blocking, warnings, incomplete, unassessed = [], [], [], [], []
    for cid, meta in p["controls"].items():
        own = [t for t in tests if t["control"] == cid]
        violations = [f for f in open_findings if f.control_id == cid and f.source == "runtime"]
        if not own and not violations:
            control = {"id": cid, **meta, "result": "unassessed", "evidence_validity": "not_collected", "failure_severity": None,
                       "runtime_violation": False, "passed": 0, "total": 0, "assessed": False}
            controls.append(control)
            unassessed.append(control)
            continue
        failing = [t for t in own if t["result"] == "failed"]
        results = {t["result"] for t in own}
        if failing or violations:
            result = "failed"
        elif "review_required" in results:
            result = "review_required"
        elif "unverified" in results or not own:
            result = "unverified"
        else:
            result = "supported"
        validities = {t["validity"] for t in own} or {"unavailable"}
        validity = "unavailable" if "unavailable" in validities else "stale" if "stale" in validities else "current"
        severity = max([t["severity"] for t in failing] + [f.severity for f in violations], key=SEVERITY_RANK.get, default=None)
        control = {"id": cid, **meta, "result": result, "evidence_validity": validity, "failure_severity": severity,
                   "runtime_violation": bool(violations), "assessed": True,
                   "passed": sum(t["result"] == "supported" for t in own), "total": len(own)}
        controls.append(control)
        if result == "failed":
            (blocking if severity in p["gate_policy"]["blocking_severities"] else warnings).append(control)
        if validity != "current" or result in ("unverified", "review_required"):
            incomplete.append(control)

    weights = {c["id"]: p["controls"][c["id"]]["weight"] for c in controls}
    total_weight = sum(weights.values())
    covered = [c for c in controls if c["evidence_validity"] == "current" and c["result"] in ("supported", "failed")]
    supported = [c for c in covered if c["result"] == "supported" and not c["runtime_violation"]]
    coverage_pct = round(100 * sum(weights[c["id"]] for c in covered) / total_weight) if total_weight else None
    support_pct = round(100 * sum(weights[c["id"]] for c in supported) / total_weight) if total_weight else None

    # Reviewed, release-bound risk acceptances move an eligible blocking failure aside; the control itself stays failed.
    accepted = []
    acceptances = risk.active_for(session, application_id, release.id)
    for c in list(blocking):
        row = acceptances.get(c["id"])
        if row is not None and risk.eligible(c, p)[0]:
            c["risk_accepted"] = {"id": row.id, "expires_at": row.expires_at, "decided_by": row.decided_by}
            blocking.remove(c)
            accepted.append(c)

    status = "blocked" if blocking else "incomplete" if incomplete else "ready"
    reason_parts = []
    for c in blocking:
        reason_parts.append(f"{c['name']} failed" + (" in operation" if c["runtime_violation"] else f" in release {release.version}"))
    stale = [c for c in incomplete if c["evidence_validity"] == "stale"]
    unverified = [c for c in incomplete if c["result"] == "unverified" and c["evidence_validity"] != "stale"]
    review = [c for c in incomplete if c["result"] == "review_required"]
    if stale:
        reason_parts.append(f"{len(stale)} control{'s' if len(stale) > 1 else ''} have stale evidence")
    if unverified:
        reason_parts.append(f"{len(unverified)} remain unverified")
    if review:
        reason_parts.append(f"{len(review)} await reviewer confirmation")
    if warnings:
        reason_parts.append(f"{len(warnings)} non-blocking failure{'s' if len(warnings) > 1 else ''}")
    for c in accepted:
        reason_parts.append(f"{c['name']} failed and is accepted as a risk until {time.strftime('%Y-%m-%d', time.gmtime(c['risk_accepted']['expires_at']))} "
                            f"({c['risk_accepted']['id']})")
    if not reason_parts:
        reason_parts.append("All assessed controls are supported with current evidence")
    if unassessed:
        reason_parts.append(f"{len(unassessed)} catalog control{'s are' if len(unassessed) > 1 else ' is'} outside this profile and not assessed "
                            f"({', '.join(c['id'] for c in unassessed)})")
    reason = "; ".join(reason_parts) + "."

    retest = [t for t in tests if t["validity"] != "current" or t["result"] in ("failed", "unverified")]
    critical_open = [f for f in open_findings if f.severity == "critical"]
    return {
        "release": {"id": release.id, "version": release.version, "collection_status": release.collection_status,
                    "manifest_hash": release.manifest_hash, "effective_gaps": gaps.get(release.id, [])},
        "profile": {"version": profile_version(p), "revision": p.get("revision"), "digest": p["digest"][:16],
                    "gate_policy": p["gate_policy"]["version"], "adapter": p["adapter"],
                    "assessed_controls": p["assessed_controls"], "unassessed_controls": p["unassessed_controls"],
                    "scope": (p.get("scope") or {}).get("statement")},
        "tests": tests,
        "controls": controls,
        "scores": {
            "evidence_support_pct": support_pct, "evidence_coverage_pct": coverage_pct,
            "controls_supported": len(supported), "controls_covered": len(covered), "controls_total": len(controls),
            "controls_assessed": len(controls) - len(unassessed), "controls_unassessed": len(unassessed),
        },
        "counts": {
            "tests_total": len(tests), "tests_current_passing": sum(t["result"] == "supported" and t["validity"] == "current" for t in tests),
            "retest_needed": len(retest), "critical_open": len(critical_open), "open_findings": len(open_findings),
            "open_incidents": len(open_incidents),
        },
        "gate": {
            "status": status, "reason": reason,
            "blocking": [c["id"] for c in blocking], "warnings": [c["id"] for c in warnings],
            "accepted_risks": [{"control": c["id"], **c["risk_accepted"]} for c in accepted],
            "incomplete": [c["id"] for c in incomplete], "unassessed": [c["id"] for c in unassessed],
            "scope_limited": bool(unassessed),
        },
        "evidence_digest": canonical_hash(sorted((t["test_id"], t.get("run_id"), t["result"], t["validity"]) for t in tests))[:16],
        "computed_at": now(),
    }


def retest_plan(state: dict, scope: str, p: dict) -> list[str]:
    """Stable, deterministic covering set: required tests ordered by test ID."""
    tests_by_id = p["tests_by_id"]
    if scope == "full":
        return sorted(tests_by_id)
    chosen = {t["test_id"] for t in state["tests"] if t["validity"] != "current" or t["result"] in ("failed", "unverified")}
    chosen |= {tid for tid, t in tests_by_id.items() if t.get("mandatory")}
    return sorted(chosen & set(tests_by_id))
