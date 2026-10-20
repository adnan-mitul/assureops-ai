"""Measured load and recovery limits on this deployment (integration plan I8).

    python scripts/load_recovery_check.py load                       # ingestion + gate-check throughput/latency
    python scripts/load_recovery_check.py recovery --app refunddesk-demo   # kill the worker mid-assessment, time recovery

Load uses a throwaway workspace with its own event source and CI credential and
removes them afterwards. Recovery runs a real full assessment against a running
lab, stops the assessment worker after the first steps complete and measures how
long the reconciler needs to finish the job once a worker is back.
Results are appended to var/benchmarks/limits.json.
"""

import argparse
import concurrent.futures
import hashlib
import json
import secrets
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "domain"))

from sqlalchemy import delete, select  # noqa: E402

from assureops_domain.db import platform_session, tenant_session  # noqa: E402
from assureops_domain.models import (  # noqa: E402
    Application, Assessment, AuditEvent, DeploymentReceipt, EventSource, JobStep, RuntimeEvent, ServiceCredential, Workspace,
)

API = "http://127.0.0.1:8700"
OUT = ROOT / "var" / "benchmarks" / "limits.json"


def pct(values, p):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(len(values) * p))], 1) if values else None


def record(entry: dict):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    history = json.loads(OUT.read_text()) if OUT.exists() else []
    history.append({"at": time.time(), **entry})
    OUT.write_text(json.dumps(history, indent=2))


def load(batches: int, batch_size: int, workers: int):
    ws, app_id, src = f"load-{uuid.uuid4().hex[:6]}", "load-app", f"load-src-{uuid.uuid4().hex[:6]}"
    token, ci = "aos_" + secrets.token_urlsafe(24), "aoci_" + secrets.token_urlsafe(24)
    with platform_session() as s:
        s.add(Workspace(id=ws, name="Load test"))
        s.add(EventSource(id=src, workspace_id=ws, application_id=app_id, environment="staging", kind="application",
                          token_hash=hashlib.sha256(token.encode()).hexdigest()))
        s.add(ServiceCredential(kind="ci", workspace_id=ws, application_id=app_id, environment="staging",
                                token_hash=hashlib.sha256(ci.encode()).hexdigest()))
    with tenant_session(ws) as s:
        s.add(Application(id=app_id, workspace_id=ws, name="Load", environment="staging", mode="observe_only", target_url="http://127.0.0.1:9", tools_url=""))
    try:
        def send(i):
            events = [{"event_id": uuid.uuid4().hex, "source_id": src, "epoch": "e1", "seq": i * batch_size + j + 1, "release": "R1",
                       "event_type": "heartbeat" if j % 10 == 0 else "observed.action", "observed_at": time.time(), "payload": {"n": j}}
                      for j in range(batch_size)]
            t0 = time.perf_counter()
            r = httpx.post(f"{API}/v1/runtime/events:batch", json={"events": events}, headers={"Authorization": f"Bearer {token}"}, timeout=60)
            return (time.perf_counter() - t0) * 1000, r.status_code, sum(x["status"] == "accepted" for x in r.json().get("results", [])) if r.status_code == 200 else 0
        t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(send, range(batches)))
        wall = time.perf_counter() - t0
        lat = [r[0] for r in results]
        accepted = sum(r[2] for r in results)
        limited = sum(1 for r in results if r[1] == 429)
        gate_lat = []
        for _ in range(30):
            g0 = time.perf_counter()
            httpx.post(f"{API}/v1/integration/release-gate/check", json={"commit_sha": "c" * 40}, headers={"Authorization": f"Bearer {ci}"}, timeout=30)
            gate_lat.append((time.perf_counter() - g0) * 1000)
        result = {"kind": "load", "ingestion": {"batches": batches, "batch_size": batch_size, "concurrency": workers, "accepted_events": accepted,
                                                "events_per_second": round(accepted / wall, 1), "batch_latency_ms_p50": pct(lat, 0.5),
                                                "batch_latency_ms_p95": pct(lat, 0.95), "rate_limited_batches": limited},
                  "release_gate_check": {"requests": 30, "latency_ms_p50": pct(gate_lat, 0.5), "latency_ms_p95": pct(gate_lat, 0.95)}}
        print(json.dumps(result, indent=2))
        record(result)
    finally:
        with tenant_session(ws) as s:
            for model in (RuntimeEvent, DeploymentReceipt, AuditEvent, Application):
                s.execute(delete(model))
        with platform_session() as s:
            s.execute(delete(EventSource).where(EventSource.id == src))
            s.execute(delete(ServiceCredential).where(ServiceCredential.workspace_id == ws))
            s.execute(delete(Workspace).where(Workspace.id == ws))


def worker_processes() -> list[int]:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'celery' -and $_.CommandLine -match 'assess@' } | ForEach-Object { $_.ProcessId }"],
                         capture_output=True, text=True)
    return [int(x) for x in out.stdout.split()]


def recovery(app_id: str, workspace: str):
    from assureops_api import services as svc

    with tenant_session(workspace) as s:
        app = s.get(Application, app_id)
        collected = svc.collect_release(s, app, "recovery-check")
        release_id = collected["release"]["id"]
    with tenant_session(workspace) as s:
        job_id = svc.create_assessment(s, s.get(Application, app_id), s.get(svc.Release, release_id), "full", "recovery-check").id
    print(f"assessment {job_id} started")
    while True:
        with tenant_session(workspace) as s:
            done = sum(st.status == "done" for st in s.scalars(select(JobStep).where(JobStep.assessment_id == job_id)))
        if done >= 2:
            break
        time.sleep(1)
    killed = worker_processes()
    for pid in killed:
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"], capture_output=True)
    t_kill = time.time()
    print(f"worker stopped (pids {killed}) after {done} steps; restarting a worker")
    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    # Independent process (not a child of this script), as a supervisor would restart it.
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Start-Process -FilePath '{py}' -ArgumentList '-m','celery','-A','assureops_worker.tasks','worker','--pool=solo',"
                    f"'-Q','assessments','-n','assess@%h','--loglevel=WARNING' -WorkingDirectory '{ROOT}' -WindowStyle Hidden "
                    f"-RedirectStandardOutput '{ROOT / 'var' / 'logs' / 'worker-restarted.log'}' -RedirectStandardError '{ROOT / 'var' / 'logs' / 'worker-restarted.err.log'}'"],
                   check=True)
    while True:
        with tenant_session(workspace) as s:
            job = s.get(Assessment, job_id)
            if job.status not in ("queued", "running"):
                steps = s.scalars(select(JobStep).where(JobStep.assessment_id == job_id)).all()
                break
        time.sleep(2)
    recovered = round(time.time() - t_kill, 1)
    result = {"kind": "recovery", "application": app_id, "assessment": job_id, "status": job.status, "steps": len(steps),
              "steps_done": sum(st.status == "done" for st in steps), "max_attempts_used": max(st.attempt for st in steps),
              "seconds_from_worker_loss_to_completion": recovered, "lease_seconds": 120, "reconcile_interval_seconds": 15}
    print(json.dumps(result, indent=2))
    record(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["load", "recovery"])
    parser.add_argument("--app", default="refunddesk-demo")
    parser.add_argument("--workspace", default="acme")
    parser.add_argument("--batches", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    if args.mode == "load":
        load(args.batches, args.batch_size, args.concurrency)
    else:
        recovery(args.app, args.workspace)


if __name__ == "__main__":
    main()
