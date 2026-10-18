"""Change benchmark: dependency-driven retesting versus full retesting on recorded releases (integration plan I8).

    python scripts/change_benchmark.py --app refunddesk-demo [--full-check]

For every recorded change set it reports how many tests the reviewed rule-only
mapping retested versus a full retest, and the measured step time. With
--full-check it runs a full assessment on the latest release and counts
critical misses: tests whose evidence the selective plan reused but which fail
when actually re-run. Reviewer effort is the number of items that needed human
review. Results are appended to var/benchmarks/<app>.json.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "domain"))

from sqlalchemy import select  # noqa: E402

from assureops_api import services as svc  # noqa: E402
from assureops_domain import reducer  # noqa: E402
from assureops_domain.db import tenant_session  # noqa: E402
from assureops_domain.models import Application, Assessment, ChangeSet, EvidenceReview, JobStep, ModelCall, Release, TestRun  # noqa: E402
from assureops_domain.profile import for_application  # noqa: E402


def step_seconds(s, assessment_id: str) -> float:
    steps = s.scalars(select(JobStep).where(JobStep.assessment_id == assessment_id)).all()
    return round(sum((st.finished_at or 0) - (st.started_at or 0) for st in steps if st.started_at and st.finished_at), 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    parser.add_argument("--workspace", default="acme")
    parser.add_argument("--full-check", action="store_true")
    args = parser.parse_args()
    ws = args.workspace
    report = {"application": args.app, "at": time.time(), "changes": []}
    with tenant_session(ws) as s:
        p = for_application(s, args.app)
        total = len(p["tests"])
        for c in s.scalars(select(ChangeSet).where(ChangeSet.application_id == args.app, ChangeSet.base_release_id.is_not(None))
                           .order_by(ChangeSet.created_at)):
            r = c.result
            job = s.scalars(select(Assessment).where(Assessment.release_id == c.target_release_id, Assessment.scope == "retest")
                            .order_by(Assessment.created_at)).first()
            report["changes"].append({"base": r["base"], "target": r["target"], "changed": [x["component"] for x in r["changes"]],
                                      "selective_tests": len(r["retest"]), "full_tests": total, "reused": r["reusable"],
                                      "conservative_fallback": r["conservative_fallback"],
                                      "selective_step_seconds": step_seconds(s, job.id) if job else None})
        reviews = s.scalars(select(EvidenceReview).join(TestRun, TestRun.id == EvidenceReview.run_id).where(TestRun.application_id == args.app)).all()
        report["reviewer_items"] = len(reviews)
        report["model_tokens"] = sum((m.usage or {}).get("total_tokens") or 0 for m in s.scalars(select(ModelCall).where(ModelCall.application_id == args.app)))

    if args.full_check:
        with tenant_session(ws) as s:
            app = s.get(Application, args.app)
            release = svc.latest_release(s, app.id)
            before = {t["test_id"]: t for t in reducer.readiness(s, app.id, release, for_application(s, app.id))["tests"]}
            job_id = svc.create_assessment(s, app, release, "full", "benchmark").id
        while True:
            with tenant_session(ws) as s:
                job = s.get(Assessment, job_id)
                if job.status not in ("queued", "running"):
                    break
            time.sleep(2)
        with tenant_session(ws) as s:
            runs = {r.test_id: r for r in s.scalars(select(TestRun).where(TestRun.assessment_id == job_id))}
            misses = [tid for tid, t in before.items() if t.get("reused") and t["result"] == "supported" and runs.get(tid) and runs[tid].outcome == "failed"]
            report["full_check"] = {"release": release.version, "full_tests": len(runs), "full_step_seconds": step_seconds(s, job_id),
                                    "reused_before": [tid for tid, t in before.items() if t.get("reused")],
                                    "critical_misses": misses, "status": job.status}
    out = ROOT / "var" / "benchmarks" / f"{args.app}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    history = json.loads(out.read_text()) if out.exists() else []
    history.append(report)
    out.write_text(json.dumps(history, indent=2))
    for c in report["changes"]:
        saved = 100 * (1 - c["selective_tests"] / c["full_tests"])
        print(f"{c['base']}->{c['target']} changed {c['changed']}: retested {c['selective_tests']}/{c['full_tests']} ({saved:.0f}% fewer), "
              f"step time {c['selective_step_seconds']}s, fallback={c['conservative_fallback']}")
    if "full_check" in report:
        fc = report["full_check"]
        print(f"full re-run on {fc['release']}: {fc['full_tests']} tests, step time {fc['full_step_seconds']}s, "
              f"critical misses among reused evidence: {len(fc['critical_misses'])} {fc['critical_misses']}")
    print(f"reviewer items: {report['reviewer_items']}; model tokens: {report['model_tokens']}")


if __name__ == "__main__":
    main()
