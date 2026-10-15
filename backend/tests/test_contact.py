"""Public contact form delivers to the company inbox."""
from backend.app.core.config import CONTACT_INBOX


def test_contact_sends_to_inbox(client, monkeypatch):
    sent = {}

    async def fake_send(to_email, subject, html_content, text_content=None, recipient_name=None, kind="system", reply_to=None):
        sent.update(to=to_email, subject=subject, text=text_content, kind=kind, reply_to=reply_to)
        return {"success": True, "method": "test"}

    monkeypatch.setattr("backend.app.api.contact.send_email_async", fake_send)
    resp = client.post("/api/v1/contact", json={
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "organization": "Analytical Engines",
        "topic": "product",
        "message": "We would like a walkthrough of the score.",
    })
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert sent["to"] == CONTACT_INBOX
    assert sent["kind"] == "general"
    assert sent["reply_to"] == "ada@example.com"
    assert "Ada Lovelace" in sent["text"]
    assert "walkthrough" in sent["text"]


def test_contact_honeypot_does_not_send(client, monkeypatch):
    called = {"n": 0}

    async def fake_send(*_a, **_k):
        called["n"] += 1
        return {"success": True}

    monkeypatch.setattr("backend.app.api.contact.send_email_async", fake_send)
    resp = client.post("/api/v1/contact", json={
        "name": "Bot",
        "email": "bot@example.com",
        "message": "Buy something from us today please.",
        "website": "https://spam.example",
    })
    assert resp.status_code == 200
    assert called["n"] == 0


def test_contact_rejects_a_short_note(client):
    resp = client.post("/api/v1/contact", json={
        "name": "Ada",
        "email": "ada@example.com",
        "message": "hi",
    })
    assert resp.status_code == 422
