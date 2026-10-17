"""Render the local Keycloak realm import from dev.env test values.

The rendered file contains test credentials and stays out of version control.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "infra" / "compose" / "dev.env"
OUT_DIR = ROOT / "infra" / "compose" / "keycloak"

CUSTOMER_USERS = [
    ("owner@acme.test", "Acme", "Owner"),
    ("dev@acme.test", "Acme", "Developer"),
    ("reviewer@acme.test", "Acme", "Reviewer"),
    ("viewer@acme.test", "Acme", "Viewer"),
    ("dev@globex.test", "Globex", "Developer"),
]
STAFF_USERS = [
    ("analyst@assureops.test", "Staff", "Analyst"),
    ("reviewer@assureops.test", "Staff", "Reviewer"),
    ("manager@assureops.test", "Case", "Manager"),
    ("operator@assureops.test", "Platform", "Operator"),
]


def load_env() -> dict:
    values = {}
    for line in ENV_FILE.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def client(client_id: str, secret: str, port: int, audience: str, token_lifespan: int) -> dict:
    origin = f"http://localhost:{port}"
    return {
        "clientId": client_id,
        "protocol": "openid-connect",
        "publicClient": False,
        "secret": secret,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        "redirectUris": [f"{origin}/auth/callback"],
        "webOrigins": [origin],
        "attributes": {
            "pkce.code.challenge.method": "S256",
            "post.logout.redirect.uris": f"{origin}/*",
            "access.token.lifespan": str(token_lifespan),
        },
        "protocolMappers": [{
            "name": f"audience-{audience}",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "config": {"included.custom.audience": audience, "access.token.claim": "true", "id.token.claim": "false"},
        }],
    }


def user(email: str, first: str, last: str, password: str) -> dict:
    return {
        "username": email, "email": email, "firstName": first, "lastName": last,
        "enabled": True, "emailVerified": True,
        "credentials": [{"type": "password", "value": password, "temporary": False}],
    }


def realm(name: str, clients: list, users: list, idle_seconds: int) -> dict:
    return {
        "realm": name, "enabled": True, "sslRequired": "none", "registrationAllowed": False, "loginWithEmailAllowed": True,
        "ssoSessionIdleTimeout": idle_seconds, "accessTokenLifespan": 300, "clients": clients, "users": users,
    }


def main():
    """Customers and staff live in separate realms: separate identity policy, sessions never mix (plan §35.1)."""
    env = load_env()
    password = env["DEMO_USER_PASSWORD"]
    realms = {
        "realm-assureops.rendered.json": realm(
            "assureops", [client("customer-web", env["CUSTOMER_WEB_CLIENT_SECRET"], 3700, "assureops-customer-api", 300)],
            [user(e, f, l, password) for e, f, l in CUSTOMER_USERS], 1800),
        "realm-assureops-staff.rendered.json": realm(
            "assureops-staff", [client("staff-web", env["STAFF_WEB_CLIENT_SECRET"], 3710, "assureops-staff-api", 300)],
            [user(e, f, l, password) for e, f, l in STAFF_USERS], 900),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, data in realms.items():
        (OUT_DIR / filename).write_text(json.dumps(data, indent=2))
        print(f"rendered infra/compose/keycloak/{filename}")


if __name__ == "__main__":
    main()
