"""AI-built test plan: one proposed profile revision assembled from reviewed phase A and phase C proposals.

Any connected application can get its first profile this way, without a hand-written profile file:
phase A proposes requirements, phase C proposes tests from the permitted template catalogue, a reviewer
accepts or rejects each result, and `assemble` combines the accepted ones with the platform's standard
gate policy and the mandatory release-identity test. The assembled revision is only a proposal: the
person who assembled it cannot activate it, and the tests it adds need a reviewer's acceptance of their
passing evidence. Controls without an accepted test stay visible as not assessed, and every test depends
on every collected component until a reviewer narrows the links, so nothing is reused by accident.
"""

import json
import re

from sqlalchemy import func, select

from assureops_connectors import templates
from assureops_domain import cases, connections
from assureops_domain.models import AiResult, ApplicationProfile, Release
from assureops_domain.profile import catalog_id, control_catalog

from .service import AiError

UNSUPPORTED_ADAPTERS = {"assureops-mcp-reference"}  # runs only its own bundled tests, never catalogue templates


def _profile_id(application_id: str) -> str:
    slug = re.sub(r"[^a-z0-9.-]+", "-", application_id.lower()).strip("-.") or "app"
    return f"{slug[:56]}-ai"


def assemble(s, app, *, actor: str) -> tuple[ApplicationProfile, dict]:
    conn = connections.latest_connection(s, app.id)
    if conn is None:
        raise AiError("no_connection", "connect the application before building its test plan")
    if conn.adapter_id in UNSUPPORTED_ADAPTERS:
        raise AiError("adapter_unsupported", f"{conn.adapter_id} runs only its bundled tests; build its plan from a profile file")
    accepted = s.scalars(select(AiResult).where(AiResult.application_id == app.id, AiResult.status == "accepted", AiResult.phase.in_(["A", "C"]),
                                                AiResult.shadow_of.is_(None)).order_by(AiResult.created_at)).all()
    proposals = [r for r in accepted if r.phase == "C"]
    if not proposals:
        raise AiError("no_accepted_tests", "accept at least one phase C test proposal first")
    release = s.scalars(select(Release).where(Release.application_id == app.id)
                        .order_by(func.coalesce(Release.last_collected_at, Release.created_at).desc())).first()
    components = sorted((release.manifest or {}).get("components", {})) if release else []

    tests = [{"id": "AI-C10-IDENTITY", "control": "C10", "severity": "high", "trials": 1, "name": "Running release matches the assessed manifest",
              "expected": "live manifest release and every component fingerprint equal the assessed release", "template": "manifest_identity",
              "args": {}, "mandatory": True}]
    seen, per_control, skipped = set(), {}, []
    for row in proposals:
        for t in row.output.get("tests", []):
            key = (t["template"], json.dumps(t.get("args") or {}, sort_keys=True))
            if key in seen or t["template"] == "manifest_identity":
                continue
            try:
                templates.validate_args(t["template"], t.get("args") or {})
            except templates.TemplateError as exc:  # validated when proposed; a catalogue change since then drops it visibly
                skipped.append({"result": row.id, "name": t.get("name"), "reason": str(exc)})
                continue
            seen.add(key)
            per_control[t["control"]] = per_control.get(t["control"], 0) + 1
            title = templates.TEMPLATES[t["template"]]["title"]
            tests.append({"id": f"AI-{t['control']}-{per_control[t['control']]:02d}", "control": t["control"], "severity": t.get("severity", "medium"),
                          "trials": 1, "name": t["name"][:160],
                          "expected": f"{title} (phase C proposal {row.id}, accepted by {row.reviewer})", "template": t["template"],
                          "args": t.get("args") or {}, "requires_review": True})
    tested = {t["control"] for t in tests}
    statements = [{"control": q["control"], "statement": q["statement"], "source": f"phase A {r.id}"}
                  for r in accepted if r.phase == "A" for q in r.output.get("requirements", [])]
    applicability = {cid: {"status": "not_assessed", "reason": "No accepted AI-proposed test covers this control yet. Propose and accept a "
                                                               "phase C test for it, or add one by hand, then rebuild the plan."}
                     for cid in control_catalog()["controls"] if cid not in tested}
    revisions = s.scalar(select(func.count()).select_from(ApplicationProfile).where(ApplicationProfile.application_id == app.id)) or 0
    raw = {
        "profile_id": _profile_id(app.id), "version": f"0.{revisions + 1}.0", "catalog": catalog_id(), "adapter": conn.adapter_id,
        "note": "Assembled from accepted phase A requirements and phase C test proposals; review every test before activating.",
        "scope": {"statement": f"AI-built test plan for {app.name}: {len(tests) - 1} proposed tests from the permitted catalogue plus the release "
                               "identity check. Controls without an accepted test are not assessed."},
        "requirements": {"self_approval_allowed": False, "statements": statements},
        "gate_policy": {"version": "1.0.0", "blocking_severities": ["critical", "high"]},
        "evidence_freshness_days": 30,
        "coverage": {"reviewer": "pending review", "reviewed_against": "AI-built plan (dependency links not yet reviewed)",
                     "dependency_edges": {t["id"]: components for t in tests if not t.get("mandatory")}, "mandatory_components": {},
                     "runtime_sources": []},
        "applicability": applicability,
        "tests": tests,
    }
    row = connections.propose_profile(s, app, raw, source="ai", actor=actor)
    summary = {"revision": row.revision, "tests": len(tests), "controls_tested": sorted(tested), "controls_not_assessed": sorted(applicability),
               "requirements": len(statements), "proposals_used": [r.id for r in proposals], "skipped": skipped}
    cases.audit(s, workspace_id=app.workspace_id, actor=actor, actor_kind="customer", action="profile.ai_plan", target=app.id, detail=summary)
    return row, summary
