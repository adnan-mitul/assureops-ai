"""Run a lab's profile through disposable runner containers on an internal (no-internet) Docker network.

    python scripts/container_runner_check.py --app refunddesk-demo --lab-dir <lab folder>

1. Creates the internal network `assureops-labnet` (no route outside Docker).
2. Starts the lab in its own container on that network, plus a sidecar that exposes its loopback port on the private address.
3. Runs every profile test as the platform does: one capsule, one fresh `assureops-runner` container
   (no capabilities, read-only, memory/CPU/PID limits, non-root) per test.
4. Proves egress is restricted: a capsule aimed at a public address cannot connect.
5. Removes the lab containers.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "domain"))

from assureops_domain.config import settings  # noqa: E402
from assureops_worker import isolation  # noqa: E402

NET = "assureops-labnet"
IMAGE = "python:3.12.8-slim-bookworm"


def sh(*args, check=True) -> str:
    return subprocess.run(list(args), capture_output=True, text=True, check=check).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    parser.add_argument("--lab-dir", required=True)
    args = parser.parse_args()
    profile = json.loads((ROOT / "profiles" / "applications" / f"{args.app}.json").read_text(encoding="utf-8"))
    conn = json.loads((ROOT / "profiles" / "connections" / f"{args.app}.json").read_text(encoding="utf-8"))
    creds = json.loads((ROOT / "var" / "demo-actors" / f"{args.app}.json").read_text(encoding="utf-8"))
    port = int(conn["config"]["base_url"].rsplit(":", 1)[1])
    lab, fwd = f"assureops-lab-{args.app}", f"assureops-lab-{args.app}-fwd"
    if NET not in sh("docker", "network", "ls", "--format", "{{.Name}}").split():
        sh("docker", "network", "create", "--internal", NET)
    sh("docker", "rm", "-f", lab, fwd, check=False)
    sh("docker", "run", "-d", "--name", lab, "--network", NET, "-v", f"{Path(args.lab_dir).resolve()}:/lab:ro", IMAGE,
       "python", "-E", "-s", "/lab/app.py", "--db", "/tmp/lab.sqlite3")
    sh("docker", "run", "-d", "--name", fwd, "--network", f"container:{lab}", "-v", f"{ROOT / 'infra' / 'runner'}:/fwd:ro", IMAGE,
       "python", "/fwd/tcp_forward.py", str(port))
    ip = sh("docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", lab)
    settings().runner_mode = "container"  # this check exercises the container runner explicitly
    try:
        fetch = ("import json,urllib.request;r=urllib.request.Request('http://%s:%d/manifest',headers={'Host':'127.0.0.1:%d'});"
                 "print(urllib.request.urlopen(r,timeout=10).read().decode())" % (ip, port, port))
        manifest = None
        for _ in range(20):
            out = subprocess.run(["docker", "run", "--rm", "--network", NET, IMAGE, "python", "-c", fetch], capture_output=True, text=True)
            if out.returncode == 0:
                manifest = json.loads(out.stdout)
                break
        if manifest is None:
            raise SystemExit("lab did not come up on the internal network")
        mhash = hashlib.sha256(json.dumps(manifest["components"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        config = {**{k: v for k, v in conn["config"].items() if v is not None}, "base_url": f"http://{ip}:{port}",
                  "host_header": f"127.0.0.1:{port}", "runner_network": NET}
        print(f"lab {args.app} release {manifest['release']} on {NET} at {ip}:{port} (internal network, no internet)")
        passed = failed = errors = 0
        for test in profile["tests"]:
            capsule = {"adapter_id": conn["adapter_id"], "connection_revision": 1, "config": config, "credentials": creds, "allow_private": True,
                       "step_id": f"container-check-{test['id']}", "release_version": manifest["release"], "frozen_manifest": manifest,
                       "manifest_hash": mhash, "run_tokens": ["ao-" + hashlib.sha256(test["id"].encode()).hexdigest()[:12]] * test["trials"],
                       "test": test, "identity_check": True}
            out = isolation.run_capsule(capsule, timeout=120)
            if out.get("status") != "completed":
                errors += 1
                print(f"  {test['id']:12} ERROR {out.get('error')}")
                continue
            ok = all(t["passed"] for t in out["trials"])
            passed += ok
            failed += not ok
            print(f"  {test['id']:12} {'PASS' if ok else 'FAIL'}")
        egress = {**config, "base_url": "http://1.1.1.1:80", "host_header": None, "scope": {"allowed_paths": ["/"]}}
        probe = isolation.run_capsule({"adapter_id": conn["adapter_id"], "connection_revision": 1, "config": egress, "credentials": {},
                                       "allow_private": False, "step_id": "egress-probe", "release_version": "x", "frozen_manifest": {},
                                       "manifest_hash": "", "run_tokens": ["ao-000000000000"],
                                       "test": {"id": "EGRESS", "control": "C04", "severity": "high", "trials": 1, "name": "egress", "expected": "x",
                                                "template": "role_forbidden", "args": {"actor": "anonymous", "request": {"method": "GET", "path": "/"}}}},
                                      timeout=60)
        print(f"summary: {passed} passed, {failed} failed, {errors} errors in disposable runner containers")
        print(f"egress probe to a public address: {probe.get('status')} ({probe.get('error')})")
    finally:
        sh("docker", "rm", "-f", lab, fwd, check=False)


if __name__ == "__main__":
    main()
