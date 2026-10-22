"""Qualify the private phase models against their pinned artifacts (CI, integration plan I7/I8).

    python scripts/ci_qualify_models.py --phases C D R --out var/qualification

For each phase it checks that the served artifact is the pinned one
(profiles/qualification/model-pins.json for Ollama digests, encoder_pins.json
for encoders), runs the synthetic holdout with scripts/qualify_phase.py and
fails if any phase does not qualify. Only synthetic holdout data is used and no
external provider is called. Writes one JSON file per phase plus a summary.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PINS = json.loads((ROOT / "profiles" / "qualification" / "model-pins.json").read_text())["phases"]


def served_digest(model: str) -> str | None:
    base = os.environ.get("PRIVATE_INFERENCE_URL", "http://127.0.0.1:8740/v1").removesuffix("/v1")
    names = {model, model if ":" in model else f"{model}:latest"}
    for m in httpx.get(f"{base}/api/tags", timeout=10).json().get("models", []):
        if m.get("name") in names or m.get("model") in names:
            return m["digest"]
    return None


def score(metrics: dict) -> str:
    if "valid_rate" in metrics:
        return f"valid {metrics['valid_rate']}"
    if "accuracy" in metrics:
        return f"accuracy {metrics['accuracy']}"
    if "recall_at_3" in metrics:
        return f"hybrid recall@3 {metrics['recall_at_3'].get('hybrid')}"
    return "-"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phases", nargs="+", default=["C", "D", "R"], choices=sorted(PINS))
    parser.add_argument("--out", type=Path, default=ROOT / "var" / "qualification")
    parser.add_argument("--suite", default="v1", choices=["v1", "v2"])
    args = parser.parse_args()
    rows, failed = [], []
    for phase in args.phases:
        pin = PINS[phase]
        if not pin.get("encoder"):
            digest = served_digest(pin["model"])
            if digest != pin["digest"]:
                rows.append((phase, pin["model"], "artifact mismatch", "-", "-"))
                failed.append(phase)
                print(f"phase {phase}: served {pin['model']} digest {str(digest)[:12]} != pinned {pin['digest'][:12]}")
                continue
        out = args.out / f"phase-{phase}.json"
        proc = subprocess.run([sys.executable, "-u", str(ROOT / "scripts" / "qualify_phase.py"), "--phase", phase, "--provider", "private",
                               "--model", pin["model"], "--suite", args.suite, "--json-out", str(out), "--require-qualified"])
        result = json.loads(out.read_text()) if out.exists() else {}
        metrics = result.get("metrics", {})
        rows.append((phase, pin["model"], "qualified" if proc.returncode == 0 else "NOT qualified",
                     score(metrics), str(metrics.get("critical_false_support", "-"))))
        if proc.returncode != 0:
            failed.append(phase)
    table = "| Phase | Model | Result | Score | Critical false support |\n|---|---|---|---|---|\n"
    table += "".join(f"| {' | '.join(r)} |\n" for r in rows)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.md").write_text(table, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Private model qualification\n\n" + table)
    print(table)
    if failed:
        raise SystemExit(f"phases not qualified: {failed}")


if __name__ == "__main__":
    main()
