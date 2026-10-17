"""Breach incidents and expiry reminders against the real, migrated test database (packet C3b, sections 4-6, 8).

Runs only against the owned loopback `cyphward_test` database through the restricted `cyphward_app` role.
Covers: no DELETE and column-limited UPDATE grants; cross-tenant rejection; members cannot write; every write
audited without notes text; times stored in UTC and shown in the organisation's zone; reminder thresholds,
dedupe across retries, and a stale cron claim that cannot write or send (emails stubbed).
"""
import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from backend.app.compliance import incidents as inc
from backend.app.compliance import reminders
from backend.app.core import cron_claim
from backend.app.core.cron_claim import COMPLIANCE_REMINDERS_CRON_NAME
from backend.app.core.execution_fence import ClaimLost
from backend.app.compliance import attestation_store as store
from backend.tests.test_compliance_attestations_postgres import _record, world  # noqa: F401 (fixture)
from backend.tests.test_scan_admission_postgres import disposable_postgres_url  # noqa: F401 (fixture)

UTC = timezone.utc
NOTES = "Customer list exported by mistake - jane.doe@example.com"
BASE = {"title": "Laptop lost", "severity": "high", "detected_at": "2026-10-15T09:00:00+00:00",
        "became_aware_at": "2026-10-15T10:00:00+00:00"}


@pytest.fixture
def team(world):  # noqa: F811
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    admin = world.make_person(org_id, "admin")
    member = world.make_person(org_id, "member")
    return org_id, owner, admin, member


def _post(world, org_id, uid, **extra):
    return world.client.post("/api/v1/compliance/incidents", json={**BASE, **extra}, headers=world.headers(uid, org_id))


def _audit(world, org_id, action):
    return world.rows("SELECT user_id, resource_id, metadata FROM audit_log WHERE org_id = %s AND action = %s "
                      "ORDER BY created_at", (org_id, action))


def _app(world):
    return psycopg.connect(world.url, autocommit=True)


# ── Grants and the schema ────────────────────────────────────────────────


def test_incidents_can_never_be_deleted_by_the_app_role(world, team):
    org_id, owner, *_ = team
    created = _post(world, org_id, owner).json()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _app(world).execute("DELETE FROM compliance_incidents WHERE id = %s", (created["id"],))
    assert len(world.rows("SELECT 1 FROM compliance_incidents WHERE id = %s", (created["id"],))) == 1


def test_only_the_narrow_columns_of_an_incident_can_change(world, team):
    org_id, owner, *_ = team
    created = _post(world, org_id, owner).json()
    conn = _app(world)
    for column, value in (("title", "'x'"), ("became_aware_at", "now()"), ("detected_at", "now()"),
                          ("org_id", f"'{uuid4()}'"), ("created_by", "NULL"), ("created_at", "now()")):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"UPDATE compliance_incidents SET {column} = {value} WHERE id = %s", (created["id"],))
    conn.execute("UPDATE compliance_incidents SET status = 'closed', severity = 'low', notes = 'n', "
                 "notified_commission_at = now(), notified_subjects_at = now(), updated_at = now() WHERE id = %s",
                 (created["id"],))


def test_reminders_are_insert_only_for_the_app_role(world, team):
    org_id, owner, *_ = team
    _record(world, org_id, owner)
    attestation = world.rows("SELECT id FROM compliance_attestations WHERE org_id = %s", (org_id,))[0]["id"]
    conn = _app(world)
    conn.execute("INSERT INTO compliance_reminders (attestation_id, threshold_days) VALUES (%s, 30)", (attestation,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO compliance_reminders (attestation_id, threshold_days) VALUES (%s, 30)", (attestation,))
    for sql in ("UPDATE compliance_reminders SET sent_at = now()", "DELETE FROM compliance_reminders"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql)


def test_the_schema_checks_hold(world, team):
    org_id, *_ = team
    conn = _app(world)
    good = (org_id, "t", "low", "open", "2026-10-15T09:00:00Z", "2026-10-15T09:00:00Z")
    insert = ("INSERT INTO compliance_incidents (org_id, title, severity, status, detected_at, became_aware_at, notes) "
              "VALUES (%s, %s, %s, %s, %s, %s, %s)")
    conn.execute(insert, (*good, "n"))
    bad = [((org_id, "x" * 201, "low", "open", good[4], good[5]), None),
           ((org_id, "", "low", "open", good[4], good[5]), None),
           ((org_id, "t", "urgent", "open", good[4], good[5]), None),
           ((org_id, "t", "low", "deleted", good[4], good[5]), None),
           ((org_id, "t", "low", "open", good[4], good[5]), "n" * 4001),
           ((org_id, "t", "low", "open", "2026-10-15T09:00:00Z", "2026-09-01T09:00:00Z"), None)]  # sanity check
    for params, notes in bad:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, (*params, notes))


# ── API: roles, plan, tenancy ────────────────────────────────────────────


def test_owner_and_admin_write_and_every_member_can_read(world, team):
    org_id, owner, admin, member = team
    first = _post(world, org_id, owner)
    second = _post(world, org_id, admin, title="Second")
    assert first.status_code == 201 and second.status_code == 201
    for uid in (owner, admin, member):
        listing = world.client.get("/api/v1/compliance/incidents", headers=world.headers(uid, org_id))
        assert listing.status_code == 200
        body = listing.json()
        assert {i["title"] for i in body["incidents"]} == {"Laptop lost", "Second"}
        assert body["deadline_hours"] == 72 and len(body["checklist"]) == 6
        assert "not legal advice" in body["disclaimer"].lower()


def test_members_cannot_write(world, team):
    org_id, owner, admin, member = team
    created = _post(world, org_id, owner).json()
    assert _post(world, org_id, member).status_code == 403
    patch = world.client.patch(f"/api/v1/compliance/incidents/{created['id']}", json={"status": "closed"},
                               headers=world.headers(member, org_id))
    assert patch.status_code == 403
    assert world.rows("SELECT status FROM compliance_incidents WHERE id = %s", (created["id"],))[0]["status"] == "open"
    assert len(_audit(world, org_id, "compliance.incident.created")) == 1
    assert _audit(world, org_id, "compliance.incident.updated") == []


def test_starter_organisations_get_the_growth_gate_on_every_incident_endpoint(world):
    org_id = world.make_org(plan="starter")
    owner = world.make_person(org_id, "owner")
    assert world.client.get("/api/v1/compliance/incidents", headers=world.headers(owner, org_id)).status_code == 403
    assert _post(world, org_id, owner).status_code == 403
    assert world.client.patch(f"/api/v1/compliance/incidents/{uuid4()}", json={"status": "closed"},
                              headers=world.headers(owner, org_id)).status_code == 403
    assert world.rows("SELECT 1 FROM compliance_incidents WHERE org_id = %s", (org_id,)) == []


def test_an_incident_of_another_organisation_is_invisible_and_cannot_be_changed(world, team):
    org_id, owner, *_ = team
    other_org = world.make_org()
    other_owner = world.make_person(other_org, "owner")
    theirs = _post(world, other_org, other_owner, title="Theirs").json()
    mine = world.client.get("/api/v1/compliance/incidents", headers=world.headers(owner, org_id)).json()
    assert mine["incidents"] == []
    patch = world.client.patch(f"/api/v1/compliance/incidents/{theirs['id']}", json={"status": "closed"},
                               headers=world.headers(owner, org_id))
    assert patch.status_code == 404
    # Naming the other organisation in the header does not help a non-member either.
    headers = {**world.headers(owner, org_id), "X-Organization-Id": other_org}
    assert world.client.get("/api/v1/compliance/incidents", headers=headers).status_code in (403, 404)
    assert world.rows("SELECT status FROM compliance_incidents WHERE id = %s", (theirs["id"],))[0]["status"] == "open"
    assert _audit(world, org_id, "compliance.incident.updated") == []
    assert _audit(world, other_org, "compliance.incident.updated") == []


def test_unknown_and_immutable_fields_are_refused(world, team):
    org_id, owner, *_ = team
    created = _post(world, org_id, owner).json()
    path = f"/api/v1/compliance/incidents/{created['id']}"
    for body in ({"title": "renamed"}, {"became_aware_at": "2026-10-16T00:00:00Z"}, {"org_id": str(uuid4())}, {}):
        assert world.client.patch(path, json=body, headers=world.headers(owner, org_id)).status_code == 422
    assert world.client.patch(path, json={"status": None}, headers=world.headers(owner, org_id)).status_code == 422
    assert world.client.patch(path, json={"status": "deleted"}, headers=world.headers(owner, org_id)).status_code == 422
    assert _post(world, org_id, owner, severity="urgent").status_code == 422
    assert _post(world, org_id, owner, extra_field=1).status_code == 422


# ── Audit ────────────────────────────────────────────────────────────────


def test_every_write_is_audited_without_notes_or_title(world, team):
    org_id, owner, admin, _ = team
    created = _post(world, org_id, owner, notes=NOTES, title="Jane Doe's laptop").json()
    patched = world.client.patch(f"/api/v1/compliance/incidents/{created['id']}", headers=world.headers(admin, org_id),
                                 json={"status": "contained", "notes": NOTES + " (updated)",
                                       "notified_commission_at": "2026-10-16T10:00:00+00:00"})
    assert patched.status_code == 200
    made, changed = _audit(world, org_id, "compliance.incident.created"), _audit(world, org_id, "compliance.incident.updated")
    assert len(made) == 1 and len(changed) == 1
    assert made[0]["resource_id"] == created["id"] == changed[0]["resource_id"]
    assert str(made[0]["user_id"]) == owner and str(changed[0]["user_id"]) == admin
    for entry in (made[0], changed[0]):
        text = json.dumps(entry["metadata"])
        assert "jane" not in text.lower() and "Customer list" not in text and "laptop" not in text.lower()
    assert changed[0]["metadata"]["changed"] == ["status", "notes", "notified_commission_at"]
    assert changed[0]["metadata"]["previous_status"] == "open" and changed[0]["metadata"]["status"] == "contained"
    assert made[0]["metadata"]["notes_recorded"] is True


def test_a_failed_audit_write_rolls_the_incident_back(world, team):
    org_id, owner, *_ = team
    import os
    admin_url = os.environ.get("CYPHWARD_TEST_DATABASE_ADMIN_URL")
    if not admin_url:
        pytest.skip("Set CYPHWARD_TEST_DATABASE_ADMIN_URL to inject an audit failure")
    created = _post(world, org_id, owner).json()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute("CREATE OR REPLACE FUNCTION c3b_fail_audit_fn() RETURNS trigger LANGUAGE plpgsql AS $$ "
                      "BEGIN RAISE EXCEPTION 'injected audit failure'; END $$")
        admin.execute("CREATE TRIGGER c3b_fail_audit BEFORE INSERT ON audit_log FOR EACH ROW "
                      "WHEN (NEW.action LIKE 'compliance.incident.%') EXECUTE FUNCTION c3b_fail_audit_fn()")
        try:
            with pytest.raises(psycopg.Error, match="injected audit failure"):
                inc.update({"id": org_id}, owner, created["id"], {"status": "closed"})
            with pytest.raises(psycopg.Error, match="injected audit failure"):
                inc.create({"id": org_id}, owner, title="No audit, no incident", severity="low",
                           detected_at=datetime(2026, 10, 15, tzinfo=UTC), became_aware_at=datetime(2026, 10, 15, tzinfo=UTC))
        finally:
            admin.execute("DROP TRIGGER IF EXISTS c3b_fail_audit ON audit_log")
            admin.execute("DROP FUNCTION IF EXISTS c3b_fail_audit_fn()")
    assert world.rows("SELECT status FROM compliance_incidents WHERE id = %s", (created["id"],))[0]["status"] == "open"
    assert len(world.rows("SELECT 1 FROM compliance_incidents WHERE org_id = %s", (org_id,))) == 1


# ── Deadline, time zones ─────────────────────────────────────────────────


def test_responses_carry_the_deadline_computed_in_utc(world, team):
    org_id, owner, *_ = team
    aware = datetime.now(UTC) - timedelta(hours=71)
    out = _post(world, org_id, owner, detected_at=(aware - timedelta(hours=2)).isoformat(),
                became_aware_at=aware.isoformat()).json()
    assert datetime.fromisoformat(out["deadline_at"]) == datetime.fromisoformat(out["became_aware_at"]) + timedelta(hours=72)
    assert out["overdue"] is False and 0.9 < out["hours_remaining"] < 1.1 and out["commission_state"] == "pending"
    old = _post(world, org_id, owner, became_aware_at="2026-10-01T10:00:00Z", detected_at="2026-10-01T09:00:00Z").json()
    assert old["overdue"] is True and old["hours_remaining"] == 0.0


def test_notified_late_and_on_time_over_the_api(world, team):
    org_id, owner, *_ = team
    late = _post(world, org_id, owner, became_aware_at="2026-10-01T10:00:00Z", detected_at="2026-10-01T09:00:00Z",
                 notified_commission_at="2026-10-04T10:01:00Z").json()
    ontime = _post(world, org_id, owner, became_aware_at="2026-10-01T10:00:00Z", detected_at="2026-10-01T09:00:00Z",
                   notified_commission_at="2026-10-04T09:59:00Z").json()
    assert late["notified_late"] is True and late["overdue"] is False and late["commission_state"] == "notified_late"
    assert ontime["notified_late"] is False and ontime["overdue"] is False and ontime["commission_state"] == "notified_on_time"
    patched = world.client.patch(f"/api/v1/compliance/incidents/{late['id']}", json={"notified_commission_at": None},
                                 headers=world.headers(owner, org_id)).json()
    assert patched["commission_state"] == "overdue" and patched["overdue"] is True


def test_a_time_typed_near_midnight_in_lagos_is_stored_utc_and_shown_in_lagos(world, team):
    org_id, owner, *_ = team
    out = _post(world, org_id, owner, detected_at="2026-10-15T23:00:00", became_aware_at="2026-10-15T23:30:00").json()
    stored = world.rows("SELECT became_aware_at FROM compliance_incidents WHERE id = %s", (out["id"],))[0]
    assert stored["became_aware_at"] == datetime(2026, 10, 15, 22, 30, tzinfo=UTC)
    assert out["became_aware_at"] == "2026-10-15T22:30:00+00:00"
    assert out["local"]["became_aware_at"] == "2026-10-15T23:30:00+01:00"
    assert out["local"]["deadline_at"] == "2026-10-18T23:30:00+01:00" and out["deadline_at"] == "2026-10-18T22:30:00+00:00"
    assert out["display_timezone"] == "Africa/Lagos"


def test_an_organisation_in_another_zone_sees_its_own_zone_across_a_clock_change(world, team):
    org_id, owner, *_ = team
    world.setup.execute("UPDATE organizations SET display_timezone = 'America/New_York' WHERE id = %s", (org_id,))
    world.setup.commit()
    out = _post(world, org_id, owner, detected_at="2026-03-07T11:00:00", became_aware_at="2026-03-07T12:00:00")
    # The fixed "now" is later than March 2026, so only the clock-change arithmetic is checked here.
    body = out.json()
    assert out.status_code == 201
    assert body["became_aware_at"] == "2026-03-07T17:00:00+00:00"
    assert body["deadline_at"] == "2026-03-10T17:00:00+00:00"
    assert body["local"]["deadline_at"] == "2026-03-10T13:00:00-04:00"
    skipped = _post(world, org_id, owner, detected_at="2026-03-08T01:00:00", became_aware_at="2026-03-08T02:30:00")
    assert skipped.status_code == 422 and "UTC offset" in skipped.json()["detail"]
    explicit = _post(world, org_id, owner, detected_at="2026-03-08T01:00:00-05:00", became_aware_at="2026-03-08T03:30:00-04:00")
    assert explicit.status_code == 201 and explicit.json()["became_aware_at"] == "2026-03-08T07:30:00+00:00"


# ── Reminders ────────────────────────────────────────────────────────────


@pytest.fixture
def mail(monkeypatch):
    sent = []

    async def fake_send(to, subject, html, text=None, name=None, kind="system", reply_to=None):
        sent.append({"to": to, "subject": subject, "html": html, "text": text, "kind": kind})
        return {"success": True}

    monkeypatch.setattr(reminders.mailer, "send_email_async", fake_send)
    return sent


@pytest.fixture
def run_day(world):  # noqa: F811
    day = date(2040, 1, 1) + timedelta(days=uuid4().int % 20000)
    yield day
    world.setup.execute("DELETE FROM cron_runs WHERE cron_name = %s AND run_day = %s", (COMPLIANCE_REMINDERS_CRON_NAME, day))
    world.setup.commit()


def _expiring(world, org_id, actor, days, key="breach.response_plan", value="yes", owner=None):
    """A current answer that expires `days` from now, attested a minute ago."""
    now = datetime.now(UTC)
    out = store.record({"id": org_id}, actor, question_key=key, answer={"value": value}, owner_user_id=owner or actor,
                       expires_at=now + timedelta(days=days), now=now - timedelta(minutes=1))
    return out["id"]


def _reminder_rows(world, attestation_id):
    return sorted(r["threshold_days"] for r in world.rows(
        "SELECT threshold_days FROM compliance_reminders WHERE attestation_id = %s", (attestation_id,)))


def _run(day, now=None):
    import asyncio
    return asyncio.run(reminders.run_compliance_reminders(now=now, run_day=day))


def test_thresholds_30_and_7_remind_once_each_and_nothing_else(world, team, mail, run_day):
    org_id, owner, admin, member = team
    d25 = _expiring(world, org_id, owner, 25, key="breach.response_plan")
    d5 = _expiring(world, org_id, owner, 5, key="breach.incident_log")
    d40 = _expiring(world, org_id, owner, 40, key="rights.process")
    _expiring(world, org_id, owner, 5, key="training.in_place", value="not_sure")
    result = _run(run_day)
    assert result["claimed"] is True and result["reminded"] == 2
    assert _reminder_rows(world, d25) == [30] and _reminder_rows(world, d5) == [7] and _reminder_rows(world, d40) == []
    notes = world.rows("SELECT type, title, body, link FROM notifications WHERE org_id = %s ORDER BY created_at", (org_id,))
    assert len(notes) == 2 and {n["type"] for n in notes} == {"compliance_renewal"} and {n["link"] for n in notes} == {"/comply"}


def test_emails_go_to_the_owner_and_org_owners_and_admins_only_with_no_answer_content(world, team, mail, run_day):
    org_id, owner, admin, member = team
    owner_of_answer = member  # a plain member owns this answer
    now = datetime.now(UTC)
    store.record({"id": org_id}, owner, question_key="dpo.designated",
                 answer={"value": "yes", "text": "Secret Person, jane.private@example.com"},
                 owner_user_id=owner_of_answer, notes="private note", evidence_link="https://private.example/doc",
                 expires_at=now + timedelta(days=6), now=now - timedelta(minutes=1))
    _run(run_day)
    expected = {f"c3a-{uid[:8]}@attestation.test" for uid in (owner, admin, member)}
    assert {m["to"] for m in mail} == expected and len(mail) == 3
    for m in mail:
        blob = (m["subject"] + m["html"] + m["text"]).lower()
        assert "secret person" not in blob and "jane.private" not in blob and "private note" not in blob
        assert "private.example" not in blob
        assert "/comply" in m["text"] and m["kind"] == "alerts"
        assert (now + timedelta(days=6)).astimezone(reminders.zone_for("Africa/Lagos")).strftime("%B %Y") in m["text"]


def test_a_retry_cannot_double_send(world, team, mail, run_day):
    org_id, owner, *_ = team
    answer = _expiring(world, org_id, owner, 5)
    first = _run(run_day)
    assert first["reminded"] == 1 and len(mail) == 2  # owner + admin... recipients are distinct people
    sent_after_first = len(mail)
    # The job fails after the sweep, so the claim is released and a retry takes over the same day.
    world.setup.execute("UPDATE cron_runs SET status = 'failed' WHERE cron_name = %s AND run_day = %s",
                        (COMPLIANCE_REMINDERS_CRON_NAME, run_day))
    world.setup.commit()
    second = _run(run_day)
    assert second["claimed"] is True and second["reminded"] == 0 and second["due"] == 0
    assert len(mail) == sent_after_first and _reminder_rows(world, answer) == [7]
    assert len(world.rows("SELECT 1 FROM notifications WHERE org_id = %s", (org_id,))) == 1
    # And a run the same day while it is completed does not even claim.
    assert _run(run_day)["claimed"] is False


def test_a_crash_between_the_reminder_and_the_email_loses_the_email_but_never_doubles_it(world, team, run_day, monkeypatch):
    org_id, owner, *_ = team
    answer = _expiring(world, org_id, owner, 5)

    async def boom(*a, **k):
        raise RuntimeError("mail down")

    monkeypatch.setattr(reminders.mailer, "send_email_async", boom)
    first = _run(run_day)
    assert first["claimed"] is True and first["reminded"] == 1 and first["email_failures"] >= 1
    assert _reminder_rows(world, answer) == [7]
    world.setup.execute("UPDATE cron_runs SET status = 'failed' WHERE cron_name = %s AND run_day = %s",
                        (COMPLIANCE_REMINDERS_CRON_NAME, run_day))
    world.setup.commit()
    sent = []

    async def ok(to, *a, **k):
        sent.append(to)

    monkeypatch.setattr(reminders.mailer, "send_email_async", ok)
    assert _run(run_day)["reminded"] == 0 and sent == []


def test_a_superseded_or_replaced_answer_is_not_reminded_and_the_new_one_is(world, team, mail, run_day):
    org_id, owner, *_ = team
    old = _expiring(world, org_id, owner, 5)
    new = _expiring(world, org_id, owner, 300)  # supersedes the old answer
    result = _run(run_day)
    assert result["reminded"] == 0 and _reminder_rows(world, old) == [] and _reminder_rows(world, new) == []
    assert mail == []


def test_an_already_expired_answer_is_not_reminded(world, team, mail, run_day):
    org_id, owner, *_ = team
    now = datetime.now(UTC)
    store.record({"id": org_id}, owner, question_key="breach.response_plan", answer={"value": "yes"},
                 owner_user_id=owner, expires_at=now - timedelta(days=1), now=now - timedelta(days=30))
    assert _run(run_day)["reminded"] == 0 and mail == []


def test_a_stale_cron_claim_cannot_write_or_send(world, team, mail, run_day):
    org_id, owner, *_ = team
    answer = _expiring(world, org_id, owner, 5)
    claim = cron_claim.claim_cron_run(COMPLIANCE_REMINDERS_CRON_NAME, run_day, "old-owner")
    world.setup.execute("UPDATE cron_runs SET lease_expires_at = clock_timestamp() - interval '1 second' "
                        "WHERE cron_name = %s AND run_day = %s", (COMPLIANCE_REMINDERS_CRON_NAME, run_day))
    world.setup.commit()
    new = cron_claim.claim_cron_run(COMPLIANCE_REMINDERS_CRON_NAME, run_day, "new-owner")
    assert new["claim_generation"] == claim["claim_generation"] + 1
    import asyncio
    with pytest.raises(ClaimLost):
        asyncio.run(reminders._sweep(claim, datetime.now(UTC)))
    assert mail == [] and _reminder_rows(world, answer) == []
    assert world.rows("SELECT 1 FROM notifications WHERE org_id = %s", (org_id,)) == []
    # The current owner still sends.
    result = asyncio.run(reminders._sweep(new, datetime.now(UTC)))
    assert result["reminded"] == 1 and len(mail) >= 1 and _reminder_rows(world, answer) == [7]


def test_a_claim_lost_between_the_reminder_and_the_email_sends_nothing(world, team, mail, run_day, monkeypatch):
    org_id, owner, *_ = team
    _expiring(world, org_id, owner, 5)
    claim = cron_claim.claim_cron_run(COMPLIANCE_REMINDERS_CRON_NAME, run_day, "owner-a")
    real_record = reminders._record_reminder

    def record_then_lose_the_claim(*args, **kwargs):
        out = real_record(*args, **kwargs)
        world.setup.execute("UPDATE cron_runs SET lease_expires_at = clock_timestamp() - interval '1 second' "
                            "WHERE cron_name = %s AND run_day = %s", (COMPLIANCE_REMINDERS_CRON_NAME, run_day))
        world.setup.commit()
        return out

    monkeypatch.setattr(reminders, "_record_reminder", record_then_lose_the_claim)
    import asyncio
    with pytest.raises(ClaimLost):
        asyncio.run(reminders._sweep(claim, datetime.now(UTC)))
    assert mail == []


def test_the_claim_is_shared_so_a_second_runner_does_nothing(world, team, mail, run_day):
    org_id, owner, *_ = team
    _expiring(world, org_id, owner, 5)
    held = cron_claim.claim_cron_run(COMPLIANCE_REMINDERS_CRON_NAME, run_day, "other-replica")
    assert held is not None
    assert _run(run_day) == {"claimed": False, "due": 0, "reminded": 0}
    assert mail == []
