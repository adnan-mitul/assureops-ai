"""Every checked-in application profile validates and only uses permitted catalogue templates."""

import json
from pathlib import Path

from assureops_connectors import templates
from assureops_domain.profile import normalize

ROOT = Path(__file__).resolve().parents[2]

for path in sorted((ROOT / "profiles" / "applications").glob("*.json")):
    p = normalize(json.loads(path.read_text(encoding="utf-8")))
    for t in p["tests"]:
        if t["template"] != "mcp_reference":
            templates.validate_args(t["template"], t["args"])
    print(f"  {path.name}: {len(p['tests'])} tests, assessed {','.join(p['assessed_controls'])}, "
          f"not assessed {','.join(p['unassessed_controls']) or 'none'}")
