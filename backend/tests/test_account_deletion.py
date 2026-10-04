"""Account self-service deletion (data-rights follow-up).

Typed-email confirmation plus the password when one is set. Sole owners
are blocked until they transfer ownership or close the workspace;
everyone else's profile, sessions, tokens, memberships and staff grants
go in one cascading delete, with a NULL-user tombstone left behind.
"""
from conftest import ALICE, BOB, ORG_A, ORG_B


def _h(auth_headers, user_id, org=None):
    return auth_headers(user_id, email=f"{user_id[:8]}@acme.test", org=org)


def test_member_self_delete_cascades_and_leaves_tombstone(client, auth_headers, store, monkeypatch):
    import backend.app.api.auth as auth_mod
    monkeypatch.setattr(auth_mod, "verify_password", lambda _h, _p: True)
    # give BOB a session + otp + reset token to prove cascade cleanup
    store.sessions.append({"id": "s-bob", "user_id": BOB, "refresh_token_hash": "x",
                           "revoked_at": None})
    store.email_otps.append({"id": "o-bob", "user_id": BOB, "code_hash": "x",
                             "attempts": 0, "created_at": "2026-10-04T00:00:00",
                             "expires_at": "2026-10-04T00:10:00", "purpose": "verify"})
    resp = client.post("/api/v1/auth/account/delete",
                       json={"email": f"{BOB[:8]}@acme.test", "password": "anything"},
                       headers=_h(auth_headers, BOB))
    assert resp.json() == {"deleted": True}
    assert BOB not in store.profiles
    assert all(m["user_id"] != BOB for m in store.memberships)
    assert all(x["user_id"] != BOB for x in store.sessions)
    assert all(x["user_id"] != BOB for x in store.email_otps)
    # other tenant + users untouched
    assert ORG_A in store.organizations and ORG_B in store.organizations
    assert ALICE in store.profiles
    tombs = [a for a in store.audit if a["params"][2] == "account.deleted"]
    assert len(tombs) == 1 and tombs[0]["params"][0] is None


def test_sole_owner_blocked_until_handover(client, auth_headers, store):
    resp = client.post("/api/v1/auth/account/delete",
                       json={"email": f"{ALICE[:8]}@acme.test", "password": "x"},
                       headers=_h(auth_headers, ALICE))
    # ALICE solely owns ORG_A — blocked (no password set in fixtures, so
    # the sole-owner guard is what fires).
    assert resp.status_code == 409
    assert "Acme" in resp.json()["detail"]
    assert ALICE in store.profiles


def test_owner_with_co_owner_can_leave(client, auth_headers, store, monkeypatch):
    import backend.app.api.auth as auth_mod
    monkeypatch.setattr(auth_mod, "verify_password", lambda _h, _p: True)
    # Promote BOB to co-owner of A, then ALICE may delete.
    store.memberships.append({"user_id": BOB, "org_id": ORG_A, "role": "owner"})
    resp = client.post("/api/v1/auth/account/delete",
                       json={"email": f"{ALICE[:8]}@acme.test", "password": "x"},
                       headers=_h(auth_headers, ALICE))
    assert resp.json() == {"deleted": True}
    assert ORG_A in store.organizations
    assert any(m["user_id"] == BOB and m["role"] == "owner" for m in store.memberships)


def test_confirmation_mismatch_and_bad_password(client, auth_headers, store, monkeypatch):
    import backend.app.api.auth as auth_mod
    monkeypatch.setattr(auth_mod, "verify_password", lambda _h, _p: False)
    store.profiles[BOB]["password_hash"] = "set"
    bad_email = client.post("/api/v1/auth/account/delete",
                            json={"email": "someone@else.test", "password": "x"},
                            headers=_h(auth_headers, BOB))
    assert bad_email.status_code == 400
    bad_pw = client.post("/api/v1/auth/account/delete",
                         json={"email": f"{BOB[:8]}@acme.test", "password": "x"},
                         headers=_h(auth_headers, BOB))
    assert bad_pw.status_code == 401
    assert BOB in store.profiles
