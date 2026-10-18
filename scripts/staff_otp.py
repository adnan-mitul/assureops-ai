"""Print the current one-time code for a local staff test user (RFC 6238 TOTP, 30 s, 6 digits).

    python scripts/staff_otp.py analyst@assureops.test

Local development only: the secret is a test value in the git-ignored dev.env.
In shared environments staff enroll their own authenticator app.
"""

import hashlib
import hmac
import struct
import sys
import time
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / "infra" / "compose" / "dev.env"


def totp(secret: str, at: float | None = None, period: int = 30, digits: int = 6) -> str:
    counter = int((at or time.time()) // period)
    digest = hmac.new(secret.encode(), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: staff_otp.py <staff username>")
    key = "STAFF_OTP_" + sys.argv[1].split("@")[0].upper().replace(".", "_")
    values = dict(line.split("=", 1) for line in ENV.read_text().splitlines() if "=" in line and not line.startswith("#"))
    if key not in values:
        raise SystemExit(f"no local TOTP secret for {sys.argv[1]}; run scripts/render_realm.py")
    remaining = 30 - int(time.time()) % 30
    print(f"{totp(values[key])}  (valid for {remaining} s)")


if __name__ == "__main__":
    main()
