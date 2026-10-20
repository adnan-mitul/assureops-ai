"""Render the local S3 (SeaweedFS) identity file from dev.env test values.

    python scripts/render_storage.py

Writes infra/compose/seaweedfs/s3.rendered.json (git-ignored). The bucket has a
single authenticated identity and no anonymous access, so evidence objects are
private; browsers only ever download through authorized API routes.
"""

import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "infra" / "compose" / "dev.env"


def main():
    text = ENV.read_text(encoding="utf-8")
    values = dict(line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#") and "=" in line)
    added = []
    for key, value in (("S3_ACCESS_KEY", "ao" + secrets.token_hex(8)), ("S3_SECRET_KEY", secrets.token_urlsafe(30)),
                       ("EVIDENCE_BACKEND", "s3"), ("S3_ENDPOINT", "http://127.0.0.1:9100"), ("S3_BUCKET", "assureops-evidence")):
        if key not in values:
            values[key] = value
            added.append(f"{key}={value}")
    if added:
        ENV.write_text(text.rstrip("\n") + "\n# Private evidence object store (local test values)\n" + "\n".join(added) + "\n", encoding="utf-8", newline="\n")
    config = {"identities": [{"name": "assureops-evidence", "credentials": [{"accessKey": values["S3_ACCESS_KEY"], "secretKey": values["S3_SECRET_KEY"]}],
                              "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}
    out = ROOT / "infra" / "compose" / "seaweedfs" / "s3.rendered.json"
    out.parent.mkdir(parents=True, exist_ok=True)  # only the rendered (git-ignored) file lives here
    out.write_text(json.dumps(config, indent=2), encoding="utf-8", newline="\n")
    print(f"rendered {out.relative_to(ROOT)} (values not shown)")


if __name__ == "__main__":
    main()
