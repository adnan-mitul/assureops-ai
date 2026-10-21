"""200-scenario change benchmark: full retest vs reviewed rule-only map vs AI-assisted map (plan v6 P10).

    python scripts/change_benchmark_200.py [--limit N] [--split held_out]

Runs on an isolated copy of the reference stack (workspace "bench", application "refund-bench",
agent :8716, tool server :8726, own state and credentials), so the reference application's
history, findings and incidents are untouched.

For every scenario in profiles/qualification/change-scenarios-v1.json it builds the variant
release from R1, deploys it, collects the manifest and computes which tests each arm would
retest:
  full      every test;
  rule      the reviewed coverage-contract edges with the platform's own conservative rules
            (unmapped change or partial collection -> retest everything);
  ai        the reviewed edges plus the links phase B (Phi-4-mini) proposed once for this
            application, under the same rules.
It then runs a full assessment through the normal worker. Ground truth: a test is affected
when its outcome differs from the R1 baseline. The baseline runs twice, and tests that differ
between the two baseline runs are flaky and excluded. Reported per arm and split: tests
retested, misses, critical misses (critical-severity misses) and false alarms. The 30 %
saving is a research target, not an assumption: the numbers are what they are.

Results: var/benchmarks/change-benchmark-200.json (counts only, no evidence content).
"""

import argparse
import copy
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import select

from assureops_ai import router, service
from assureops_api import services as svc
from assureops_domain import connections, reducer
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import (
    AiResult, Application, ApplicationProfile, Assessment, EventSource, Release, ServiceCredential, TestRun, Workspace,
)
from assureops_domain.profile import load_profile_file

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from change_scenarios import apply  # noqa: E402

WS, APP = "bench", "refund-bench"
AGENT_PORT, TOOLS_PORT = 8716, 8726
STATE = ROOT / "var" / "bench-reference"
VARIANTS = STATE / "releases"
R1 = ROOT / "packages" / "integrations" / "mcp" / "assureops_mcp" / "agent" / "releases" / "R1"
AGENT = f"http://127.0.0.1:{AGENT_PORT}"
OUT = ROOT / "var" / "benchmarks" / "change-benchmark-200.json"


def h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_stack() -> list[subprocess.Popen]:
    """Fresh credentials every run (hashes stored, tokens only in these processes' environments)."""
    tokens = {k: "aobench_" + secrets.token_urlsafe(24) for k in ("gateway", "tool_server", "agent_src", "tools_src")}
    with platform_session() as p:
        ws = p.get(Workspace, WS) or Workspace(id=WS, name="Change benchmark (isolated)")
        ws.assessments_per_day = 2000  # this isolated workspace runs one full assessment per scenario
        p.add(ws)
        for c in p.scalars(select(ServiceCredential).where(ServiceCredential.workspace_id == WS)):
            c.revoked = True
        for kind in ("gateway", "tool_server"):
            p.add(ServiceCredential(kind=kind, workspace_id=WS, application_id=APP, environment="staging", token_hash=h(tokens[kind])))
        for sid, kind, key in (("bench-agent-1", "agent", "agent_src"), ("bench-tools-1", "tool_server", "tools_src")):
            src = p.get(EventSource, sid) or EventSource(id=sid, workspace_id=WS, application_id=APP, environment="staging", kind=kind, token_hash="")
            src.token_hash, src.revoked = h(tokens[key]), False
            p.add(src)
    with tenant_session(WS) as s:
        if s.get(Application, APP) is None:
            s.add(Application(id=APP, workspace_id=WS, name="Refund agent (benchmark copy)", purpose="Change benchmark", environment="staging",
                              mode="enforce_supported_actions", target_url=AGENT, tools_url=f"http://127.0.0.1:{TOOLS_PORT}/mcp", authorized_scope={}))
    VARIANTS.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "REFERENCE_VAR_DIR": str(STATE), "TOOLS_PORT": str(TOOLS_PORT), "TOOLS_MCP_URL": f"http://127.0.0.1:{TOOLS_PORT}/mcp",
           "GATEWAY_SERVICE_TOKEN": tokens["gateway"], "TOOLS_SERVICE_TOKEN": tokens["tool_server"], "AGENT_SOURCE_TOKEN": tokens["agent_src"],
           "TOOLS_SOURCE_TOKEN": tokens["tools_src"], "AGENT_SOURCE_ID": "bench-agent-1", "TOOLS_SOURCE_ID": "bench-tools-1",
           "AGENT_EXTRA_RELEASES": str(VARIANTS)}
    logs = ROOT / "var" / "logs"
    procs = [subprocess.Popen([sys.executable, "-m", "assureops_mcp.tool_server"], env=env, stdout=open(logs / "bench-tools.log", "w"), stderr=subprocess.STDOUT)]
    time.sleep(3)
    procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "assureops_mcp.agent.app:app", "--port", str(AGENT_PORT)], env=env,
                                  stdout=open(logs / "bench-agent.log", "w"), stderr=subprocess.STDOUT))
    for _ in range(60):
        try:
            if httpx.get(f"{AGENT}/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(1)
    return procs


def ensure_connection_and_profile():
    deploy("R1")
    with tenant_session(WS) as s:
        app = s.get(Application, APP)
        conn = connections.latest_connection(s, APP)
        if conn is None:
            conn = connections.create_connection(s, app, adapter_id="assureops-mcp-reference", actor="bench-dev", config={
                "base_url": AGENT, "tools_url": f"http://127.0.0.1:{TOOLS_PORT}/mcp", "environment": "staging",
                "manifest_path": "/manifest", "health_path": "/health", "ownership": {"method": "manifest_application"}})
        if s.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == APP, ApplicationProfile.status == "active")).first() is None:
            row = connections.propose_profile(s, app, load_profile_file("refund-agent"), source="file", actor="bench-dev")
            connections.activate_profile(s, app, row.revision, reviewer="bench-reviewer", note="reference profile for the change benchmark")
        connections.verify(s, app, conn, svc.app_profile(s, APP))
        return conn.status


def sync_edges() -> int:
    """Benchmark only: make the isolated bench application's accepted edges equal the contract file (after a reviewed edit)."""
    from assureops_domain.models import DependencyEdge
    from assureops_domain.profile import load_coverage_contract

    contract = load_coverage_contract("refund-agent.mcp-reference")["dependency_edges"]
    with tenant_session(WS) as s:
        for row in s.scalars(select(DependencyEdge).where(DependencyEdge.application_id == APP)):
            s.delete(row)
        s.flush()
        n = 0
        for test_id, comps in contract.items():
            for comp in comps:
                s.add(DependencyEdge(workspace_id=WS, application_id=APP, test_id=test_id, component_id=comp, status="accepted",
                                     source="coverage_contract", reviewer="bench-reviewer"))
                n += 1
        return n


def deploy(name: str):
    httpx.post(f"{AGENT}/admin/release", json={"release": name}, timeout=10).raise_for_status()


def write_variant(sid: str, operators: list[str]):
    cfg = {n: json.loads((R1 / f"{n}.json").read_text()) for n in ("permission_policy", "tool_allowlist", "limits", "security", "model")}
    cfg["system_prompt"] = (R1 / "system_prompt.txt").read_text()
    for op in operators:
        apply(op, cfg)
    folder = VARIANTS / sid
    folder.mkdir(parents=True, exist_ok=True)
    for n in ("permission_policy", "tool_allowlist", "limits", "security", "model"):
        (folder / f"{n}.json").write_text(json.dumps(cfg[n], indent=2))
    (folder / "system_prompt.txt").write_text(cfg["system_prompt"])


def collect() -> Release:
    with tenant_session(WS) as s:
        out = svc.collect_release(s, s.get(Application, APP), "change-benchmark")
        return s.get(Release, out["release"]["id"])


def assess(release: Release) -> dict[str, str]:
    with tenant_session(WS) as s:
        job_id = svc.create_assessment(s, s.get(Application, APP), s.get(Release, release.id), "full", "change-benchmark").id
    while True:
        with tenant_session(WS) as s:
            job = s.get(Assessment, job_id)
            if job.status not in ("queued", "running"):
                return {r.test_id: r.outcome for r in s.scalars(select(TestRun).where(TestRun.assessment_id == job_id))}
        time.sleep(2)


def ai_links(release: Release) -> set[tuple[str, str]]:
    """Phase B once on the baseline release; every proposed link is taken as accepted (an upper bound of AI help)."""
    with tenant_session(WS) as s:
        rid = service.request(s, s.get(Application, APP), "B", {"release_id": release.id}, "change-benchmark").id
    for _ in range(service.MAX_ATTEMPTS + 1):
        if service.execute(WS, rid) not in ("pending",):
            break
    with tenant_session(WS) as s:
        row = s.get(AiResult, rid)
        links = {(x["test_id"], x["component_id"]) for x in (row.output or {}).get("links", [])}
        print(f"phase B ({(row.versions or {}).get('model')}): {row.status}, {len(links)} links proposed")
        return links


def selection(edges: dict[str, set[str]], tests: list[dict], base: Release, target: Release) -> set[str]:
    """The platform's change rule (reducer.compare) applied to a given edge map."""
    changed = {c["component"] for c in reducer.diff_components(base, target)}
    mapped = {c for comps in edges.values() for c in comps}
    if (changed - mapped) or target.collection_gaps:
        return {t["id"] for t in tests}
    return {t["id"] for t in tests if not edges.get(t["id"]) or t.get("mandatory") or changed & edges[t["id"]]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--split", choices=["development", "held_out"], default=None)
    parser.add_argument("--sync-edges", action="store_true", help="reset the bench application's reviewed edges to the coverage contract file")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    spec = json.loads((ROOT / "profiles" / "qualification" / "change-scenarios-v1.json").read_text())
    scenarios = [s for s in spec["scenarios"] if not args.split or s["split"] == args.split][: args.limit]
    procs = start_stack()
    try:
        print("connection:", ensure_connection_and_profile())
        if args.sync_edges:
            print("reviewed edges synced from the coverage contract:", sync_edges())
        base = collect()
        base_a, base_b = assess(base), assess(base)
        flaky = {t for t in base_a if base_a.get(t) != base_b.get(t)}
        with tenant_session(WS) as s:
            p = svc.app_profile(s, APP)
            reviewed = {k: set(v) for k, v in reducer.accepted_edges(s, APP, p).items()}
        tests = p["tests"]
        severity = {t["id"]: t["severity"] for t in tests}
        ai = copy.deepcopy(reviewed)
        for test_id, comp in ai_links(base):
            if test_id in severity:
                ai.setdefault(test_id, set()).add(comp)
        print(f"baseline: {sum(v == 'passed' for v in base_a.values())}/{len(base_a)} passed; flaky {sorted(flaky)}")
        rows, started = [], time.time()
        for i, sc in enumerate(scenarios, 1):
            write_variant(sc["id"], sc["operators"])
            deploy(sc["id"])
            target = collect()
            truth = assess(target)
            affected = {t for t in truth if t not in flaky and truth.get(t) != base_a.get(t)}
            row = {"id": sc["id"], "operators": sc["operators"], "split": sc["split"], "affected": sorted(affected)}
            for arm, chosen in (("full", {t["id"] for t in tests}), ("rule", selection(reviewed, tests, base, target)),
                                ("ai", selection(ai, tests, base, target))):
                missed = affected - chosen
                row[arm] = {"retested": len(chosen), "missed": sorted(missed), "critical_missed": sorted(m for m in missed if severity[m] == "critical"),
                            "false_alarms": len(chosen - affected)}
            rows.append(row)
            print(f"[{i}/{len(scenarios)}] {sc['id']} {'+'.join(sc['operators'])}: affected {len(affected)}; "
                  f"rule {row['rule']['retested']} (miss {len(row['rule']['missed'])}), ai {row['ai']['retested']} (miss {len(row['ai']['missed'])})", flush=True)
        summary = {}
        for split in ("development", "held_out"):
            part = [r for r in rows if r["split"] == split]
            if not part:
                continue
            summary[split] = {"scenarios": len(part), **{arm: {
                "tests_retested": sum(r[arm]["retested"] for r in part),
                "misses": sum(len(r[arm]["missed"]) for r in part),
                "critical_misses": sum(len(r[arm]["critical_missed"]) for r in part),
                "false_alarms": sum(r[arm]["false_alarms"] for r in part),
                "saving_vs_full_pct": round(100 * (1 - sum(r[arm]["retested"] for r in part) / sum(r["full"]["retested"] for r in part)), 1),
            } for arm in ("full", "rule", "ai")}}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"at": time.time(), "minutes": round((time.time() - started) / 60, 1), "flaky_excluded": sorted(flaky),
                                   "ai_model": router.resolve("B", False).model, "summary": summary, "scenarios": rows}, indent=1), encoding="utf-8")
        print(json.dumps(summary, indent=1))
    finally:
        for proc in procs:
            proc.terminate()


if __name__ == "__main__":
    main()
