"""Remembered browsers for the sign-in step-up code.

Owners/admins always confirm sign-in with a code, but a browser remembered
after a correct code (opt-in checkbox) skips the second factor for 30 days.
The cookie never replaces the first factor, is bound to one user, expires,
fails closed, and is forgotten on factor changes or on request.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import backend.app.api.auth as auth_mod
import backend.app.api.auth_google as google_mod
import backend.app.core.trusted_browsers as tb
from backend.app.core.security import hash_password
from conftest import ADMI, ALICE

PASSWORD = "correct-horse-42"
CODE = "000042"


def _prep(store, monkeypatch, *users):
    for uid in users:
        store.profiles[uid]["password_hash"] = hash_password(PASSWORD)
        store.profiles[uid]["email_verified_at"] = datetime.now(timezone.utc)
    sent = []

    async def _send(*a, **k):
        sent.append(a)
        return {"success": True}

    monkeypatch.setattr(auth_mod, "send_email_async", _send)
    monkeypatch.setattr(auth_mod.secrets, "randbelow", lambda _n: 42)
    store.test_actions = []
    monkeypatch.setattr(auth_mod, "log_audit",
                        lambda _org, uid, action, *a, **k: store.test_actions.append((str(uid), action)))
    return sent


def _login(client, uid):
    return client.post("/api/v1/auth/login", json={"email": f"{uid[:8]}@acme.test", "password": PASSWORD})


def _verify(client, token, remember):
    return client.post("/api/v1/auth/mfa/verify", json={"mfa_token": token, "code": CODE, "remember": remember})


def _actions(store, uid):
    return [action for who, action in store.test_actions if who == uid]


def test_remembered_browser_skips_only_the_second_factor(client, store, monkeypatch):
    _prep(store, monkeypatch, ALICE)
    challenge = _login(client, ALICE).json()
    assert challenge["mfa_required"] is True
    verified = _verify(client, challenge["mfa_token"], remember=True)
    assert verified.status_code == 200 and "access_token" in verified.json()
    assert tb.COOKIE_NAME in verified.cookies
    assert len(store.trusted_browsers) == 1
    assert store.trusted_browsers[0]["token_hash"] != client.cookies.get(tb.COOKIE_NAME)  # only the hash is stored

    again = _login(client, ALICE)
    assert again.status_code == 200 and "access_token" in again.json()
    assert "auth.mfa_skipped_trusted_browser" in _actions(store, ALICE)

    # The first factor is still required: a wrong password is refused.
    wrong = client.post("/api/v1/auth/login", json={"email": f"{ALICE[:8]}@acme.test", "password": "nope"})
    assert wrong.status_code == 401


def test_without_remember_the_code_is_asked_every_time(client, store, monkeypatch):
    _prep(store, monkeypatch, ALICE)
    first = _login(client, ALICE).json()
    assert _verify(client, first["mfa_token"], remember=False).status_code == 200
    assert store.trusted_browsers == []
    assert _login(client, ALICE).json().get("mfa_required") is True


def test_remembered_browser_is_bound_to_its_user(client, store, monkeypatch):
    _prep(store, monkeypatch, ALICE, ADMI)
    _verify(client, _login(client, ALICE).json()["mfa_token"], remember=True)
    # Same browser, different owner/admin account: still asked for a code.
    assert _login(client, ADMI).json().get("mfa_required") is True


def test_expired_remembered_browser_asks_for_the_code(client, store, monkeypatch):
    _prep(store, monkeypatch, ALICE)
    _verify(client, _login(client, ALICE).json()["mfa_token"], remember=True)
    store.trusted_browsers[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert _login(client, ALICE).json().get("mfa_required") is True


def test_lookup_failure_fails_closed(client, store, monkeypatch):
    _prep(store, monkeypatch, ALICE)
    _verify(client, _login(client, ALICE).json()["mfa_token"], remember=True)

    def boom(*_a, **_k):
        raise RuntimeError("relation trusted_browsers does not exist")

    monkeypatch.setattr(tb, "execute_one", boom)
    assert _login(client, ALICE).json().get("mfa_required") is True


def test_google_step_up_defers_the_email_to_mfa_start(client, store, monkeypatch):
    sent = _prep(store, monkeypatch, ALICE)
    token = asyncio.run(google_mod._google_step_up(store.profiles[ALICE]))
    assert token and sent == [], "the OAuth callback must not mail a code"

    started = client.post("/api/v1/auth/mfa/start", json={"mfa_token": token})
    assert started.status_code == 200
    assert started.json()["mfa_required"] is True and len(sent) == 1

    # A second start reuses the still-valid code instead of mailing another.
    client.post("/api/v1/auth/mfa/start", json={"mfa_token": token})
    assert len(sent) == 1

    assert _verify(client, token, remember=True).status_code == 200
    fresh = asyncio.run(google_mod._google_step_up(store.profiles[ALICE]))
    trusted = client.post("/api/v1/auth/mfa/start", json={"mfa_token": fresh})
    assert trusted.status_code == 200 and "access_token" in trusted.json()
    assert len(sent) == 1, "a remembered browser gets no new email"


def test_mfa_start_rejects_an_invalid_token(client, store, monkeypatch):
    _prep(store, monkeypatch, ALICE)
    assert client.post("/api/v1/auth/mfa/start", json={"mfa_token": "forged"}).status_code == 401


def test_forget_and_factor_changes_clear_remembered_browsers(client, store, monkeypatch, auth_headers):
    _prep(store, monkeypatch, ALICE)
    headers = auth_headers(ALICE, email=f"{ALICE[:8]}@acme.test")
    _verify(client, _login(client, ALICE).json()["mfa_token"], remember=True)
    assert client.get("/api/v1/auth/mfa/status", headers=headers).json()["remembered_browsers"] == 1

    forgot = client.post("/api/v1/auth/trusted-browsers/forget", headers=headers)
    assert forgot.status_code == 200 and store.trusted_browsers == []
    assert "auth.trusted_browsers_forgotten" in _actions(store, ALICE)
    assert _login(client, ALICE).json().get("mfa_required") is True

    _verify(client, _login(client, ALICE).json()["mfa_token"], remember=True)
    assert len(store.trusted_browsers) == 1
    assert client.post("/api/v1/auth/mfa/enroll", headers=headers).status_code == 200
    assert store.trusted_browsers == [], "turning a factor on or off forgets remembered browsers"
