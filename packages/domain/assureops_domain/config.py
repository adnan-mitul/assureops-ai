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
        self.profiles_dir = Path(get("PROFILES_DIR", str(ROOT / "profiles" / "applications")))
        self.catalog_path = Path(get("CONTROL_CATALOG_PATH", str(ROOT / "profiles" / "controls" / "agentops-controls-v1.json")))
        self.coverage_dir = Path(get("COVERAGE_DIR", str(ROOT / "profiles" / "coverage")))
        # Evidence object storage: "s3" (private bucket) in shared environments, "fs" only for isolated development.
        self.evidence_backend = get("EVIDENCE_BACKEND", "fs")
        self.s3_endpoint = get("S3_ENDPOINT", "http://127.0.0.1:9100")
        self.s3_bucket = get("S3_BUCKET", "assureops-evidence")
        self.s3_access_key = get("S3_ACCESS_KEY", "")
        self.s3_secret_key = get("S3_SECRET_KEY", "")
        # Key that encrypts connector secrets at rest (Fernet). Required to store target credentials.
        self.secret_key = get("ASSUREOPS_SECRET_KEY", "")
        # Loopback/private targets are only reachable when explicitly allowed (local labs, private networks).
        self.allow_private_targets = get("ALLOW_PRIVATE_TARGETS", "false").lower() == "true"
        # Test runners: "subprocess" (scrubbed environment) or "container" (disposable, no network but the target).
        self.runner_mode = get("RUNNER_MODE", "subprocess")
        self.runner_image = get("RUNNER_IMAGE", "assureops-runner:local")
        self.receipt_ttl_seconds = int(get("RECEIPT_TTL_SECONDS", "3600"))
        self.receipt_signing_key = get("RECEIPT_SIGNING_KEY", "")
        # HMAC key for per-trial run tokens that let ingestion recognise AssureOps' own test traffic.
        self.run_token_key = get("RUN_TOKEN_KEY", "")
        self.github_webhook_secret = get("GITHUB_WEBHOOK_SECRET", "")
        # Groq: disabled unless explicitly enabled with a server-side key and a qualified model.
        self.groq_enabled = get("GROQ_ENABLED", "false").lower() == "true"
        self.groq_api_key = get("GROQ_API_KEY", "")
        self.groq_base_url = get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        self.groq_model_f = get("GROQ_MODEL_F", "")
        self.groq_timeout_seconds = float(get("GROQ_TIMEOUT_SECONDS", "20"))
        self.groq_max_output_tokens = int(get("GROQ_MAX_OUTPUT_TOKENS", "700"))
        self.groq_daily_token_limit = int(get("GROQ_DAILY_TOKEN_LIMIT_PER_WORKSPACE", "60000"))
        # Private inference: OpenAI-compatible generation and TEI-compatible embed/classify endpoints per phase.
        self.private_inference_url = get("PRIVATE_INFERENCE_URL", "")
        self.api_url = get("ASSUREOPS_API_URL", "http://127.0.0.1:8700")
        # Service credentials: test values from dev.env, hashed in the database at seed time.
        self.runner_token = get("RUNNER_SERVICE_TOKEN", "")


@lru_cache
def settings() -> Settings:
    return Settings()
