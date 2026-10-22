"""End-to-end journey for an HTTP lab application through the real API route handlers.

    python scripts/lab_journey.py --app refunddesk-demo --name RefundDesk --lab-readme <lab>/README.md
    python scripts/lab_journey.py --app docvault-demo --name DocVault --lab-readme <lab>/README.md
    python scripts/lab_journey.py --app refunddesk-ai --connection refunddesk-demo --name RefundDesk --lab-readme <lab>/README.md --ai-plan

With --ai-plan no profile file is used: the application is registered with its declared purpose, the developer
requests phases A and C, a reviewer accepts each proposal, the developer builds the test plan from the accepted
proposals and a reviewer activates it. The journey then verifies the connection and runs the R1 assessment.

Steps (integration plan §5 acceptance): connect -> verify -> profile proposed by a
developer and activated by a reviewer -> R1 full assessment -> R2 deployed: show
stale evidence and run the dependency-driven retest, preserving observed
failures -> live (non-test) traffic through the event bridge -> R3 deployed and
retested -> staff evidence review, incident closure, draft and independent
publication. Route handlers are called directly as the seeded users (the
portals call the same handlers over HTTP with OIDC tokens).
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assureops_api import routes_customer as rc  # noqa: E402
from assureops_api import routes_handoffs as rh  # noqa: E402
from assureops_api import routes_onboarding as ro  # noqa: E402
from assureops_api import routes_staff as rs  # noqa: E402
from assureops_api.auth import Caller  # noqa: E402
from assureops_domain.db import platform_session, tenant_session  # noqa: E402
from assureops_domain.models import (  # noqa: E402
    Application, Assessment, AssessmentCase, CaseAssignment, Incident, Membership, Report, StaffRole, User,
)

API = "http://127.0.0.1:8700"


def customer(username: str) -> Caller:
    with platform_session() as s:
        u = s.scalars(select(User).where(User.username == username)).one()
        m = {x.workspace_id: x.role for x in s.scalars(select(Membership).where(Membership.user_id == u.id))}
    ws = next(iter(m))
    return Caller(u.id, u.username, u.display_name, "customer", workspace_id=ws, role=m[ws], memberships=m)


def staff(username: str) -> Caller:
    with platform_session() as s:
        u = s.scalars(select(User).where(User.username == username)).one()
        roles = {r.role for r in s.scalars(select(StaffRole).where(StaffRole.user_id == u.id))}
    return Caller(u.id, u.username, u.display_name, "staff", staff_roles=roles)


def step(title: str):
    print(f"\n== {title}")


def gate_line(state: dict) -> str:
    g, sc = state["gate"], state["scores"]
    return (f"gate {g['status']} | support {sc['evidence_support_pct']}% coverage {sc['evidence_coverage_pct']}% | "
            f"assessed {sc['controls_assessed']}/{sc['controls_total']} controls | {g['reason']}")


def wait_for(job_id: str, ws: str, timeout: int = 600) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with tenant_session(ws) as s:
            job = s.get(Assessment, job_id)
            if job.status not in ("queued", "running"):
                return {"status": job.status, "error": job.error}
        time.sleep(2)
    raise SystemExit(f"assessment {job_id} did not finish within {timeout}s")


def ai_phase(app_id: str, phase: str, requester: Caller, reviewer: Caller, timeout: int = 3600) -> dict:
    """Request one phase as the developer, wait for the model, and have a different person accept a valid proposal."""
    from assureops_api import ai_routes
    from assureops_domain.models import AiResult

    row = ai_routes.request_phase(app_id, phase, ai_routes.PhaseIn(), caller=requester)
    started, deadline = time.time(), time.time() + timeout
    while time.time() < deadline:
        with tenant_session(requester.workspace_id) as s:
            result = s.get(AiResult, row["id"])
            status, output, error = result.status, result.output, result.error
        if status not in ("pending", "running"):
            break
        time.sleep(5)
    print(f"  phase {phase}: {status} after {round(time.time() - started)} s{(' (' + error + ')') if error else ''}")
    if status != "proposed":
        raise SystemExit(f"phase {phase} produced no acceptable proposal ({status}); rerun or build the plan by hand")
    ai_routes.review_result(row["id"], ai_routes.AiReviewIn(decision="accept", note=f"Reviewed the phase {phase} proposal"), caller=reviewer)
    return output


def lab_switch(conn_cfg: dict, actors: dict, release: str):
    r = httpx.post(f"{conn_cfg['config']['base_url']}/admin/release", json={"release": release},
                   headers={"Authorization": f"Bearer {actors['lab_admin']}"}, timeout=5)
    r.raise_for_status()


def results(state: dict) -> str:
    rows = [f"{t['test_id']}={t['result']}/{t['validity']}{'(reused)' if t.get('reused') else ''}" for t in state["tests"]]
    return ", ".join(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--lab-readme", required=True)
    parser.add_argument("--live-traffic", default=None, help="JSON file with one live (non-test) request to send on R2")
    parser.add_argument("--connection", default=None, help="connection file name under profiles/connections (default: --app)")
    parser.add_argument("--ai-plan", action="store_true", help="build the test plan with phases A and C instead of a profile file")
    parser.add_argument("--purpose", default=None, help="declared application purpose (phase A reads it when no document is added)")
    parser.add_argument("--source-file", default=None, help="policy or requirements text a reviewer approves as phase A's reference source")
    args = parser.parse_args()

    actors_file = ROOT / "var" / "demo-actors" / f"{args.app}.json"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_actor_tokens.py"), "--readme", args.lab_readme, "--out", str(actors_file)], check=True)
    actors = json.loads(actors_file.read_text(encoding="utf-8"))
    conn_name = args.connection or args.app
    conn_cfg = json.loads((ROOT / "profiles" / "connections" / f"{conn_name}.json").read_text(encoding="utf-8"))
    conn_cfg["config"] = {k: v for k, v in conn_cfg["config"].items() if v is not None}
    profile_file = ROOT / "profiles" / "applications" / f"{args.app}.json"
    raw_profile = None if args.ai_plan else json.loads(profile_file.read_text(encoding="utf-8"))
    purpose = args.purpose or (raw_profile["scope"]["statement"] if raw_profile else f"{args.name}, an AI application under assessment")
    owner, dev, reviewer = customer("owner@acme.test"), customer("dev@acme.test"), customer("reviewer@acme.test")
    analyst, senior, manager = staff("analyst@assureops.test"), staff("reviewer@assureops.test"), staff("manager@assureops.test")
    ws = owner.workspace_id
    lab_switch(conn_cfg, actors, "R1")

    step("1. Register and connect the application")
    with tenant_session(ws) as s:
        exists = s.get(Application, args.app) is not None
    if not exists:
        rc.register_application(rc.ApplicationIn(id=args.app, name=args.name, purpose=purpose, environment="staging",
                                                 mode="observe_only"), caller=owner)
    rh.assign_application_developer(args.app, dev.username, caller=owner)  # the owner assigns the developer to this application
    conn = ro.create_connection(args.app, ro.ConnectionIn(adapter_id=conn_cfg["adapter_id"], config=conn_cfg["config"],
                                                          actors={a: ro.ActorCredentialIn(secret_value=actors[a]) for a in conn_cfg["actors"]}), caller=dev)
    print(f"connection r{conn['revision']} {conn['adapter_id']} status={conn['status']}; credentials stored as fingerprints "
          f"{sorted(v['secret']['fingerprint'] for v in conn['actors'].values())[:2]}...")

    step("2. Profile: proposed by the developer, activated by a different reviewer")
    if args.ai_plan:
        from assureops_api import ai_routes

        if args.source_file:
            src = ai_routes.add_source(args.app, ai_routes.SourceIn(title=f"{args.name} policy", kind="policy",
                                                                    text=Path(args.source_file).read_text(encoding="utf-8")), caller=reviewer)
            print(f"  reference source approved by {reviewer.username}: {src['id']} (sha256 {src['sha256'][:12]})")
        reqs = ai_phase(args.app, "A", dev, reviewer)
        print(f"  requirements: {[(r['control'], r['statement'][:60]) for r in reqs.get('requirements', [])]}")
        tests = ai_phase(args.app, "C", dev, reviewer)
        print(f"  proposed tests: {[(t['control'], t['template'], t['name'][:50]) for t in tests.get('tests', [])]}")
        built = ai_routes.build_ai_plan(args.app, caller=dev)
        print(f"  plan r{built['revision']}: {built['plan']['tests']} tests on {built['plan']['controls_tested']}, "
              f"not assessed {built['plan']['controls_not_assessed']}, skipped {built['plan']['skipped']}")
        proposed = built
    else:
        proposed = ro.propose_profile(args.app, ro.ProfileIn(profile=raw_profile), caller=dev)
    try:
        ro.activate_profile(args.app, proposed["revision"], ro.ProfileDecisionIn(note="self-activation attempt"), caller=dev)
        print("ERROR: proposer activated their own profile")
    except Exception as exc:
        print(f"proposer self-activation refused: {getattr(exc, 'detail', exc)}")
    active = ro.activate_profile(args.app, proposed["revision"], ro.ProfileDecisionIn(note="Reviewed against the lab source and connector.json"),
                                 caller=reviewer)
    print(f"profile r{active['revision']} active: assessed {active['assessed_controls']}, not assessed {active['unassessed_controls']}")

    step("3. Verify connection (destination, health, manifest, ownership, credentials, events, profile scope)")
    verified = ro.verify_connection(args.app, caller=dev)
    for c in verified["verification"]["checks"]:
        print(f"  {c['id']:15} {c['status']:5} {c['detail']}")
    print(f"  gaps: {verified['verification']['gaps']}")
    if verified["status"] != "verified":
        raise SystemExit("connection not verified")

    step("4. Event source credential and bridge")
    source_id = f"{args.app.split('-')[0]}-bridge-1"
    token_file = ROOT / "var" / "bridge" / f"{source_id}.token"
    try:
        src = ro.create_event_source(args.app, ro.EventSourceIn(source_id=source_id, kind="application"), caller=owner)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(src["token"], encoding="utf-8")
        print(f"source {source_id} issued (token saved to {token_file.relative_to(ROOT)}, not shown)")
    except Exception as exc:
        print(f"source {source_id}: {getattr(exc, 'detail', exc)}")
    bridge_cmd = [sys.executable, "-m", "assureops_connectors.bridge", "--api", API, "--source-id", source_id, "--source-token-file", str(token_file),
                  "--connection", str(ROOT / "profiles" / "connections" / f"{conn_name}.json"), "--actors-file", str(actors_file), "--once"]

    def bridge():
        out = subprocess.run(bridge_cmd, capture_output=True, text=True, cwd=ROOT)
        print("  bridge:", (out.stdout.strip() or out.stderr.strip() or "no new events")[-300:])

    step("5. Customer submits a case; manager assigns analyst and an independent reviewer")
    case = rc.submit_case(rc.CaseIn(application_id=args.app, title=f"{args.name} readiness assessment", scope_note="Staging lab R1-R3"), caller=dev)
    case_id = case["id"]
    rs.assign(case_id, rs.AssignIn(staff_user="analyst@assureops.test", duty="analyst"), caller=manager)
    rs.assign(case_id, rs.AssignIn(staff_user="reviewer@assureops.test", duty="reviewer"), caller=manager)
    with tenant_session(ws) as s:
        print(f"case {case_id} state {s.get(AssessmentCase, case_id).state}")

    def assess(release: str, scope: str):
        lab_switch(conn_cfg, actors, release)
        submitted = rc.submit_release(args.app, caller=dev)
        print(f"release {submitted['release']['version']} collected (created={submitted['created']}, gaps={submitted['gaps']})")
        if submitted.get("change_id"):
            change = rc.get_change(submitted["change_id"], caller=dev)
            print(f"  change vs previous: {[c['component'] for c in change['changes']]}; retest {len(change['retest'])}, reuse {len(change['reusable'])} "
                  f"{change['reusable']}; fallback={change['conservative_fallback']}")
            before = rc.application_readiness(args.app, caller=dev)
            print(f"  before retest: {gate_line(before)}")
            stale = [t["test_id"] for t in before["tests"] if t["validity"] == "stale"]
            print(f"  stale evidence: {stale}")
            job = rs.staff_assessment(case_id, rs.StaffAssessmentIn(scope="retest"), caller=analyst, idempotency_key=None)
        else:
            job = rs.staff_assessment(case_id, rs.StaffAssessmentIn(scope=scope), caller=analyst, idempotency_key=None)
        print(f"  assessment {job['id']} running {len(job['tests'])} tests in isolated runners...")
        done = wait_for(job["id"], ws)
        state = rc.application_readiness(args.app, caller=dev)
        print(f"  job {done['status']}{(' (' + done['error'] + ')') if done['error'] else ''}")
        print(f"  {gate_line(state)}")
        print(f"  tests: {results(state)}")
        return state

    step("6. R1 full assessment")
    assess("R1", "full")
    if args.ai_plan:
        print("\nAI-built plan journey complete: the plan came from accepted phase A and C proposals, not from a profile file.")
        return
    bridge()

    step("7. R2 deployed (seeded fault): stale evidence, dependency-driven retest, failures preserved")
    r2 = assess("R2", "retest")
    findings = rc.list_findings(args.app, caller=dev)
    print(f"  findings: {[(f['test_id'] or f['control'], f['severity'], f['state']) for f in findings]}")
    bridge()
    if args.live_traffic:
        live = json.loads(Path(args.live_traffic).read_text(encoding="utf-8"))
        r = httpx.request(live["method"], conn_cfg["config"]["base_url"] + live["path"], json=live.get("body"),
                          headers={"Authorization": f"Bearer {actors[live['actor']]}"}, timeout=5)
        print(f"  live (non-test) request as {live['actor']}: HTTP {r.status_code}")
        bridge()
        with tenant_session(ws) as s:
            incs = s.scalars(select(Incident).where(Incident.application_id == args.app)).all()
            print(f"  incidents: {[(i.control_id, i.state, i.cohort, i.title) for i in incs]}")

    step("8. R3 deployed (fix): retest")
    r3 = assess("R3", "retest")
    bridge()

    step("9. Staff review: evidence needing review, incidents, draft and independent publication")
    for t in r3["tests"]:
        if t["result"] == "review_required":
            rs.review_evidence(case_id, rs.EvidenceReviewIn(run_id=t["run_id"], decision="accept",
                                                            note="Recorded answer and citation match the expectation"), caller=senior)
            print(f"  evidence {t['test_id']} accepted by senior reviewer")
    with tenant_session(ws) as s:
        open_incidents = [(i.id, i.revision) for i in s.scalars(select(Incident).where(Incident.application_id == args.app, Incident.state == "open"))]
    for iid, rev in open_incidents:
        out = rs.close(iid, rs.CloseIn(case_id=case_id, note="R3 fix verified by current passing retest evidence", expected_revision=rev), caller=senior)
        print(f"  incident {iid} {out['state']}")
    state = rc.application_readiness(args.app, caller=dev)
    print(f"  {gate_line(state)}")
    draft = rs.draft_report(case_id, caller=analyst)
    try:
        rs.review_report(case_id, rs.ReviewIn(report_id=draft["id"], decision="publish", reason="self", expected_revision=1), caller=analyst)
    except Exception as exc:
        print(f"  drafter self-publication refused: {getattr(exc, 'detail', exc)}")
    with tenant_session(ws) as s:
        rev = s.get(Report, draft["id"]).revision
    published = rs.review_report(case_id, rs.ReviewIn(report_id=draft["id"], decision="publish",
                                                       reason="Snapshot matches current evidence; unassessed controls are disclosed", expected_revision=rev),
                                 caller=senior)
    print(f"  report {published['report_id']} {published['state']}; case {published['case_state']}")
    report = rc.get_report(published["report_id"], caller=dev)
    snap = report["snapshot"]
    print(f"  customer report: integrity {report['integrity']}, release {snap['release']['version']}, profile {snap['profile']}, "
          f"not assessed {[c['id'] for c in snap['unassessed_controls']]}")
    print("\nJOURNEY COMPLETE")


if __name__ == "__main__":
    main()
