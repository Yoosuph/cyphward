"""Owner console access (admin.cyphward.com): one see-everything principal.

Entry needs email + password + a fresh authenticator code; only the owner
cookie authenticates owner endpoints; every attempt is audited and an audit
failure returns no access. See backend/app/core/owner.py.
"""
import time
from datetime import datetime, timedelta, timezone

import backend.app.core.owner as owner_mod
from backend.app.core import totp
from backend.app.core.security import hash_password
from conftest import ALICE, BOB, sign_token

PASSWORD = "correct-horse-42"
ORIGIN = {"Origin": "http://testserver"}
SECRET = totp.generate_secret()


def _code(offset=0):
    return f"{totp._hotp(SECRET, int(time.time() // 30) + offset):06d}"


def _make_owner(store, uid=ALICE, enrolled=True):
    store.profiles[uid]["password_hash"] = hash_password(PASSWORD)
    if enrolled:
        store.profiles[uid]["totp_secret_enc"] = totp.encrypt_secret(SECRET)
        store.profiles[uid]["totp_enrolled_at"] = datetime.now(timezone.utc)
    store.platform_owners[uid] = {"user_id": uid, "last_totp_step": None}


def _sign_in(client, uid=ALICE, password=PASSWORD, code=None, headers=ORIGIN):
    return client.post("/api/v1/owner/session", headers=headers,
                       json={"email": f"{uid[:8]}@acme.test", "password": password,
                             "code": code if code is not None else _code()})


def test_owner_signs_in_with_password_and_authenticator(client, store):
    _make_owner(store)
    resp = _sign_in(client)
    assert resp.status_code == 200 and resp.json()["ok"] is True
    assert owner_mod.COOKIE_NAME in resp.cookies
    assert client.get("/api/v1/owner/me").json()["email"] == f"{ALICE[:8]}@acme.test"
    assert store.owner_sessions[0]["token_hash"] != client.cookies.get(owner_mod.COOKIE_NAME)
    assert store.owner_audit[-1]["action"] == "owner.sign_in" and store.owner_audit[-1]["outcome"] == "success"


def test_every_failure_looks_the_same(client, store):
    _make_owner(store)
    _make_owner(store, BOB, enrolled=False)
    del store.platform_owners[BOB]
    attempts = [
        _sign_in(client, password="wrong"),                  # wrong password
        _sign_in(client, code="000000" if _code() != "000000" else "111111"),  # wrong code
        _sign_in(client, BOB),                                # not an owner
    ]
    store.platform_owners[BOB] = {"user_id": BOB, "last_totp_step": None}
    attempts.append(_sign_in(client, BOB))                   # owner without authenticator
    attempts.append(client.post("/api/v1/owner/session", headers=ORIGIN,
                                json={"email": "nobody@acme.test", "password": PASSWORD, "code": _code()}))
    assert {(r.status_code, r.json()["detail"]) for r in attempts} == {(401, "Sign-in failed.")}
    assert owner_mod.COOKIE_NAME not in client.cookies
    assert {a["outcome"] for a in store.owner_audit} == {"denied"}


def test_a_code_cannot_be_used_twice(client, store):
    _make_owner(store)
    code = _code()
    assert _sign_in(client, code=code).status_code == 200
    replay = _sign_in(client, code=code)
    assert replay.status_code == 401
    assert store.owner_audit[-1]["metadata"]["reason"] == "code_replayed"
    assert _sign_in(client, code=_code(1)).status_code == 200  # the next step is fine


def test_customer_credentials_never_open_the_console(client, store, auth_headers):
    _make_owner(store)
    # A normal (customer) access token is refused, alone or alongside a valid owner cookie.
    assert client.get("/api/v1/owner/me", headers=auth_headers(ALICE)).status_code == 401
    assert _sign_in(client).status_code == 200
    assert client.get("/api/v1/owner/me", headers=auth_headers(ALICE)).status_code == 401
    # The owner cookie never authenticates customer endpoints.
    assert client.get("/api/v1/auth/mfa/status").status_code == 401


def test_removing_the_owner_row_ends_access_immediately(client, store):
    _make_owner(store)
    assert _sign_in(client).status_code == 200
    del store.platform_owners[ALICE]
    assert client.get("/api/v1/owner/me").status_code == 401


def test_idle_and_absolute_expiry(client, store):
    _make_owner(store)
    assert _sign_in(client).status_code == 200
    store.owner_sessions[0]["last_seen_at"] = datetime.now(timezone.utc) - timedelta(minutes=31)
    assert client.get("/api/v1/owner/me").status_code == 401

    assert _sign_in(client, code=_code(1)).status_code == 200
    store.owner_sessions[-1]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert client.get("/api/v1/owner/me").status_code == 401


def test_sign_in_requires_the_console_origin(client, store):
    _make_owner(store)
    assert _sign_in(client, headers={"Origin": "https://evil.example"}).status_code == 403
    assert _sign_in(client, headers={}).status_code == 403


def test_audit_failure_gives_no_access(client, store):
    _make_owner(store)
    store.owner_audit_fails = True
    resp = _sign_in(client)
    assert resp.status_code == 503
    assert all(s["revoked_at"] is not None for s in store.owner_sessions)
    store.owner_audit_fails = False
    assert client.get("/api/v1/owner/me").status_code == 401


def test_logout_always_clears_the_cookie_and_revokes(client, store):
    anonymous = client.post("/api/v1/owner/logout")
    assert anonymous.status_code == 200
    assert owner_mod.COOKIE_NAME in anonymous.headers.get("set-cookie", "")

    _make_owner(store)
    assert _sign_in(client).status_code == 200
    assert client.post("/api/v1/owner/logout").status_code == 200
    assert store.owner_sessions[0]["revoked_at"] is not None
    assert client.get("/api/v1/owner/me").status_code == 401


def test_authenticator_cannot_be_silently_replaced(client, store, auth_headers):
    _make_owner(store)
    store.profiles[ALICE]["email_verified_at"] = datetime.now(timezone.utc)
    headers = auth_headers(ALICE, email=f"{ALICE[:8]}@acme.test")
    resp = client.post("/api/v1/auth/totp/enroll/start", headers=headers)
    assert resp.status_code == 409
    assert totp.decrypt_secret(store.profiles[ALICE]["totp_secret_enc"]) == SECRET


def test_switching_the_authenticator_off_ends_owner_sessions(client, store, auth_headers):
    _make_owner(store)
    assert _sign_in(client).status_code == 200
    resp = client.post("/api/v1/auth/totp/disable", headers=auth_headers(ALICE), json={"code": _code()})
    assert resp.status_code == 200
    assert store.owner_sessions[0]["revoked_at"] is not None
