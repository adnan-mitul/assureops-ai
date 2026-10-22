"""Write the API's OpenAPI document for the generated frontend contracts.

    python scripts/export_openapi.py && npm run gen:api

CI regenerates both files and fails if they differ from the committed ones, so the portals
cannot drift from the backend's paths, methods and request bodies.
"""

import json
from pathlib import Path

from assureops_api.main import app

OUT = Path(__file__).resolve().parent.parent / "packages" / "ui" / "src" / "api" / "openapi.json"

spec = app.openapi()
OUT.write_text(json.dumps(spec, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {OUT.name}: {len(spec['paths'])} paths")
