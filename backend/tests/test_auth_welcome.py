"""
Welcome mail & auth lifecycle tests (no network, no Brevo dispatch).
"""
from datetime import datetime, timedelta, timezone

from backend.app.api import auth as auth_mod
from backend.app.services.mailer import generate_welcome_email_html, generate_welcome_email_text
from conftest import ALICE


def _clear_cooldown():
    auth_mod._last_sent.clear()


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------
def test_welcome_template_renders_personalized():
    html = generate_welcome_email_html("Yusuf Lawal", "yusuf@example.com")
    assert len(html) > 1000
    assert "Welcome, Yusuf." in html
    assert "yusuf@example.com" in html
    assert "Get started in 3 steps" in html
    assert "Open your dashboard" in html
    assert "cyphward.com/apple-touch-icon.png" in html
    # light theme (matches report template)
    assert "#F3F1EC" in html
    assert "color-scheme: only light" in html


def test_welcome_template_handles_empty_name():
    html = generate_welcome_email_html("", "ops@example.com")
    assert "Welcome, there." in html


def test_welcome_text_version():
    text = generate_welcome_email_text("Ada Obi", "ada@example.com")
    assert "Welcome to Cyphward" in text
    assert "https://cyphward.com/" in text
    assert "ada@example.com" in text


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
def test_welcome_requires_token(client):
    _clear_cooldown()
    resp = client.post("/api/v1/auth/welcome")
    assert resp.status_code == 401
    assert "token" in resp.json()["detail"].lower()


def test_welcome_rejects_invalid_token(client):
    _clear_cooldown()
    resp = client.post(
        "/api/v1/auth/welcome",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401


def test_welcome_sends_to_verified_account_email(client, auth_headers, monkeypatch):
    _clear_cooldown()
    sent: list = []

    def record(to_email, subject, html_content, text_content=None, recipient_name=None):
        sent.append({"to": to_email, "subject": subject, "html": html_content})

    monkeypatch.setattr(auth_mod, "send_email_async", record)

    resp = client.post("/api/v1/auth/welcome", headers=auth_headers("aaaaaaaa-0000-4000-8000-000000000001"))
    assert resp.status_code == 200
    assert resp.json() == {"sent": True}

    assert len(sent) == 1
    # recipient comes from verified JWT claims, not from any client input
    assert sent[0]["to"].endswith("@acme.test")
    assert sent[0]["subject"].startswith("Welcome to Cyphward,")
    assert "Welcome," in sent[0]["html"]


def test_welcome_cooldown_prevents_duplicates(client, auth_headers, monkeypatch):
    _clear_cooldown()
    sent: list = []
    monkeypatch.setattr(auth_mod, "send_email_async", lambda *a, **k: sent.append(a))

    headers = auth_headers("aaaaaaaa-0000-4000-8000-000000000001")
    first = client.post("/api/v1/auth/welcome", headers=headers)
    second = client.post("/api/v1/auth/welcome", headers=headers)

    assert first.json() == {"sent": True}
    assert second.json() == {"sent": False, "reason": "recently_sent"}
    assert len(sent) == 1


# ---------------------------------------------------------------------------
# First-time-only semantics (welcome is a signup gift, not a login ritual)
# ---------------------------------------------------------------------------
def test_welcome_existing_account_is_rejected(client, auth_headers, monkeypatch, store):
    _clear_cooldown()
    sent: list = []
    monkeypatch.setattr(auth_mod, "send_email_async", lambda *a, **k: sent.append(a))

    # Account created 3 days ago — an existing user signing in again.
    store.profiles[ALICE] = {
        "id": ALICE, "email": "user@acme.test", "full_name": "Alice", "role": "owner",
        "created_at": datetime.now(timezone.utc) - timedelta(days=3),
    }

    resp = client.post(
        "/api/v1/auth/welcome",
        headers=auth_headers(ALICE),
    )
    assert resp.status_code == 200
    assert resp.json() == {"sent": False, "reason": "existing_account"}
    assert sent == []


def test_welcome_sends_exactly_once_ever(client, auth_headers, monkeypatch):
    _clear_cooldown()
    sent: list = []
    monkeypatch.setattr(auth_mod, "send_email_async", lambda *a, **k: sent.append(a))

    headers = auth_headers(ALICE)
    first = client.post("/api/v1/auth/welcome", headers=headers)
    _clear_cooldown()  # bypass the hour cooldown — the audit marker must hold
    second = client.post("/api/v1/auth/welcome", headers=headers)

    assert first.json() == {"sent": True}
    assert second.json() == {"sent": False, "reason": "already_sent"}
    assert len(sent) == 1


def test_welcome_unreadable_created_at_fails_safe(client, auth_headers, monkeypatch, store):
    _clear_cooldown()
    sent: list = []
    monkeypatch.setattr(auth_mod, "send_email_async", lambda *a, **k: sent.append(a))

    store.profiles[ALICE] = {
        "id": ALICE, "email": "user@acme.test", "full_name": "Alice", "role": "owner",
        "created_at": "not-a-timestamp",
    }

    resp = client.post("/api/v1/auth/welcome", headers=auth_headers(ALICE))
    assert resp.json() == {"sent": False, "reason": "existing_account"}
    assert sent == []
