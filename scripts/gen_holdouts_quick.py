"""Derive the quick qualification tier: 20 cases per phase taken from the v2 held-out suites.

    python scripts/gen_holdouts_quick.py     # writes profiles/qualification/phase-<X>-holdout-quick.json

The pick is deterministic and stratified so every control (A, B, C, E), gate state and failed control (F),
label (D, G) or query family (R) appears at least twice where the 20 cases allow it. Zero critical errors in
20 cases only bounds the true rate below about 16 % (Wilson, 95 %), so a quick run is recorded as a quick check:
it can switch a route off when it finds a critical error, never qualify one.
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
N = 20
PER_KEY = {"D": 7, "G": 10}  # classifiers: balanced labels rather than two of each
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
    for phase, keys in KEYS.items():
        src = OUT / f"phase-{phase}-holdout-v2.json"
        data = json.loads(src.read_text(encoding="utf-8"))
        field = "queries" if phase == "R" else "cases"
        picked = stratified(data[field], keys, N, PER_KEY.get(phase, 2))
        covered = sorted({k for c in picked for k in keys(c)})
        out = {**{k: v for k, v in data.items() if k not in ("cases", "queries", "note", "suite")}, "suite": "quick",
               "note": f"Quick tier: {len(picked)} of the {len(data[field])} v2 held-out cases (scripts/gen_holdouts_quick.py), "
                       f"stratified over {len(covered)} keys. A quick check, never a qualification. " + data.get("note", ""),
               "derived_from": {"file": src.name, "sha256": hashlib.sha256(src.read_bytes()).hexdigest()[:16]},
               "covers": covered, field: picked}
        (OUT / f"phase-{phase}-holdout-quick.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print(f"phase {phase}: {len(picked)} cases, {len(covered)} keys covered")


if __name__ == "__main__":
    main()
