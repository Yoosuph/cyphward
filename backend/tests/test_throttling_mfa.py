"""Shared throttling + admin login step-up (review P2 — throttling).

Login, reset and welcome cooldowns were process-memory dicts: invisible
across replicas, lost on restart, unbounded. They now share one atomic
Postgres fixed-window store (rate_limits). Password logins for
owner/admin accounts additionally require a 6-digit email step-up code
before any session is issued; member logins are unchanged.
"""
import backend.app.api.auth as auth_mod
from backend.app.core.security import hash_opaque_token, hash_password
from conftest import ADMI, ALICE, BOB, ORG_A
from datetime import datetime, timedelta, timezone

PASSWORD = "correct-horse-42"


def _set_password(store, user_id):
    store.profiles[user_id]["password_hash"] = hash_password(PASSWORD)


def _login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_member_login_issues_session_without_mfa(client, store):
    _set_password(store, BOB)
    resp = _login(client, f"{BOB[:8]}@acme.test")
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_owner_login_requires_mfa_step_up(client, store, monkeypatch):
    _set_password(store, ALICE)
    monkeypatch.setattr(auth_mod, "send_email_sync", lambda *a, **k: {"success": True})
    monkeypatch.setattr(auth_mod.secrets, "randbelow", lambda _n: 42)
    resp = _login(client, f"{ALICE[:8]}@acme.test")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("mfa_required") is True
    assert body.get("mfa_token")
    assert "access_token" not in body

    verify = client.post("/api/v1/auth/mfa/verify",
                         json={"mfa_token": body["mfa_token"], "code": "000042"})
    assert verify.status_code == 200
    assert "access_token" in verify.json()

    # single-use: the same code is dead afterwards
    again = client.post("/api/v1/auth/mfa/verify",
                        json={"mfa_token": body["mfa_token"], "code": "000042"})
    assert again.status_code in (400, 401)


def test_mfa_wrong_code_rejected(client, store, monkeypatch):
    _set_password(store, ADMI)
    monkeypatch.setattr(auth_mod, "send_email_sync", lambda *a, **k: {"success": True})
    monkeypatch.setattr(auth_mod.secrets, "randbelow", lambda _n: 42)
    token = _login(client, f"{ADMI[:8]}@acme.test").json()["mfa_token"]
    resp = client.post("/api/v1/auth/mfa/verify",
                       json={"mfa_token": token, "code": "999999"})
    assert resp.status_code == 401


def test_mfa_token_tampered_rejected(client):
    resp = client.post("/api/v1/auth/mfa/verify",
                       json={"mfa_token": "tampered.token.here", "code": "000042"})
    assert resp.status_code == 401


def test_login_throttle_is_fail_closed_and_shared(client, store):
    _set_password(store, BOB)
    email = f"{BOB[:8]}@acme.test"
    for _ in range(6):
        resp = _login(client, email, password="wrong-password")
        assert resp.status_code == 401  # no throttle oracle, even when throttled
        assert resp.json()["detail"] == "Invalid email or password."
    bucket = next(r for r in store.rate_limits if r["bucket_key"] == f"login:{email}")
    assert bucket["count"] == 6


def test_successful_login_resets_throttle_bucket(client, store):
    _set_password(store, BOB)
    email = f"{BOB[:8]}@acme.test"
    _login(client, email, password="wrong-password")
    assert _login(client, email).status_code == 200
    assert all(r["bucket_key"] != f"login:{email}" for r in store.rate_limits)


def test_reset_cooldown_is_shared_and_generic(client, store, monkeypatch):
    async def fake_send(*a, **k):
        return {"success": True}
    monkeypatch.setattr(auth_mod, "send_email_async", fake_send)
    _set_password(store, BOB)
    email = f"{BOB[:8]}@acme.test"
    assert client.post("/api/v1/auth/forgot-password", json={"email": email}).json() == {"ok": True}
    assert client.post("/api/v1/auth/forgot-password", json={"email": email}).json() == {"ok": True}
    assert len(store.password_reset_tokens) == 1


def test_password_reset_sends_recovery_alert(client, store, monkeypatch):
    sent = []

    async def fake_send(to, subject, html, text, recipient_name=None, **k):
        sent.append({"to": to, "subject": subject})
        return {"success": True}

    monkeypatch.setattr(auth_mod, "send_email_async", fake_send)
    _set_password(store, BOB)
    email = f"{BOB[:8]}@acme.test"
    store.password_reset_tokens.append({
        "id": "rst-1", "user_id": BOB, "token_hash": hash_opaque_token("tok-abc"),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=20),
        "used_at": None, "created_at": "2026-10-04T00:00:00",
    })
    # mirror the CAS update + cleanup handlers used by reset-password
    resp = client.post("/api/v1/auth/reset-password",
                       json={"token": "tok-abc", "password": "brand-new-pass-9"})
    assert resp.status_code == 200
    assert any(s["subject"] == "Your Cyphward password was changed" for s in sent), sent


def test_mfa_resend_cooldown_and_recovery(client, store, monkeypatch):
    _set_password(store, ALICE)
    monkeypatch.setattr(auth_mod, "send_email_sync", lambda *a, **k: {"success": True})
    monkeypatch.setattr(auth_mod.secrets, "randbelow", lambda _n: 7)
    token = _login(client, f"{ALICE[:8]}@acme.test").json()["mfa_token"]
    # resend immediately after login-issued code -> 429 cooldown
    assert client.post("/api/v1/auth/mfa/send",
                       json={"mfa_token": token, "code": ""}).status_code == 429
    # age the stored row past the 60s resend window, then resend works
    for r in store.email_otps:
        if r.get("purpose") == "mfa":
            r["created_at"] = datetime.now(timezone.utc) - timedelta(seconds=61)
    assert client.post("/api/v1/auth/mfa/send",
                       json={"mfa_token": token, "code": ""}).json() == {"sent": True}
