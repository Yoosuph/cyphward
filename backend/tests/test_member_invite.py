"""
Member invitation flow (tokenized, review P0-2) + member role management.

POST /members/invite          — stores a single-use, time-limited token (hash
                                 only) and emails it. No profile, no membership.
POST /members/invites/accept  — consumes the token; membership is created only
                                 here, for an authenticated account whose
                                 verified email matches the invitation.
GET  /members/invites         — pending invitations (admins+).
DELETE /members/invites/{id}  — revoke.
PATCH /members/{user_id}      — role changes, incl. last-owner protection.

Run: uv run --with pytest ... python -m pytest backend/tests/test_member_invite.py -q
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

import backend.app.api.members as members_mod
from conftest import ORG_A, ALICE, BOB, ADMI, CAROL

INVITEE = "newbie@acme.com"  # .test TLD is rejected by EmailStr validation
NEWBIE = "99999999-0000-4000-8000-000000000099"


def _recorder(fail=False):
    sent = []

    async def fake_send(to_email, subject, html_content, text_content=None,
                        recipient_name=None, kind="system"):
        if fail:
            raise RuntimeError("brevo unavailable")
        sent.append({
            "to": to_email, "subject": subject, "html": html_content,
            "text": text_content or "", "recipient_name": recipient_name,
            "kind": kind,
        })
        return {"success": True, "method": "fake", "recipient": to_email}

    return fake_send, sent


def _invite(client, auth_headers, monkeypatch, body=None, fail=False,
            as_user=ALICE, as_email="alice@acme.test"):
    fake_send, sent = _recorder(fail=fail)
    monkeypatch.setattr(members_mod, "send_email_async", fake_send)
    payload = body or {"email": INVITEE, "full_name": "New Bie", "role": "member"}
    resp = client.post(
        "/api/v1/members/invite", json=payload,
        headers=auth_headers(as_user, email=as_email, org=ORG_A),
    )
    return resp, sent


def _token_from_mail(mail):
    m = re.search(r"[?&]invite=([A-Za-z0-9_\-]+)", mail["html"])
    assert m, "invite email must carry an ?invite= token"
    return m.group(1)


def _seed_invitee(store, user_id=NEWBIE, email=INVITEE, verified=True):
    now = datetime.now(timezone.utc)
    store.profiles[user_id] = {
        "id": user_id, "email": email, "full_name": "New Bie", "role": "Member",
        "password_hash": None, "provider": "email",
        "email_verified_at": now if verified else None, "created_at": now,
    }
    return store.profiles[user_id]


def _accept(client, auth_headers, token, user_id=NEWBIE, email=INVITEE):
    return client.post(
        "/api/v1/members/invites/accept", json={"token": token},
        headers=auth_headers(user_id, email=email),
    )


def _pending(store):
    return [i for i in store.organization_invites
            if i["accepted_at"] is None and i["revoked_at"] is None]


# -- POST /members/invite ----------------------------------------------------

def test_invite_sends_tokenized_link_and_creates_no_account(client, auth_headers, monkeypatch, store):
    before_memberships = len(store.memberships)

    resp, sent = _invite(client, auth_headers, monkeypatch)

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
    assert "/login" in mail["html"]
    assert "member" in mail["html"].lower()
    assert "Acme Traders" in mail["text"] and INVITEE in mail["text"]

    # P0-2: no profile and no membership may exist for the invitee before accept.
    assert not any((p.get("email") or "").lower() == INVITEE for p in store.profiles.values())
    assert len(store.memberships) == before_memberships


def test_invite_stores_only_the_token_hash(client, auth_headers, monkeypatch, store):
    resp, sent = _invite(client, auth_headers, monkeypatch)
    assert resp.status_code == 201

    token = _token_from_mail(sent[0])
    rows = _pending(store)
    assert len(rows) == 1
    row = rows[0]
    # Hash only — the raw token exists solely inside the emailed link.
    assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in json.dumps(row, default=str)


def test_invite_pending_row_and_audit(client, auth_headers, monkeypatch, store):
    resp, _ = _invite(client, auth_headers, monkeypatch)
    assert resp.status_code == 201

    row = _pending(store)[0]
    assert row["org_id"] == ORG_A
    assert row["role"] == "member"
    assert row["invited_by"] == ALICE
    assert row["expires_at"] > datetime.now(timezone.utc)

    invited = [a for a in store.audit if a["params"][2] == "member.invited"]
    assert len(invited) == 1
    assert json.loads(invited[0]["params"][5])["email_sent"] is True


def test_invite_email_failure_still_saves_invite(client, auth_headers, monkeypatch, store):
    resp, sent = _invite(client, auth_headers, monkeypatch, fail=True)

    assert resp.status_code == 201
    data = resp.json()
    assert data["email_sent"] is False
    assert "failed" in data["message"].lower()
    assert sent == []  # recorder raised before recording

    # The invitation is still revocable/listable; email failure never blocks it.
    assert len(_pending(store)) == 1
    assert not any((p.get("email") or "").lower() == INVITEE for p in store.profiles.values())
    invited_row = next(a for a in store.audit if a["params"][2] == "member.invited")
    assert json.loads(invited_row["params"][5])["email_sent"] is False


def test_invite_rejects_unknown_role(client, auth_headers, monkeypatch, store):
    resp, sent = _invite(
        client, auth_headers, monkeypatch,
        body={"email": INVITEE, "full_name": "New Bie", "role": "superuser"},
    )
    assert resp.status_code == 400
    assert sent == []
    assert _pending(store) == []


def test_invite_member_forbidden(client, auth_headers, monkeypatch, store):
    resp, sent = _invite(client, auth_headers, monkeypatch,
                         as_user=BOB, as_email="bob@acme.test")
    assert resp.status_code == 403
    assert sent == []
    assert _pending(store) == []


def test_invite_owner_role_requires_owner(client, auth_headers, monkeypatch, store):
    body = {"email": INVITEE, "full_name": "New Bie", "role": "owner"}

    resp_admin, _ = _invite(client, auth_headers, monkeypatch, body=body,
                            as_user=ADMI, as_email="admin@acme.test")
    assert resp_admin.status_code == 403  # admins may not mint owners
    assert _pending(store) == []

    resp_owner, _ = _invite(client, auth_headers, monkeypatch, body=body,
                            as_user=ALICE, as_email="alice@acme.test")
    assert resp_owner.status_code == 201
    assert len(_pending(store)) == 1


def test_invite_existing_member_conflict(client, auth_headers, monkeypatch, store):
    """Inviting a current member must not touch their role (no downgrade path)."""
    existing_id = "77777777-0000-4000-8000-000000000077"
    existing_email = "existing@acme.com"  # .test TLD is rejected by EmailStr
    _seed_invitee(store, user_id=existing_id, email=existing_email, verified=True)
    store.memberships.append({"user_id": existing_id, "org_id": ORG_A, "role": "admin"})

    resp, sent = _invite(client, auth_headers, monkeypatch,
                         body={"email": existing_email, "full_name": "Existing", "role": "member"})
    assert resp.status_code == 409
    assert "already a member" in resp.json()["detail"]
    assert sent == []
    assert _pending(store) == []
    role = next(m["role"] for m in store.memberships
                if m["user_id"] == existing_id and m["org_id"] == ORG_A)
    assert role == "admin"  # invite never rewrites an existing membership


def test_reinvite_supersedes_previous_token(client, auth_headers, monkeypatch, store):
    resp1, sent1 = _invite(client, auth_headers, monkeypatch)
    assert resp1.status_code == 201
    token1 = _token_from_mail(sent1[0])

    resp2, sent2 = _invite(client, auth_headers, monkeypatch)
    assert resp2.status_code == 201
    token2 = _token_from_mail(sent2[0])

    assert len(_pending(store)) == 1  # one live invitation per (org, email)

    _seed_invitee(store)
    stale = _accept(client, auth_headers, token1)
    assert stale.status_code == 400
    assert "not valid" in stale.json()["detail"]

    fresh = _accept(client, auth_headers, token2)
    assert fresh.status_code == 200


# -- POST /members/invites/accept --------------------------------------------

def test_accept_requires_verified_email(client, auth_headers, monkeypatch, store):
    _, sent = _invite(client, auth_headers, monkeypatch)
    token = _token_from_mail(sent[0])
    _seed_invitee(store, verified=False)

    resp = _accept(client, auth_headers, token)

    assert resp.status_code == 403
    assert "Verify your email" in resp.json()["detail"]
    assert not any(m["user_id"] == NEWBIE for m in store.memberships)
    assert _pending(store)[0]["accepted_at"] is None  # token not burned


def test_accept_rejects_mismatched_email(client, auth_headers, monkeypatch, store):
    _, sent = _invite(client, auth_headers, monkeypatch)
    token = _token_from_mail(sent[0])
    _seed_invitee(store)
    before = len(store.memberships)

    # ALICE's session tries to consume an invite addressed to newbie@acme.com
    resp = _accept(client, auth_headers, token, user_id=ALICE, email="alice@acme.test")

    assert resp.status_code == 400
    assert "different email" in resp.json()["detail"]
    assert len(store.memberships) == before  # no membership side effects
    assert _pending(store)[0]["accepted_at"] is None


def test_accept_invalid_or_missing_token(client, auth_headers, store):
    _seed_invitee(store)
    headers = auth_headers(NEWBIE, email=INVITEE)
    bad = client.post("/api/v1/members/invites/accept",
                      json={"token": "definitely-not-a-real-token"}, headers=headers)
    assert bad.status_code == 400
    assert "not valid" in bad.json()["detail"]

    empty = client.post("/api/v1/members/invites/accept", json={"token": ""}, headers=headers)
    assert empty.status_code == 400
    assert "token" in empty.json()["detail"].lower()


def test_accept_happy_path(client, auth_headers, monkeypatch, store):
    _, sent = _invite(client, auth_headers, monkeypatch)
    token = _token_from_mail(sent[0])
    _seed_invitee(store)
    before = len(store.memberships)

    resp = _accept(client, auth_headers, token)

    assert resp.status_code == 200
    assert "welcome" in resp.json()["message"].lower()
    assert len(store.memberships) == before + 1
    entry = next(m for m in store.memberships if m["user_id"] == NEWBIE)
    assert entry["org_id"] == ORG_A
    assert entry["role"] == "member"

    row = store.organization_invites[0]
    assert row["accepted_at"] is not None
    assert row["accepted_user_id"] == NEWBIE
    assert _pending(store) == []

    actions = [a["params"][2] for a in store.audit]
    assert "member.invite_accepted" in actions


def test_accept_is_single_use(client, auth_headers, monkeypatch, store):
    _, sent = _invite(client, auth_headers, monkeypatch)
    token = _token_from_mail(sent[0])
    _seed_invitee(store)

    first = _accept(client, auth_headers, token)
    assert first.status_code == 200

    second = _accept(client, auth_headers, token)
    assert second.status_code == 409
    assert "already been used" in second.json()["detail"]
    assert sum(1 for m in store.memberships if m["user_id"] == NEWBIE) == 1


def test_accept_never_changes_an_existing_membership_role(client, auth_headers, monkeypatch, store):
    _, sent = _invite(client, auth_headers, monkeypatch)
    token = _token_from_mail(sent[0])
    _seed_invitee(store)
    # Joined as owner between invite and accept (e.g. added manually).
    store.memberships.append({"user_id": NEWBIE, "org_id": ORG_A, "role": "owner"})
    before = len(store.memberships)

    resp = _accept(client, auth_headers, token)

    assert resp.status_code == 200
    assert len(store.memberships) == before  # DO NOTHING — no duplicate row
    entry = next(m for m in store.memberships if m["user_id"] == NEWBIE)
    assert entry["role"] == "owner"  # invite can neither escalate nor downgrade


def test_accept_expired_invite(client, auth_headers, monkeypatch, store):
    _, sent = _invite(client, auth_headers, monkeypatch)
    token = _token_from_mail(sent[0])
    _seed_invitee(store)
    store.organization_invites[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    resp = _accept(client, auth_headers, token)

    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"]
    assert not any(m["user_id"] == NEWBIE for m in store.memberships)


def test_accept_revoked_invite(client, auth_headers, monkeypatch, store):
    _, sent = _invite(client, auth_headers, monkeypatch)
    token = _token_from_mail(sent[0])
    _seed_invitee(store)
    invite_id = store.organization_invites[0]["id"]

    revoked = client.delete(f"/api/v1/members/invites/{invite_id}",
                            headers=auth_headers(ALICE, email="alice@acme.test", org=ORG_A))
    assert revoked.status_code == 200

    resp = _accept(client, auth_headers, token)
    assert resp.status_code == 400
    assert "cancelled" in resp.json()["detail"]
    assert not any(m["user_id"] == NEWBIE for m in store.memberships)


# -- GET /members/invites + DELETE -------------------------------------------

def test_list_invites_admin_only(client, auth_headers, monkeypatch, store):
    _, sent = _invite(client, auth_headers, monkeypatch)
    token = _token_from_mail(sent[0])

    as_owner = client.get("/api/v1/members/invites",
                          headers=auth_headers(ALICE, email="alice@acme.test", org=ORG_A))
    assert as_owner.status_code == 200
    assert len(as_owner.json()) == 1
    assert as_owner.json()[0]["email"] == INVITEE

    as_member = client.get("/api/v1/members/invites",
                           headers=auth_headers(BOB, email="bob@acme.test", org=ORG_A))
    assert as_member.status_code == 403

    _seed_invitee(store)
    assert _accept(client, auth_headers, token).status_code == 200
    after = client.get("/api/v1/members/invites",
                       headers=auth_headers(ALICE, email="alice@acme.test", org=ORG_A))
    assert after.json() == []


def test_revoke_invite_twice_404(client, auth_headers, monkeypatch, store):
    _, _ = _invite(client, auth_headers, monkeypatch)
    invite_id = store.organization_invites[0]["id"]
    headers = auth_headers(ALICE, email="alice@acme.test", org=ORG_A)

    assert client.delete(f"/api/v1/members/invites/{invite_id}", headers=headers).status_code == 200
    again = client.delete(f"/api/v1/members/invites/{invite_id}", headers=headers)
    assert again.status_code == 404


def test_revoke_other_org_invite_404(client, auth_headers, monkeypatch, store):
    _, _ = _invite(client, auth_headers, monkeypatch)
    invite_id = store.organization_invites[0]["id"]
    # CAROL is an outsider — require_admin against ORG_A rejects before lookup.
    resp = client.delete(f"/api/v1/members/invites/{invite_id}",
                         headers=auth_headers(CAROL, email="carol@acme.test", org=ORG_A))
    assert resp.status_code == 403


# -- PATCH /members/{user_id} (last-owner protection) ------------------------

def test_last_owner_cannot_be_demoted(client, auth_headers, store):
    headers = auth_headers(ALICE, email="alice@acme.test", org=ORG_A)

    blocked = client.patch(f"/api/v1/members/{ALICE}", json={"role": "member"}, headers=headers)
    assert blocked.status_code == 403
    assert "at least one owner" in blocked.json()["detail"]
    assert next(m["role"] for m in store.memberships
                if m["user_id"] == ALICE and m["org_id"] == ORG_A) == "owner"

    # With a second owner in place, demotion is allowed.
    store.memberships.append({"user_id": CAROL, "org_id": ORG_A, "role": "owner"})
    allowed = client.patch(f"/api/v1/members/{ALICE}", json={"role": "member"}, headers=headers)
    assert allowed.status_code == 200
    assert allowed.json()["role"] == "member"
    assert next(m["role"] for m in store.memberships
                if m["user_id"] == ALICE and m["org_id"] == ORG_A) == "member"
    assert "member.role_changed" in [a["params"][2] for a in store.audit]


def test_demoting_non_owner_bypasses_last_owner_guard(client, auth_headers, store):
    headers = auth_headers(ALICE, email="alice@acme.test", org=ORG_A)
    resp = client.patch(f"/api/v1/members/{BOB}", json={"role": "member"}, headers=headers)
    assert resp.status_code == 200  # BOB was already a member; guard only guards owners
