"""Assess the model-driven reference release (L1: a real local LLM chooses tool calls) with the reference profile.

    python scripts/model_target_check.py            # deploy L1, full assessment, compare with deterministic R1 if assessed
    python scripts/model_target_check.py --restore R1

Unlike the deterministic fixtures, the outcome here is what the model actually did under the same
gateway and the same 15 tests. Results (per test, no evidence content) go to
var/benchmarks/model-target-L1.json. Requires the backend services, the assessment worker and
the private inference host (Ollama) to be running.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

from assureops_api import services as svc
from assureops_domain import reducer
from assureops_domain.db import tenant_session
from assureops_domain.models import Application, Assessment, Release

ROOT = Path(__file__).resolve().parent.parent
AGENT = "http://127.0.0.1:8710"


def wait(job_id: str, limit_s: int = 7200) -> Assessment:
    started = time.time()
    while time.time() - started < limit_s:
        with tenant_session("acme") as s:
            job = s.get(Assessment, job_id)
            if job.status not in ("queued", "running"):
                return job
        time.sleep(5)
    sys.exit("assessment did not finish in time")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", default=None, help="release to redeploy afterwards (for example R1)")
    args = parser.parse_args()
    httpx.post(f"{AGENT}/admin/release", json={"release": "L1"}).raise_for_status()
    model = httpx.get(f"{AGENT}/manifest", timeout=30).json()
    with tenant_session("acme") as s:
        app = s.get(Application, "refund-agent")
        collected = svc.collect_release(s, app, "model-target-check")
        release = s.get(Release, collected["release"]["id"])
        job_id = svc.create_assessment(s, app, release, "full", "model-target-check").id
    print(f"L1 collected as {release.version} ({len(model['components'])} components); assessment {job_id} queued")
    started = time.time()
    job = wait(job_id)
    with tenant_session("acme") as s:
        p = svc.app_profile(s, "refund-agent")
        state = reducer.readiness(s, "refund-agent", s.get(Release, job.release_id), p)
    tests = [{"test_id": t["test_id"], "control": t["control"], "name": t["name"], "result": t["result"], "trials": t.get("trials"),
              "passed_trials": t.get("passed_trials")} for t in state["tests"]]
    out = {"release": "L1", "planner": "llm", "model": json.loads((ROOT / "packages/integrations/mcp/assureops_mcp/agent/releases/L1/model.json").read_text())["model"],
           "assessment": job_id, "status": job.status, "minutes": round((time.time() - started) / 60, 1),
           "gate": state["gate"]["status"], "reason": state["gate"]["reason"], "scores": state["scores"], "tests": tests}
    target = ROOT / "var" / "benchmarks" / "model-target-L1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"L1: job {job.status} in {out['minutes']} min; gate {out['gate']}; support {state['scores']['evidence_support_pct']}%")
    for t in tests:
        print(f"  {t['test_id']:<10} {t['control']} {t['result']:<16} {t['passed_trials']}/{t['trials']}  {t['name']}")
    if args.restore:
        httpx.post(f"{AGENT}/admin/release", json={"release": args.restore}).raise_for_status()
        print(f"agent restored to {args.restore}")


if __name__ == "__main__":
    main()
