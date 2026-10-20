"""List the models this Groq account can use and whether each fits the project's model-size constraint.

    python scripts/groq_models.py

Reads GROQ_API_KEY from the server-side environment or dev.env; never prints it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "domain"))

from assureops_ai.providers.groq import GroqProvider, STRUCTURED_OUTPUT_MODELS, parameters_billion  # noqa: E402
from assureops_ai.router import env  # noqa: E402
from assureops_domain.config import settings  # noqa: E402


def main():
    cfg = settings()
    if not cfg.groq_api_key:
        raise SystemExit("GROQ_API_KEY is not configured (dev.env or the server environment)")
    limit = float(env("GROQ_MAX_PARAMS_B", "3.8"))
    status, models = GroqProvider(cfg.groq_base_url, cfg.groq_api_key, timeout=15).list_models()
    if status != "succeeded":
        raise SystemExit(f"/models request failed: {status}")
    print(f"{len(models)} models available; project constraint <= {limit}B parameters for generative phases")
    for m in sorted(models, key=lambda x: x["id"]):
        size = parameters_billion(m["id"])
        fit = "fits" if size is not None and size <= limit else ("unknown size" if size is None else "exceeds")
        print(f"  {m['id']:55} {('%sB' % size) if size else '?':>7}  {fit:12} {'json_schema' if m['id'] in STRUCTURED_OUTPUT_MODELS else 'json_object'}"
              f"  ctx={m.get('context_window', '?')}  active={m.get('active', '?')}")


if __name__ == "__main__":
    main()
