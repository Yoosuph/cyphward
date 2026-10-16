"""Dedicated owner-console logins: operator-created, first sign-in setup.

The operator gives a setup password that works once, only to open a short
setup session: choose a new password and enrol an authenticator. The login
never works in the customer app and never resets by email.
"""
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import backend.app.core.owner as owner_mod
from backend.app.core import totp
from backend.app.core.security import hash_password

SETUP_PASSWORD = "Given-in-chat-2020"
NEW_PASSWORD = "a-much-better-owner-passphrase"
ORIGIN = {"Origin": "http://testserver"}


def _admin(store, open_hours=24):
    uid = str(uuid4())
    store.profiles[uid] = {"id": uid, "email": "admin@cyphward.test", "full_name": "Cyphward Admin",
                           "role": "Member", "password_hash": hash_password(SETUP_PASSWORD), "provider": "email",
                           "email_verified_at": datetime.now(timezone.utc)}
    store.platform_owners[uid] = {"user_id": uid, "last_totp_step": None, "console_only": True}
    store.owner_setups[uid] = {"user_id": uid, "completed_at": None,
                               "expires_at": datetime.now(timezone.utc) + timedelta(hours=open_hours)}
    return uid


def _sign_in(client, password=SETUP_PASSWORD, code=""):
    return client.post("/api/v1/owner/session", headers=ORIGIN,
                       json={"email": "admin@cyphward.test", "password": password, "code": code})


def _code(secret, offset=0):
    return f"{totp._hotp(secret, int(time.time() // 30) + offset):06d}"


def test_first_sign_in_completes_setup_and_retires_the_setup_password(client, store):
    uid = _admin(store)
    first = _sign_in(client)
    assert first.status_code == 200 and first.json()["setup_required"] is True
    # A setup session sees no data and no console.
    assert client.get("/api/v1/owner/me").status_code == 401

    issued = client.post("/api/v1/owner/setup/authenticator", headers=ORIGIN).json()
    secret = issued["secret"]
    assert issued["otpauth_url"].startswith("otpauth://totp/")

    weak = client.post("/api/v1/owner/setup/complete", headers=ORIGIN,
                       json={"new_password": "short", "code": _code(secret)})
    assert weak.status_code == 400
    same = client.post("/api/v1/owner/setup/complete", headers=ORIGIN,
                       json={"new_password": SETUP_PASSWORD + "", "code": _code(secret)})
    assert same.status_code == 400
    wrong = client.post("/api/v1/owner/setup/complete", headers=ORIGIN,
                        json={"new_password": NEW_PASSWORD, "code": "000000" if _code(secret) != "000000" else "111111"})
    assert wrong.status_code == 401

    done = client.post("/api/v1/owner/setup/complete", headers=ORIGIN,
                       json={"new_password": NEW_PASSWORD, "code": _code(secret)})
    assert done.status_code == 200
    assert client.get("/api/v1/owner/me").json()["email"] == "admin@cyphward.test"
    assert store.owner_setups[uid]["completed_at"] is not None

    # The setup password is gone; the real one needs a fresh code.
    client.post("/api/v1/owner/logout")
    assert _sign_in(client).status_code == 401
    assert _sign_in(client, NEW_PASSWORD, _code(secret)).status_code == 401  # same step: replay refused
    assert _sign_in(client, NEW_PASSWORD, _code(secret, 1)).status_code == 200


def test_setup_endpoints_need_a_setup_session(client, store):
    _admin(store)
    assert client.post("/api/v1/owner/setup/authenticator", headers=ORIGIN).status_code == 401
    assert client.post("/api/v1/owner/setup/complete", headers=ORIGIN,
                       json={"new_password": NEW_PASSWORD, "code": "123456"}).status_code == 401


def test_expired_or_finished_setup_does_not_open(client, store):
    uid = _admin(store, open_hours=-1)
    assert _sign_in(client).status_code == 401
    store.owner_setups[uid]["expires_at"] = datetime.now(timezone.utc) + timedelta(hours=1)
    store.owner_setups[uid]["completed_at"] = datetime.now(timezone.utc)
    assert _sign_in(client).status_code == 401


def test_setup_needs_the_console_origin(client, store):
    _admin(store)
    assert _sign_in(client).status_code == 200
    assert client.post("/api/v1/owner/setup/authenticator", headers={"Origin": "https://evil.example"}).status_code == 403


def test_console_only_login_never_reaches_the_customer_app(client, store):
    uid = _admin(store)
    login = client.post("/api/v1/auth/login", json={"email": "admin@cyphward.test", "password": SETUP_PASSWORD})
    assert login.status_code == 401 and login.json()["detail"] == "Invalid email or password."
    sent = client.post("/api/v1/auth/forgot-password", json={"email": "admin@cyphward.test"})
    assert sent.status_code == 200 and store.password_reset_tokens == []
    import backend.app.api.auth_google as google_mod
    assert google_mod._upsert_google_profile("admin@cyphward.test", "Someone") is None
    from backend.app.core.sessions import issue_session
    try:
        issue_session(store.profiles[uid])
        raise AssertionError("console-only login must not get a customer session")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 401
