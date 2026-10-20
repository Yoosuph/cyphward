"""Demo sign-in endpoint against the migrated test database. Shares the demo fixtures with the seed tests."""
import psycopg
import pytest
from fastapi.testclient import TestClient

from backend.app.api import demo_login
from backend.app.core.rate_limit import reset_bucket
from backend.app.main import app
from backend.scripts import seed_fintech_demo as demo
from backend.tests.test_fintech_demo_seed_postgres import PASSWORD, demo_db, outbox  # noqa: F401 (fixtures)
from backend.tests.test_scan_admission_postgres import disposable_postgres_url  # noqa: F401 (fixture)

OTHER_ORG = "f1ac0000-0000-4000-8000-0000000000aa"
OTHER_USER = "f1ac0000-0000-4000-8000-0000000000ab"


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEMO_LOGIN_PASSWORD", PASSWORD)
    reset_bucket("demo-login:testclient")
    reset_bucket("demo-login:all")


def _post(client=None):
    return (client or TestClient(app)).post("/api/v1/auth/demo-login")


def test_the_button_stays_hidden_and_the_route_is_absent_when_the_flag_is_off(demo_db, monkeypatch):
    demo.seed(demo_db, PASSWORD, apply=True)
    monkeypatch.delenv("DEMO_LOGIN_ENABLED", raising=False)
    monkeypatch.setenv("DEMO_LOGIN_PASSWORD", PASSWORD)
    client = TestClient(app)
    assert client.get("/api/v1/auth/demo-login").json() == {"enabled": False}
    assert _post(client).status_code == 404


def test_flag_on_without_a_server_password_is_still_off(demo_db, monkeypatch):
    demo.seed(demo_db, PASSWORD, apply=True)
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "true")
    monkeypatch.delenv("DEMO_LOGIN_PASSWORD", raising=False)
    client = TestClient(app)
    assert client.get("/api/v1/auth/demo-login").json() == {"enabled": False}
    assert _post(client).status_code == 404


def test_a_wrong_server_password_gives_nothing(demo_db, monkeypatch, demo_on):
    demo.seed(demo_db, PASSWORD, apply=True)
    monkeypatch.setenv("DEMO_LOGIN_PASSWORD", "not-the-demo-password")
    resp = _post()
    assert resp.status_code == 404 and "access_token" not in resp.json()


def test_the_demo_session_is_the_demo_owner_in_the_demo_organisation_only(demo_db, demo_on):
    demo.seed(demo_db, PASSWORD, apply=True)
    client = TestClient(app)
    assert client.get("/api/v1/auth/demo-login").json() == {"enabled": True}
    resp = _post(client)
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": demo.DEMO_ORG_ID}
    me = client.get("/api/v1/organizations/current", headers=headers)
    assert me.status_code == 200 and me.json()["name"] == demo.DEMO_ORG_NAME


def test_the_demo_session_cannot_read_another_organisation_or_the_owner_console(demo_db, demo_on):
    demo.seed(demo_db, PASSWORD, apply=True)
    with psycopg.connect(demo_db) as conn:
        conn.execute("INSERT INTO profiles (id, email, full_name, role, password_hash, provider) VALUES "
                     "(%s, 'other-owner@other.test', 'Other', 'Member', NULL, 'email')", (OTHER_USER,))
        conn.execute("INSERT INTO organizations (id, name, slug, sector, plan) VALUES "
                     "(%s, 'Other Customer', 'other-customer-x', 'Technology', 'growth')", (OTHER_ORG,))
        conn.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s, %s, 'owner')",
                     (OTHER_USER, OTHER_ORG))
        conn.commit()
    try:
        client = TestClient(app)
        token = _post(client).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": OTHER_ORG}
        assert client.get("/api/v1/scans", headers=headers).status_code in (403, 404)
        assert client.get("/api/v1/organizations/current", headers=headers).status_code in (403, 404)
        owner = client.get("/api/v1/owner/overview", headers={"Authorization": f"Bearer {token}"})
        assert owner.status_code in (401, 403, 404)
    finally:
        with psycopg.connect(demo_db) as conn:
            conn.execute("DELETE FROM organizations WHERE id = %s", (OTHER_ORG,))
            conn.execute("DELETE FROM profiles WHERE id = %s", (OTHER_USER,))
            conn.commit()


def test_repeated_attempts_are_rate_limited(demo_db, monkeypatch, demo_on):
    demo.seed(demo_db, PASSWORD, apply=True)
    monkeypatch.setenv("DEMO_LOGIN_PASSWORD", "wrong-on-purpose")
    client = TestClient(app)
    reset_bucket("demo-login:testclient")
    statuses = [_post(client).status_code for _ in range(11)]
    assert statuses[:10] == [404] * 10 and statuses[10] == 429


def test_the_demo_account_must_stay_a_plain_member(demo_db, demo_on):
    demo.seed(demo_db, PASSWORD, apply=True)
    with psycopg.connect(demo_db) as conn:
        conn.execute("UPDATE organization_members SET role = 'owner' WHERE user_id = %s", (demo.DEMO_USER_ID,))
        conn.commit()
    try:
        assert _post().status_code == 404
    finally:
        with psycopg.connect(demo_db) as conn:
            conn.execute("UPDATE organization_members SET role = 'member' WHERE user_id = %s", (demo.DEMO_USER_ID,))
            conn.commit()


def test_the_demo_account_is_capped_on_ai_calls_and_nobody_else_is(demo_db, demo_on):
    from fastapi import HTTPException

    from backend.app.api.demo_login import DEMO_AI_MAX_CALLS, limit_demo_ai

    demo.seed(demo_db, PASSWORD, apply=True)
    with psycopg.connect(demo_db) as conn:
        conn.execute("DELETE FROM rate_limits WHERE bucket_key LIKE 'demo-ai%'")
        conn.commit()
    demo_org = {"id": demo.DEMO_ORG_ID, "current_user_id": demo.DEMO_USER_ID}
    for _ in range(DEMO_AI_MAX_CALLS):
        limit_demo_ai(demo_org)
    with pytest.raises(HTTPException) as refused:
        limit_demo_ai(demo_org)
    assert refused.value.status_code == 429
    for _ in range(DEMO_AI_MAX_CALLS + 5):  # any other account is not counted
        limit_demo_ai({"id": demo.DEMO_ORG_ID, "current_user_id": "00000000-0000-4000-8000-000000000099"})


def _demo_token(demo_db, demo_on):
    demo.seed(demo_db, PASSWORD, apply=True)
    resp = _post()
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


REFUSED_ROUTES = [
    ("post", "/api/v1/auth/mfa/enroll", {}),
    ("post", "/api/v1/auth/mfa/disable/request", {}),
    ("post", "/api/v1/auth/totp/enroll/start", {}),
    ("post", "/api/v1/auth/totp/enroll/confirm", {"code": "123456"}),
    ("post", "/api/v1/auth/totp/disable", {"code": "123456"}),
    ("post", "/api/v1/auth/account/delete", {}),
    ("post", "/api/v1/organizations", {"name": "Second Org", "sector": "Technology", "plan": "growth"}),
    ("post", "/api/v1/domains", {"domain": "example.com"}),
    ("post", "/api/v1/domains/00000000-0000-4000-8000-000000000009/verify", {}),
    ("post", "/api/v1/scans/launch", {}),
    ("post", "/api/v1/members/invites/accept", {"token": "x"}),
]


@pytest.mark.parametrize("method,path,body", REFUSED_ROUTES)
def test_account_level_routes_refuse_the_demo_account(demo_db, demo_on, method, path, body):
    token = _demo_token(demo_db, demo_on)
    client = TestClient(app)
    resp = getattr(client, method)(path, json=body, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403, (path, resp.status_code, resp.text)


def test_rotating_forwarded_headers_do_not_bypass_the_per_client_limit(demo_db, monkeypatch, demo_on):
    demo.seed(demo_db, PASSWORD, apply=True)
    monkeypatch.setenv("DEMO_LOGIN_PASSWORD", "wrong-on-purpose")
    reset_bucket("demo-login:203.0.113.9")
    client = TestClient(app)
    statuses = []
    for i in range(11):  # the leftmost value changes every time; the proxy's hop (last value) does not
        statuses.append(client.post("/api/v1/auth/demo-login",
                                    headers={"X-Forwarded-For": f"10.9.{i}.1, 203.0.113.9"}).status_code)
    assert statuses[:10] == [404] * 10 and statuses[10] == 429


def test_the_global_ceiling_holds_whatever_addresses_are_claimed(demo_db, monkeypatch, demo_on):
    demo.seed(demo_db, PASSWORD, apply=True)
    monkeypatch.setenv("DEMO_LOGIN_PASSWORD", "wrong-on-purpose")
    monkeypatch.setattr(demo_login, "DEMO_LOGIN_GLOBAL_MAX", 3)
    reset_bucket("demo-login:all")
    client = TestClient(app)
    statuses = [client.post("/api/v1/auth/demo-login", headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code
                for i in range(5)]
    assert statuses[:3] == [404] * 3 and statuses[3:] == [429, 429]
