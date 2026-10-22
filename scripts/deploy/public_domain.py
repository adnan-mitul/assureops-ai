"""Point a local AssureOps install at public addresses under your own domain (e.g. a Cloudflare Tunnel on a laptop).

    python scripts/deploy/public_domain.py --domain example.com            # app., staff. and auth.example.com
    python scripts/deploy/public_domain.py --domain example.com --api      # also api.example.com for CI release gates

Writes the public origins and token issuers into the git-ignored infra/compose/dev.env, then renders the
Keycloak realms and the portals' settings. Run it before the first `bash scripts/docker_up.sh`; on an install
that already ran, also run with --reset-identity (Keycloak keeps its first realm import in the kcdata volume).
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / "infra" / "compose" / "dev.env"


def set_values(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        line = f"{key}={value}"
        text, n = re.subn(rf"^{key}=.*$", line, text, flags=re.M)
        if not n:
            text = text.rstrip("\n") + "\n" + line + "\n"
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, help="your domain on Cloudflare, e.g. assureops.me")
    parser.add_argument("--app", default="app", help="subdomain of the customer portal")
    parser.add_argument("--staff", default="staff", help="subdomain of the staff portal")
    parser.add_argument("--auth", default="auth", help="subdomain of sign-in (Keycloak)")
    parser.add_argument("--api", action="store_true", help="also expose api.<domain> for customers' CI release gates")
    parser.add_argument("--reset-identity", action="store_true",
                        help="drop the Keycloak data volume so the realms are imported again with the new addresses (accounts reset)")
    args = parser.parse_args()
    domain = args.domain.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", domain):
        sys.exit("give a domain such as example.com")
    if not ENV.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "init_dev_env.py")], check=True)
    auth = f"https://{args.auth}.{domain}"
    values = {
        "PUBLIC_CUSTOMER_ORIGIN": f"https://{args.app}.{domain}", "PUBLIC_STAFF_ORIGIN": f"https://{args.staff}.{domain}",
        "PUBLIC_AUTH_ORIGIN": auth, "CUSTOMER_OIDC_ISSUER": f"{auth}/realms/assureops", "STAFF_OIDC_ISSUER": f"{auth}/realms/assureops-staff",
        "STAFF_MFA_REQUIRED": "true",
    }
    ENV.write_text(set_values(ENV.read_text(encoding="utf-8"), values), encoding="utf-8")
    for script in ("render_realm.py", "render_storage.py", "render_web_env.py"):
        subprocess.run([sys.executable, str(ROOT / "scripts" / script)], check=True, stdout=subprocess.DEVNULL)
    if args.reset_identity:
        subprocess.run(["docker", "compose", "--env-file", str(ENV), "-f", str(ROOT / "infra/compose/full-stack.yml"), "rm", "-sf", "keycloak"], check=False)
        subprocess.run(["docker", "volume", "rm", "assureops_kcdata"], check=False)
    print("Public addresses written to infra/compose/dev.env:")
    for key in ("PUBLIC_CUSTOMER_ORIGIN", "PUBLIC_STAFF_ORIGIN", "PUBLIC_AUTH_ORIGIN"):
        print(f"  {key}={values[key]}")
    print("\nIn Cloudflare Zero Trust -> Networks -> Tunnels -> your tunnel -> Public hostnames, add:")
    print(f"  {args.app}.{domain}    -> http://localhost:3700")
    print(f"  {args.staff}.{domain}  -> http://localhost:3710")
    print(f"  {args.auth}.{domain}   -> http://localhost:8780")
    if args.api:
        print(f"  api.{domain}    -> http://localhost:8700   (customers set ASSUREOPS_API_URL=https://api.{domain})")
    print("\nThen start (or restart) the stack:  bash scripts/docker_up.sh")


if __name__ == "__main__":
    main()
