"""Fresh phase D held-out set (v3), generated after the D-2 decision rule was designed.

    python scripts/gen_holdouts_d_v3.py      # writes profiles/qualification/phase-D-holdout-v3.json

The D-2 rule (numbers and identifiers a premise does not contain are never entailed) was written after the
v2 holdout showed a critical error, so v2 no longer measures D independently. v3 uses the same fact
templates with a new seed: new values, same structure. It is a fresh draw, not new kinds of claims.
"""

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gen_holdouts_v2 as v2  # noqa: E402

SEED, FAMILIES = 20261023, 100


def main():
    v2.RNG = random.Random(SEED)
    cases = v2.phase_d(FAMILIES)
    body = {"note": "Synthetic data only; no customer evidence. Each family has one entailed, one contradicted and one neutral hypothesis "
                    f"for the same premise. Fresh draw (seed {SEED}) after the D-2 rule was designed against v2.",
            "phase": "D", "suite": "v3", "cases": cases}
    (v2.OUT / "phase-D-holdout-v3.json").write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")
    print(f"phase D v3: {len(cases)} cases")


if __name__ == "__main__":
    main()
