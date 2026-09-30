"""
Brevo 6-digit email OTP verification tests (no network, no Brevo dispatch).

Covers: templates, send (recipient from JWT, hash-only storage, cooldown),
verify (wrong/expired/attempts/success), status endpoint, org-create gate.
"""
import re
from datetime import datetime, timedelta, timezone

from backend.app.api import auth as auth_mod
from backend.app.api.organizations import create_organization  # noqa: F401 (route presence)
from backend.app.services.mailer import generate_otp_email_html, generate_otp_email_text

ALICE = "aaaaaaaa-0000-4000-8000-000000000001"


def _clear():
    auth_mod._last_sent.clear()


def _send_and_capture(client, headers, monkeypatch, store):
    """POST /otp/send, return (response, captured 6-digit code)."""
    sent = []
    monkeypatch.setattr(auth_mod, "send_email_async", lambda *a, **k: sent.append(a))
    resp = client.post("/api/v1/auth/otp/send", headers=headers)
    assert resp.status_code == 200, resp.text
    assert len(sent) == 1
    html = sent[0][2]
    match = re.search(r"\b(\d{6})\b", html)
    assert match, "OTP code missing from email HTML"
    return resp, match.group(1), sent[0]


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
def test_otp_template_renders_code():
    html = generate_otp_email_html("Yusuf Lawal", "123456")
    assert "123456" in html
    assert "Hi Yusuf" in html
    assert "expires in 10 minutes" in html
    assert "#F3F1EC" in html  # light theme, matches welcome/report
    assert "color-scheme: only light" in html


def test_otp_template_handles_empty_name():
    html = generate_otp_email_html("", "654321")
    assert "Hi there" in html


def test_otp_text_version():
    text = generate_otp_email_text("Ada Obi", "246810")
    assert "246810" in text
    assert "expires in 10 minutes" in text


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------
def test_otp_send_requires_token(client):
    _clear()
    assert client.post("/api/v1/auth/otp/send").status_code == 401


def test_otp_send_stores_hash_not_plaintext(client, auth_headers, monkeypatch, store):
    _clear()
    headers = auth_headers(ALICE)
    _resp, code, sent = _send_and_capture(client, headers, monkeypatch, store)

    # recipient comes from verified JWT claims
    assert sent[0].endswith("@acme.test") or sent[0].endswith("acme.test")
    assert sent[1].startswith("Your Cyphward verification code")

    assert len(store.email_otps) == 1
    row = store.email_otps[0]
    assert row["code_hash"] != code
    assert row["code_hash"] == auth_mod._hash_code("aaaaaaaa@acme.test", code)
    assert row["attempts"] == 0

    body = _resp.json()
    assert body["sent"] is True
    assert body["expires_in"] == 600
    assert body["resend_after"] == 60


def test_otp_send_cooldown(client, auth_headers, monkeypatch, store):
    _clear()
    headers = auth_headers(ALICE)
    _send_and_capture(client, headers, monkeypatch, store)

    # second request within 60s -> 429
    resp = client.post("/api/v1/auth/otp/send", headers=headers)
    assert resp.status_code == 429
    assert "Resend available" in resp.json()["detail"]

    # after the cooldown window, resending replaces the old code
    store.email_otps[0]["created_at"] = datetime.now(timezone.utc) - timedelta(seconds=120)
    _send_and_capture(client, headers, monkeypatch, store)
    assert len(store.email_otps) == 1  # old code purged


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
def test_otp_verify_requires_token(client):
    _clear()
    assert client.post(
        "/api/v1/auth/otp/verify", json={"code": "123456"}
    ).status_code == 401


def test_otp_verify_rejects_bad_shape(client, auth_headers):
    _clear()
    headers = auth_headers(ALICE)
    assert client.post("/api/v1/auth/otp/verify", json={"code": "12ab56"}, headers=headers).status_code == 400
    assert client.post("/api/v1/auth/otp/verify", json={"code": "12345"}, headers=headers).status_code == 400


def test_otp_verify_wrong_code_counts_attempts(client, auth_headers, monkeypatch, store):
    _clear()
    headers = auth_headers(ALICE)
    _send_and_capture(client, headers, monkeypatch, store)

    resp = client.post("/api/v1/auth/otp/verify", json={"code": "000000"}, headers=headers)
    assert resp.status_code == 400
    assert "Invalid code" in resp.json()["detail"]
    assert "4 attempt(s) left" in resp.json()["detail"]
    assert store.email_otps[0]["attempts"] == 1
    assert "email_verified_at" not in store.profiles[ALICE]


def test_otp_verify_attempt_limit(client, auth_headers, monkeypatch, store):
    _clear()
    headers = auth_headers(ALICE)
    _send_and_capture(client, headers, monkeypatch, store)

    for i in range(4):
        resp = client.post("/api/v1/auth/otp/verify", json={"code": "000000"}, headers=headers)
        assert resp.status_code == 400
    # 5th wrong attempt exhausts the budget
    resp = client.post("/api/v1/auth/otp/verify", json={"code": "000000"}, headers=headers)
    assert resp.status_code == 400
    # next attempt -> code invalidated entirely
    resp = client.post("/api/v1/auth/otp/verify", json={"code": "000000"}, headers=headers)
    assert resp.status_code == 429
    assert store.email_otps == []


def test_otp_verify_expired_code(client, auth_headers, monkeypatch, store):
    _clear()
    headers = auth_headers(ALICE)
    _send_and_capture(client, headers, monkeypatch, store)
    store.email_otps[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    resp = client.post("/api/v1/auth/otp/verify", json={"code": "111111"}, headers=headers)
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()
    assert store.email_otps == []


def test_otp_verify_success_marks_verified(client, auth_headers, monkeypatch, store):
    _clear()
    headers = auth_headers(ALICE)
    _send_and_capture(client, headers, monkeypatch, store)

    # status before: unverified
    before = client.get("/api/v1/auth/verification", headers=headers)
    assert before.status_code == 200
    assert before.json()["verified"] is False

    # capture a fresh code (past resend cooldown), then verify it
    store.email_otps[0]["created_at"] = datetime.now(timezone.utc) - timedelta(seconds=120)
    _resp, real_code, _sent = _send_and_capture(client, headers, monkeypatch, store)

    resp = client.post("/api/v1/auth/otp/verify", json={"code": real_code}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"verified": True}
    assert store.profiles[ALICE]["email_verified_at"] is not None
    assert store.email_otps == []  # consumed

    after = client.get("/api/v1/auth/verification", headers=headers)
    assert after.json()["verified"] is True

    # resend after verification -> no-op
    resend = client.post("/api/v1/auth/otp/send", headers=headers)
    assert resend.status_code == 200
    assert resend.json() == {"sent": False, "reason": "already_verified"}

    # audit trail recorded
    actions = [a["params"] for a in store.audit]
    assert any("auth.email_verified" in str(p) for p in actions)


def test_otp_verify_no_active_code(client, auth_headers):
    _clear()
    headers = auth_headers(ALICE)
    resp = client.post("/api/v1/auth/otp/verify", json={"code": "123456"}, headers=headers)
    assert resp.status_code == 400
    assert "No active code" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Org creation gate
# ---------------------------------------------------------------------------
def test_create_org_blocked_until_verified(client, auth_headers, monkeypatch, store):
    _clear()
    headers = auth_headers(ALICE)
    resp = client.post(
        "/api/v1/organizations",
        json={"name": "Unverified Org"},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "Verify your email" in resp.json()["detail"]

    # verify, then creation succeeds
    sent = []
    monkeypatch.setattr(auth_mod, "send_email_async", lambda *a, **k: sent.append(a))
    client.post("/api/v1/auth/otp/send", headers=headers)
    code = re.search(r"\b(\d{6})\b", sent[0][2]).group(1)
    assert client.post("/api/v1/auth/otp/verify", json={"code": code}, headers=headers).status_code == 200

    resp = client.post(
        "/api/v1/organizations",
        json={"name": "Verified Org"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
