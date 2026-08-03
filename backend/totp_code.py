"""
Print the current TOTP code for a seeded account, and optionally drive the whole
login -> 2FA -> /auth/me flow against the running backend.

DEVELOPMENT ONLY. It decrypts the stored TOTP secret with TOTP_ENCRYPTION_KEY,
which is exactly what an authenticator app holds — so this is a stand-in for the
phone you would otherwise need, not a bypass of anything. It cannot work without
the key, and the key is not in the database.

    uv run python totp_code.py                      # code for osairum
    uv run python totp_code.py yahya@...            # code for someone else
    uv run python totp_code.py osairum@... --trace  # full flow, prints /auth/me
"""

import sys

import pyotp
from sqlalchemy import text

from app.auth.totp import decrypt_secret
from app.core.db import service_engine

DEFAULT_EMAIL = "osairum@edubridge.example.com"
PASSWORDS = {
    "osairum@edubridge.example.com": "osairum123",
    "yahya@edubridge.example.com": "yahya123",
    "muneeb@edubridge.example.com": "muneeb123",
    "mujtaba@edubridge.example.com": "mujtaba123",
}
API = "http://localhost:8000/api"


def current_code(email: str) -> str:
    with service_engine.connect() as conn:
        secret = conn.execute(
            text(
                "SELECT tf.totp_secret_encrypted FROM two_factor_enrollment tf "
                "JOIN app_user u ON u.id = tf.user_id "
                "WHERE u.email = :e AND tf.status = 'active'"
            ),
            {"e": email},
        ).scalar_one_or_none()
    if secret is None:
        raise SystemExit(f"{email} has no ACTIVE totp enrolment (enrol first, or check the email)")
    return pyotp.TOTP(decrypt_secret(bytes(secret))).now()


def trace(email: str, code: str) -> None:
    import httpx

    with httpx.Client(base_url=API, timeout=15) as client:
        login = client.post(
            "/auth/login", json={"email": email, "password": PASSWORDS[email]}
        ).json()
        print("login            ->", login.get("status"))
        if login.get("status") != "two_factor_required":
            raise SystemExit(f"unexpected: {login}")

        verify = client.post(
            "/auth/2fa/verify",
            json={"pending_token": login["pending_token"], "code": code, "type": "totp"},
        )
        print("2fa/verify       ->", verify.status_code)
        if verify.status_code != 200:
            raise SystemExit(f"  {verify.text}")
        body = verify.json()
        print("  onboarding_state:", body["onboarding_state"])
        # The cookie the browser needs on reload. Its Path is what decides
        # whether it comes back on /auth/refresh.
        for name, value in verify.headers.multi_items():
            if name.lower() == "set-cookie":
                print("  set-cookie:", value.split("=", 1)[0], "|", value.split(";", 1)[1].strip())

        me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        print("GET /auth/me     ->", me.status_code)
        for key in ("role", "onboarding_state", "email_verified"):
            print(f"  {key}: {me.json().get(key)}")
        print("  guardian:", me.json().get("guardian"))

        refreshed = client.post("/auth/refresh")
        print(
            "POST /auth/refresh (with the cookie the client just stored) ->", refreshed.status_code
        )


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    email = args[0] if args else DEFAULT_EMAIL
    code = current_code(email)
    print(f"\n  TOTP code for {email}:  {code}\n")
    if "--trace" in sys.argv:
        trace(email, code)
