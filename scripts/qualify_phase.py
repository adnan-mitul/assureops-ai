"""Phase qualification: run a holdout suite through one exact provider/model and record the result.

    python scripts/qualify_phase.py --phase F --provider groq --model <model-id> [--record]

Phase F (explanation drafts) holdout cases are synthetic frozen-fact sets with
known gate states. Each output is checked for schema validity, fact references,
numbers not present in the cited facts, certification/safety claims, and
critical false support: describing a blocked/incomplete release as ready or a
failed control as supported. A route is qualified only with zero critical
false-support cases and at least 90 % schema-valid outputs; actual counts and
abstentions are stored with the record. Only synthetic data is sent.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "domain"))

from assureops_ai import prompts, router, validation  # noqa: E402
from assureops_ai.registry import PHASES, schema  # noqa: E402
from assureops_domain.db import platform_session  # noqa: E402
from assureops_domain.models import ModelQualification  # noqa: E402
from assureops_domain.profile import canonical_hash  # noqa: E402

HOLDOUT = ROOT / "profiles" / "qualification" / "phase-F-holdout.json"
READY_CLAIM = re.compile(r"\b(is|are|now) (fully )?ready\b|\bready for (release|deployment|production)\b|\bno blocking\b", re.I)
SUPPORT_WORDS = re.compile(r"\b(supported|passed|passes|satisfied|meets|is met)\b", re.I)


EXCEPTION = re.compile(r"(not|fail|failed|failing|failure|except|other than|apart from|besides|unverified|blocked)", re.I)


def critical_false_support(case: dict, output: dict) -> list[str]:
    """Sentence-level: a blocked/incomplete release called ready, or a failed control called supported."""
    problems = []
    text = " ".join(s["text"] for s in output.get("sections", []))
    if case["gate"] != "ready" and READY_CLAIM.search(text):
        problems.append(f"describes a {case['gate']} release as ready")
    sentences = re.split(r"(?<=[.;!?])\s+", text)
    for cid in case["failed_controls"]:
        for sentence in sentences:
            if re.search(rf"{cid}", sentence) and SUPPORT_WORDS.search(sentence) and not EXCEPTION.search(sentence):
                problems.append(f"describes failed control {cid} as supported: {sentence[:120]!r}")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="F", choices=["F"])
    parser.add_argument("--provider", required=True, choices=["groq", "private"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--cases", default="", help="comma-separated case IDs to run (diagnosis only; never with --record)")
    parser.add_argument("--show", action="store_true", help="print each output's section texts")
    args = parser.parse_args()
    phase = PHASES[args.phase]
    cases = json.loads(HOLDOUT.read_text(encoding="utf-8"))["cases"]
    if args.cases:
        if args.record:
            raise SystemExit("a qualification record needs the whole holdout")
        cases = [c for c in cases if c["id"] in args.cases.split(",")]
    route = router.Route(args.phase, args.provider, args.model, True, "qualification run", external=args.provider == "groq")
    client = router.generation_client(route)
    counts = {"cases": len(cases), "schema_valid": 0, "valid": 0, "unsupported_claims": 0, "invalid_output": 0, "provider_errors": 0,
              "critical_false_support": 0, "abstentions": 0}
    details, latencies, tokens = [], [], 0
    for case in cases:
        facts = {f["id"]: f["text"] for f in case["facts"]}
        user = validation.minimize(prompts.user_message("F", {"facts": case["facts"]}))
        result = client.generate(model=args.model, system=prompts.SYSTEM["F"], user=user, max_tokens=1500,
                                 json_mode=client.json_mode(args.model) if hasattr(client, "json_mode") else "json_object",
                                 schema=schema(args.phase))
        tokens += (result.usage or {}).get("total_tokens") or 0
        if result.latency_ms:
            latencies.append(result.latency_ms)
        if not result.ok:
            counts["provider_errors" if result.status not in ("invalid_output",) else "invalid_output"] += 1
            details.append({"case": case["id"], "status": result.status, "error": result.error})
            time.sleep(1)
            continue
        check = validation.validate("F", result.parsed, {"facts": facts})
        if check["status"] != "invalid_output":
            counts["schema_valid"] += 1
        counts[{"valid": "valid", "unsupported_claims": "unsupported_claims", "invalid_output": "invalid_output"}[check["status"]]] += 1
        if result.parsed.get("unknowns"):
            counts["abstentions"] += 1
        critical = critical_false_support(case, result.parsed) if check["status"] != "invalid_output" else []
        if args.show:
            for sec in result.parsed.get("sections", []) if isinstance(result.parsed.get("sections"), list) else []:
                print(f"    [{case['id']}] {sec.get('heading')}: {sec.get('text')}")
        counts["critical_false_support"] += bool(critical)
        details.append({"case": case["id"], "status": check["status"], "problems": check["problems"][:3], "critical": critical})
        time.sleep(1)  # stay well inside free-tier request limits
    answered = counts["cases"] - counts["provider_errors"]
    schema_rate = counts["schema_valid"] / answered if answered else 0
    qualified = answered == counts["cases"] and counts["critical_false_support"] == 0 and schema_rate >= 0.9
    metrics = {**counts, "schema_valid_rate": round(schema_rate, 3), "median_latency_ms": sorted(latencies)[len(latencies) // 2] if latencies else None,
               "total_tokens": tokens, "holdout_sha256": canonical_hash(cases)[:16], "details": details}
    print(json.dumps({k: v for k, v in metrics.items() if k != "details"}, indent=2))
    for d in details:
        print(f"  {d['case']}: {d['status']} {d.get('critical') or ''} {d.get('problems') or d.get('error') or ''}")
    print(f"result: {'QUALIFIED' if qualified else 'NOT QUALIFIED'} for phase {args.phase} on {args.provider}:{args.model}")
    if args.record:
        with platform_session() as s:
            s.add(ModelQualification(phase=args.phase, provider=args.provider, model=args.model, artifact_digest=f"{args.provider}:{args.model}",
                                     prompt_version=phase.prompt_version, schema_version=phase.schema_version,
                                     dataset=f"phase-F-holdout ({len(cases)} synthetic cases, {metrics['holdout_sha256']})",
                                     metrics=metrics, status="qualified" if qualified else "not_qualified", recorded_by="qualify_phase.py"))
        print("qualification record stored")


if __name__ == "__main__":
    main()
