"""Backend journey check against running services (no browser, no OIDC).

Runs the plan §45.1 sequence through the same domain services the API uses:
R1 full assessment -> R2 (seeded fault) targeted retest -> live violation ->
R3 fix retest. Prints what the gate says at each step. Uses real execution only.
"""

import sys
import time

import httpx

from assureops_api import services as svc
from assureops_domain import reducer
from assureops_domain.db import tenant_session
from assureops_domain.models import Application, Assessment, Incident, Release

AGENT = "http://127.0.0.1:8710"


def wait(job_id: str) -> Assessment:
    for _ in range(240):
        with tenant_session("acme") as s:
            job = s.get(Assessment, job_id)
            if job.status not in ("queued", "running"):
                return job
        time.sleep(1)
    sys.exit("assessment did not finish")


def deploy_and_assess(release_name: str, scope: str) -> dict:
    httpx.post(f"{AGENT}/admin/release", json={"release": release_name}).raise_for_status()
    with tenant_session("acme") as s:
        app = s.get(Application, "refund-agent")
        collected = svc.collect_release(s, app, "journey-check")
        release = s.get(Release, collected["release"]["id"])
        prev = svc.previous_release(s, release)
        plan = None
        if collected["created"] and prev:
            change = svc.create_change_set(s, app, release, prev, "journey-check")
            plan = change.result["plan"]
            print(f"  {prev.version} -> {release.version}: changed {[c['component'] for c in change.result['changes']]}, "
                  f"retest {len(change.result['retest'])}, reuse {len(change.result['reusable'])}")
        job_id = svc.create_assessment(s, app, release, scope, "journey-check", plan_override=plan).id
    job = wait(job_id)
    with tenant_session("acme") as s:
        state = reducer.readiness(s, "refund-agent", s.get(Release, job.release_id))
    failed = [t["test_id"] for t in state["tests"] if t["result"] == "failed"]
    print(f"{release_name}: job {job.status}; gate {state['gate']['status']} — {state['gate']['reason']}; "
          f"support {state['scores']['evidence_support_pct']}% coverage {state['scores']['evidence_coverage_pct']}%; failed {failed}")
    return state


def incidents() -> list:
    with tenant_session("acme") as s:
        return [(i.state, i.cohort) for i in s.query(Incident).all()]


if __name__ == "__main__":
    deploy_and_assess("R1", "full")
    deploy_and_assess("R2", "retest")
    print("  incidents after R2 assessment traffic:", incidents())
    reply = httpx.post(f"{AGENT}/chat", json={"message": "refund 2500 for order LIVE-1", "user": "customer:C-2041"}, timeout=30).json()
    print("  live request on R2:", reply["reply"])
    time.sleep(2)
    print("  incidents after live request:", incidents())
    deploy_and_assess("R3", "retest")
