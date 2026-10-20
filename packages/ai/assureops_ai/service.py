"""Durable AI phase jobs: request -> routed call -> validation -> proposal awaiting review.

Each request records workspace/application/release, allowed evidence
references, phase, prompt/schema versions, budget and job/fencing identity.
The prompt is rebuilt from those references inside the worker and never
stored; only its hash is. Model failure leaves a truthful pending,
unavailable or review_required state.
"""

import json
import os
import socket

from sqlalchemy import func, select, text

from assureops_domain import cases, connections
from assureops_domain.config import settings
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import (
    AiResult, Application, DependencyEdge, Incident, ModelCall, Outbox, Release, Report, RuntimeEvent, SourceDocument, Workspace, now,
)
from assureops_domain.profile import canonical_hash, control_catalog, try_for_application

from . import prompts, retrieval, router, validation
from .registry import PHASES
from .registry import constrained as registry_constrained

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
LEASE_SECONDS = 180
MAX_ATTEMPTS = 3
BUDGET = {"A": 1500, "B": 1500, "C": 3000, "E": 1200, "F": 1500}


class AiError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def external_allowed(workspace_id: str) -> bool:
    with platform_session() as s:
        ws = s.get(Workspace, workspace_id)
        return bool(ws and ws.external_processing)


def route_table(workspace) -> list[dict]:
    allowed = bool(workspace and workspace.external_processing)
    out = []
    for phase in PHASES.values():
        r = router.resolve(phase.id, allowed)
        out.append({"phase": phase.name, "id": phase.id, "model": phase.candidate, "parameters": phase.parameters, "purpose": phase.purpose,
                    "kind": phase.kind, "enabled": r.available, "route": {"provider": r.provider, "model": r.model, "external": r.external},
                    "status": r.reason, "qualification": r.qualification, "optional": phase.optional,
                    "prompt_version": phase.prompt_version, "schema_version": phase.schema_version})
    return out


# ---------------- requests ----------------

def request(s, app: Application, phase: str, refs: dict, actor: str) -> AiResult:
    if phase not in PHASES or phase == "R":
        raise AiError("unsupported_phase", f"phase {phase} cannot be requested directly")
    p = PHASES[phase]
    row = AiResult(workspace_id=app.workspace_id, application_id=app.id, release_id=refs.get("release_id"), phase=phase, status="pending",
                   request={"refs": refs, "phase": phase, "prompt_version": p.prompt_version, "schema_version": p.schema_version,
                            "budget_tokens": BUDGET.get(phase, 600)},
                   versions={"prompt": p.prompt_version, "schema": p.schema_version, "candidate": p.candidate}, requested_by=actor)
    s.add(row)
    s.flush()
    s.add(Outbox(workspace_id=app.workspace_id, kind="ai_phase", ref_id=row.id))
    return row


# ---------------- inputs (rebuilt in the worker from references) ----------------

def _facts_from_snapshot(snapshot: dict) -> dict[str, str]:
    r = snapshot["readiness"]
    facts = {
        "F-gate": f"Release gate status for {snapshot['release']['version']} is {r['gate']['status']}: {r['gate']['reason']}",
        "F-scores": (f"Evidence support {r['scores']['evidence_support_pct']}% and evidence coverage {r['scores']['evidence_coverage_pct']}% "
                     f"across {r['scores']['controls_total']} catalog controls; {r['scores']['controls_assessed']} assessed."),
        "F-scope": snapshot.get("scope_note", ""),
    }
    for c in r["controls"]:
        facts[f"F-{c['id']}"] = f"{c['id']} {c['name']}: result {c['result']}, evidence {c['evidence_validity']}, {c['passed']} of {c['total']} tests supported."
    for i, f in enumerate(snapshot.get("findings", [])[:12]):
        facts[f"F-finding-{i + 1}"] = f"Finding ({f['severity']}, {f['state']}) on {f['control']}: {f['title']}."
    return facts


def build_input(s, row: AiResult) -> tuple[dict, dict]:
    """(data for the prompt, validation context). Only references named in the request are read."""
    refs = row.request["refs"]
    app = s.get(Application, row.application_id)
    if row.phase == "A":
        docs = s.scalars(select(SourceDocument).where(SourceDocument.application_id == app.id)).all()
        if not docs:
            raise AiError("no_sources", "no approved reference sources for this application")
        ids = set(refs.get("source_ids") or [d.id for d in docs])
        docs = [d for d in docs if d.id in ids]
        method, hits = retrieval.hybrid_search([{"id": d.id, "title": d.title, "text": d.text} for d in docs],
                                               refs.get("query") or app.purpose or "requirements", k=8)
        data = {"application_purpose": app.purpose,
                "controls": {k: f"{v['name']}: {v['description']}" for k, v in control_catalog()["controls"].items()},
                "sources": [{"source_id": c.source_id, "title": c.title, "text": c.text} for _, c in hits]}
        return data, {"sources": {d.id: d.text for d in docs}}
    if row.phase in ("B", "C"):
        p = try_for_application(s, app.id)
        accepted = [r.output for r in s.scalars(select(AiResult).where(AiResult.application_id == app.id, AiResult.phase == "A",
                                                                       AiResult.status == "accepted"))]
        requirements = [q for out in accepted for q in out.get("requirements", [])]
        if row.phase == "B":
            release = s.get(Release, refs["release_id"])
            data = {"tests": [{"id": t["id"], "name": t["name"], "control": t["control"], "template": t["template"]} for t in (p or {"tests": []})["tests"]],
                    "components": [{"id": cid, "type": c["type"]} for cid, c in release.manifest["components"].items()],
                    "requirements": requirements}
            return data, {"test_ids": [t["id"] for t in data["tests"]], "component_ids": [c["id"] for c in data["components"]]}
        from assureops_connectors import templates

        conn = connections.latest_connection(s, app.id)
        actors = sorted((conn.config.get("actors") or {}) if conn else {})
        data = {"requirements": requirements, "templates": templates.catalogue(), "actors": actors,
                "allowed_paths": (conn.config.get("scope") or {}).get("allowed_paths", []) if conn else []}
        return data, {"actors": actors, "templates": [t["id"] for t in data["templates"]]}
    if row.phase == "E":
        incident = s.get(Incident, refs["incident_id"])
        events = s.scalars(select(RuntimeEvent).where(RuntimeEvent.revision.in_(incident.event_revisions))).all()
        sources = {f"event:{e.revision}": json.dumps({"type": e.event_type, "release": e.release, "classification": e.classification,
                                                      "payload": e.payload}, sort_keys=True) for e in events}
        p = try_for_application(s, app.id)
        data = {"incident": {"control": incident.control_id, "title": incident.title, "release": incident.release},
                "events": [{"source_id": k, "text": v} for k, v in sources.items()],
                "tests": [{"id": t["id"], "control": t["control"], "name": t["name"]} for t in (p or {"tests": []})["tests"]]}
        return data, {"sources": sources, "test_ids": [t["id"] for t in data["tests"]]}
    if row.phase == "G":
        texts = list(refs.get("texts") or [])
        if refs.get("source_ids"):
            texts += [d.text[:2000] for d in s.scalars(select(SourceDocument).where(SourceDocument.id.in_(refs["source_ids"])))]
        if not texts:
            raise AiError("no_text", "phase G screens supplied texts or approved sources")
        return {"texts": texts[:10]}, {}
    if row.phase == "D":
        from assureops_domain import evidence_store
        from assureops_domain.models import Artifact, TestRun

        run = s.get(TestRun, refs["run_id"])
        record = evidence_store.read_json(s.get(Artifact, run.artifact_id))
        premises = []

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for v in value.values():
                    yield from strings(v)
            elif isinstance(value, list):
                for v in value:
                    yield from strings(v)

        for trial in record.get("trials", []):
            for entry in (trial.get("record") or {}).get("transcript", []):
                resp = entry.get("response")
                for r in resp if isinstance(resp, list) else [resp]:
                    if isinstance(r, dict) and r.get("body") is not None:
                        text = " ".join(t for t in strings(r["body"]) if len(t) > 2)[:1500]
                        if text:
                            premises.append(text)
        claims = refs.get("claims") or [run.expected]  # atomic claims from the reviewer, else the test's expectation
        return {"pairs": [[p, c] for p in premises[:4] for c in claims[:4]]}, {"outcome": run.outcome}
    if row.phase == "F":
        report = s.get(Report, refs["report_id"])
        facts = _facts_from_snapshot(report.snapshot)
        return {"facts": [{"id": k, "text": v} for k, v in facts.items()]}, {"facts": facts}
    raise AiError("unsupported_phase", row.phase)


# ---------------- execution (worker) ----------------

def claim(workspace_id: str, result_id: str) -> int | None:
    with tenant_session(workspace_id) as s:
        row = s.execute(text("""
            UPDATE ai_results SET status = 'running', attempts = attempts + 1, lease_owner = :owner,
                   lease_expires_at = extract(epoch from now()) + :lease, fencing_token = fencing_token + 1,
                   updated_at = extract(epoch from now())
            WHERE id = :id AND attempts < :max
              AND (status = 'pending' OR (status = 'running' AND lease_expires_at < extract(epoch from now())))
            RETURNING fencing_token"""), {"owner": WORKER_ID, "lease": LEASE_SECONDS, "id": result_id, "max": MAX_ATTEMPTS}).first()
        return row[0] if row else None


def _usage_today(s, workspace_id: str) -> int:
    rows = s.scalars(select(ModelCall).where(ModelCall.provider == "groq", ModelCall.created_at > now() - 86400)).all()
    return sum((r.usage or {}).get("total_tokens") or 0 for r in rows)


def execute(workspace_id: str, result_id: str) -> str:
    token = claim(workspace_id, result_id)
    if token is None:
        return "not_claimable"
    with tenant_session(workspace_id) as s:
        row = s.get(AiResult, result_id)
        phase = PHASES[row.phase]
        try:
            data, ctx = build_input(s, row)
        except AiError as exc:
            return _finish(workspace_id, result_id, token, "unavailable", error=f"{exc.code}: {exc.detail}")
        route = router.resolve(row.phase, external_allowed(workspace_id))
        used_today = _usage_today(s, workspace_id) if route.provider == "groq" else 0
    if not route.available:
        return _finish(workspace_id, result_id, token, "unavailable", error=route.reason, route=route)
    if row.phase == "G":
        return _screen(workspace_id, result_id, token, route, data)
    if phase.kind == "classify":
        return _classify(workspace_id, result_id, token, route, data, ctx)
    if route.provider == "groq" and used_today >= settings().groq_daily_token_limit:
        return _finish(workspace_id, result_id, token, "unavailable", error="quota_exceeded: daily external token budget used", route=route)
    user = prompts.user_message(row.phase, data)
    if route.external:
        user = validation.minimize(user)  # local-only requests never reach this branch
    client = router.generation_client(route)
    result = client.generate(model=route.model, system=prompts.SYSTEM[row.phase], user=user, max_tokens=row.request["budget_tokens"],
                             json_mode=client.json_mode(route.model) if hasattr(client, "json_mode") else "json_object",
                             schema=registry_constrained(row.phase, ctx))
    check = validation.validate(row.phase, result.parsed, ctx) if result.ok else {"status": result.status, "problems": [result.error or ""]}
    call = {"provider": route.provider, "model": route.model, "request_id": result.request_id, "prompt_version": phase.prompt_version,
            "schema_version": phase.schema_version, "input_sha256": canonical_hash({"system": prompts.SYSTEM[row.phase], "user": user}),
            "status": "succeeded" if check["status"] == "valid" else check["status"], "validation": check, "usage": result.usage,
            "latency_ms": result.latency_ms, "attempts": result.attempts}
    if check["status"] == "valid":
        return _finish(workspace_id, result_id, token, "proposed", output=result.parsed, call=call, route=route,
                       spans=_spans(row.phase, result.parsed), unknowns=result.parsed.get("unknowns") or result.parsed.get("gaps") or [])
    if check["status"] == "unsupported_claims":
        return _finish(workspace_id, result_id, token, "review_required", output=result.parsed, call=call, route=route,
                       error="; ".join(check["problems"])[:2000])
    retry = result.status in ("rate_limited", "timeout", "unavailable")
    return _finish(workspace_id, result_id, token, "pending" if retry else "unavailable", call=call, route=route,
                   error=f"{result.status}: {'; '.join(check['problems'])}"[:2000], retry=retry)


LABELS = {"entailment", "contradiction", "neutral"}


def _screen(workspace_id, result_id, token, route, data) -> str:
    """Phase G: advisory injection screening of untrusted text. A high score asks for review; it never authorizes or blocks."""
    client = router.encoder_client(route)
    items, statuses = [], set()
    for text in data["texts"]:
        status, score = client.screen(validation.minimize(text) if route.external else text, route.model)
        statuses.add(status)
        if status == "succeeded":
            items.append({"excerpt": text[:160], "score": round(score, 4), "flagged": score >= 0.5})
    call = {"provider": route.provider, "model": route.model, "prompt_version": "G-1", "schema_version": "G-1",
            "input_sha256": canonical_hash(data), "status": "succeeded" if items else "unavailable", "validation": {}, "usage": {}}
    if not items:
        return _finish(workspace_id, result_id, token, "unavailable", call=call, route=route, error=f"screening failed: {sorted(statuses)}")
    status = "review_required" if any(i["flagged"] for i in items) else "proposed"
    return _finish(workspace_id, result_id, token, status, call=call, route=route,
                   output={"items": items, "note": "advisory screening signal; never authorizes or blocks an action"})


def _classify(workspace_id, result_id, token, route, data, ctx) -> str:
    """Phase D: NLI signals beside the actual test outcome. A signal never changes the outcome; disagreement asks for review."""
    result = router.encoder_client(route).classify_pairs([tuple(p) for p in data["pairs"]], route.model)
    call = {"provider": route.provider, "model": route.model, "prompt_version": "D-1", "schema_version": "D-1",
            "input_sha256": canonical_hash(data), "status": result.status, "validation": {}, "usage": {}, "latency_ms": result.latency_ms}
    if not result.ok:
        return _finish(workspace_id, result_id, token, "pending" if result.status in ("timeout", "unavailable") else "unavailable",
                       call=call, route=route, error=result.error, retry=result.status in ("timeout", "unavailable"))
    signals = []
    for pair, scores in zip(data["pairs"], result.parsed["result"]):
        best = max(scores, key=lambda x: x.get("score", 0)) if isinstance(scores, list) and scores else {}
        label = str(best.get("label", "")).lower()
        if label not in LABELS:
            return _finish(workspace_id, result_id, token, "unavailable", call={**call, "status": "invalid_output"}, route=route,
                           error=f"classifier returned unknown label {label!r}")
        signals.append({"claim": pair[1], "premise_excerpt": pair[0][:200], "label": label, "score": round(float(best.get("score", 0)), 4)})
    contradicts = any(sg["label"] == "contradiction" for sg in signals) and ctx["outcome"] == "passed"
    unsupported = ctx["outcome"] == "passed" and not any(sg["label"] == "entailment" for sg in signals)
    status = "review_required" if contradicts or unsupported else "proposed"
    return _finish(workspace_id, result_id, token, status, output={"signals": signals, "test_outcome": ctx["outcome"],
                   "note": "advisory semantic signal; the deterministic outcome stands"}, call={**call, "status": "succeeded"}, route=route)


def _spans(phase: str, output: dict) -> list:
    if phase == "A":
        return [sp for r in output["requirements"] for sp in r["spans"]]
    return output.get("spans", [])


def _finish(workspace_id, result_id, token, status, *, output=None, call=None, route=None, error=None, spans=None, unknowns=None, retry=False):
    with tenant_session(workspace_id) as s:
        row = s.scalars(select(AiResult).where(AiResult.id == result_id).with_for_update()).first()
        if row.fencing_token != token or row.status != "running":
            if call:
                s.add(ModelCall(workspace_id=workspace_id, application_id=row.application_id, release_id=row.release_id, phase=row.phase,
                                job_ref=result_id, fencing_token=token, **{**_call_fields(call), "status": "stale_owner"}))
            return "stale_owner"
        if call:
            mc = ModelCall(workspace_id=workspace_id, application_id=row.application_id, release_id=row.release_id, phase=row.phase,
                           input_refs=[row.request["refs"]], job_ref=result_id, fencing_token=token, **_call_fields(call))
            s.add(mc)
            s.flush()
            row.model_call_id = mc.id
        if retry and row.attempts >= MAX_ATTEMPTS:
            status = "unavailable"
        row.status, row.error, row.updated_at, row.lease_owner = status, error, now(), None
        if output is not None:
            row.output = output
        if spans is not None:
            row.supporting_spans = spans
        if unknowns is not None:
            row.unknowns = unknowns
        if route is not None:
            row.versions = {**row.versions, "provider": route.provider, "model": route.model, "route": route.reason,
                            "qualification": (route.qualification or {}).get("id")}
        if status == "pending":
            s.add(Outbox(workspace_id=workspace_id, kind="ai_phase", ref_id=result_id))
        return status


def _call_fields(call: dict) -> dict:
    return {k: call.get(k) for k in ("provider", "model", "request_id", "prompt_version", "schema_version", "input_sha256", "status",
                                     "validation", "usage", "latency_ms")} | {"provider": call.get("provider") or "none", "model": call.get("model") or "none"}


# ---------------- review ----------------

def review(s, row: AiResult, *, decision: str, reviewer: str, note: str) -> dict:
    """Accepting a proposal only creates further proposals (edges, profile revisions) that keep their own reviews."""
    if row.status not in ("proposed", "review_required"):
        raise AiError("invalid_state", f"result is {row.status}")
    if row.requested_by == reviewer:
        raise AiError("separation_of_duties", "the requester cannot review this proposal")
    effects = {}
    if decision == "reject":
        row.status = "rejected"
    else:
        if row.status == "review_required" and row.phase not in ("D", "G"):  # D/G signals are advisory and may be acknowledged
            raise AiError("unsupported_claims", "a result with unsupported claims can only be rejected; request it again")
        row.status = "accepted"
        app = s.get(Application, row.application_id)
        if row.phase == "B":
            created = 0
            for link in row.output.get("links", []):
                exists = s.scalars(select(DependencyEdge).where(DependencyEdge.application_id == app.id, DependencyEdge.test_id == link["test_id"],
                                                                DependencyEdge.component_id == link["component_id"])).first()
                if exists is None:
                    s.add(DependencyEdge(workspace_id=app.workspace_id, application_id=app.id, test_id=link["test_id"], component_id=link["component_id"],
                                         status="proposed", source="ai", rationale=f"phase B proposal {row.id}: {link['rationale']}", reviewer=None))
                    created += 1
            effects["edges_proposed"] = created
        if row.phase == "C":
            p = try_for_application(s, app.id)
            if p is None:
                raise AiError("no_profile", "activate a profile before adding proposed tests")
            from assureops_domain.models import ApplicationProfile

            active = s.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == app.id, ApplicationProfile.status == "active")).first()
            raw = json.loads(json.dumps(active.profile))
            for i, t in enumerate(row.output.get("tests", []), start=1):
                raw["tests"].append({"id": f"AI-{row.id[-6:]}-{i}", "control": t["control"], "severity": t.get("severity", "medium"), "trials": 1,
                                     "name": t["name"], "expected": f"proposed by phase C ({row.id}); reviewer must confirm the expectation",
                                     "template": t["template"], "args": t["args"], "requires_review": True})
            major, minor, patch = (int(x) for x in raw["version"].split("."))
            raw["version"] = f"{major}.{minor + 1}.0"
            revision = connections.propose_profile(s, app, raw, source="ai", actor=f"ai:{row.id}")
            effects["profile_revision_proposed"] = revision.revision
    row.reviewer, row.review_note, row.updated_at = reviewer, note, now()
    cases.audit(s, workspace_id=row.workspace_id, actor=reviewer, actor_kind="customer", action=f"ai.{decision}", target=row.id, detail=effects)
    return effects


def result_json(row: AiResult) -> dict:
    return {"id": row.id, "phase": row.phase, "phase_name": PHASES[row.phase].name, "status": row.status, "output": row.output,
            "supporting_spans": row.supporting_spans, "unknowns": row.unknowns, "versions": row.versions, "attempts": row.attempts,
            "error": row.error, "reviewer": row.reviewer, "review_note": row.review_note, "requested_by": row.requested_by,
            "refs": row.request.get("refs"), "model_call_id": row.model_call_id, "created_at": row.created_at, "updated_at": row.updated_at}


def operations_summary() -> dict:
    with platform_session() as s:
        workspaces = [w.id for w in s.scalars(select(Workspace))]
    counts: dict[str, int] = {}
    for ws in workspaces:
        with tenant_session(ws) as s:
            for status, n in s.execute(select(AiResult.status, func.count()).group_by(AiResult.status)):
                counts[status] = counts.get(status, 0) + n
    enabled = sum(1 for r in route_table(None) if r["enabled"])
    return {"routes_enabled": enabled, "jobs": counts,
            "note": "Models only propose; unavailable phases leave work with reviewers." if not enabled else "Qualified routes active; outputs await review."}
