"""
Own-auth tests: register/login/refresh/logout, password reset via Brevo link,
bootstrap, and Google OAuth endpoints (no network — Google calls are avoided
by only exercising offline paths).

All emails are mocked (auth_mod.send_email_async) — nothing touches Brevo.
"""
import re
import uuid
from datetime import datetime, timezone

import pytest

from backend.app.api import auth as auth_mod
from backend.app.api import auth_google as google_mod
from backend.app.core import config
from backend.app.core.security import hash_opaque_token
from conftest import ALICE, ORG_A

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    auth_mod._login_attempts.clear()
    auth_mod._reset_cooldown.clear()
    auth_mod._last_sent.clear()
    yield
    auth_mod._login_attempts.clear()
    auth_mod._reset_cooldown.clear()
    auth_mod._last_sent.clear()


@pytest.fixture
def capture_email(monkeypatch):
    """Capture Brevo payloads instead of sending them."""
    captured = []

    def _fake(*args, **kwargs):
        captured.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(auth_mod, "send_email_async", _fake)
    return captured


def _register(client, email="ada@example.com", password=PASSWORD, name="Ada Obi"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": name},
    )


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def test_register_returns_session(client, store):
    resp = _register(client)
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["email"] == "ada@example.com"
    assert data["user"]["full_name"] == "Ada Obi"
    assert data["user"]["email_verified_at"] is None

    stored = next(p for p in store.profiles.values() if p["email"] == "ada@example.com")
    assert stored["password_hash"] and stored["password_hash"].startswith("$argon2")


def test_register_rejects_short_password(client):
    resp = _register(client, password="short")
    assert resp.status_code == 400


def test_register_rejects_duplicate_email(client):
    assert _register(client).status_code == 200
    resp = _register(client)
    assert resp.status_code == 409


def test_register_refuses_to_adopt_existing_profile(client, store):
    """P0-1: public registration must never take over an existing profile.

    The old adopt-by-email path handed the registrant every organization
    membership attached to a passwordless (Google or invited) profile.
    """
    invited_id = str(uuid.uuid4())
    store.profiles[invited_id] = {
        "id": invited_id, "email": "invited@acme.test", "full_name": "Real Owner",
        "password_hash": None, "provider": "google",
        "email_verified_at": datetime.now(timezone.utc),
    }
    store.memberships.append(
        {"user_id": invited_id, "org_id": ORG_A, "role": "owner"}
    )

    resp = _register(client, email="invited@acme.test", name="Invited Person")

    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]
    # No session for the victim's account, and nothing about it changed.
    assert "access_token" not in resp.json()
    profile = store.profiles[invited_id]
    assert profile["password_hash"] is None
    assert profile["provider"] == "google"
    assert profile["full_name"] == "Real Owner"
    assert any(
        m["user_id"] == invited_id and m["org_id"] == ORG_A and m["role"] == "owner"
        for m in store.memberships
    )


# ---------------------------------------------------------------------------
# Login / refresh / logout
# ---------------------------------------------------------------------------
def test_login_success_and_works(client):
    _register(client)
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": PASSWORD},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    boot = client.get("/api/v1/auth/bootstrap", headers={"Authorization": f"Bearer {token}"})
    assert boot.status_code == 200
    assert boot.json()["user"]["email"] == "ada@example.com"


def test_login_wrong_password_and_unknown_email_are_generic(client):
    _register(client)
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password."

    resp2 = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever-123"},
    )
    assert resp2.status_code == 401
    assert resp2.json()["detail"] == "Invalid email or password."


def test_refresh_rotates_token(client):
    tokens = _register(client).json()
    old_refresh = tokens["refresh_token"]

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200
    rotated = resp.json()
    assert rotated["refresh_token"] != old_refresh
    assert rotated["access_token"]

    # Old refresh token is dead after rotation
    resp2 = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp2.status_code == 401


def test_logout_revokes_refresh_token(client):
    tokens = _register(client).json()
    out = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert out.status_code == 200

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 401


def test_refresh_rejects_garbage(client):
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-token"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Password reset (Brevo link)
# ---------------------------------------------------------------------------
def _extract_reset_token(captured):
    html = captured[-1]["args"][2]
    match = re.search(r"token=([A-Za-z0-9_\-]+)", html)
    assert match, "reset email is missing the link"
    return match.group(1)


def test_forgot_password_sends_brevo_link(client, store, capture_email):
    _register(client)
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "ada@example.com"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert len(capture_email) == 1
    assert "Reset your Cyphward password" in capture_email[0]["args"][1]
    assert store.password_reset_tokens, "token row should be stored (hash only)"
    # plaintext never stored
    token = _extract_reset_token(capture_email)
    assert store.password_reset_tokens[0]["token_hash"] == hash_opaque_token(token)


def test_forgot_password_unknown_email_is_generic(client, capture_email):
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert capture_email == []


def test_forgot_password_resend_cooldown(client, capture_email):
    _register(client)
    client.post("/api/v1/auth/forgot-password", json={"email": "ada@example.com"})
    client.post("/api/v1/auth/forgot-password", json={"email": "ada@example.com"})
    assert len(capture_email) == 1


def test_reset_password_flow_revokes_sessions(client, store, capture_email):
    tokens = _register(client).json()
    client.post("/api/v1/auth/forgot-password", json={"email": "ada@example.com"})
    token = _extract_reset_token(capture_email)

    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": "brand-new-secret-9"},
    )
    assert resp.status_code == 200

    # Old sessions are revoked
    refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401

    # Old password dead, new password works
    old = client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
    )
    assert old.status_code == 401
    new = client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "brand-new-secret-9"}
    )
    assert new.status_code == 200

    # Token is single-use
    again = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": "another-one-10"},
    )
    assert again.status_code == 400


def test_reset_password_bad_token(client):
    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": "totally-invalid", "password": "brand-new-secret-9"},
    )
    assert resp.status_code == 400


def test_reset_password_rejects_short_password(client, store, capture_email):
    _register(client)
    client.post("/api/v1/auth/forgot-password", json={"email": "ada@example.com"})
    token = _extract_reset_token(capture_email)
    resp = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "short"}
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Session binding (P1 — access JWTs die with their session)
# ---------------------------------------------------------------------------
def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_logout_revokes_the_access_token(client):
    """Logout must kill the access JWT immediately, not just the refresh token."""
    tokens = _register(client).json()
    access = tokens["access_token"]

    ok = client.get("/api/v1/auth/bootstrap", headers=_auth(access))
    assert ok.status_code == 200

    out = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert out.status_code == 200

    dead = client.get("/api/v1/auth/bootstrap", headers=_auth(access))
    assert dead.status_code == 401
    assert "Session" in dead.json()["detail"] or "session" in dead.json()["detail"]


def test_stale_token_cannot_recreate_a_deleted_profile(client, store):
    """get_current_user must 401 on a missing profile, never re-insert it."""
    tokens = _register(client).json()
    access = tokens["access_token"]
    user_id = tokens["user"]["id"]
    assert user_id in store.profiles

    del store.profiles[user_id]

    resp = client.get("/api/v1/auth/bootstrap", headers=_auth(access))
    assert resp.status_code == 401
    assert user_id not in store.profiles  # still gone — no resurrection from claims


def test_access_token_dies_with_password_reset(client, store, capture_email):
    """reset-password revokes every session; old access JWTs stop working now."""
    tokens = _register(client).json()
    access = tokens["access_token"]

    client.post("/api/v1/auth/forgot-password", json={"email": "ada@example.com"})
    reset_token = _extract_reset_token(capture_email)
    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": reset_token, "password": "brand-new-secret-9"},
    )
    assert resp.status_code == 200

    dead = client.get("/api/v1/auth/bootstrap", headers=_auth(access))
    assert dead.status_code == 401


# ---------------------------------------------------------------------------
# Bootstrap (replaces the old direct PostgREST reads)
# ---------------------------------------------------------------------------
def test_bootstrap_returns_memberships_and_domains(client, auth_headers):
    resp = client.get("/api/v1/auth/bootstrap", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["id"] == ALICE
    assert data["email_verified"] is False
    assert len(data["memberships"]) == 1
    entry = data["memberships"][0]
    assert entry["role"] == "owner"
    assert entry["org"]["slug"] == "acme-traders"
    assert entry["domains"] and entry["domains"][0]["domain"] == "acme.test"


# ---------------------------------------------------------------------------
# Google OAuth (offline paths only)
# ---------------------------------------------------------------------------
def test_google_start_requires_configuration(client, monkeypatch):
    monkeypatch.setattr(google_mod, "GOOGLE_CLIENT_ID", None)
    monkeypatch.setattr(google_mod, "GOOGLE_CLIENT_SECRET", None)
    resp = client.get("/api/v1/auth/google", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"].endswith("/login?error=google_not_configured")


def test_google_start_redirects_to_consent(client, monkeypatch):
    monkeypatch.setattr(google_mod, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(google_mod, "GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(google_mod, "AUTH_JWT_SECRET", config.AUTH_JWT_SECRET)

    resp = client.get("/api/v1/auth/google", follow_redirects=False)
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-client-id" in location
    assert "state=" in location
    assert "redirect_uri=" in location


def test_google_callback_rejects_bad_state(client):
    resp = client.get(
        "/api/v1/auth/google/callback?code=abc&state=forged",
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert resp.headers["location"].endswith("/login?error=oauth_failed")


def test_google_callback_rejects_missing_code(client, monkeypatch):
    monkeypatch.setattr(google_mod, "AUTH_JWT_SECRET", config.AUTH_JWT_SECRET)
    state = google_mod._make_state()
    resp = client.get(
        f"/api/v1/auth/google/callback?state={state}&error=access_denied",
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert resp.headers["location"].endswith("/login?error=oauth_failed")


def test_google_client_id_is_public(client, monkeypatch):
    monkeypatch.setattr(google_mod, "GOOGLE_CLIENT_ID", "public-client-id")
    resp = client.get("/api/v1/auth/google/client-id")
    assert resp.status_code == 200
    assert resp.json() == {"client_id": "public-client-id"}

    monkeypatch.setattr(google_mod, "GOOGLE_CLIENT_ID", None)
    assert client.get("/api/v1/auth/google/client-id").json() == {"client_id": None}


def test_one_tap_rejects_malformed_credential(client, monkeypatch):
    # Configure Google explicitly so the config guard (503) can't mask the
    # malformed-credential path — CI runners have no .env to supply it.
    monkeypatch.setattr(google_mod, "GOOGLE_CLIENT_ID", "ci-test-client.apps.googleusercontent.com")
    resp = client.post("/api/v1/auth/google/one-tap", json={"credential": "garbage"})
    assert resp.status_code == 401
    assert "could not be verified" in resp.json()["detail"]


def test_one_tap_requires_configuration(client, monkeypatch):
    monkeypatch.setattr(google_mod, "GOOGLE_CLIENT_ID", None)
    resp = client.post(
        "/api/v1/auth/google/one-tap", json={"credential": "not-even-checked"}
    )
    assert resp.status_code == 503


def test_one_tap_issues_session_for_verified_claims(client, monkeypatch, store):
    # Skip JWKS/network: the verifier is stubbed, everything else is real.
    claims = {"email": "onetap@example.com", "email_verified": True, "name": "One Tapper"}
    monkeypatch.setattr(google_mod, "_verify_one_tap_credential", lambda _c: claims)

    resp = client.post("/api/v1/auth/google/one-tap", json={"credential": "stub-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] and data["refresh_token"]
    assert data["user"]["email"] == "onetap@example.com"
    assert data["user"]["provider"] == "google"

    # Second sign-in adopts the existing profile (still google, not duplicated)
    again = client.post("/api/v1/auth/google/one-tap", json={"credential": "stub-token"})
    assert again.status_code == 200
    assert again.json()["user"]["id"] == data["user"]["id"]
    assert sum(1 for p in store.profiles.values() if p["email"] == "onetap@example.com") == 1
    assert any(e["params"][2] == "auth.google_onetap" for e in store.audit)


def test_exchange_consumes_otc_once(client, store):
    # Simulate what the OAuth callback does: session row carrying an otc hash.
    registered = _register(client, email="guser@example.com").json()
    session = store.sessions[-1]
    otc = "single-use-code-123"
    session["otc_hash"] = hash_opaque_token(otc)
    from datetime import datetime, timedelta, timezone
    session["otc_expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=5)

    resp = client.post("/api/v1/auth/exchange", json={"otc": otc})
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["user"]["email"] == "guser@example.com"

    # Single use
    again = client.post("/api/v1/auth/exchange", json={"otc": otc})
    assert again.status_code == 401

    # Original register refresh still valid (separate row) — sanity only
    assert registered["refresh_token"]


def test_exchange_rejects_unknown_otc(client):
    resp = client.post("/api/v1/auth/exchange", json={"otc": "never-issued"})
    assert resp.status_code == 401
