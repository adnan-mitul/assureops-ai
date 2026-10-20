"""Local digest-based promotion: staging -> canary -> production, health-gated, with rollback.

    python scripts/deploy/local_promote.py promote <image-ref>     # stage, canary, then production
    python scripts/deploy/local_promote.py rollback                 # production back to the previous digest
    python scripts/deploy/local_promote.py status

Each stage is a container started from the image's immutable digest (never a
moving tag) against the same database with already-applied, backward-compatible
migrations. A stage must pass /health and an authenticated-surface probe before
the next one starts; any failure stops promotion and leaves production as it was.
History lives in var/deploy/history.json. Hosted environments use the same
sequence through scripts/deploy/promote.sh and DEPLOY_ENDPOINT.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
HISTORY = ROOT / "var" / "deploy" / "history.json"
STAGES = {"staging": 8800, "canary": 8801, "production": 8802}


def sh(*args, check=True) -> str:
    return subprocess.run(list(args), capture_output=True, text=True, check=check).stdout.strip()


def env_args() -> list[str]:
    values = dict(line.split("=", 1) for line in (ROOT / "infra" / "compose" / "dev.env").read_text().splitlines() if "=" in line and not line.startswith("#"))
    pw = values["ASSUREOPS_APP_PASSWORD"]
    env = {"DATABASE_URL": f"postgresql+psycopg://assureops_app:{pw}@host.docker.internal:5441/assureops",
           "REDIS_URL": "redis://host.docker.internal:6391/0", "CUSTOMER_OIDC_ISSUER": "http://localhost:8780/realms/assureops",
           "STAFF_OIDC_ISSUER": "http://localhost:8780/realms/assureops-staff", "EVIDENCE_BACKEND": "s3", "S3_ENDPOINT": "http://host.docker.internal:9100",
           "S3_ACCESS_KEY": values.get("S3_ACCESS_KEY", ""), "S3_SECRET_KEY": values.get("S3_SECRET_KEY", ""),
           "ASSUREOPS_SECRET_KEY": values.get("ASSUREOPS_SECRET_KEY", ""), "OWNER_DATABASE_URL": "unused"}
    env_file = ROOT / "var" / "deploy" / "stage.env"  # git-ignored; keeps secrets off the command line and out of process listings
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
    return ["--env-file", str(env_file)]


def digest_of(ref: str) -> str:
    return sh("docker", "image", "inspect", "-f", "{{.Id}}", ref)


def start(stage: str, digest: str) -> bool:
    name = f"assureops-api-{stage}"
    sh("docker", "rm", "-f", name, check=False)
    run = subprocess.run(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{STAGES[stage]}:8700", *env_args(), digest, "api"],
                         capture_output=True, text=True)
    return run.returncode == 0  # failure details stay out of the output: the command carries environment references


def healthy(stage: str, timeout: float = 60) -> tuple[bool, str]:
    base = f"http://127.0.0.1:{STAGES[stage]}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/health", timeout=3).status_code == 200:
                probe = httpx.get(f"{base}/v1/me", timeout=5)  # must refuse an anonymous caller, not crash
                return probe.status_code == 401, f"health 200, anonymous /v1/me -> {probe.status_code}"
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False, "no healthy response"


def history() -> dict:
    return json.loads(HISTORY.read_text()) if HISTORY.exists() else {"production": [], "events": []}


def save(h: dict):
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(h, indent=2))


def promote(ref: str) -> int:
    digest = digest_of(ref)
    h = history()
    for stage in ("staging", "canary", "production"):
        ok, detail = healthy(stage) if start(stage, digest) else (False, "container failed to start")
        h["events"].append({"at": time.time(), "stage": stage, "digest": digest, "ok": ok, "detail": detail})
        print(f"{stage:10} {digest[:19]} {'healthy' if ok else 'FAILED'} ({detail})")
        if not ok:
            if stage == "production" and h["production"]:
                start("production", h["production"][-1])  # restore the previous production digest
                print(f"production restored to {h['production'][-1][:19]}")
            save(h)
            return 1
    h["production"].append(digest)
    save(h)
    return 0


def rollback() -> int:
    h = history()
    if len(h["production"]) < 2:
        print("no previous production digest to roll back to")
        return 1
    current, previous = h["production"][-1], h["production"][-2]
    start("production", previous)
    ok, detail = healthy("production")
    h["events"].append({"at": time.time(), "stage": "rollback", "from": current, "to": previous, "ok": ok, "detail": detail})
    if ok:
        h["production"].append(previous)
    save(h)
    print(f"rollback {current[:19]} -> {previous[:19]}: {'healthy' if ok else 'FAILED'} ({detail})")
    return 0 if ok else 1


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "promote":
        raise SystemExit(promote(sys.argv[2]))
    if cmd == "rollback":
        raise SystemExit(rollback())
    h = history()
    print(json.dumps({"production_history": [d[:19] for d in h["production"]], "events": h["events"][-6:]}, indent=2))


if __name__ == "__main__":
    main()
