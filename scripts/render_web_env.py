"""Write each portal's .env.local from dev.env test values (git-ignored)."""

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "infra/compose/dev.env"
env = dict(line.split("=", 1) for line in ENV_FILE.read_text().splitlines() if line and not line.startswith("#"))
if "SESSION_ENCRYPTION_KEY" not in env:  # server-only key for portal session tokens at rest
    env["SESSION_ENCRYPTION_KEY"] = secrets.token_urlsafe(32)
    NL = chr(10)
    ENV_FILE.write_text(ENV_FILE.read_text().rstrip(NL) + NL + f"SESSION_ENCRYPTION_KEY={env['SESSION_ENCRYPTION_KEY']}" + NL,
                        encoding="utf-8", newline=NL)

PORTALS = {
    "customer-web": ("customer-web", env["CUSTOMER_WEB_CLIENT_SECRET"], 3700, "assureops"),
    "staff-web": ("staff-web", env["STAFF_WEB_CLIENT_SECRET"], 3710, "assureops-staff"),
}
# Hosted: the public addresses people use (set in dev.env or the environment); local development keeps localhost.
AUTH = (env.get("PUBLIC_AUTH_ORIGIN") or "http://localhost:8780").rstrip("/")
ORIGIN = {"customer-web": env.get("PUBLIC_CUSTOMER_ORIGIN"), "staff-web": env.get("PUBLIC_STAFF_ORIGIN")}
for folder, (client_id, secret, port, realm) in PORTALS.items():
    path = ROOT / "apps" / folder / ".env.local"
    path.write_text("\n".join([
        "# Local development only. Only NEXT_PUBLIC_PORTAL_ID (not secret) reaches the browser.",
        f"OIDC_ISSUER={AUTH}/realms/{realm}",
        f"OIDC_CLIENT_ID={client_id}",
        f"NEXT_PUBLIC_PORTAL_ID={client_id}",
        f"OIDC_CLIENT_SECRET={secret}",
        f"APP_ORIGIN={(ORIGIN[folder] or f'http://localhost:{port}').rstrip('/')}",
        "ASSUREOPS_API_URL=http://127.0.0.1:8700",
        "SESSION_REDIS_URL=redis://127.0.0.1:6391/1",
        f"SESSION_ENCRYPTION_KEY={env['SESSION_ENCRYPTION_KEY']}",
        "",
    ]))
    print(f"wrote apps/{folder}/.env.local")
