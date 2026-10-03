"""
Member invite flow: POST /members/invite.

The endpoint creates/links the membership AND sends the invitee an
invitation email (Brevo via send_email_async). Covers: delivery success
(subject/recipients/content), membership + audit side effects, and the
failure path where the member is still added but `email_sent` is false.

Run: uv run --with pytest ... python -m pytest backend/tests/test_member_invite.py -q
"""
import json

import backend.app.api.members as members_mod
from conftest import ORG_A, ALICE

INVITEE = "newbie@acme.com"  # .test TLD is rejected by EmailStr validation


def _post_invite(client, auth_headers, monkeypatch, body=None, fail=False):
    """POST the invite with send_email_async swapped for a recorder."""
    sent = []

    async def fake_send(to_email, subject, html_content, text_content=None,
                        recipient_name=None, kind="system"):
        if fail:
            raise RuntimeError("brevo unavailable")
        sent.append({
            "to": to_email,
            "subject": subject,
            "html": html_content,
            "text": text_content or "",
            "recipient_name": recipient_name,
            "kind": kind,
        })
        return {"success": True, "method": "fake", "recipient": to_email}

    monkeypatch.setattr(members_mod, "send_email_async", fake_send)
    payload = body or {"email": INVITEE, "full_name": "New Bie", "role": "member"}
    resp = client.post(
        "/api/v1/members/invite",
        json=payload,
        headers=auth_headers(ALICE, email="alice@acme.test", org=ORG_A),
    )
    return resp, sent


def test_invite_sends_invitation_email(client, auth_headers, monkeypatch, store):
    resp, sent = _post_invite(client, auth_headers, monkeypatch)

    assert resp.status_code == 201
    data = resp.json()
    assert data["email_sent"] is True
    assert data["member"]["email"] == INVITEE
    assert data["member"]["role"] == "member"
    assert "Invite sent" in data["message"]

    assert len(sent) == 1
    mail = sent[0]
    assert mail["to"] == INVITEE
    assert mail["subject"] == "Alice invited you to Acme Traders on Cyphward"
    assert "Alice" in mail["html"]
    assert "Acme Traders" in mail["html"]
    assert INVITEE in mail["html"]
    assert "/login" in mail["html"]
    assert "member" in mail["html"].lower()
    assert "Acme Traders" in mail["text"]
    assert INVITEE in mail["text"]


def test_invite_creates_membership_and_audit(client, auth_headers, monkeypatch, store):
    before = len(store.memberships)
    resp, _ = _post_invite(client, auth_headers, monkeypatch)

    assert resp.status_code == 201
    assert len(store.memberships) == before + 1
    entry = store.memberships[-1]
    assert entry["org_id"] == ORG_A
    assert entry["role"] == "member"
    # invitee profile was created (no prior account)
    invitee_id = entry["user_id"]
    assert store.profiles[invitee_id]["email"] == INVITEE

    audit_actions = [a["params"][2] for a in store.audit]
    assert "member.invited" in audit_actions
    invited_row = next(a for a in store.audit if a["params"][2] == "member.invited")
    assert json.loads(invited_row["params"][5])["email_sent"] is True


def test_invite_email_failure_still_adds_member(client, auth_headers, monkeypatch, store):
    before = len(store.memberships)
    resp, sent = _post_invite(client, auth_headers, monkeypatch, fail=True)

    assert resp.status_code == 201
    data = resp.json()
    assert data["email_sent"] is False
    assert "failed" in data["message"].lower()
    assert sent == []  # recorder raised before recording

    # membership and profile still exist — email failure never blocks the invite
    assert len(store.memberships) == before + 1
    invited_row = next(a for a in store.audit if a["params"][2] == "member.invited")
    assert json.loads(invited_row["params"][5])["email_sent"] is False


def test_invite_rejects_unknown_role(client, auth_headers, monkeypatch, store):
    resp, sent = _post_invite(
        client, auth_headers, monkeypatch,
        body={"email": INVITEE, "full_name": "New Bie", "role": "superuser"},
    )
    assert resp.status_code == 400
    assert sent == []


def test_invite_existing_account_reuses_profile(client, auth_headers, monkeypatch, store):
    # First invite creates the profile + membership.
    resp1, _ = _post_invite(client, auth_headers, monkeypatch)
    assert resp1.status_code == 201
    profiles_before = len(store.profiles)

    # Second invite for the same email reuses the profile row (no duplicate).
    resp2, sent2 = _post_invite(client, auth_headers, monkeypatch)
    assert resp2.status_code == 201
    assert resp2.json()["email_sent"] is True
    assert len(store.profiles) == profiles_before
    assert len(sent2) == 1
