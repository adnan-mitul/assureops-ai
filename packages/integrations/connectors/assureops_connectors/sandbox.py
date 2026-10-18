"""Disposable test runner entrypoint.

    python -I -m assureops_connectors.sandbox < capsule.json > result.json

The worker launches this per step (as a subprocess with a scrubbed environment,
or inside a disposable container). The capsule holds exactly one frozen test,
the frozen release manifest, the connection configuration and the actor
credentials for that connection. The process has no database, broker,
evidence-store or platform secrets, and it exits after one step.
"""

import hashlib
import json
import sys

LIMIT_STDIN = 1_000_000


def execute(capsule: dict) -> dict:
    from .base import AdapterError, ConnectionSpec, TestContext, get
    from .egress import EgressDenied
    from .http_client import TargetError
    from .scenario import PreconditionFailed, ScenarioError
    from .templates import TemplateError

    spec = ConnectionSpec(adapter_id=capsule["adapter_id"], revision=capsule["connection_revision"], config=capsule["config"],
                          credentials=capsule.get("credentials", {}), allow_private=capsule.get("allow_private", False))
    ctx = TestContext(step_id=capsule["step_id"], release_version=capsule["release_version"], frozen_manifest=capsule["frozen_manifest"],
                      run_tokens=capsule["run_tokens"])
    adapter = get(spec.adapter_id)
    test = capsule["test"]
    trials = []
    try:
        if capsule.get("identity_check"):
            live = adapter.collect_manifest(spec)["manifest"]
            live_hash = hashlib.sha256(json.dumps(live["components"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if live_hash != capsule["manifest_hash"] or live["release"] != capsule["release_version"]:
                # Evidence from a different running release must never be attributed to the assessed one.
                return {"status": "error", "trials": [],
                        "error": f"identity_mismatch: target is running {live['release']} (components {live_hash[:12]}), "
                                 f"not assessed release {capsule['release_version']} ({capsule['manifest_hash'][:12]})"}
        for i in range(test["trials"]):
            ok, record = adapter.run_allowed_test(spec, test, ctx, i)
            trials.append({"passed": bool(ok), "record": record})
        return {"status": "completed", "trials": trials, "adapter": adapter.adapter_id, "adapter_version": adapter.version,
                "evaluator_version": adapter.evaluator_version}
    except PreconditionFailed as exc:
        return {"status": "error", "error": f"PreconditionFailed: {exc}", "trials": trials, "partial_record": exc.record}
    except AdapterError as exc:
        return {"status": "error", "error": f"{exc.code}: {exc.detail}", "trials": trials}
    except (TargetError, EgressDenied) as exc:
        return {"status": "error", "error": f"{exc.__class__.__name__}: {exc}", "trials": trials}
    except (ScenarioError, TemplateError) as exc:
        return {"status": "error", "error": f"InvalidTest: {exc}", "trials": trials}


def main():
    raw = sys.stdin.buffer.read(LIMIT_STDIN + 1)
    if len(raw) > LIMIT_STDIN:
        print(json.dumps({"status": "error", "error": "capsule too large"}))
        return 2
    try:
        result = execute(json.loads(raw))
    except Exception as exc:  # never leak capsule contents (credentials) in the error
        result = {"status": "error", "error": f"RunnerCrash: {exc.__class__.__name__}"}
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
