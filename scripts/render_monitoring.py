"""Issue a scoped `metrics` service credential and render the Prometheus scrape config (git-ignored).

    python scripts/render_monitoring.py

The metrics endpoint serves only counts. Prometheus authenticates with a
credential of kind `metrics` that can read nothing else; only its hash is stored.
"""

import hashlib
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "domain"))

from sqlalchemy import select  # noqa: E402

from assureops_domain.db import platform_session  # noqa: E402
from assureops_domain.models import ServiceCredential  # noqa: E402

OUT = ROOT / "infra" / "compose" / "prometheus"


def main():
    token = "aomet_" + secrets.token_urlsafe(24)
    with platform_session() as s:
        for old in s.scalars(select(ServiceCredential).where(ServiceCredential.kind == "metrics", ServiceCredential.revoked.is_(False))):
            old.revoked = True  # one live scrape credential at a time
        s.add(ServiceCredential(kind="metrics", workspace_id="platform", application_id="platform", environment="local",
                                token_hash=hashlib.sha256(token.encode()).hexdigest()))
    (OUT / "metrics.token.rendered").write_text(token, encoding="utf-8")
    (OUT / "prometheus.rendered.yml").write_text(
        "global:\n  scrape_interval: 15s\n  evaluation_interval: 15s\n"
        "rule_files:\n  - /etc/prometheus/alerts.yml\n"
        "scrape_configs:\n  - job_name: assureops-api\n    metrics_path: /metrics\n"
        "    authorization:\n      type: Bearer\n      credentials_file: /etc/prometheus/metrics.token\n"
        "    static_configs:\n      - targets: ['host.docker.internal:8700']\n", encoding="utf-8")
    print("rendered prometheus scrape config and a new metrics credential (value not shown)")


if __name__ == "__main__":
    main()
