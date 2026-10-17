"""Settings read from the environment, with local development defaults from dev.env."""

import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEV_ENV = ROOT / "infra" / "compose" / "dev.env"


def _dev_env() -> dict:
    if not DEV_ENV.exists():
        return {}
    values = {}
    for line in DEV_ENV.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


class Settings:
    def __init__(self):
        dev = _dev_env()

        def get(name: str, default: str | None = None) -> str:
            value = os.environ.get(name) or dev.get(name) or default
            if value is None:
                raise RuntimeError(f"missing setting {name}")
            return value

        self.app_database_url = get("DATABASE_URL", f"postgresql+psycopg://assureops_app:{dev.get('ASSUREOPS_APP_PASSWORD', '')}@127.0.0.1:5441/assureops")
        self.owner_database_url = get("OWNER_DATABASE_URL", f"postgresql+psycopg://assureops_owner:{dev.get('ASSUREOPS_OWNER_PASSWORD', '')}@127.0.0.1:5441/assureops")
        self.redis_url = get("REDIS_URL", "redis://127.0.0.1:6391/0")
        self.customer_issuer = get("CUSTOMER_OIDC_ISSUER", "http://localhost:8780/realms/assureops")
        self.staff_issuer = get("STAFF_OIDC_ISSUER", "http://localhost:8780/realms/assureops-staff")
        self.customer_audience = get("CUSTOMER_API_AUDIENCE", "assureops-customer-api")
        self.staff_audience = get("STAFF_API_AUDIENCE", "assureops-staff-api")
        self.evidence_dir = Path(get("EVIDENCE_DIR", str(ROOT / "var" / "evidence")))
        self.profile_path = Path(get("PROFILE_PATH", str(ROOT / "profiles" / "agentops-v1.json")))
        self.coverage_dir = Path(get("COVERAGE_DIR", str(ROOT / "profiles" / "coverage")))
        self.api_url = get("ASSUREOPS_API_URL", "http://127.0.0.1:8700")
        # Service credentials: test values from dev.env, hashed in the database at seed time.
        self.runner_token = get("RUNNER_SERVICE_TOKEN", "")


@lru_cache
def settings() -> Settings:
    return Settings()
