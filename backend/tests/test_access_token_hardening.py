"""Only live, session-bound access tokens authenticate API calls.

Regression for the step-up bypass: the sign-in challenge (mfa_token) is
signed with the same secret and carries sub/exp, and used to pass the bearer
check, so a password (or Google account) alone gave 10 minutes of access
without the emailed code. Challenge tokens, sid-less tokens and tokens bound
to an unknown, foreign, revoked or expired session are now rejected.
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

import jwt as pyjwt

import backend.app.api.auth as auth_mod
import backend.app.api.auth_google as google_mod
from backend.app.core import config
from backend.app.core.security import hash_password
from conftest import ALICE, BOB, ORG_A, sign_token

PASSWORD = "correct-horse-42"
ENDPOINTS = ("/api/v1/auth/mfa/status", "/api/v1/overview", "/api/v1/domains")


def _bearer(token):
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": ORG_A}


def _raw_token(**claims):
    now = int(time.time())
    return pyjwt.encode({"sub": ALICE, "iat": now, "exp": now + 600, **claims},
                        config.AUTH_JWT_SECRET, algorithm="HS256")


def _all_unauthorized(client, token):
    return {path: client.get(path, headers=_bearer(token)).status_code for path in ENDPOINTS}


def test_password_step_up_challenge_is_not_an_access_token(client, store, monkeypatch):
    store.profiles[ALICE]["password_hash"] = hash_password(PASSWORD)

    async def _send(*a, **k):
        return {"success": True}

    monkeypatch.setattr(auth_mod, "send_email_async", _send)
    challenge = client.post("/api/v1/auth/login",
                            json={"email": f"{ALICE[:8]}@acme.test", "password": PASSWORD}).json()
    assert challenge["mfa_required"] is True
    assert set(_all_unauthorized(client, challenge["mfa_token"]).values()) == {401}


def test_google_step_up_challenge_is_not_an_access_token(client, store):
    token = asyncio.run(google_mod._google_step_up(store.profiles[ALICE]))
    assert token
    assert set(_all_unauthorized(client, token).values()) == {401}


def test_tokens_with_another_purpose_or_type_are_rejected(client, store):
    sid = store.create_session(ALICE)
    assert client.get(ENDPOINTS[0], headers=_bearer(_raw_token(sid=sid, purpose="mfa"))).status_code == 401
    assert client.get(ENDPOINTS[0], headers=_bearer(_raw_token(sid=sid, typ="refresh"))).status_code == 401


def test_token_without_a_session_is_rejected(client, store):
    assert client.get(ENDPOINTS[0], headers=_bearer(_raw_token(typ="access"))).status_code == 401
    assert client.get(ENDPOINTS[0], headers=_bearer(_raw_token(typ="access", sid="not-a-uuid"))).status_code == 401


def test_unknown_or_foreign_session_is_rejected(client, store):
    unknown = "00000000-0000-4000-8000-00000000abcd"
    assert client.get(ENDPOINTS[0], headers=_bearer(_raw_token(typ="access", sid=unknown))).status_code == 401
    bobs = store.create_session(BOB)
    assert client.get(ENDPOINTS[0], headers=_bearer(_raw_token(typ="access", sid=bobs))).status_code == 401


def test_revoked_or_expired_session_is_rejected(client, store):
    sid = store.create_session(ALICE)
    token = sign_token(ALICE, f"{ALICE[:8]}@acme.test", sid=sid)
    assert client.get(ENDPOINTS[0], headers=_bearer(token)).status_code == 200

    session = next(s for s in store.sessions if s["id"] == sid)
    session["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert client.get(ENDPOINTS[0], headers=_bearer(token)).status_code == 401

    session["expires_at"] = datetime.now(timezone.utc) + timedelta(days=1)
    session["revoked_at"] = datetime.now(timezone.utc)
    assert client.get(ENDPOINTS[0], headers=_bearer(token)).status_code == 401


def test_pre_typ_access_token_with_live_session_still_works(client, store):
    """Tokens minted just before this release (no typ claim) stay valid until expiry."""
    sid = store.create_session(ALICE)
    legacy = _raw_token(sid=sid, email=f"{ALICE[:8]}@acme.test")
    assert client.get(ENDPOINTS[0], headers=_bearer(legacy)).status_code == 200


def test_issued_access_tokens_are_typed_and_session_bound(client, store):
    store.profiles[BOB]["password_hash"] = hash_password(PASSWORD)
    tokens = client.post("/api/v1/auth/login",
                         json={"email": f"{BOB[:8]}@acme.test", "password": PASSWORD}).json()
    claims = pyjwt.decode(tokens["access_token"], config.AUTH_JWT_SECRET, algorithms=["HS256"])
    assert claims["typ"] == "access" and claims["sid"]
    assert client.get(ENDPOINTS[0], headers=_bearer(tokens["access_token"])).status_code == 200
