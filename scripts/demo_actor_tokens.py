"""Extract a synthetic lab's published fixture tokens into a local, git-ignored actor file.

    python scripts/demo_actor_tokens.py --readme <lab>/README.md --out var/demo-actors/<app>.json

The supplied demo labs publish synthetic Bearer tokens in their README actor
table. They are fixture identities, not credentials of any real system, but
they still never enter the repository: the output lives under var/.
"""

import argparse
import json
import re
from pathlib import Path

LABELS = {
    "acme customer": "customer",
    "another acme customer": "customer_other",
    "acme manager": "manager",
    "globex customer": "other_tenant",
    "local release switch and event inspection": "lab_admin",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--readme", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    actors = {}
    for line in Path(args.readme).read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|$", line.strip())
        if match and match.group(2).lower() in LABELS:
            actors[LABELS[match.group(2).lower()]] = match.group(1)
    if set(actors) != set(LABELS.values()):
        raise SystemExit(f"actor table incomplete: found {sorted(actors)}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(actors, indent=2), encoding="utf-8")
    print(f"wrote {len(actors)} actor credentials to {out} (values not shown)")


if __name__ == "__main__":
    main()
