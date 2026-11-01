"""Notifications phase 1 against the isolated, migrated PostgreSQL database, as the real app role.

Rules (services/notifications.py): tenancy, dedupe, grouping, the daily info cap, preferences, critical-only email,
the 50-row page cap, idempotent mark read, and every phase 1 trigger driven through its real code path exactly once.
Grants: the migration takes back Supabase-style ALL grants and leaves the app role only what it needs.

Reuses the owner-views fixtures: a platform owner, a customer who owns "Views Org <tag>" (a verified domain and a
queued scan), plus the phase 1 extras (org B with its own owner, a plain member of org A). Mail is never sent: the
conftest `notification_mail` fixture records every notification email.
"""
import asyncio
import random
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

import backend.app.core.database as database
from backend.app.compliance import attestation_store, reminders
from backend.app.core import scan_execution as ex
from backend.app.core import scan_recovery, sessions
from backend.app.core.cron_claim import COMPLIANCE_REMINDERS_CRON_NAME
from backend.app.core.execution_fence import ClaimLost
from backend.app.core.scan_failures import CATEGORIES as FAILURE_SENTENCES
from backend.app.main import app
from backend.app.services import notification_messages as msg
from backend.app.services import notifications
from test_owner_phase1_postgres import OWNER, REASON, _admin, more  # noqa: F401 (fixture)
from test_owner_views_postgres import ORIGIN, _signed_in, urls, world  # noqa: F401 (fixtures)

RAW = "Traceback ConnectError [Errno 111] 10.9.8.7 NOTIF-RAW-WORKER-TEXT"
API = "/api/v1/notifications"
MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20261101200000_notifications_phase1.sql"


@pytest.fixture
def nw(world, more, urls, monkeypatch):
    """The two organisations, an admin of org A, and scan execution on the app-role connection."""
    monkeypatch.setattr(ex, "get_db", database.get_db)
    admin_id = str(uuid4())
    with _admin(urls) as conn:
        conn.execute("INSERT INTO profiles (id, email, full_name, role, provider, email_verified_at) "
                     "VALUES (%s,%s,'Ada Admin','Member','email',now())", (admin_id, f"adm-{world['tag']}@views.test"))
        conn.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s,%s,'admin')",
                     (admin_id, world["org"]))
    yield {**world, **more, "admin": admin_id}
    with _admin(urls) as conn:
        conn.execute("DELETE FROM notifications WHERE org_id IN (%s, %s)", (world["org"], more["org_b"]))
        conn.execute("DELETE FROM profiles WHERE id = %s", (admin_id,))


def _token(urls, uid):
    with _admin(urls) as conn:
        profile = conn.execute("SELECT * FROM profiles WHERE id = %s", (uid,)).fetchone()
    return sessions.issue_session(profile)["access_token"]


def _client(urls, uid, org):
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_token(urls, uid)}", "X-Organization-Id": org})
    return client


def _rows(urls, sql, params=()):
    with _admin(urls) as conn:
        return conn.execute(sql, params).fetchall()


def _mine(urls, uid, org, audience="customer"):
    return _rows(urls, "SELECT * FROM notifications WHERE user_id = %s AND org_id = %s AND audience = %s "
                       "ORDER BY created_at", (uid, org, audience))


def _members(nw):
    return {nw["customer"], nw["admin"], nw["member"]}


def _recipients(urls, org, kind, audience="customer"):
    return sorted(str(r["user_id"]) for r in _rows(
        urls, "SELECT user_id FROM notifications WHERE org_id = %s AND type = %s AND audience = %s", (org, kind, audience)))


def _day():
    return date(2050, 1, 1) + timedelta(days=random.randrange(30000))


@pytest.fixture
def run_day(urls, monkeypatch):
    """A fresh run day for the daily reminders job; its own reminder emails are recorded, never sent."""
    async def no_send(*a, **k):
        return {"success": True}

    monkeypatch.setattr(reminders.mailer, "send_email_async", no_send)
    days = []

    def make():
        days.append(_day())
        return days[-1]

    yield make
    with _admin(urls) as conn:
        for d in days:
            conn.execute("DELETE FROM cron_runs WHERE cron_name = %s AND run_day = %s", (COMPLIANCE_REMINDERS_CRON_NAME, d))


# ── Tenancy ────────────────────────────────────────────────────────────────
def test_a_person_sees_only_their_own_organisations_notifications(nw, urls):
    notifications.emit("scan_completed", nw["org"], key=f"t:{uuid4()}", params={"domain": "a.test"})
    notifications.emit("scan_completed", nw["org_b"], key=f"t:{uuid4()}", params={"domain": "b.test"})
    a = _client(urls, nw["customer"], nw["org"]).get(API).json()
    assert [n["title"] for n in a["notifications"]] == ["Scan finished for a.test"] and a["unread_count"] == 1
    b = _client(urls, nw["user_b"], nw["org_b"]).get(API).json()
    assert [n["title"] for n in b["notifications"]] == ["Scan finished for b.test"]
    # Naming another organisation is refused by the membership check; a row id from it is not found.
    assert _client(urls, nw["customer"], nw["org_b"]).get(API).status_code in (403, 404)
    a_id = a["notifications"][0]["id"]
    assert _client(urls, nw["user_b"], nw["org_b"]).patch(f"{API}/{a_id}/read").status_code == 404
    assert _mine(urls, nw["customer"], nw["org"])[0]["read_at"] is None
    # Rows are per person: the member's copy stays unread when the owner reads theirs.
    assert _client(urls, nw["customer"], nw["org"]).patch(f"{API}/{a_id}/read").status_code == 200
    assert _mine(urls, nw["member"], nw["org"])[0]["read_at"] is None
    assert _client(urls, nw["member"], nw["org"]).get(API).json()["unread_count"] == 1
    # Nothing internal leaves the API.
    for item in a["notifications"]:
        assert not {"user_id", "dedupe_key", "group_keys", "email_status", "audience", "in_app"} & set(item)


def test_rows_written_before_phase_1_are_kept_and_shown_with_reviewed_wording(nw, urls):
    with _admin(urls) as conn:
        conn.execute("INSERT INTO notifications (org_id, type, title, body, severity, link) "
                     "VALUES (%s, 'critical_finding', 'Critical finding: X', %s, 'high', '/findings')",
                     (nw["org"], RAW))
    for uid in (nw["customer"], nw["member"]):
        items = _client(urls, uid, nw["org"]).get(API).json()["notifications"]
        legacy = next(i for i in items if i["kind"] == "critical_finding")
        assert legacy["body"] == msg.LEGACY_REVIEWED_BODY["critical_finding"] and RAW not in str(items)
        assert legacy["severity"] == "warning" and legacy["category"] == "findings"
    assert _client(urls, nw["user_b"], nw["org_b"]).get(API).json()["notifications"] == []


# ── Dedupe, grouping, cap ──────────────────────────────────────────────────
def test_one_key_never_makes_two_rows_even_when_raced(nw, urls):
    key = f"race:{uuid4()}"
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: notifications.emit("scan_failed", nw["org"], key=key, params={"code": "timeout"}),
                      range(8)))
    notifications.emit("scan_failed", nw["org"], key=key, params={"code": "timeout"})
    rows = _rows(urls, "SELECT user_id, audience FROM notifications WHERE dedupe_key = %s", (key,))
    assert sorted(str(r["user_id"]) for r in rows if r["audience"] == "customer") == sorted(_members(nw))
    assert [str(r["user_id"]) for r in rows if r["audience"] == "owner"].count(nw["owner"]) == 1


def test_repeats_within_15_minutes_fold_into_one_row_with_a_count(nw, urls):
    keys = [f"asset:{uuid4()}" for _ in range(3)]
    for i, key in enumerate(keys):
        notifications.emit("asset_discovered", nw["org"], key=key, params={"hostname": f"h{i}.a.test", "domain": "a.test"})
    notifications.emit("asset_discovered", nw["org"], key=keys[1], params={"hostname": "h1.a.test"})  # a repeat
    rows = _mine(urls, nw["customer"], nw["org"])
    assert len(rows) == 1 and rows[0]["group_count"] == 3 and rows[0]["title"] == "3 new hosts found"
    assert set(rows[0]["group_keys"]) == set(keys[1:]) and rows[0]["dedupe_key"] == keys[0]
    listed = _client(urls, nw["customer"], nw["org"]).get(API).json()["notifications"]
    assert listed[0]["count"] == 3
    # Outside the window, a new row starts.
    with _admin(urls) as conn:
        conn.execute("UPDATE notifications SET last_event_at = now() - interval '16 minutes' WHERE org_id = %s",
                     (nw["org"],))
    notifications.emit("asset_discovered", nw["org"], key=f"asset:{uuid4()}", params={"hostname": "h9.a.test"})
    assert [r["group_count"] for r in _mine(urls, nw["customer"], nw["org"])] == [3, 1]


def test_info_is_capped_at_20_a_day_and_critical_is_never_dropped(nw, urls):
    for i in range(23):
        notifications.emit("asset_discovered", nw["org"], key=f"cap:{uuid4()}", params={"hostname": f"c{i}.a.test"})
        with _admin(urls) as conn:  # read at once, so nothing folds and each event wants its own row
            conn.execute("UPDATE notifications SET read_at = now() WHERE org_id = %s AND read_at IS NULL", (nw["org"],))
    info = [r for r in _mine(urls, nw["customer"], nw["org"]) if r["severity"] == "info"]
    assert len(info) == notifications.DAILY_INFO_CAP
    notifications.emit_finding(nw["org"], uuid4(), "critical", "a.test")
    notifications.emit_finding(nw["org"], uuid4(), "high", "a.test")
    severities = [r["severity"] for r in _mine(urls, nw["customer"], nw["org"])]
    assert severities.count("critical") == 1 and severities.count("warning") == 1


# ── Preferences and email ──────────────────────────────────────────────────
def test_muting_hides_in_app_and_stops_email_but_never_hides_critical_from_the_owner_console(
        nw, urls, notification_mail):
    customer = _client(urls, nw["customer"], nw["org"])
    assert customer.put(f"{API}/preferences/findings", json={"in_app": False}).json()["preference"] == {
        "category": "findings", "label": "Findings", "hint": msg.CATEGORY_HINTS["findings"], "in_app": False,
        "email": True}
    notifications.emit_finding(nw["org"], uuid4(), "critical", "a.test")
    assert customer.get(API).json()["notifications"] == []
    # Email is still on for this category: a hidden row carries the email.
    hidden = _mine(urls, nw["customer"], nw["org"])
    assert len(hidden) == 1 and hidden[0]["in_app"] is False and hidden[0]["email_status"] == "pending"
    asyncio.run(notifications.deliver_pending_emails())
    assert nw["customer_email"] in {m["to"] for m in notification_mail}
    # Mute email too: no row, no email. The owner console still has every critical event.
    customer.put(f"{API}/preferences/findings", json={"email": False})
    notification_mail.clear()
    notifications.emit_finding(nw["org"], uuid4(), "critical", "b.test")
    asyncio.run(notifications.deliver_pending_emails())
    assert len(_mine(urls, nw["customer"], nw["org"])) == 1
    assert nw["customer_email"] not in {m["to"] for m in notification_mail}
    owner = [n for n in _signed_in(nw).get(f"{OWNER}/notifications").json()["notifications"] if n["org_id"] == nw["org"]]
    assert {n["severity"] for n in owner} == {"critical"} and sum(n["count"] for n in owner) == 2
    # Other people's settings are their own.
    theirs = _client(urls, nw["member"], nw["org"]).get(API).json()
    # The first email to them had gone before the second event, so the second has its own row (and email).
    assert theirs["unread_count"] == 2 and [n["count"] for n in theirs["notifications"]] == [1, 1]
    got = customer.get(f"{API}/preferences").json()
    assert got["email_note"] == ("Email goes out for critical alerts, such as a critical finding or a suspension, and "
                                 "for compliance reminders. Everything else stays in the app.")
    prefs = {p["category"]: p for p in got["preferences"]}
    assert prefs["findings"]["in_app"] is False and prefs["findings"]["email"] is False and prefs["scans"]["in_app"]
    assert customer.put(f"{API}/preferences/nonsense", json={"email": False}).status_code == 404


def test_email_goes_only_for_critical_events(nw, urls, notification_mail):
    notifications.emit_finding(nw["org"], uuid4(), "high", "a.test")
    notifications.emit("scan_failed", nw["org"], key=f"t:{uuid4()}", params={"code": "blocked"})
    notifications.emit("scan_completed", nw["org"], key=f"t:{uuid4()}", params={"domain": "a.test"})
    assert {r["email_status"] for r in _rows(urls, "SELECT email_status FROM notifications WHERE org_id = %s",
                                             (nw["org"],))} == {None}
    asyncio.run(notifications.deliver_pending_emails())
    assert [m for m in notification_mail if nw["tag"] in m["to"]] == []
    notifications.emit_finding(nw["org"], uuid4(), "critical", "a.test")
    asyncio.run(notifications.deliver_pending_emails())
    mine = [m for m in notification_mail if nw["tag"] in m["to"]]
    assert {m["to"] for m in mine} == {nw["customer_email"], nw["member_email"], f"adm-{nw['tag']}@views.test"}
    for m in mine:
        assert m["unsubscribe"].endswith("/settings?tab=notifications&category=findings")
        assert "Critical finding on a.test" in m["subject"] and RAW not in m["html"] + m["text"]
        assert "Notification settings" in m["html"] and m["unsubscribe"] in m["text"]
    # At most once: a second delivery run sends nothing more.
    sent = len(notification_mail)
    asyncio.run(notifications.deliver_pending_emails())
    assert len(notification_mail) == sent
    assert {r["email_status"] for r in _rows(urls, "SELECT email_status FROM notifications WHERE org_id = %s "
                                             "AND severity = 'critical' AND audience = 'customer'", (nw["org"],))} == {"sent"}


# ── Limits and marking read ────────────────────────────────────────────────
def test_the_list_is_capped_at_50_a_page(nw, urls):
    with _admin(urls) as conn:
        for i in range(60):
            conn.execute("INSERT INTO notifications (org_id, user_id, type, category, severity, title, body, link, "
                         "dedupe_key, created_at) VALUES (%s, %s, 'scan_completed', 'scans', 'info', %s, 'b', '/scans', "
                         "%s, now() - make_interval(secs => %s))",
                         (nw["org"], nw["customer"], f"Row {i}", f"page:{uuid4()}", i))
    client = _client(urls, nw["customer"], nw["org"])
    first = client.get(API, params={"limit": 200}).json()
    assert len(first["notifications"]) == 50 and first["has_more"] is True and first["limit"] == 50
    assert first["notifications"][0]["title"] == "Row 0"  # newest first
    rest = client.get(API, params={"limit": 50, "offset": 50}).json()
    assert len(rest["notifications"]) == 10 and rest["has_more"] is False and first["unread_count"] == 60


def test_mark_read_and_mark_all_read_are_idempotent_and_owner_marks_are_audited(nw, urls):
    notifications.emit("org_unsuspended", nw["org"], key=f"t:{uuid4()}")
    client = _client(urls, nw["customer"], nw["org"])
    nid = client.get(API).json()["notifications"][0]["id"]
    first = client.patch(f"{API}/{nid}/read")
    second = client.patch(f"{API}/{nid}/read")
    assert first.status_code == second.status_code == 200
    assert first.json()["notification"]["read_at"] == second.json()["notification"]["read_at"] is not None
    assert client.patch(f"{API}/not-a-uuid/read").status_code == 404
    notifications.emit("scan_completed", nw["org"], key=f"t:{uuid4()}", params={"domain": "a.test"})
    assert client.post(f"{API}/read-all").json()["marked"] == 1
    assert client.post(f"{API}/read-all").json()["marked"] == 0 and client.get(API).json()["unread_count"] == 0

    owner = _signed_in(nw)
    owner_id = next(n["id"] for n in owner.get(f"{OWNER}/notifications").json()["notifications"]
                    if n["org_id"] == nw["org"])
    assert owner.post(f"{OWNER}/notifications/{owner_id}/read").status_code == 403  # console Origin required
    assert owner.post(f"{OWNER}/notifications/{owner_id}/read", headers=ORIGIN).status_code == 200
    assert owner.post(f"{OWNER}/notifications/{owner_id}/read", headers=ORIGIN).status_code == 200
    assert owner.post(f"{OWNER}/notifications/read-all", headers=ORIGIN).status_code == 200
    audit = _rows(urls, "SELECT action, target_id, metadata FROM owner_audit WHERE actor_user_id = %s "
                        "AND action LIKE 'owner.notifications.%%' ORDER BY created_at", (nw["owner"],))
    assert [(a["action"], a["metadata"].get("changed")) for a in audit] == [
        ("owner.notifications.read", True), ("owner.notifications.read", False), ("owner.notifications.read_all", None)]
    assert owner.get(f"{OWNER}/notifications/unread-count").json() == {"unread_count": 0}
    # A customer token never opens the owner list.
    assert TestClient(app).get(f"{OWNER}/notifications", headers=dict(client.headers)).status_code == 401


# ── Every trigger, through its real code path, exactly once ────────────────
def _claim(nw):
    return ex.claim_from_row(ex.claim_recon(f"notif-{nw['tag']}", "worker", 120, nw["scan"]))


def test_trigger_scan_failed_from_fail_claim(nw, urls):
    claim = _claim(nw)
    ex.fail_claim(claim, RAW)
    with pytest.raises(ClaimLost):
        ex.fail_claim(claim, RAW)  # a replay of the same worker call
    assert _recipients(urls, nw["org"], "scan_failed") == sorted(_members(nw))
    assert nw["owner"] in _recipients(urls, nw["org"], "scan_failed", "owner")
    for row in _mine(urls, nw["customer"], nw["org"]):
        assert row["body"] == FAILURE_SENTENCES["unreachable"] and RAW not in row["title"] + row["body"]
        assert row["title"] == f"Scan did not finish for views-{nw['tag']}.test"


def test_trigger_scan_completed_from_finish_assessment(nw, urls):
    core = ex.handoff_to_core(_claim(nw))
    finish = lambda: ex.finish_assessment(  # noqa: E731
        core, nw["org"], {"score": 81, "subscores": [], "factors": [], "risk_points": 1},
        {"scoring": {"status": "completed"}}, {"score": 81},
        {"model": "test-v2", "scope": "organization", "params": {"score": 81, "grade": "B", "new": 2, "resolved": 1}})
    finish()
    with pytest.raises(ClaimLost):
        finish()
    assert _recipients(urls, nw["org"], "scan_completed") == sorted(_members(nw))
    assert _recipients(urls, nw["org"], "scan_completed", "owner") == []  # not owner-relevant
    row = _mine(urls, nw["customer"], nw["org"])[0]
    assert row["body"].startswith("Score 81/100, grade B") and row["title"] == f"Scan finished for views-{nw['tag']}.test"


def test_trigger_scan_failed_from_interrupted_scan_recovery(nw, urls, monkeypatch):
    monkeypatch.setattr(scan_recovery, "SCANNER_MODE", "local")
    with _admin(urls) as conn:
        conn.execute("UPDATE scans SET status = 'running', claimed_by = NULL, claim_token = NULL, execution_phase = NULL "
                     "WHERE id = %s", (nw["scan"],))
    assert scan_recovery.recover_interrupted_scans() >= 1
    scan_recovery.recover_interrupted_scans()  # nothing left to recover; no second notice
    assert _recipients(urls, nw["org"], "scan_failed") == sorted(_members(nw))
    assert _mine(urls, nw["customer"], nw["org"])[0]["body"] == FAILURE_SENTENCES["interrupted"]


def test_trigger_finding_critical_from_the_scan_pipeline(nw, urls, monkeypatch, notification_mail):
    from backend.app.workflows import inngest_workflow as wf
    from test_scan_execution_postgres import no_external
    host = f"views-{nw['tag']}.test"

    async def one_critical(hostname, dns_item, http_item, is_apex=True):
        return [{"title": "Missing Email DMARC Authentication Policy", "severity": "critical",
                 "category": "DNS & Email Security", "description": RAW, "remediation": RAW,
                 "evidence": {"dns_query": f"_dmarc.{hostname}", "record_type": "TXT"}}]

    no_external(monkeypatch)
    monkeypatch.setattr(wf, "run_security_checks", one_critical)
    for attempt in range(2):  # the second scan sees the same, still-open finding: no new notice
        sid = nw["scan"] if attempt == 0 else str(uuid4())
        if attempt:
            with _admin(urls) as conn:
                conn.execute("INSERT INTO scans (id, org_id, domain_id, status, scan_type) "
                             "VALUES (%s,%s,%s,'queued','EXTERNAL_ASSESSMENT')", (sid, nw["org"], nw["domain"]))
        worker = ex.claim_from_row(ex.claim_recon("w", "worker", 120, sid))
        ex.store_observation(worker, "discovery", {"discovered_hosts": [host]})
        ex.store_observation(worker, "dns", {"dns_records": [{"hostname": host, "primary_ip": "93.184.216.34",
                                                              "records": {}}]})
        ex.store_observation(worker, "http", {"http_probes": [{"hostname": host, "http_status": 200, "tls_info": {}}]})
        core = ex.handoff_to_core(worker)
        assert asyncio.run(wf.finalize_scan(core.scan_id, core))["status"] == "completed"
    assert _recipients(urls, nw["org"], "finding_critical") == sorted(_members(nw))
    assert nw["owner"] in _recipients(urls, nw["org"], "finding_critical", "owner")
    row = next(r for r in _mine(urls, nw["customer"], nw["org"]) if r["type"] == "finding_critical")
    assert row["title"] == f"Critical finding on {host}" and RAW not in row["body"]
    # The email waited for the scan; finalize_scan sent it once the scan had completed, once per member.
    assert row["email_scan_id"] is not None and row["email_status"] == "sent"
    sent = [m["to"] for m in notification_mail if nw["tag"] in m["to"]]
    assert sorted(sent) == sorted({nw["customer_email"], nw["member_email"], f"adm-{nw['tag']}@views.test"})


def test_trigger_finding_rating_raised_and_reopened_use_their_own_keys(nw, urls):
    finding = uuid4()
    notifications.emit_finding(nw["org"], finding, "high", "a.test")
    notifications.emit_finding(nw["org"], finding, "high", "a.test")
    notifications.emit_finding(nw["org"], finding, "critical", "a.test")  # became critical
    notifications.emit_finding(nw["org"], finding, "critical", "a.test", scan_id=str(uuid4()), reopened=True)
    assert notifications.emit_finding(nw["org"], finding, "medium", "a.test") == 0
    rows = _mine(urls, nw["customer"], nw["org"])
    assert [r["type"] for r in rows].count("finding_high") == 1
    # The raised rating and the reopening are two events; the reopening's email waits on its own scan, so it does
    # not fold into the row whose email is free to go now.
    assert sorted(r["group_count"] for r in rows if r["type"] == "finding_critical") == [1, 1]


def test_trigger_member_invited_and_joined(nw, urls, monkeypatch):
    from backend.app.api import members as members_mod
    links = []

    async def fake_send(to, subject, html, text=None, recipient_name=None, **_):
        links.extend(re.findall(r"invite=([A-Za-z0-9_\-]+)", text or ""))
        return {"success": True}

    monkeypatch.setattr(members_mod, "send_email_async", fake_send)
    invitee = f"new-{nw['tag']}@notif-views.example.com"
    owner_client = _client(urls, nw["customer"], nw["org"])
    assert owner_client.post("/api/v1/members/invite", json={"email": invitee, "full_name": "New Person",
                                                             "role": "member"}).status_code == 201
    assert _recipients(urls, nw["org"], "member_invited") == [nw["admin"]]  # owners and admins, not the inviter
    assert _mine(urls, nw["admin"], nw["org"])[0]["title"] == f"{invitee} was invited"
    new_id = str(uuid4())
    with _admin(urls) as conn:
        conn.execute("INSERT INTO profiles (id, email, full_name, role, provider, email_verified_at) "
                     "VALUES (%s,%s,'New Person','Member','email',now())", (new_id, invitee))
    try:
        joiner = _client(urls, new_id, nw["org"])
        assert joiner.post("/api/v1/members/invites/accept", json={"token": links[0]}).status_code == 200
        assert joiner.post("/api/v1/members/invites/accept", json={"token": links[0]}).status_code == 409
        assert _recipients(urls, nw["org"], "member_joined") == sorted([nw["customer"], nw["admin"]])
    finally:
        with _admin(urls) as conn:
            conn.execute("DELETE FROM profiles WHERE id = %s", (new_id,))


def test_trigger_member_removed_from_the_owner_console(nw, urls):
    owner = _signed_in(nw)
    url = f"{OWNER}/organizations/{nw['org']}/members/{nw['member']}/remove"
    body = {"reason": REASON, "confirm_name": nw["org_name"]}
    assert owner.post(url, json=body, headers=ORIGIN).status_code == 200
    assert owner.post(url, json=body, headers=ORIGIN).status_code == 404
    assert _recipients(urls, nw["org"], "member_removed") == sorted([nw["customer"], nw["admin"]])
    assert _mine(urls, nw["admin"], nw["org"])[0]["title"] == f"{nw['member_email']} was removed"


def test_trigger_suspension_and_unsuspension_with_the_critical_email(nw, urls, notification_mail):
    owner = _signed_in(nw)
    body = {"reason": REASON, "confirm_name": nw["org_name"]}
    org = f"{OWNER}/organizations/{nw['org']}"
    assert owner.post(f"{org}/suspend", json=body, headers=ORIGIN).status_code == 200
    assert owner.post(f"{org}/suspend", json=body, headers=ORIGIN).status_code == 409
    assert _recipients(urls, nw["org"], "org_suspended") == sorted(_members(nw))
    assert nw["owner"] in _recipients(urls, nw["org"], "org_suspended", "owner")
    # The background task after the response sent the critical email to every member.
    assert {m["to"] for m in notification_mail if nw["tag"] in m["to"]} == {
        nw["customer_email"], nw["member_email"], f"adm-{nw['tag']}@views.test"}
    assert owner.post(f"{org}/unsuspend", json=body, headers=ORIGIN).status_code == 200
    assert owner.post(f"{org}/unsuspend", json=body, headers=ORIGIN).status_code == 409
    assert _recipients(urls, nw["org"], "org_unsuspended") == sorted(_members(nw))
    # Reading still works while suspended: the bell is not a gated write.
    assert owner.post(f"{org}/suspend", json=body, headers=ORIGIN).status_code == 200
    client = _client(urls, nw["customer"], nw["org"])
    assert client.post(f"{API}/read-all").status_code == 200
    assert owner.post(f"{org}/unsuspend", json=body, headers=ORIGIN).status_code == 200


def test_trigger_trial_ending_7_days_and_1_day_before(nw, urls, run_day):
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=5)
    with _admin(urls) as conn:
        conn.execute("INSERT INTO subscriptions (org_id, plan, status, current_period_end, trial_ends_at) "
                     "VALUES (%s, 'growth', 'trialing', %s, %s)", (nw["org"], end, end))
    asyncio.run(reminders.run_compliance_reminders(now=now, run_day=run_day()))
    asyncio.run(reminders.run_compliance_reminders(now=now + timedelta(hours=1), run_day=run_day()))
    assert _recipients(urls, nw["org"], "trial_ending_soon") == [nw["customer"]]  # owners only
    assert nw["owner"] in _recipients(urls, nw["org"], "trial_ending_soon", "owner")
    assert _recipients(urls, nw["org"], "trial_ending_tomorrow") == []
    later = end - timedelta(hours=12)
    asyncio.run(reminders.run_compliance_reminders(now=later, run_day=run_day()))
    asyncio.run(reminders.run_compliance_reminders(now=later + timedelta(hours=1), run_day=run_day()))
    assert _recipients(urls, nw["org"], "trial_ending_tomorrow") == [nw["customer"]]
    assert _recipients(urls, nw["org"], "trial_ending_soon") == [nw["customer"]]


def test_trigger_attestation_expiring_within_30_days(nw, urls, run_day, monkeypatch):
    async def no_mail(*a, **k):
        return {"success": True}

    monkeypatch.setattr(reminders.mailer, "send_email_async", no_mail)
    now = datetime.now(timezone.utc)
    attestation_store.record({"id": nw["org"]}, nw["customer"], question_key="breach.response_plan",
                             answer={"value": "yes"}, owner_user_id=nw["member"],
                             expires_at=now + timedelta(days=20), now=now - timedelta(minutes=1))
    asyncio.run(reminders.run_compliance_reminders(now=now, run_day=run_day()))
    asyncio.run(reminders.run_compliance_reminders(now=now + timedelta(hours=2), run_day=run_day()))
    # The answer's owner (a plain member) plus the organisation's owners and admins, once each.
    assert _recipients(urls, nw["org"], "attestation_expiring_30") == sorted(_members(nw))
    row = _mine(urls, nw["member"], nw["org"])[0]
    assert row["title"].startswith("Renewal due in 30 days: ") and row["link"] == "/comply"


def test_reminder_emails_respect_an_email_mute(nw, urls, run_day, monkeypatch):
    sent = []

    async def record(to, *a, **k):
        sent.append(to)
        return {"success": True}

    monkeypatch.setattr(reminders.mailer, "send_email_async", record)
    _client(urls, nw["admin"], nw["org"]).put(f"{API}/preferences/compliance", json={"email": False})
    now = datetime.now(timezone.utc)
    attestation_store.record({"id": nw["org"]}, nw["customer"], question_key="breach.incident_log",
                             answer={"value": "yes"}, owner_user_id=nw["customer"],
                             expires_at=now + timedelta(days=5), now=now - timedelta(minutes=1))
    asyncio.run(reminders.run_compliance_reminders(now=now, run_day=run_day()))
    assert nw["customer_email"] in sent and f"adm-{nw['tag']}@views.test" not in sent


# ── The migration's grants ─────────────────────────────────────────────────
TABLES = ("notifications", "notification_preferences")
EXPECTED_TABLE_PRIVILEGES = {
    ("cyphward_app", "notifications", "SELECT"), ("cyphward_app", "notifications", "INSERT"),
    ("cyphward_app", "notification_preferences", "SELECT"), ("cyphward_app", "notification_preferences", "INSERT"),
}
EXPECTED_UPDATE_COLUMNS = {
    ("notifications", c) for c in ("read_at", "title", "body", "group_keys", "group_count", "last_event_at",
                                   "email_status", "email_attempted_at", "email_sent")
} | {("notification_preferences", c) for c in ("in_app_muted", "email_muted", "updated_at")}


@pytest.fixture
def admin(urls):
    conn = psycopg.connect(urls[1], row_factory=psycopg.rows.dict_row, autocommit=True)
    try:
        yield conn
    finally:
        conn.execute(MIGRATION.read_text())  # always leave the real grants in place
        conn.close()


def _supabase_defaults(admin):
    """What Supabase's default privileges hand out, plus an over-broad app grant to take back."""
    for table in TABLES:
        for role in ("PUBLIC", "anon", "authenticated", "cyphward_app"):
            admin.execute(f"GRANT ALL ON {table} TO {role}")


def _grant_problems(admin):
    """Every privilege that differs from the intended list, read from the catalogue as the administrator."""
    skip = {"postgres", "service_role", "supabase_admin"}
    rows = admin.execute(
        "SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END AS grantee, "
        "c.relname, a.privilege_type FROM pg_class c, aclexplode(c.relacl) a "
        "WHERE c.relname = ANY(%s) AND c.relnamespace = 'public'::regnamespace", (list(TABLES),)).fetchall()
    actual = {(r["grantee"], r["relname"], r["privilege_type"]) for r in rows if r["grantee"] not in skip}
    problems = [f"extra {p}" for p in sorted(actual - EXPECTED_TABLE_PRIVILEGES)]
    problems += [f"missing {p}" for p in sorted(EXPECTED_TABLE_PRIVILEGES - actual)]
    cols = admin.execute(
        "SELECT c.relname, a.attname, CASE WHEN x.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(x.grantee) END "
        "AS grantee, x.privilege_type FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid, aclexplode(a.attacl) x "
        "WHERE c.relname = ANY(%s) AND c.relnamespace = 'public'::regnamespace", (list(TABLES),)).fetchall()
    col_actual = {(r["grantee"], r["relname"], r["attname"], r["privilege_type"]) for r in cols if r["grantee"] not in skip}
    col_expected = {("cyphward_app", t, c, "UPDATE") for t, c in EXPECTED_UPDATE_COLUMNS}
    problems += [f"extra column {p}" for p in sorted(col_actual - col_expected)]
    problems += [f"missing column {p}" for p in sorted(col_expected - col_actual)]
    rls = admin.execute("SELECT relname FROM pg_class WHERE relname = ANY(%s) AND NOT relrowsecurity", (list(TABLES),))
    problems += [f"RLS off on {r['relname']}" for r in rls.fetchall()]
    return problems


def test_migration_takes_back_supabase_default_grants(admin):
    _supabase_defaults(admin)
    assert _grant_problems(admin), "the setup must start from over-broad grants"
    admin.execute(MIGRATION.read_text())
    assert _grant_problems(admin) == []
    for role in ("anon", "authenticated"):
        for table in TABLES:
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                assert not admin.execute("SELECT has_table_privilege(%s, %s, %s) AS g",
                                         (role, table, privilege)).fetchone()["g"], (role, table, privilege)
    for table in TABLES:
        assert not admin.execute("SELECT has_table_privilege('cyphward_app', %s, 'DELETE') AS g",
                                 (table,)).fetchone()["g"]


REVOKE_LINES = [line for line in MIGRATION.read_text().splitlines()
                if "REVOKE ALL" in line and not line.lstrip().startswith("--")]


@pytest.mark.parametrize("line", REVOKE_LINES)
def test_removing_any_revoke_fails_the_grant_check(admin, line):
    assert len(REVOKE_LINES) == 6
    mutated = MIGRATION.read_text().replace(line + "\n", "", 1)
    assert mutated != MIGRATION.read_text()
    _supabase_defaults(admin)
    admin.execute(mutated)
    assert _grant_problems(admin), f"removing this line went unnoticed: {line.strip()}"


def test_the_migration_is_additive_idempotent_and_bounded(admin):
    sql = MIGRATION.read_text()
    code = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--")).upper()
    assert "DROP TABLE" not in code and "DROP COLUMN" not in code and "TRUNCATE" not in code
    assert "SET LOCAL lock_timeout = '5s';" in sql and "SET LOCAL statement_timeout = '60s';" in sql
    admin.execute(sql)
    admin.execute(sql)
    assert _grant_problems(admin) == []
    checks = admin.execute("SELECT count(*) AS n FROM pg_constraint WHERE conrelid = 'notifications'::regclass "
                           "AND conname = 'notifications_severity_phase1'").fetchone()["n"]
    assert checks == 1


def test_the_app_role_never_deletes_notifications_or_preferences(nw, urls):
    with psycopg.connect(urls[0]) as conn:
        for table in TABLES:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"DELETE FROM {table} WHERE false")
            conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE notifications SET org_id = org_id WHERE false")


def test_trigger_plan_period_ending_7_days_and_1_day_before(nw, urls, run_day):
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=5)
    with _admin(urls) as conn:
        conn.execute("INSERT INTO subscriptions (org_id, plan, status, current_period_end) "
                     "VALUES (%s, 'growth', 'active', %s)", (nw["org"], end))
    asyncio.run(reminders.run_compliance_reminders(now=now, run_day=run_day()))
    asyncio.run(reminders.run_compliance_reminders(now=now + timedelta(hours=1), run_day=run_day()))
    assert _recipients(urls, nw["org"], "subscription_ending_soon") == [nw["customer"]]
    assert nw["owner"] in _recipients(urls, nw["org"], "subscription_ending_soon", "owner")
    later = end - timedelta(hours=12)
    asyncio.run(reminders.run_compliance_reminders(now=later, run_day=run_day()))
    asyncio.run(reminders.run_compliance_reminders(now=later + timedelta(hours=1), run_day=run_day()))
    assert _recipients(urls, nw["org"], "subscription_ending_tomorrow") == [nw["customer"]]
    assert _recipients(urls, nw["org"], "trial_ending_soon") == []
    body = next(r["body"] for r in _mine(urls, nw["customer"], nw["org"]) if r["type"] == "subscription_ending_soon")
    assert "Contact Cyphward through the Contact page to renew" in body


def test_the_owner_bell_poll_does_not_keep_an_idle_session_alive(nw, urls):
    owner = _signed_in(nw)
    with _admin(urls) as conn:
        conn.execute("UPDATE owner_sessions SET last_seen_at = now() - interval '10 minutes' WHERE user_id = %s",
                     (nw["owner"],))
        before = conn.execute("SELECT last_seen_at FROM owner_sessions WHERE user_id = %s AND revoked_at IS NULL",
                              (nw["owner"],)).fetchone()["last_seen_at"]
    assert owner.get(f"{OWNER}/notifications/unread-count").status_code == 200
    with _admin(urls) as conn:
        after = conn.execute("SELECT last_seen_at FROM owner_sessions WHERE user_id = %s AND revoked_at IS NULL",
                             (nw["owner"],)).fetchone()["last_seen_at"]
        assert after == before, "the poll is not activity"
        conn.execute("UPDATE owner_sessions SET last_seen_at = now() - interval '31 minutes' WHERE user_id = %s",
                     (nw["owner"],))
    assert owner.get(f"{OWNER}/notifications/unread-count").status_code == 401  # idle: signed out
    assert owner.get(f"{OWNER}/notifications").status_code == 401


def test_the_shared_demo_account_cannot_change_notification_settings(nw, urls):
    from backend.app.core.demo_org import DEMO_USER_ID
    client = TestClient(app)
    from backend.app.api.demo_login import refuse_demo_account
    app.dependency_overrides[refuse_demo_account] = lambda: (_ for _ in ()).throw(
        __import__("fastapi").HTTPException(status_code=403, detail="This change is not available on the sample account."))
    try:
        client.headers.update({"Authorization": f"Bearer {_token(urls, nw['customer'])}"})
        assert client.put(f"{API}/preferences/scans", json={"email": False}).status_code == 403
    finally:
        app.dependency_overrides.pop(refuse_demo_account, None)
    assert DEMO_USER_ID  # the guard keys on this account and on demo sessions (api/demo_login.py)


# ── Review round 2: an email per critical event, scan-held email, owner scope, caps, the lock ──
def test_a_second_critical_event_after_the_email_went_gets_its_own_row_and_email(nw, urls, notification_mail):
    notifications.emit_finding(nw["org"], uuid4(), "critical", "a.test")
    notifications.emit_finding(nw["org"], uuid4(), "critical", "b.test")  # before delivery: folds, one email
    asyncio.run(notifications.deliver_pending_emails())

    def mine():
        return [m for m in notification_mail if m["to"] == nw["customer_email"]]

    assert len(mine()) == 1 and "2 critical findings recorded" in mine()[0]["subject"]
    notifications.emit_finding(nw["org"], uuid4(), "critical", "c.test")  # within 15 minutes, after the email
    asyncio.run(notifications.deliver_pending_emails())
    rows = [r for r in _mine(urls, nw["customer"], nw["org"]) if r["severity"] == "critical"]
    assert [r["group_count"] for r in rows] == [2, 1] and [r["email_status"] for r in rows] == ["sent", "sent"]
    assert len(mine()) == 2 and "Critical finding on c.test" in mine()[1]["subject"]


def _end_scan(nw, urls, claim, state):
    if state == "failed":
        ex.fail_claim(claim, RAW)
    elif state == "cancelled":  # the owner console's or the customer's cancel: the row ends cancelled
        with _admin(urls) as conn:
            conn.execute("UPDATE scans SET status = 'cancelled', claimed_by = NULL, claim_token = NULL, "
                         "execution_phase = NULL, lease_expires_at = NULL WHERE id = %s", (nw["scan"],))
    else:  # removed altogether
        with _admin(urls) as conn:
            conn.execute("DELETE FROM scans WHERE id = %s", (nw["scan"],))


@pytest.mark.parametrize("state", ["failed", "cancelled", "deleted"])
def test_a_critical_finding_email_waits_for_its_scan_and_is_skipped_if_the_scan_does_not_complete(
        nw, urls, notification_mail, state):
    claim = _claim(nw)  # the world's scan, now running
    notifications.emit_finding(nw["org"], uuid4(), "critical", "a.test", scan_id=nw["scan"])
    asyncio.run(notifications.deliver_pending_emails())
    assert [m for m in notification_mail if nw["tag"] in m["to"]] == [], "nothing goes out while the scan runs"
    _end_scan(nw, urls, claim, state)
    result = asyncio.run(notifications.deliver_pending_emails())
    assert result["scan_not_completed"] >= 3 and [m for m in notification_mail if nw["tag"] in m["to"]] == []
    rows = [r for r in _mine(urls, nw["customer"], nw["org"]) if r["type"] == "finding_critical"]
    assert [r["email_status"] for r in rows] == ["skipped"], "the in-app notice stays; the email never goes"


def test_a_critical_finding_email_goes_once_its_scan_has_completed(nw, urls, notification_mail):
    core = ex.handoff_to_core(_claim(nw))
    notifications.emit_finding(nw["org"], uuid4(), "critical", "a.test", scan_id=nw["scan"])
    asyncio.run(notifications.deliver_pending_emails())
    assert [m for m in notification_mail if nw["tag"] in m["to"]] == []
    ex.finish_assessment(core, nw["org"], {"score": 50, "subscores": [], "factors": [], "risk_points": 1},
                         {"scoring": {"status": "completed"}}, {"score": 50}, {"model": "test-v2", "scope": "organization"})
    asyncio.run(notifications.deliver_pending_emails())
    assert {m["to"] for m in notification_mail if nw["tag"] in m["to"]} == {
        nw["customer_email"], nw["member_email"], f"adm-{nw['tag']}@views.test"}


def test_the_per_recipient_lock_folds_a_burst_of_distinct_events_into_one_row(nw, urls):
    keys = [f"burst:{uuid4()}" for _ in range(8)]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda k: notifications.emit("asset_discovered", nw["org"], key=k,
                                                   params={"hostname": "h.a.test"}), keys))
    for uid in _members(nw):
        rows = _mine(urls, uid, nw["org"])
        assert len(rows) == 1 and rows[0]["group_count"] == 8, (uid, [(r["dedupe_key"], r["group_count"]) for r in rows])
        assert sorted([rows[0]["dedupe_key"], *rows[0]["group_keys"]]) == sorted(keys)


@pytest.fixture
def second_owner(nw, urls):
    uid = str(uuid4())
    with _admin(urls) as conn:
        conn.execute("INSERT INTO profiles (id, email, full_name, role, provider, email_verified_at) "
                     "VALUES (%s,%s,'Second Owner','Member','email',now())", (uid, f"owner2-{nw['tag']}@views.test"))
        conn.execute("INSERT INTO platform_owners (user_id, note) VALUES (%s, 'second test owner')", (uid,))
    yield uid
    with _admin(urls) as conn:
        conn.execute("DELETE FROM profiles WHERE id = %s", (uid,))


def test_an_owner_sees_and_marks_only_their_own_owner_rows(nw, urls, second_owner):
    notifications.emit("org_unsuspended", nw["org"], key=f"t:{uuid4()}")
    other = _rows(urls, "SELECT id FROM notifications WHERE audience = 'owner' AND user_id = %s AND org_id = %s",
                  (second_owner, nw["org"]))
    assert len(other) == 1
    owner = _signed_in(nw)
    listed = owner.get(f"{OWNER}/notifications").json()["notifications"]
    assert str(other[0]["id"]) not in {n["id"] for n in listed} and any(n["org_id"] == nw["org"] for n in listed)
    assert owner.post(f"{OWNER}/notifications/{other[0]['id']}/read", headers=ORIGIN).status_code == 404
    owner.post(f"{OWNER}/notifications/read-all", headers=ORIGIN)
    assert _rows(urls, "SELECT read_at FROM notifications WHERE id = %s", (other[0]["id"],))[0]["read_at"] is None


def test_owner_rows_ignore_preferences_even_for_an_owner_who_is_also_a_muted_customer(nw, urls):
    with _admin(urls) as conn:
        conn.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s,%s,'member')",
                     (nw["owner"], nw["org"]))
    as_customer = _client(urls, nw["owner"], nw["org"])
    for category in ("findings", "organisation"):
        assert as_customer.put(f"{API}/preferences/{category}", json={"in_app": False, "email": False}).status_code == 200
    notifications.emit_finding(nw["org"], uuid4(), "critical", "a.test")
    notifications.emit("org_suspended", nw["org"], key=f"t:{uuid4()}")
    assert _mine(urls, nw["owner"], nw["org"], "customer") == [], "their customer copy follows their mutes"
    owner_rows = _mine(urls, nw["owner"], nw["org"], "owner")
    assert sorted(r["type"] for r in owner_rows) == ["finding_critical", "org_suspended"]
    assert {r["email_status"] for r in owner_rows} == {None}


def test_the_customer_list_never_shows_owner_rows_to_an_owner_who_is_also_a_member(nw, urls):
    with _admin(urls) as conn:
        conn.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s,%s,'member')",
                     (nw["owner"], nw["org"]))
    notifications.emit("scan_failed", nw["org"], key=f"t:{uuid4()}", params={"code": "blocked"})
    assert len(_mine(urls, nw["owner"], nw["org"], "owner")) == 1
    as_customer = _client(urls, nw["owner"], nw["org"])
    listed = as_customer.get(API).json()
    assert len(listed["notifications"]) == 1 and listed["unread_count"] == 1
    assert not listed["notifications"][0]["title"].startswith(nw["org_name"]), "the customer copy, not the owner copy"
    owner_row = _mine(urls, nw["owner"], nw["org"], "owner")[0]["id"]
    assert as_customer.patch(f"{API}/{owner_row}/read").status_code == 404


def test_owner_console_rows_are_not_capped_but_customer_info_rows_are(nw, urls):
    for _ in range(23):
        notifications.emit("org_unsuspended", nw["org"], key=f"cap2:{uuid4()}")
        with _admin(urls) as conn:  # read at once, so nothing folds
            conn.execute("UPDATE notifications SET read_at = now() WHERE org_id = %s AND read_at IS NULL", (nw["org"],))
    assert len(_mine(urls, nw["owner"], nw["org"], "owner")) == 23
    assert len(_mine(urls, nw["customer"], nw["org"])) == notifications.DAILY_INFO_CAP


def test_trigger_six_monthly_report_due(nw, urls, run_day):
    from backend.app.compliance.reminders import dpo_period
    now = datetime.now(timezone.utc)
    asyncio.run(reminders.run_compliance_reminders(now=now, run_day=run_day()))
    asyncio.run(reminders.run_compliance_reminders(now=now + timedelta(hours=3), run_day=run_day()))
    # Owners and admins of a Growth organisation with a verified domain, once per half-year.
    assert _recipients(urls, nw["org"], "compliance_report_due") == sorted([nw["customer"], nw["admin"]])
    row = _mine(urls, nw["admin"], nw["org"])[0]
    assert row["dedupe_key"] == f"dpo_report:{nw['org']}:{dpo_period(now)['key']}" and row["link"] == "/comply"


def test_reapplying_over_the_first_draft_widens_the_email_state_check(admin):
    """If the first draft of this file (email states without 'skipped') had been applied, applying this one fixes it."""
    admin.execute("ALTER TABLE notifications DROP CONSTRAINT notifications_email_status_check")
    admin.execute("ALTER TABLE notifications ADD CONSTRAINT notifications_email_status_check CHECK "
                  "(email_status IS NULL OR email_status IN ('pending', 'sending', 'sent', 'failed')) NOT VALID")
    admin.execute(MIGRATION.read_text())
    definition = admin.execute("SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint "
                               "WHERE conname = 'notifications_email_status_check'").fetchone()["d"]
    assert "skipped" in definition
    assert _grant_problems(admin) == []


def test_a_soft_deleted_organisation_notifies_and_emails_no_member(nw, urls, notification_mail):
    """Main's rule (core/org_guard.py): a deleted organisation emails nobody. The owner console still records it."""
    notifications.emit_finding(nw["org"], uuid4(), "critical", "a.test")  # pending email written before the delete
    with _admin(urls) as conn:
        conn.execute("INSERT INTO organization_suspensions (org_id, status, changed_at, changed_by, deleted_at) "
                     "VALUES (%s, 'deleted', now(), %s, now()) ON CONFLICT (org_id) DO UPDATE SET status = 'deleted', "
                     "deleted_at = now()", (nw["org"], nw["owner"]))
    notifications.emit_finding(nw["org"], uuid4(), "critical", "b.test")
    notifications.emit("scan_completed", nw["org"], key=f"t:{uuid4()}", params={"domain": "a.test"})
    asyncio.run(notifications.deliver_pending_emails())
    assert [m for m in notification_mail if nw["tag"] in m["to"]] == [], "no email after the delete"
    customer_rows = _rows(urls, "SELECT type, email_status FROM notifications WHERE org_id = %s AND audience = 'customer'",
                          (nw["org"],))
    assert {(r["type"], r["email_status"]) for r in customer_rows} == {("finding_critical", "failed")}, \
        "only the rows written before the delete, and their email was not sent"
    assert len(_mine(urls, nw["owner"], nw["org"], "owner")) >= 1
