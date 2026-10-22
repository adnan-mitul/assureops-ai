"""Reference integration settings: environment first, then local dev.env test values."""

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[3]
DEV_ENV = ROOT / "infra" / "compose" / "dev.env"


def _dev() -> dict:
    values = {}
    if DEV_ENV.exists():
        for line in DEV_ENV.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k] = v
    return values


_DEV = _dev()


def get(name: str, default: str = "") -> str:
    return os.environ.get(name) or _DEV.get(name) or default


API_URL = get("ASSUREOPS_API_URL", "http://127.0.0.1:8700")
TOOLS_URL = get("TOOLS_MCP_URL", "http://127.0.0.1:8720/mcp")
AGENT_URL = get("AGENT_URL", "http://127.0.0.1:8710")
ENVIRONMENT = "staging"
DOCS_PATH = PACKAGE / "docs.json"
# Overrides let an isolated second copy run beside the reference stack (for example the change benchmark).
VAR_DIR = Path(get("REFERENCE_VAR_DIR", str(ROOT / "var")))
TOOLS_PORT = int(get("TOOLS_PORT", "8720"))
AGENT_SOURCE_ID = get("AGENT_SOURCE_ID", "refund-agent-1")
TOOLS_SOURCE_ID = get("TOOLS_SOURCE_ID", "refund-tools-1")
EXTRA_RELEASES = get("AGENT_EXTRA_RELEASES", "")  # folder with additional release configurations (benchmark variants)
