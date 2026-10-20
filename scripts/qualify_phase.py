"""Phase qualification: run a phase's synthetic holdout through one exact provider/model and record the result.

    python scripts/qualify_phase.py --phase A --provider private --model granite4:micro [--record]
    python scripts/qualify_phase.py --phase F --provider groq --model openai/gpt-oss-20b --record

Criteria live in packages/ai/assureops_ai/qualification.py: zero critical
false-support cases plus a per-phase quality floor; actual counts, abstentions
and per-case outcomes are stored with the record. Only synthetic data is sent.
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "domain"))

from assureops_ai import qualification, router  # noqa: E402
from assureops_ai.registry import PHASES  # noqa: E402
from assureops_domain.db import platform_session  # noqa: E402
from assureops_domain.models import ModelQualification  # noqa: E402


def artifact_digest(phase_kind: str, provider: str, model: str) -> str:
    if provider == "groq":
        return f"groq:{model}"
    if phase_kind == "generate":
        base = router.env("PRIVATE_INFERENCE_URL").removesuffix("/v1")
        for m in httpx.get(f"{base}/api/tags", timeout=10).json().get("models", []):
            if model in (m.get("name"), m.get("model")):
                return f"ollama:{model}@{m['digest']}"
        return f"ollama:{model}@unknown"
    pins = json.loads((ROOT / "packages" / "ai" / "assureops_ai" / "encoder_pins.json").read_text())
    pin = pins.get(model, {})
    return f"hf:{model}@{pin.get('revision', '?')[:12]}#{pin.get('artifact_digest', '?')[:16]}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=sorted(PHASES))
    parser.add_argument("--provider", required=True, choices=["groq", "private"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    phase = PHASES[args.phase]
    route = router.Route(args.phase, args.provider, args.model, True, "qualification run", external=args.provider == "groq")
    print(f"qualifying phase {args.phase} ({phase.name}) on {args.provider}:{args.model}")
    result = qualification.run(args.phase, route)
    metrics = {**result["metrics"], "holdout_sha256": qualification.holdout_digest(args.phase), "details": result["details"]}
    print(json.dumps({k: v for k, v in metrics.items() if k != "details"}, indent=2))
    print(f"result: {'QUALIFIED' if result['qualified'] else 'NOT QUALIFIED'} for phase {args.phase} on {args.provider}:{args.model}")
    if args.record:
        with platform_session() as s:
            s.add(ModelQualification(phase=args.phase, provider=args.provider, model=args.model,
                                     artifact_digest=artifact_digest(phase.kind, args.provider, args.model),
                                     prompt_version=phase.prompt_version, schema_version=phase.schema_version,
                                     dataset=f"phase-{args.phase}-holdout ({metrics['holdout_sha256']})", metrics=metrics,
                                     status="qualified" if result["qualified"] else "not_qualified", recorded_by="qualify_phase.py"))
        print("qualification record stored")


if __name__ == "__main__":
    main()
