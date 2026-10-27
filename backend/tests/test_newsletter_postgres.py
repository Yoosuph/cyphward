"""Newsletter on the real test database, as the restricted app role (docs/newsletter/README.md).

Double opt-in end to end through the API, token hashes only at rest, 72-hour expiry, one-click
unsubscribe, the send-once claim under a real race, the trigger and column grants that keep a sent
issue sent, and the privileges: no DELETE for the app role, nothing at all for anon/authenticated.
The app role cannot delete, so every test uses fresh addresses and never counts rows it did not make.
"""
import re
import threading
import uuid
from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

import backend.app.api.newsletter as api
import backend.app.core.owner as owner_mod
from backend.app.core import config, database
from backend.app.core import newsletter as nl
from backend.app.main import app
from backend.app.services import newsletter_brevo
from backend.tests.newsletter_fakes import StubBrevo
from backend.tests.test_newsletter import BASE, CONSENT, DRAFT_KEY, POSTAL, SECRET, good_draft, token_from
from backend.tests.test_scan_admission_postgres import disposable_postgres_url  # noqa: F401 (fixture)

OWNER_ID = str(uuid.uuid4())


@pytest.fixture
def pg(disposable_postgres_url, monkeypatch):
    @contextmanager
    def get_db():
        conn = psycopg.connect(disposable_postgres_url, row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(database, "get_db", get_db)
    for name, value in {
        "NEWSLETTER_ENABLED": True, "NEWSLETTER_DRAFT_API_KEY": DRAFT_KEY, "NEWSLETTER_TOKEN_SECRET": SECRET,
        "NEWSLETTER_BREVO_LIST_ID": "7", "NEWSLETTER_POSTAL_LINE": POSTAL, "NEWSLETTER_PUBLIC_BASE_URL": BASE,
        "NEWSLETTER_BREVO_UNSUB_ATTRIBUTE": "CW_UNSUB_TOKEN", "BREVO_API_KEY": "test-brevo-key",
    }.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(nl, "_STORE", nl.PostgresNewsletterStore())
    brevo = StubBrevo()
    monkeypatch.setattr(newsletter_brevo, "get_client", lambda list_id, attribute: brevo)
    sent = []

    async def fake_send(to_email, subject, html_content, text_content=None, **kw):
        sent.append({"to": to_email, "text": text_content, **kw})
        return {"success": True}

    monkeypatch.setattr(api, "send_email_async", fake_send)
    monkeypatch.setattr(api, "MIN_RESPONSE_SECONDS", 0)
    monkeypatch.setattr(owner_mod, "require_owner", lambda request: {"user_id": OWNER_ID, "email": "owner@x.test",
                                                                     "session_id": "s", "expires_at": None})
    monkeypatch.setattr(owner_mod, "OWNER_CONSOLE_ORIGINS", ["https://admin.cyphward.test"])
    conn = psycopg.connect(disposable_postgres_url, row_factory=dict_row, autocommit=True)
    client = TestClient(app)
    client.conn, client.brevo, client.sent = conn, brevo, sent
    yield client
    conn.close()


def email():
    return f"reader-{uuid.uuid4().hex[:12]}@example.com"


def row_for(pg, address):
    return pg.conn.execute("SELECT * FROM newsletter_subscribers WHERE email_normalised = %s", (address,)).fetchone()


def subscribe(pg, address):
    resp = pg.post("/api/v1/newsletter/subscribe", json={"email": address.upper(), **CONSENT},
                   headers={"X-Forwarded-For": f"10.{uuid.uuid4().int % 250}.0.1"})
    assert resp.status_code == 202
    return resp


def test_double_opt_in_end_to_end_with_hashes_only(pg):
    address = email()
    subscribe(pg, address)
    row = row_for(pg, address)
    assert row["status"] == "pending" and row["consent_wording_version"] == nl.CONSENT_WORDING_VERSION
    assert row["source"] == "newsletter_page" and row["consent_at"] is not None
    mail = pg.sent[-1]
    confirm, unsub = token_from(mail["text"], "confirm"), token_from(mail["text"], "unsubscribe")
    values = " ".join(str(v) for v in row.values())
    assert confirm.split(".")[1] not in values and unsub.split(".")[1] not in values
    assert re.fullmatch(r"s1\$[0-9a-f]{32}\$[0-9a-f]{64}", row["confirm_token_hash"])
    assert pg.brevo.calls == []

    resp = pg.get(f"/api/v1/newsletter/confirm?token={confirm}", follow_redirects=False)
    assert resp.headers["location"] == f"{BASE}/newsletter/confirmed?result=ok"
    assert row_for(pg, address)["status"] == "confirmed"
    assert pg.brevo.contacts[address]["attributes"]["CW_UNSUB_TOKEN"] == unsub

    resp = pg.get(f"/api/v1/newsletter/unsubscribe?token={unsub}", follow_redirects=False)
    assert resp.headers["location"] == f"{BASE}/newsletter/unsubscribed?result=ok"
    final = row_for(pg, address)
    assert final["status"] == "unsubscribed" and final["unsubscribed_at"] and final["confirm_token_hash"] is None
    assert address not in pg.brevo.contacts


def test_expired_link_does_not_confirm(pg):
    address = email()
    subscribe(pg, address)
    pg.conn.execute("UPDATE newsletter_subscribers SET confirm_expires_at = now() - interval '1 minute' "
                    "WHERE email_normalised = %s", (address,))
    resp = pg.get(f"/api/v1/newsletter/confirm?token={token_from(pg.sent[-1]['text'], 'confirm')}", follow_redirects=False)
    assert resp.headers["location"].endswith("result=expired")
    assert row_for(pg, address)["status"] == "pending"


def test_expiry_is_72_hours(pg):
    address = email()
    subscribe(pg, address)
    hours = pg.conn.execute("SELECT extract(epoch FROM confirm_expires_at - consent_at) / 3600 AS h "
                            "FROM newsletter_subscribers WHERE email_normalised = %s", (address,)).fetchone()["h"]
    assert abs(float(hours) - 72) < 0.01


def test_a_confirmed_address_is_left_untouched(pg):
    address = email()
    subscribe(pg, address)
    pg.get(f"/api/v1/newsletter/confirm?token={token_from(pg.sent[-1]['text'], 'confirm')}")
    before = row_for(pg, address)
    sent_before = len(pg.sent)
    subscribe(pg, address)
    assert row_for(pg, address) == before and len(pg.sent) == sent_before


def test_concurrent_first_subscriptions_make_one_row(pg):
    address = email()
    store = nl.PostgresNewsletterStore()
    barrier = threading.Barrier(4)
    results = []

    def run():
        barrier.wait(timeout=10)
        results.append(store.subscribe(address, nl.CONSENT_WORDING_VERSION, "landing_footer", SECRET))

    threads = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in threads]
    [t.join(timeout=20) for t in threads]
    assert pg.conn.execute("SELECT count(*) AS n FROM newsletter_subscribers WHERE email_normalised = %s",
                           (address,)).fetchone()["n"] == 1
    assert sum(r is not None for r in results) >= 1


def _draft(pg, **over):
    resp = pg.post("/api/v1/newsletter/drafts", json=good_draft(**over), headers={"Authorization": f"Bearer {DRAFT_KEY}"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_send_once_through_the_api_with_audit(pg):
    address = email()
    subscribe(pg, address)
    pg.get(f"/api/v1/newsletter/confirm?token={token_from(pg.sent[-1]['text'], 'confirm')}")
    iid = _draft(pg)
    origin = {"Origin": "https://admin.cyphward.test"}
    resp = pg.post(f"/api/v1/newsletter/drafts/{iid}/send", json={"approve": True, "subject": "Cyphward notes for October"},
                   headers=origin)
    assert resp.status_code == 200, resp.text
    row = pg.conn.execute("SELECT * FROM newsletter_issues WHERE id = %s", (iid,)).fetchone()
    assert row["status"] == "sent" and row["sent_at"] and row["brevo_campaign_id"] == resp.json()["brevo_campaign_id"]
    assert str(row["approved_by"]) == OWNER_ID
    again = pg.post(f"/api/v1/newsletter/drafts/{iid}/send", json={"approve": True, "subject": "Cyphward notes for October"},
                    headers=origin)
    assert again.status_code == 409 and len(pg.brevo.sent) == 1
    actions = [r["action"] for r in pg.conn.execute(
        "SELECT action FROM audit_log WHERE resource_type = 'newsletter_issue' AND resource_id = %s ORDER BY created_at, action",
        (iid,)).fetchall()]
    assert sorted(actions) == sorted(["newsletter.draft_created", "newsletter.send_approved",
                                      "newsletter.campaign_created", "newsletter.sent"])
    assert address in pg.brevo.campaigns[row["brevo_campaign_id"]]["recipients"]


def test_racing_claims_succeed_once(pg):
    iid = _draft(pg)
    store = nl.PostgresNewsletterStore()
    barrier = threading.Barrier(6)
    results = []

    def run(i):
        barrier.wait(timeout=10)
        results.append(store.claim_issue(iid, {"kind": "owner", "user_id": str(uuid.uuid4())}))

    threads = [threading.Thread(target=run, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join(timeout=20) for t in threads]
    assert sum(r is not None for r in results) == 1
    n = pg.conn.execute("SELECT count(*) AS n FROM audit_log WHERE action = 'newsletter.send_approved' AND resource_id = %s",
                        (iid,)).fetchone()["n"]
    assert n == 1


def test_the_database_keeps_a_claimed_or_sent_issue_final(pg):
    iid = _draft(pg)
    pg.conn.execute("UPDATE newsletter_issues SET send_claimed_at = now() WHERE id = %s", (iid,))
    with pytest.raises(psycopg.errors.RaiseException):
        pg.conn.execute("UPDATE newsletter_issues SET send_claimed_at = NULL WHERE id = %s", (iid,))
    pg.conn.execute("UPDATE newsletter_issues SET brevo_campaign_id = '42', status = 'sent', sent_at = now() WHERE id = %s", (iid,))
    with pytest.raises(psycopg.errors.RaiseException):
        pg.conn.execute("UPDATE newsletter_issues SET status = 'draft' WHERE id = %s", (iid,))
    with pytest.raises(psycopg.errors.RaiseException):
        pg.conn.execute("UPDATE newsletter_issues SET brevo_campaign_id = '43' WHERE id = %s", (iid,))
    with pytest.raises(psycopg.errors.CheckViolation):
        other = _draft(pg)
        pg.conn.execute("UPDATE newsletter_issues SET status = 'sent' WHERE id = %s", (other,))


def test_the_app_role_cannot_edit_draft_content(pg):
    iid = _draft(pg)
    for column, value in (("subject", "changed"), ("body_json", '{"sections": []}'), ("created_by", "someone")):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            pg.conn.execute(f"UPDATE newsletter_issues SET {column} = %s WHERE id = %s", (value, iid))


def test_the_app_role_never_deletes(pg):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        pg.conn.execute("DELETE FROM newsletter_subscribers WHERE false")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        pg.conn.execute("DELETE FROM newsletter_issues WHERE false")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        pg.conn.execute("TRUNCATE newsletter_subscribers")


def test_public_roles_have_no_access(pg):
    for role in ("anon", "authenticated", "public"):
        for table in ("newsletter_subscribers", "newsletter_issues"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                if role == "public":
                    granted = pg.conn.execute(
                        "SELECT count(*) AS n FROM information_schema.role_table_grants "
                        "WHERE grantee = 'PUBLIC' AND table_name = %s", (table,)).fetchone()["n"] > 0
                else:
                    granted = pg.conn.execute("SELECT has_table_privilege(%s, %s, %s) AS g",
                                              (role, table, privilege)).fetchone()["g"]
                assert not granted, (role, table, privilege)
    rls = {r["relname"]: r["relrowsecurity"] for r in pg.conn.execute(
        "SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('newsletter_subscribers', 'newsletter_issues')")}
    assert rls == {"newsletter_subscribers": True, "newsletter_issues": True}


def test_constraints_refuse_raw_tokens_and_unnormalised_addresses(pg):
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.conn.execute("INSERT INTO newsletter_subscribers (email_normalised, consent_at, consent_wording_version, source, "
                        "confirm_token_hash, confirm_expires_at) VALUES (%s, now(), 'v', 'newsletter_page', 's1$x$y', now())",
                        (email(),))
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.conn.execute("INSERT INTO newsletter_subscribers (email_normalised, status, consent_at, consent_wording_version, source) "
                        "VALUES (%s, 'confirmed', now(), 'v', 'newsletter_page')", ("Mixed@Example.com",))
    with pytest.raises(psycopg.errors.CheckViolation):  # pending needs its confirm hash and expiry
        pg.conn.execute("INSERT INTO newsletter_subscribers (email_normalised, consent_at, consent_wording_version, source) "
                        "VALUES (%s, now(), 'v', 'newsletter_page')", (email(),))


def test_flag_off_on_the_real_database(pg, monkeypatch):
    monkeypatch.setattr(config, "NEWSLETTER_ENABLED", False)
    address = email()
    assert pg.post("/api/v1/newsletter/subscribe", json={"email": address, **CONSENT}).status_code == 404
    assert row_for(pg, address) is None
