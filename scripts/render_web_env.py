"""Write each portal's .env.local from dev.env test values (git-ignored)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env = dict(line.split("=", 1) for line in (ROOT / "infra/compose/dev.env").read_text().splitlines() if line and not line.startswith("#"))

PORTALS = {
    "customer-web": ("customer-web", env["CUSTOMER_WEB_CLIENT_SECRET"], 3700, "assureops"),
    "staff-web": ("staff-web", env["STAFF_WEB_CLIENT_SECRET"], 3710, "assureops-staff"),
}
for folder, (client_id, secret, port, realm) in PORTALS.items():
    path = ROOT / "apps" / folder / ".env.local"
    path.write_text("\n".join([
        "# Local development only. Only NEXT_PUBLIC_PORTAL_ID (not secret) reaches the browser.",
        f"OIDC_ISSUER=http://localhost:8780/realms/{realm}",
        f"OIDC_CLIENT_ID={client_id}",
        f"NEXT_PUBLIC_PORTAL_ID={client_id}",
        f"OIDC_CLIENT_SECRET={secret}",
        f"APP_ORIGIN=http://localhost:{port}",
        "ASSUREOPS_API_URL=http://127.0.0.1:8700",
        "",
    ]))
    print(f"wrote apps/{folder}/.env.local")
