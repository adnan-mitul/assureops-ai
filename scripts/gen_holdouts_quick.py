"""Derive the smaller qualification tiers from the v2 held-out suites.

    python scripts/gen_holdouts_quick.py     # writes profiles/qualification/phase-<X>-holdout-{quick,compact,standard}.json

quick (20 cases per phase): every control (A, B, C, E), gate state and failed control (F), label (D, G) or query
family (R) appears at least twice where 20 cases allow it. Zero critical errors in 20 cases only bounds the true
rate below about 16 % (Wilson, 95 %), so a quick run is recorded as a quick check: it can switch a route off when
it finds a critical error, never qualify one.

compact (50 cases per phase): the qualification tier for CPU-served private models (zero critical bounds the rate
below about 7.1 %); every key at least four times where it can.

standard (75 cases per phase): the qualification tier for routine use; every key at least six times where it can,
classifier labels balanced. Zero critical errors in 75 bounds the rate below about 4.9 % (200 cases: 1.9 %), so
v2 remains the stronger, release-grade evidence.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "ai"))

from assureops_ai.qualification import stratified  # noqa: E402

OUT = ROOT / "profiles" / "qualification"
BOUND = {"compact": "7.1 %", "standard": "4.9 %"}
# tier -> (cases, per-key minimum, per-phase overrides); classifiers get balanced labels rather than the minimum
TIERS = {"quick": (20, 2, {"D": 7, "G": 10}), "compact": (50, 4, {"D": 17, "G": 25}), "standard": (75, 6, {"D": 25, "G": 38})}
CONTROL = re.compile(r"C\d\d")

KEYS = {
    "A": lambda c: c["expected_controls"],
    "B": lambda c: CONTROL.findall(c["family"]),
    "C": lambda c: c["expected_controls"],
    "D": lambda c: [c["label"]],
    "E": lambda c: CONTROL.findall(c["family"]),
    "F": lambda c: [f"gate:{c['gate']}", *c["failed_controls"]],
    "G": lambda c: [f"malicious:{c['malicious']}"],
    "R": lambda c: [c["family"]],
}


def main():
    for tier, (n, per_key, overrides) in TIERS.items():
        for phase, keys in KEYS.items():
            src = OUT / f"phase-{phase}-holdout-v2.json"
            data = json.loads(src.read_text(encoding="utf-8"))
            field = "queries" if phase == "R" else "cases"
            picked = stratified(data[field], keys, n, overrides.get(phase, per_key))
            covered = sorted({k for c in picked for k in keys(c)})
            kind = ("A quick check, never a qualification." if tier == "quick" else
                    f"A qualification tier (zero critical in {n}: below {BOUND[tier]}).")
            out = {**{k: v for k, v in data.items() if k not in ("cases", "queries", "note", "suite")}, "suite": tier,
                   "note": f"{tier.capitalize()} tier: {len(picked)} of the {len(data[field])} v2 held-out cases (scripts/gen_holdouts_quick.py), "
                           f"stratified over {len(covered)} keys. {kind} " + data.get("note", ""),
                   "derived_from": {"file": src.name, "sha256": hashlib.sha256(src.read_bytes()).hexdigest()[:16]},
                   "covers": covered, field: picked}
            (OUT / f"phase-{phase}-holdout-{tier}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
            print(f"{tier} phase {phase}: {len(picked)} cases, {len(covered)} keys covered")


if __name__ == "__main__":
    main()
