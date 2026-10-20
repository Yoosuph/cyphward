"""Fintech Org sample-data seed against the real, migrated test database.

Runs only against the owned loopback `cyphward_test` database through the restricted `cyphward_app` role
(see `disposable_postgres_url`). Every test leaves the database as it found it: the fixture unseeds the demo
organisation before and after each test, and the count test compares every public table.
"""
import json
import re

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from backend.app.core import database
from backend.app.packs import render
from backend.app.risk.engine import SCORE_MODEL, compute_risk_score, latest_assessment
from backend.scripts import seed_fintech_demo as demo
from backend.tests.test_scan_admission_postgres import disposable_postgres_url  # noqa: F401 (fixture)

BANNED = ("compliant", "certified", "certification", "satisfies", "satisfied", "adequate", "adequacy", "guarantee",
          "passes audit", "pass the audit", "compliance score", "meets the requirement", "fully meets",
          "is met", "partial compliance", "fully compliant", "is compliant", "non-compliant", "noncompliant")
PASSWORD = "fintech-demo-pass-2026"


@pytest.fixture
def outbox(monkeypatch):
    """Captures every email the app tries to send. Nothing is delivered in these tests."""
    import backend.app.api.auth as auth_api
    from backend.app.services import mailer

    sent = []

    async def capture(*args, **kwargs):
        sent.append({"args": args, "kwargs": kwargs})
        return True

    monkeypatch.setattr(auth_api, "send_email_async", capture)
    monkeypatch.setattr(mailer, "send_email_async", capture)
    return sent


@pytest.fixture
def demo_db(disposable_postgres_url, monkeypatch, outbox):
    """The migrated test database, with the app's database accessor pointed at it, and no demo rows before or after."""
    url = disposable_postgres_url
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("COMPLIANCE_DOCS_MODEL", "off")

    from contextlib import contextmanager

    @contextmanager
    def get_db():
        conn = psycopg.connect(url, row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(database, "get_db", get_db)
    if demo.status(url) != "absent":
        demo.unseed(url, apply=True)
    demo.clear_throttles(url)
    yield url
    if demo.status(url) != "absent":
        demo.unseed(url, apply=True)
    demo.clear_throttles(url)


def _seed(url, now=None):
    return demo.seed(url, PASSWORD, apply=True, now=now)


def _one(url, sql, params=()):
    with psycopg.connect(url, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


def _code_from(outbox):
    """The six-digit step-up code the app emailed (read from the captured message, never from the database)."""
    for mail in reversed(outbox):
        for value in list(mail["args"]) + list(mail["kwargs"].values()):
            if isinstance(value, str):
                found = re.findall(r"(?<!\d)(\d{6})(?!\d)", value)
                if found:
                    return found[0]
    raise AssertionError("no sign-in code was emailed")


def _sign_in(outbox, client=None):
    """The normal password login. The demo owner is a member, so no emailed step-up code is needed."""
    client = client or TestClient(_app())
    resp = client.post("/api/v1/auth/login", json={"email": demo.DEMO_EMAIL, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "mfa_required" not in body and body.get("access_token")
    assert outbox == []  # nothing was emailed
    return client, body["access_token"]


def _app():
    from backend.app.main import app
    return app


def _headers(token):
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": demo.DEMO_ORG_ID}


def docs_module():
    from backend.app.compliance import documents
    return documents


def _snapshot(url):
    return demo.count_all(url)


# ── Dry run, seed, unseed ────────────────────────────────────────────────────


def test_dry_run_writes_nothing_and_says_so(demo_db):
    before = _snapshot(demo_db)
    result = demo.seed(demo_db, PASSWORD, apply=False)
    assert result["action"] == "dry-run"
    assert result["state"] == "absent"
    assert _snapshot(demo_db) == before


def test_seed_then_unseed_leaves_every_table_exactly_as_it_was(demo_db):
    before = _snapshot(demo_db)
    _seed(demo_db)
    assert demo.status(demo_db) == "seeded"
    assert sum(_snapshot(demo_db).values()) > sum(before.values())
    removed = demo.unseed(demo_db, apply=True)
    assert removed["action"] == "unseeded"
    assert _snapshot(demo_db) == before


def test_seeding_twice_is_a_no_op(demo_db):
    _seed(demo_db)
    after_first = _snapshot(demo_db)
    second = demo.seed(demo_db, PASSWORD, apply=True)
    assert second["action"] == "noop"
    assert _snapshot(demo_db) == after_first


def test_unseed_refuses_when_the_demo_org_is_missing(demo_db):
    with pytest.raises(demo.Refused, match="not in this database"):
        demo.unseed(demo_db, apply=True)


def test_unseed_refuses_when_the_org_or_members_look_different(demo_db):
    _seed(demo_db)
    with psycopg.connect(demo_db) as conn:
        conn.execute("UPDATE organizations SET name = 'Fintech Org' WHERE id = %s", (demo.DEMO_ORG_ID,))
        conn.commit()
    with pytest.raises(demo.Refused, match="looks different"):
        demo.unseed(demo_db, apply=True)
    with psycopg.connect(demo_db) as conn:
        conn.execute("UPDATE organizations SET name = %s WHERE id = %s", (demo.DEMO_ORG_NAME, demo.DEMO_ORG_ID))
        conn.commit()
    # A real customer joins the demo organisation: unseed must not delete around them.
    real = "00000000-1111-4222-8333-444444444444"
    with psycopg.connect(demo_db) as conn:
        conn.execute("INSERT INTO profiles (id, email, full_name, role, password_hash, provider) "
                     "VALUES (%s, 'customer@example.com', 'Customer', 'Member', NULL, 'email')", (real,))
        conn.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s, %s, 'member')",
                     (real, demo.DEMO_ORG_ID))
        conn.commit()
    try:
        with pytest.raises(demo.Refused, match="looks different"):
            demo.unseed(demo_db, apply=True)
        assert demo.status(demo_db) == "conflict"
    finally:
        with psycopg.connect(demo_db) as conn:
            conn.execute("DELETE FROM organization_members WHERE user_id = %s", (real,))
            conn.execute("DELETE FROM profiles WHERE id = %s", (real,))
            conn.commit()


def test_seed_refuses_to_take_over_an_id_used_by_something_else(demo_db):
    with psycopg.connect(demo_db) as conn:
        conn.execute("INSERT INTO organizations (id, name, slug, sector, plan) VALUES (%s, 'Other', 'other-org-x', "
                     "'Technology', 'starter')", (demo.DEMO_ORG_ID,))
        conn.commit()
    try:
        with pytest.raises(demo.Refused):
            _seed(demo_db)
        assert demo.status(demo_db) == "conflict"
    finally:
        with psycopg.connect(demo_db) as conn:
            conn.execute("DELETE FROM organizations WHERE id = %s", (demo.DEMO_ORG_ID,))
            conn.commit()


# ── Scores, grades and counts agree with the stored findings ─────────────


def _replayed_scores(url):
    """Rebuild each scan's score from the stored findings with the risk engine, independent of the seed's lists."""
    scans = _one(url, "SELECT id, score, completed_at FROM scans WHERE org_id = %s AND status = 'completed' "
                      "ORDER BY completed_at", (demo.DEMO_ORG_ID,))
    findings = _one(url, "SELECT title, severity, category, evidence, status, first_seen_at, resolved_at "
                         "FROM findings WHERE org_id = %s", (demo.DEMO_ORG_ID,))
    domain = _one(url, "SELECT id FROM domains WHERE org_id = %s", (demo.DEMO_ORG_ID,))[0]["id"]
    out = []
    for scan in scans:
        seen = [f for f in findings
                if f["first_seen_at"] <= scan["completed_at"]
                and (f["resolved_at"] is None or f["resolved_at"] > scan["completed_at"])]
        assessment = {
            "scan_id": str(scan["id"]), "status": "completed", "completed_at": scan["completed_at"].isoformat(),
            "model": SCORE_MODEL,
            "coverage": demo.COVERAGE,
            "domains": [{"domain_id": str(domain), "domain": demo.DEMO_DOMAIN, "scan_id": str(scan["id"]),
                         "completed_at": scan["completed_at"].isoformat(), "state": "complete"}],
        }
        out.append((scan, compute_risk_score([dict(f, status="open") for f in seen], assessment=assessment), seen))
    return out


def test_each_scan_grade_and_finding_count_agree_with_the_scoring_code(demo_db):
    _seed(demo_db)
    replays = _replayed_scores(demo_db)
    assert len(replays) == 3
    for scan, scored, seen in replays:
        stored = _one(demo_db, "SELECT score FROM scans WHERE id = %s", (scan["id"],))[0]["score"]
        snapshot = _one(demo_db, "SELECT score, risk_points, scope, model FROM score_snapshots WHERE scan_id = %s",
                        (scan["id"],))[0]
        assert float(stored) == scored["score"] == float(snapshot["score"])
        assert snapshot["risk_points"] == scored["risk_points"]
        assert snapshot["model"] == "cyphward-risk-v3" and snapshot["scope"] == "organization"
        assert scored["grade"] in {"A", "B", "C", "D", "F"}
        assert sum(scored["counts"].values()) == len(seen)
    grades = [scored["grade"] for _, scored, _ in replays]
    assert grades == ["D", "D", "C"]  # the history improves, one band at the last scan


def test_the_latest_scan_counts_match_the_open_rows(demo_db):
    _seed(demo_db)
    scan, scored, seen = _replayed_scores(demo_db)[-1]
    open_rows = _one(demo_db, "SELECT count(*) AS n FROM findings WHERE org_id = %s AND status <> 'resolved'",
                     (demo.DEMO_ORG_ID,))[0]["n"]
    assert open_rows == len(seen) == 7
    by_severity = {s: sum(1 for f in seen if f["severity"] == s) for s in ("critical", "high", "medium", "low")}
    assert by_severity == {"critical": 0, "high": 2, "medium": 2, "low": 3}
    assert scored["counts"]["high"] == 2 and scored["counts"]["low"] == 3


def test_the_domain_stays_pending_so_no_organisation_grade_is_claimed(demo_db):
    _seed(demo_db)
    domain = _one(demo_db, "SELECT verification_status, verified_at, verification_token FROM domains "
                           "WHERE org_id = %s", (demo.DEMO_ORG_ID,))
    assert domain == [{"verification_status": "pending", "verified_at": None,
                       "verification_token": demo.DEMO_TOKEN}]
    from backend.app.risk import domain_coverage
    assert domain_coverage.org_domain_coverage(demo.DEMO_ORG_ID) == []
    # The live engine, reading the same data the dashboard reads, refuses an organisation grade.
    from backend.app.core.database import execute_query
    findings = execute_query("SELECT * FROM findings WHERE org_id = %s AND status != 'resolved'",
                             (demo.DEMO_ORG_ID,))
    live = compute_risk_score(findings, assessment=latest_assessment(demo.DEMO_ORG_ID))
    assert live["grade"] is None and live["posture_label"] == "Not all domains assessed"
    latest = _one(demo_db, "SELECT score FROM score_snapshots WHERE org_id = %s AND scan_id IS NOT NULL "
                           "ORDER BY created_at DESC LIMIT 1", (demo.DEMO_ORG_ID,))[0]["score"]
    assert live["score"] == float(latest)  # the live score and the latest scan's stored score agree


def test_sample_scan_is_never_queued_or_scanned(demo_db):
    _seed(demo_db)
    assert _one(demo_db, "SELECT count(*) AS n FROM scans WHERE org_id = %s AND status <> 'completed'",
                (demo.DEMO_ORG_ID,))[0]["n"] == 0
    assert _one(demo_db, "SELECT count(*) AS n FROM scan_launch_requests WHERE org_id = %s",
                (demo.DEMO_ORG_ID,))[0]["n"] == 0


# ── Sign-in through the existing login route ────────────────────────────


def test_the_demo_owner_signs_in_through_the_existing_login_route(demo_db, outbox):
    _seed(demo_db)
    client, token = _sign_in(outbox)
    me = client.get("/api/v1/organizations/current", headers=_headers(token))
    assert me.status_code == 200, me.text
    assert me.json()["name"] == demo.DEMO_ORG_NAME and me.json()["role"] == "member"


def test_a_wrong_password_gives_no_session(demo_db, outbox):
    _seed(demo_db)
    client = TestClient(_app())
    resp = client.post("/api/v1/auth/login", json={"email": demo.DEMO_EMAIL, "password": "not-the-demo-password"})
    assert resp.status_code == 401 and "access_token" not in resp.json()


def test_the_password_is_hashed_and_never_stored_in_plain_text(demo_db):
    _seed(demo_db)
    row = _one(demo_db, "SELECT password_hash FROM profiles WHERE id = %s", (demo.DEMO_USER_ID,))[0]
    assert row["password_hash"].startswith("$argon2")
    text = json.dumps(_one(demo_db, "SELECT * FROM profiles WHERE id = %s", (demo.DEMO_USER_ID,)), default=str)
    assert PASSWORD not in text


# ── Packs, documents and the SAMPLE DATA marker ─────────────────────────


def test_the_pack_and_drafts_render_with_the_sample_marker(demo_db, outbox):
    _seed(demo_db)
    client, token = _sign_in(outbox)
    headers = _headers(token)
    packs = client.get("/api/v1/packs", headers=headers)
    assert packs.status_code == 200, packs.text
    listing = packs.json()
    items = listing.get("packs", listing) if isinstance(listing, dict) else listing
    assert len(items) == 1
    pack_id = items[0]["id"]
    html = client.get(f"/api/v1/packs/{pack_id}/html", headers=headers).content.decode()
    pdf_text = " ".join(render.pdf_extract_text(client.get(f"/api/v1/packs/{pack_id}/pdf", headers=headers).content).split())
    assert demo.SAMPLE_LABEL in html
    assert demo.SAMPLE_LABEL in pdf_text
    docs = client.get("/api/v1/compliance/documents", headers=headers)
    assert docs.status_code == 200, docs.text
    drafts = [d for d in docs.json().get("documents", []) if d.get("latest")]
    assert sorted(d["kind"] for d in drafts) == sorted(docs_module().KINDS)
    for draft in drafts:
        detail = client.get(f"/api/v1/compliance/documents/{draft['latest']['id']}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert demo.SAMPLE_LABEL in json.dumps(detail.json()), draft["kind"]
        stored = _one(demo_db, "SELECT text FROM compliance_documents WHERE id = %s", (draft["latest"]["id"],))
        assert demo.SAMPLE_LABEL in stored[0]["text"], draft["kind"]


# ── Wording and isolation ─────────────────────────────────────────────────


def _seed_texts():
    texts = [demo.DEMO_ORG_NAME, demo.DEMO_NAME, demo.SAMPLE_NOTE, demo.COVERAGE["label"]]
    for finding in demo.FINDINGS:
        texts += [finding["title"], finding["description"], finding["remediation"]]
    for item in demo.INCIDENTS:
        texts += [item["title"], item["notes"]]
    for _, answer in demo.ATTESTATIONS:
        texts.append(json.dumps(answer))
    texts += [task["title"] for task in demo.REMEDIATION_TASKS]
    return texts


def test_no_banned_claim_phrase_in_seed_text():
    for text in _seed_texts():
        lowered = text.lower()
        for phrase in BANNED:
            assert not re.search(r"\b" + re.escape(phrase) + r"\b", lowered), (phrase, text)


def test_no_banned_claim_phrase_in_stored_rows_or_generated_documents(demo_db):
    _seed(demo_db)
    text = json.dumps(_one(demo_db, "SELECT text FROM compliance_documents WHERE org_id = %s",
                           (demo.DEMO_ORG_ID,)), default=str)
    text += json.dumps(_one(demo_db, "SELECT title, description, remediation FROM findings WHERE org_id = %s",
                            (demo.DEMO_ORG_ID,)), default=str)
    text += json.dumps(_one(demo_db, "SELECT title, notes FROM compliance_incidents WHERE org_id = %s",
                            (demo.DEMO_ORG_ID,)), default=str)
    lowered = text.lower()
    for phrase in BANNED:
        assert not re.search(r"\b" + re.escape(phrase) + r"\b", lowered), phrase


def test_no_seeded_row_has_an_email_outside_the_reserved_sample_domain(demo_db):
    _seed(demo_db)
    emails = _one(demo_db, "SELECT email FROM profiles WHERE id = %s OR id IN "
                           "(SELECT user_id FROM organization_members WHERE org_id = %s)",
                  (demo.DEMO_USER_ID, demo.DEMO_ORG_ID))
    assert emails and all(row["email"] == demo.DEMO_EMAIL for row in emails)
    assert demo.DEMO_EMAIL.endswith(".test")
    blobs = _one(demo_db, "SELECT metadata::text AS t FROM audit_log WHERE org_id = %s", (demo.DEMO_ORG_ID,))
    assert not any(re.search(r"[\w.+-]+@(?!fintech-org\.test)[\w-]+\.[\w.]+", row["t"]) for row in blobs)


def test_billing_is_manual_trialing_with_no_provider_reference_or_invoices(demo_db):
    _seed(demo_db)
    sub = _one(demo_db, "SELECT plan, status, provider, provider_ref FROM subscriptions WHERE org_id = %s",
               (demo.DEMO_ORG_ID,))
    assert sub == [{"plan": "growth", "status": "trialing", "provider": "manual", "provider_ref": None}]
    assert _one(demo_db, "SELECT count(*) AS n FROM invoices WHERE org_id = %s", (demo.DEMO_ORG_ID,))[0]["n"] == 0


def test_seeding_sends_no_mail_and_writes_no_notifications(demo_db, monkeypatch):
    sent = []

    async def refuse(*args, **kwargs):
        sent.append(args)
        raise AssertionError("the demo seed must not send mail")

    import backend.app.api.auth as auth_api
    monkeypatch.setattr(auth_api, "send_email_async", refuse, raising=False)
    _seed(demo_db)
    assert sent == []
    assert _one(demo_db, "SELECT count(*) AS n FROM notifications WHERE org_id = %s", (demo.DEMO_ORG_ID,))[0]["n"] == 0


def test_the_seed_only_writes_to_the_url_it_is_given(demo_db):
    with pytest.raises(demo.RefusedTarget):
        demo.check_target("postgresql://u@db.example.com/cyphward_prod", "local", None)
    with pytest.raises(demo.RefusedTarget):
        demo.check_target(demo_db.replace("cyphward_test", "cyphward_prod"), "local", None)
    with pytest.raises(demo.RefusedTarget):
        demo.check_target(demo_db, "production", None)
    demo.check_target(demo_db, "local", None)


def test_production_metrics_are_the_same_with_and_without_the_demo(demo_db, monkeypatch):
    from types import SimpleNamespace

    from backend.app.api import owner_views

    monkeypatch.setattr(owner_views, "_view", lambda *args, **kwargs: None)

    def metrics():
        view = owner_views.overview(SimpleNamespace(), owner={})
        return {"counts": view["counts"], "signups": view["signups_14d"], "subscriptions": view["subscriptions"],
                "invoices": view["invoices"]}

    before = metrics()
    _seed(demo_db)
    assert metrics() == before


def test_the_scan_and_finding_lists_show_the_rows(demo_db, outbox):
    _seed(demo_db)
    client, token = _sign_in(outbox)
    headers = _headers(token)
    scans = client.get("/api/v1/scans", headers=headers)
    assert scans.status_code == 200, scans.text
    rows = scans.json()
    assert len(rows) == 3
    stored = {str(r["id"]): float(r["score"]) for r in _one(demo_db, "SELECT id, score FROM scans WHERE org_id = %s",
                                                           (demo.DEMO_ORG_ID,))}
    assert {str(r["id"]): float(r["score"]) for r in rows} == stored
    findings = client.get("/api/v1/findings", headers=headers)
    assert findings.status_code == 200, findings.text
    body = findings.json()
    items = body.get("findings", body) if isinstance(body, dict) else body
    total = _one(demo_db, "SELECT count(*) AS n FROM findings WHERE org_id = %s", (demo.DEMO_ORG_ID,))[0]["n"]
    assert len(items) == total == len(demo.FINDINGS)


def test_an_issued_pack_contains_no_banned_claim_phrase(demo_db, outbox):
    _seed(demo_db)
    client, token = _sign_in(outbox)
    headers = _headers(token)
    pack_id = client.get("/api/v1/packs", headers=headers).json()
    items = pack_id.get("packs", pack_id) if isinstance(pack_id, dict) else pack_id
    html = client.get(f"/api/v1/packs/{items[0]['id']}/html", headers=headers).content.decode().lower()
    pdf = " ".join(render.pdf_extract_text(client.get(f"/api/v1/packs/{items[0]['id']}/pdf",
                                                      headers=headers).content).split()).lower()
    for phrase in BANNED:
        assert not re.search(r"\b" + re.escape(phrase) + r"\b", html), phrase
        assert not re.search(r"\b" + re.escape(phrase) + r"\b", pdf), phrase


def test_each_attestation_has_the_owner_and_an_expiry_date(demo_db):
    _seed(demo_db)
    rows = _one(demo_db, "SELECT question_key, owner_user_id, expires_at FROM compliance_attestations "
                         "WHERE org_id = %s AND superseded_by IS NULL", (demo.DEMO_ORG_ID,))
    assert len(rows) == len(demo.ATTESTATIONS)
    assert all(str(r["owner_user_id"]) == demo.DEMO_USER_ID for r in rows)
    assert all(r["expires_at"] is not None for r in rows), [r["question_key"] for r in rows if not r["expires_at"]]
