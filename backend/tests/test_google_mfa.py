"""Google logins face the same step-up gate (no bypass by provider).

Admins and enrolled users signing in via One Tap (or the OAuth redirect,
which shares `_google_step_up`) get an MFA challenge instead of a
session; everyone else signs in directly as before.
"""
import backend.app.api.auth_google as google_mod
from conftest import ALICE, BOB


def _claims(email):
    return {"email": email, "email_verified": True, "name": "Test User"}


def test_one_tap_owner_gets_mfa_challenge(client, store, monkeypatch):
    monkeypatch.setattr(google_mod, "_verify_one_tap_credential",
                        lambda _cred: _claims(f"{ALICE[:8]}@acme.test"))
    monkeypatch.setattr(google_mod, "_send_mfa_code", lambda _user: None)
    resp = client.post("/api/v1/auth/google/one-tap", json={"credential": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("mfa_required") is True and body.get("mfa_token")


def test_one_tap_member_signs_in_directly(client, store, monkeypatch):
    monkeypatch.setattr(google_mod, "_verify_one_tap_credential",
                        lambda _cred: _claims(f"{BOB[:8]}@acme.test"))
    resp = client.post("/api/v1/auth/google/one-tap", json={"credential": "x"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_google_step_up_unit_respects_role_and_enrollment(store, monkeypatch):
    monkeypatch.setattr(google_mod, "_send_mfa_code", lambda _user: None)
    assert google_mod._google_step_up({"id": BOB}) is None
    token = google_mod._google_step_up({"id": ALICE, "email": f"{ALICE[:8]}@acme.test"})
    assert isinstance(token, str) and token.count(".") == 2
    store.profiles[BOB]["mfa_enrolled_at"] = "2026-10-04T00:00:00"
    enrolled = google_mod._google_step_up({"id": BOB, "email": f"{BOB[:8]}@acme.test",
                                           "mfa_enrolled_at": "2026-10-04T00:00:00"})
    assert isinstance(enrolled, str)


def test_google_start_popup_mode_embeds_flag(monkeypatch):
    import asyncio
    import jwt as pyjwt
    from urllib.parse import parse_qs, urlparse
    monkeypatch.setattr(google_mod, "GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")
    monkeypatch.setattr(google_mod, "GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(google_mod, "AUTH_JWT_SECRET", "test-secret")
    plain = asyncio.run(google_mod.google_start())
    popup = asyncio.run(google_mod.google_start(mode="popup"))
    assert plain.status_code in (302, 307)
    assert popup.status_code in (302, 307)

    def popup_flag(resp):
        q = parse_qs(urlparse(resp.headers["location"]).query)
        claims = pyjwt.decode(q["state"][0], "test-secret", algorithms=["HS256"])
        return claims.get("popup")

    assert popup_flag(plain) is False
    assert popup_flag(popup) is True


def test_popup_result_page_posts_to_opener_not_redirect():
    resp = google_mod._popup_result_page({"otc": "abc"})
    assert resp.status_code == 200
    body = resp.body.decode()
    assert "postMessage" in body and "window.close()" in body
    assert '"otc": "abc"' in body
    assert google_mod._state_is_popup("garbage") is False
