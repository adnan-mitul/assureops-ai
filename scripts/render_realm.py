"""Render the local Keycloak realm import from dev.env test values.

The rendered file contains test credentials and stays out of version control.
Staff sign-in requires a second factor: the staff realm's browser flow demands
password and TOTP, both carrying authentication-method references, so staff
tokens include `amr: ["pwd", "otp"]` and the staff API can enforce MFA. Local
staff users get a pre-provisioned TOTP secret from dev.env
(`python scripts/staff_otp.py <user>` prints the current code); new staff
users must enroll an authenticator on first sign-in.
"""

import json
import secrets
import string
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


def client(client_id: str, secret: str, port: int, audience: str, token_lifespan: int, origin: str | None = None) -> dict:
    origin = (origin or f"http://localhost:{port}").rstrip("/")  # PUBLIC_*_ORIGIN when hosted
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


def user(email: str, first: str, last: str, password: str, otp_secret: str | None = None) -> dict:
    credentials = [{"type": "password", "value": password, "temporary": False}]
    if otp_secret:
        credentials.append({"type": "otp", "userLabel": "local test authenticator",
                            "secretData": json.dumps({"value": otp_secret}),
                            "credentialData": json.dumps({"subType": "totp", "digits": 6, "counter": 0, "period": 30, "algorithm": "HmacSHA1"})})
    return {
        "username": email, "email": email, "firstName": first, "lastName": last,
        "enabled": True, "emailVerified": True, "credentials": credentials,
    }


def otp_key(email: str) -> str:
    return "STAFF_OTP_" + email.split("@")[0].upper().replace(".", "_")


MFA_FLOWS = {
    "browserFlow": "staff browser mfa",
    "authenticationFlows": [
        {"alias": "staff browser mfa", "description": "Password and one-time code for every staff sign-in", "providerId": "basic-flow",
         "topLevel": True, "builtIn": False, "authenticationExecutions": [
             {"authenticator": "auth-cookie", "authenticatorFlow": False, "requirement": "ALTERNATIVE", "priority": 10, "userSetupAllowed": False},
             {"authenticatorFlow": True, "flowAlias": "staff browser mfa forms", "requirement": "ALTERNATIVE", "priority": 20, "userSetupAllowed": False}]},
        {"alias": "staff browser mfa forms", "description": "Username/password then TOTP", "providerId": "basic-flow",
         "topLevel": False, "builtIn": False, "authenticationExecutions": [
             {"authenticator": "auth-username-password-form", "authenticatorConfig": "staff-pwd-reference", "authenticatorFlow": False,
              "requirement": "REQUIRED", "priority": 10, "userSetupAllowed": False},
             {"authenticator": "auth-otp-form", "authenticatorConfig": "staff-otp-reference", "authenticatorFlow": False,
              "requirement": "REQUIRED", "priority": 20, "userSetupAllowed": True}]},
    ],
    "authenticatorConfig": [
        {"alias": "staff-pwd-reference", "config": {"default.reference.value": "pwd", "default.reference.maxAge": "43200"}},
        {"alias": "staff-otp-reference", "config": {"default.reference.value": "otp", "default.reference.maxAge": "43200"}},
    ],
    "otpPolicyType": "totp", "otpPolicyAlgorithm": "HmacSHA1", "otpPolicyDigits": 6, "otpPolicyPeriod": 30, "otpPolicyLookAheadWindow": 1,
    "requiredActions": [{"alias": "CONFIGURE_TOTP", "name": "Configure OTP", "providerId": "CONFIGURE_TOTP", "enabled": True,
                         "defaultAction": True, "priority": 10, "config": {}}],
}
AMR_MAPPER = {"name": "amr", "protocol": "openid-connect", "protocolMapper": "oidc-amr-mapper",
              "config": {"access.token.claim": "true", "id.token.claim": "true", "introspection.token.claim": "true"}}


def realm(name: str, clients: list, users: list, idle_seconds: int, registration: bool = False) -> dict:
    # Customer self-registration only creates an identity: API access still needs a membership, and a membership
    # needs an invitation sent to that exact e-mail address. Staff accounts are never self-registered.
    # Hosted environments add SMTP and "verifyEmail": true.
    return {
        "realm": name, "enabled": True, "sslRequired": "none", "registrationAllowed": registration, "registrationEmailAsUsername": registration,
        "loginWithEmailAllowed": True, "ssoSessionIdleTimeout": idle_seconds, "accessTokenLifespan": 300, "clients": clients, "users": users,
    }


def main():
    """Customers and staff live in separate realms: separate identity policy, sessions never mix (plan §35.1)."""
    env = load_env()
    password = env["DEMO_USER_PASSWORD"]
    added = []
    for email, _, _ in STAFF_USERS:  # local test TOTP secrets, generated once into the git-ignored dev.env
        if otp_key(email) not in env:
            env[otp_key(email)] = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))
            added.append(f"{otp_key(email)}={env[otp_key(email)]}")
    if added:
        ENV_FILE.write_text(ENV_FILE.read_text().rstrip("\n") + "\n# Staff TOTP secrets (local test values)\n" + "\n".join(added) + "\n")
    staff_client = client("staff-web", env["STAFF_WEB_CLIENT_SECRET"], 3710, "assureops-staff-api", 300, env.get("PUBLIC_STAFF_ORIGIN"))
    staff_client["protocolMappers"].append(AMR_MAPPER)
    realms = {
        "realm-assureops.rendered.json": realm(
            "assureops", [client("customer-web", env["CUSTOMER_WEB_CLIENT_SECRET"], 3700, "assureops-customer-api", 300,
                                       env.get("PUBLIC_CUSTOMER_ORIGIN"))],
            [user(e, f, l, password) for e, f, l in CUSTOMER_USERS], 1800, registration=True),
        "realm-assureops-staff.rendered.json": {**realm(
            "assureops-staff", [staff_client],
            [user(e, f, l, password, env[otp_key(e)]) for e, f, l in STAFF_USERS], 900), **MFA_FLOWS},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, data in realms.items():
        (OUT_DIR / filename).write_text(json.dumps(data, indent=2))
        print(f"rendered infra/compose/keycloak/{filename}")


if __name__ == "__main__":
    main()
