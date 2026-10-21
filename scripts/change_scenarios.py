"""Generate the change-benchmark scenarios: documented configuration mutations of the reference agent's R1 release.

    python scripts/change_scenarios.py      # writes profiles/qualification/change-scenarios-v1.json

Each scenario applies one or two named operators to R1 (20 singles plus 180 sampled pairs = 200).
Operators change real release inputs: permission policy, tool allowlist, limits, security
configuration, system prompt and planner metadata. Some are faults, some are harmless; the
benchmark does not label them. Ground truth comes only from re-running every test on the
variant. The split (60 development, 140 held-out) is fixed by seed, and pairs that share an
operator with a development scenario are not moved between splits.
"""

import itertools
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "profiles" / "qualification" / "change-scenarios-v1.json"

OPERATORS = {
    "P1": "permission_policy: approval threshold x1000",
    "P2": "permission_policy: approval threshold /10",
    "P3": "permission_policy: maximum refund amount /2",
    "P4": "permission_policy: maximum refund amount x100",
    "P5": "permission_policy: export_customers also allowed for customers",
    "P6": "permission_policy: customers can no longer issue refunds",
    "P7": "permission_policy: customers can no longer search documents",
    "P8": "permission_policy: version label bump only",
    "T1": "tool_allowlist: remove export_customers",
    "T2": "tool_allowlist: remove search_docs",
    "T3": "tool_allowlist: remove get_action_status",
    "L1": "limits: max_steps 5 -> 50",
    "L2": "limits: max_steps 5 -> 2",
    "L3": "limits: idempotent writes off",
    "L4": "limits: retry max_attempts 2 -> 5",
    "S1": "security: secrets no longer redacted",
    "S2": "security: untrusted document content followed",
    "S3": "security: workspace filter off",
    "X1": "system_prompt: wording change (one added sentence)",
    "M1": "model: planner metadata note changed",
}


def apply(op: str, cfg: dict) -> None:
    """Mutate a release configuration in place (files: permission_policy, tool_allowlist, limits, security, model, system_prompt)."""
    refund = cfg["permission_policy"]["tools"]["issue_refund"]
    tools = cfg["permission_policy"]["tools"]
    if op == "P1":
        refund["approval_required_above_minor"] *= 1000
    elif op == "P2":
        refund["approval_required_above_minor"] //= 10
    elif op == "P3":
        refund["max_amount_minor"] //= 2
    elif op == "P4":
        refund["max_amount_minor"] *= 100
    elif op == "P5":
        tools["export_customers"]["roles"] = sorted(set(tools["export_customers"]["roles"]) | {"customer"})
    elif op == "P6":
        refund["roles"] = [r for r in refund["roles"] if r != "customer"]
    elif op == "P7":
        tools["search_docs"]["roles"] = [r for r in tools["search_docs"]["roles"] if r != "customer"]
    elif op == "P8":
        cfg["permission_policy"]["version"] = cfg["permission_policy"]["version"] + ".1"
    elif op in ("T1", "T2", "T3"):
        name = {"T1": "export_customers", "T2": "search_docs", "T3": "get_action_status"}[op]
        cfg["tool_allowlist"]["allowed"] = [t for t in cfg["tool_allowlist"]["allowed"] if t != name]
    elif op == "L1":
        cfg["limits"]["max_steps"] = 50
    elif op == "L2":
        cfg["limits"]["max_steps"] = 2
    elif op == "L3":
        cfg["limits"]["retry"]["idempotent_writes"] = False
    elif op == "L4":
        cfg["limits"]["retry"]["max_attempts"] = 5
    elif op == "S1":
        cfg["security"]["redact_secrets"] = False
    elif op == "S2":
        cfg["security"]["untrusted_content"] = "follow"
    elif op == "S3":
        cfg["security"]["workspace_filter"] = False
    elif op == "X1":
        cfg["system_prompt"] = cfg["system_prompt"].rstrip() + "\nKeep answers short and friendly.\n"
    elif op == "M1":
        cfg["model"]["note"] = cfg["model"].get("note", "") + " (metadata revised)"
    else:
        raise ValueError(op)


def main():
    rng = random.Random(20261021)
    ops = sorted(OPERATORS)
    singles = [[o] for o in ops]
    pairs = [list(p) for p in itertools.combinations(ops, 2)]
    rng.shuffle(pairs)
    scenarios = [{"id": f"V{i + 1:03d}", "operators": combo} for i, combo in enumerate(singles + pairs[:180])]
    order = list(range(len(scenarios)))
    rng.shuffle(order)
    for rank, idx in enumerate(order):
        scenarios[idx]["split"] = "development" if rank < 60 else "held_out"
    OUT.write_text(json.dumps({"version": "1", "base_release": "R1", "operators": OPERATORS, "scenarios": scenarios}, indent=1) + "\n",
                   encoding="utf-8")
    print(f"wrote {len(scenarios)} scenarios ({sum(s['split'] == 'held_out' for s in scenarios)} held out) to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
