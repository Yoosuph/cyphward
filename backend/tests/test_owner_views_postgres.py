"""Owner console views against an isolated, migrated PostgreSQL database.

Run with CYPHWARD_TEST_DATABASE_URL (app role) and
CYPHWARD_TEST_DATABASE_ADMIN_URL (owner/superuser, to create the owner row the
app role cannot) pointing at the local `cyphward_test` database. Synthetic
rows are created with unique ids and removed afterwards.
"""
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient

import backend.app.core.database as database
from backend.app.core import totp
from backend.app.core.security import hash_password
from backend.app.main import app

PASSWORD = "owner-views-pass-42"
ORIGIN = {"Origin": "http://testserver"}
SENSITIVE_KEYS = {"password_hash", "totp_secret_enc", "token_hash", "claim_token", "verification_token",
                  "refresh_token_hash", "otc_hash", "code_hash"}


def _local(url):
    info = conninfo_to_dict(url)
    return info.get("dbname") == "cyphward_test" and info.get("host", "") in {"127.0.0.1", "localhost", "::1"}


@pytest.fixture(scope="module")
def urls():
    app_url = os.environ.get("CYPHWARD_TEST_DATABASE_URL")
    admin_url = os.environ.get("CYPHWARD_TEST_DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("Set CYPHWARD_TEST_DATABASE_URL and CYPHWARD_TEST_DATABASE_ADMIN_URL (local cyphward_test)")
    if not (_local(app_url) and _local(admin_url)):
        pytest.fail("Refusing owner-view tests outside the local cyphward_test database")
    with psycopg.connect(admin_url, row_factory=dict_row) as conn:
        if not conn.execute("SELECT to_regclass('public.owner_audit') IS NOT NULL AS ok").fetchone()["ok"]:
            pytest.fail("owner console migration missing")
    return app_url, admin_url


@pytest.fixture
def world(urls, monkeypatch):
    app_url, admin_url = urls

    @contextmanager
    def get_db():
        conn = psycopg.connect(app_url, row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(database, "get_db", get_db)
    secret = totp.generate_secret()
    ids = {"owner": str(uuid4()), "customer": str(uuid4()), "org": str(uuid4()), "domain": str(uuid4()),
           "scan": str(uuid4()), "tag": uuid4().hex[:8]}
    owner_email = f"owner-{ids['tag']}@views.test"
    customer_email = f"cust-{ids['tag']}@views.test"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        # Every TestClient sign-in shares one per-IP bucket; start each test below its limit.
        conn.execute("DELETE FROM rate_limits WHERE bucket_key = 'owner-login-ip:testclient'")
        conn.execute(
            "INSERT INTO profiles (id, email, full_name, role, password_hash, provider, email_verified_at, "
            "totp_secret_enc, totp_enrolled_at) VALUES (%s,%s,'Owner','Member',%s,'email',now(),%s,now())",
            (ids["owner"], owner_email, hash_password(PASSWORD), totp.encrypt_secret(secret)))
        conn.execute(
            "INSERT INTO profiles (id, email, full_name, role, password_hash, provider, email_verified_at) "
            "VALUES (%s,%s,'Customer Person','Member',%s,'email',now())",
            (ids["customer"], customer_email, hash_password("customer-secret-1")))
        conn.execute("INSERT INTO platform_owners (user_id, note) VALUES (%s, 'test owner')", (ids["owner"],))
        conn.execute("INSERT INTO organizations (id, name, slug, sector, plan) VALUES (%s,%s,%s,'Retail','growth')",
                     (ids["org"], f"Views Org {ids['tag']}", f"views-{ids['tag']}"))
        conn.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s,%s,'owner')",
                     (ids["customer"], ids["org"]))
        conn.execute("INSERT INTO domains (id, org_id, domain, verification_status, verification_token, verified_at) "
                     "VALUES (%s,%s,%s,'verified','cyphward-verification=SECRET-TOKEN',now())",
                     (ids["domain"], ids["org"], f"views-{ids['tag']}.test"))
        conn.execute(
            "INSERT INTO scans (id, org_id, domain_id, status, scan_type, created_at, stage_progress, claim_token) "
            "VALUES (%s,%s,%s,'queued','EXTERNAL_ASSESSMENT', now() - interval '20 minutes', "
            "'{\"http\": {\"status\": \"failed\", \"error\": \"1 of 2 targets could not be assessed.\"}}'::jsonb, 'claim-SECRET')",
            (ids["scan"], ids["org"], ids["domain"]))
        conn.execute("INSERT INTO audit_log (org_id, user_id, action, resource_type, metadata) "
                     "VALUES (%s,%s,'scan.launched','scan','{}'::jsonb)", (ids["org"], ids["customer"]))
    ids.update(secret=secret, owner_email=owner_email, customer_email=customer_email,
               org_name=f"Views Org {ids['tag']}")
    yield ids
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("DELETE FROM audit_log WHERE org_id = %s", (ids["org"],))
        conn.execute("DELETE FROM scans WHERE id = %s", (ids["scan"],))
        conn.execute("DELETE FROM organizations WHERE id = %s", (ids["org"],))
        conn.execute("DELETE FROM owner_audit WHERE actor_user_id = %s OR actor_email = %s",
                     (ids["owner"], owner_email))
        conn.execute("DELETE FROM rate_limits WHERE bucket_key LIKE %s", (f"%{ids['tag']}%",))
        conn.execute("DELETE FROM profiles WHERE id IN (%s, %s)", (ids["owner"], ids["customer"]))


def _signed_in(world):
    client = TestClient(app)
    code = f"{totp._hotp(world['secret'], int(time.time() // 30)):06d}"
    resp = client.post("/api/v1/owner/session", headers=ORIGIN,
                       json={"email": world["owner_email"], "password": PASSWORD, "code": code})
    assert resp.status_code == 200, resp.text
    return client


def _no_secrets(payload):
    if isinstance(payload, dict):
        assert not (SENSITIVE_KEYS & set(payload)), SENSITIVE_KEYS & set(payload)
        for v in payload.values():
            _no_secrets(v)
    elif isinstance(payload, list):
        for v in payload:
            _no_secrets(v)
    elif isinstance(payload, str):
        assert "SECRET" not in payload


def test_views_require_an_owner_session(world):
    client = TestClient(app)
    for path in ("/overview", "/organizations", "/users", "/subscriptions", "/scans", "/logs", "/system"):
        assert client.get(f"/api/v1/owner{path}").status_code == 401


def test_owner_sees_everything_without_secrets(world):
    client = _signed_in(world)
    overview = client.get("/api/v1/owner/overview").json()
    assert overview["counts"]["users_total"] >= 2 and overview["counts"]["scans_queued"] >= 1

    orgs = client.get("/api/v1/owner/organizations", params={"q": world["tag"]}).json()
    assert [o["id"] for o in orgs["items"]] == [world["org"]] and orgs["total"] == 1
    assert orgs["items"][0]["owner_email"] == world["customer_email"]
    by_domain = client.get("/api/v1/owner/organizations", params={"q": f"views-{world['tag']}.test"}).json()
    assert by_domain["total"] == 1

    detail = client.get(f"/api/v1/owner/organizations/{world['org']}").json()
    assert detail["members"][0]["email"] == world["customer_email"]
    assert detail["domains"][0]["verification_status"] == "verified"

    users = client.get("/api/v1/owner/users", params={"q": world["tag"]}).json()
    assert {u["email"] for u in users["items"]} == {world["owner_email"], world["customer_email"]}
    owner_row = next(u for u in users["items"] if u["email"] == world["owner_email"])
    assert owner_row["platform_owner"] is True and owner_row["mfa"] == "authenticator"

    user = client.get(f"/api/v1/owner/users/{world['customer']}").json()
    assert user["memberships"][0]["role"] == "owner" and user["activity"][0]["action"] == "scan.launched"

    scans = client.get("/api/v1/owner/scans", params={"q": world["tag"]}).json()
    assert scans["items"][0]["state"] == "queued_delayed"
    assert scans["items"][0]["failed_stages"] == ["http"]
    scan = client.get(f"/api/v1/owner/scans/{world['scan']}").json()
    assert scan["stages"][0]["error"] == "1 of 2 targets could not be assessed."

    logs = client.get("/api/v1/owner/logs", params={"q": world["customer_email"]}).json()
    assert logs["items"][0]["action"] == "scan.launched"
    owner_logs = client.get("/api/v1/owner/logs", params={"source": "owner", "q": world["owner_email"]}).json()
    assert {"owner.sign_in", "owner.view.organizations"} <= {r["action"] for r in owner_logs["items"]}

    system = client.get("/api/v1/owner/system").json()
    assert system["database"]["ok"] is True

    for payload in (overview, orgs, detail, users, user, scans, scan, logs, owner_logs, system):
        _no_secrets(payload)


def test_every_view_is_audited_before_data_is_returned(world, urls):
    client = _signed_in(world)
    client.get(f"/api/v1/owner/organizations/{world['org']}")
    with psycopg.connect(urls[1], row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT action, target_type, target_id, outcome FROM owner_audit WHERE actor_user_id = %s "
            "AND action = 'owner.view.organization' ORDER BY created_at DESC LIMIT 1", (world["owner"],)).fetchone()
    assert row == {"action": "owner.view.organization", "target_type": "organization",
                   "target_id": world["org"], "outcome": "success"}


def test_unknown_and_malformed_ids_are_404(world):
    client = _signed_in(world)
    assert client.get("/api/v1/owner/organizations/not-a-uuid").status_code == 404
    assert client.get(f"/api/v1/owner/users/{uuid4()}").status_code == 404
    assert client.get(f"/api/v1/owner/scans/{uuid4()}").status_code == 404


def test_dedicated_admin_setup_works_with_real_grants(urls, monkeypatch):
    """Operator-created console-only login: setup session, authenticator, new password, console."""
    app_url, admin_url = urls

    @contextmanager
    def get_db():
        conn = psycopg.connect(app_url, row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(database, "get_db", get_db)
    uid, email = str(uuid4()), f"admin-{uuid4().hex[:8]}@views.test"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("DELETE FROM rate_limits WHERE bucket_key = 'owner-login-ip:testclient'")
        conn.execute("INSERT INTO profiles (id, email, full_name, role, password_hash, provider, email_verified_at) "
                     "VALUES (%s,%s,'Admin','Member',%s,'email',now())", (uid, email, hash_password("setup-pass-123")))
        conn.execute("INSERT INTO platform_owners (user_id, note, console_only) VALUES (%s,'test',true)", (uid,))
        conn.execute("INSERT INTO owner_setups (user_id, expires_at) VALUES (%s, now() + interval '1 hour')", (uid,))
    try:
        client = TestClient(app)
        first = client.post("/api/v1/owner/session", headers=ORIGIN,
                            json={"email": email, "password": "setup-pass-123", "code": ""})
        assert first.json()["setup_required"] is True
        secret = client.post("/api/v1/owner/setup/authenticator", headers=ORIGIN).json()["secret"]
        code = f"{totp._hotp(secret, int(time.time() // 30)):06d}"
        done = client.post("/api/v1/owner/setup/complete", headers=ORIGIN,
                           json={"new_password": "a-long-new-owner-passphrase", "code": code})
        assert done.status_code == 200, done.text
        assert client.get("/api/v1/owner/me").json()["email"] == email
        assert client.post("/api/v1/auth/login",
                           json={"email": email, "password": "a-long-new-owner-passphrase"}).status_code == 401
        with psycopg.connect(admin_url, row_factory=dict_row) as conn:
            row = conn.execute("SELECT completed_at IS NOT NULL AS done FROM owner_setups WHERE user_id = %s",
                               (uid,)).fetchone()
        assert row["done"] is True
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute("DELETE FROM owner_audit WHERE actor_user_id = %s OR actor_email = %s", (uid, email))
            conn.execute("DELETE FROM rate_limits WHERE bucket_key LIKE %s", (f"%{email}%",))
            conn.execute("DELETE FROM profiles WHERE id = %s", (uid,))
