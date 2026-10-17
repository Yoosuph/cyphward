"""Customer attestations against the real, migrated test database (packet C3a, section 8).

Runs only against the owned loopback `cyphward_test` database through the
restricted `cyphward_app` role. Covers: atomic superseding with one current
answer; a failed audit write rolls the supersede back; append-only grants and
the supersede-once trigger; cross-tenant owners refused; members cannot write;
every write audited; concurrent writers serialise; expiry; the API's role and
plan gates.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from backend.app.compliance import attestation_store as store
from backend.app.compliance import attestations as truth
from backend.app.core import database
from backend.app.core.security import hash_password
from backend.app.core.sessions import issue_session
from backend.app.main import app
from backend.tests.test_scan_admission_postgres import disposable_postgres_url  # noqa: F401 (fixture)

ACTION = "compliance.attestation.recorded"
PASSWORD = "compliance-pass-1"


@pytest.fixture
def world(disposable_postgres_url, monkeypatch):
    @contextmanager
    def get_db():
        conn = psycopg.connect(disposable_postgres_url, row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(database, "get_db", get_db)
    setup = psycopg.connect(disposable_postgres_url, row_factory=dict_row)
    orgs, people = [], []

    def make_org(plan="growth"):
        oid = str(uuid4())
        setup.execute("INSERT INTO organizations (id, name, slug, sector, plan) VALUES (%s, %s, %s, %s, %s)",
                      (oid, "Attestation Test", f"attest-{oid}", "Technology", plan))
        setup.commit()
        orgs.append(oid)
        return oid

    def make_person(org_id, role="member"):
        uid = str(uuid4())
        email = f"c3a-{uid[:8]}@attestation.test"
        setup.execute("INSERT INTO profiles (id, email, full_name, role, password_hash, provider, email_verified_at) "
                      "VALUES (%s, %s, 'Attestation Tester', 'Member', %s, 'email', now())",
                      (uid, email, hash_password(PASSWORD)))
        if org_id:
            setup.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s, %s, %s)",
                          (uid, org_id, role))
        setup.commit()
        people.append(uid)
        return uid

    def headers(uid, org_id):
        token = issue_session({"id": uid, "email": f"c3a-{uid[:8]}@attestation.test",
                               "full_name": "Attestation Tester", "role": "Member"})["access_token"]
        return {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}

    def org_dict(org_id):
        return {"id": org_id, "display_timezone": "Africa/Lagos"}

    def rows(sql, params=()):
        with psycopg.connect(disposable_postgres_url, row_factory=dict_row) as conn:
            return conn.execute(sql, params).fetchall()

    yield SimpleNamespace(setup=setup, make_org=make_org, make_person=make_person, headers=headers,
                          org=org_dict, rows=rows, url=disposable_postgres_url, client=TestClient(app))
    setup.rollback()
    for oid in orgs:
        setup.execute("DELETE FROM organizations WHERE id = %s", (oid,))
    for uid in people:
        setup.execute("DELETE FROM profiles WHERE id = %s", (uid,))
    setup.commit()
    setup.close()


def _record(world, org_id, actor, *, key="breach.response_plan", value="yes", owner=None, **extra):
    return store.record({"id": org_id}, actor, question_key=key, answer={"value": value},
                        owner_user_id=owner or actor, **extra)


def _current(world, org_id, key="breach.response_plan"):
    return world.rows("SELECT id, answer, superseded_by FROM compliance_attestations "
                      "WHERE org_id = %s AND question_key = %s AND superseded_by IS NULL", (org_id, key))


# ── Defaults and the schema ───────────────────────────────────────────────


def test_organization_display_timezone_defaults_to_lagos(world):
    org_id = world.make_org()
    row = world.rows("SELECT display_timezone FROM organizations WHERE id = %s", (org_id,))[0]
    assert row["display_timezone"] == "Africa/Lagos"


def test_one_current_answer_per_question_is_enforced_by_the_database(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    _record(world, org_id, owner, value="yes")
    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(world.url) as conn:
            conn.execute("INSERT INTO compliance_attestations (org_id, question_key, questionnaire_version, answer, "
                         "owner_user_id, expires_at) VALUES (%s, 'breach.response_plan', 'v', %s, %s, now())",
                         (org_id, json.dumps({"value": "no"}), owner))


# ── Superseding (atomic) ─────────────────────────────────────────────────


def test_recording_a_new_answer_supersedes_the_current_one(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    first = _record(world, org_id, owner, value="yes")
    second = _record(world, org_id, owner, value="no")
    assert second["superseded_id"] == first["id"]
    current = _current(world, org_id)
    assert len(current) == 1 and str(current[0]["id"]) == second["id"] and current[0]["answer"]["value"] == "no"
    old = world.rows("SELECT superseded_by FROM compliance_attestations WHERE id = %s", (first["id"],))[0]
    assert str(old["superseded_by"]) == second["id"]


def test_a_failed_audit_write_rolls_the_supersede_back(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    first = _record(world, org_id, owner, value="yes")
    admin_url = os.environ.get("CYPHWARD_TEST_DATABASE_ADMIN_URL", "")
    if not admin_url:
        pytest.skip("Set CYPHWARD_TEST_DATABASE_ADMIN_URL to inject an audit failure")
    # The administrator installs a temporary failure on the audit insert only; the app role is unchanged.
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute("CREATE OR REPLACE FUNCTION c3a_fail_audit_fn() RETURNS trigger LANGUAGE plpgsql AS $$ "
                      "BEGIN RAISE EXCEPTION 'injected audit failure'; END $$")
        admin.execute("CREATE TRIGGER c3a_fail_audit BEFORE INSERT ON audit_log FOR EACH ROW "
                      "WHEN (NEW.action = 'compliance.attestation.recorded') EXECUTE FUNCTION c3a_fail_audit_fn()")
    try:
        with pytest.raises(psycopg.Error, match="injected audit failure"):
            _record(world, org_id, owner, value="no")
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute("DROP TRIGGER IF EXISTS c3a_fail_audit ON audit_log")
            admin.execute("DROP FUNCTION IF EXISTS c3a_fail_audit_fn()")
    current = _current(world, org_id)
    assert [str(r["id"]) for r in current] == [first["id"]] and current[0]["answer"]["value"] == "yes"
    assert world.rows("SELECT count(*) AS n FROM compliance_attestations WHERE org_id = %s", (org_id,))[0]["n"] == 1


def test_concurrent_answers_serialise_to_one_current_answer(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    barrier = Barrier(2)

    def write(value):
        barrier.wait(timeout=10)
        return _record(world, org_id, owner, value=value)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=30) for future in [pool.submit(write, "yes"), pool.submit(write, "no")]]
    assert all(results)
    current = _current(world, org_id)
    everything = world.rows("SELECT id, superseded_by FROM compliance_attestations WHERE org_id = %s", (org_id,))
    assert len(current) == 1 and len(everything) == 2
    superseded = [r for r in everything if r["superseded_by"] is not None]
    assert len(superseded) == 1 and superseded[0]["superseded_by"] == current[0]["id"]


def test_a_superseded_answer_cannot_be_superseded_again_or_reopened(world):
    org_a, org_b = world.make_org(), world.make_org()
    owner_a = world.make_person(org_a, "owner")
    owner_b = world.make_person(org_b, "owner")
    first = _record(world, org_a, owner_a, value="yes")
    second = _record(world, org_a, owner_a, value="no")
    other = _record(world, org_b, owner_b, value="yes")
    with pytest.raises(psycopg.errors.RaiseException, match="only a current answer"):
        with psycopg.connect(world.url) as conn:
            conn.execute("UPDATE compliance_attestations SET superseded_by = %s WHERE id = %s",
                         (other["id"], first["id"]))
    with pytest.raises(psycopg.errors.RaiseException, match="only a current answer"):
        with psycopg.connect(world.url) as conn:
            conn.execute("UPDATE compliance_attestations SET superseded_by = NULL WHERE id = %s", (first["id"],))
    assert str(_current(world, org_a)[0]["id"]) == second["id"]


def test_a_supersede_cannot_point_into_another_organization(world):
    org_a, org_b = world.make_org(), world.make_org()
    owner_a = world.make_person(org_a, "owner")
    owner_b = world.make_person(org_b, "owner")
    victim = _record(world, org_a, owner_a, value="yes")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(world.url) as conn:
            with conn.transaction():
                conn.execute("INSERT INTO compliance_attestations (id, org_id, question_key, questionnaire_version, "
                             "answer, owner_user_id, expires_at, superseded_by) "
                             "VALUES (%s, %s, 'breach.response_plan', 'v', %s, %s, now(), %s)",
                             (str(uuid4()), org_b, json.dumps({"value": "no"}), owner_b, victim["id"]))


# ── Grants, triggers, checks ─────────────────────────────────────────────


def test_the_app_role_cannot_edit_or_delete_an_answer(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    row = _record(world, org_id, owner, value="yes")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(world.url) as conn:
            conn.execute("UPDATE compliance_attestations SET answer = %s WHERE id = %s",
                         (json.dumps({"value": "no"}), row["id"]))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(world.url) as conn:
            conn.execute("UPDATE compliance_attestations SET notes = 'edited' WHERE id = %s", (row["id"],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(world.url) as conn:
            conn.execute("DELETE FROM compliance_attestations WHERE id = %s", (row["id"],))


def test_evidence_links_must_be_https_and_bounded_in_the_database(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(world.url) as conn:
            conn.execute("INSERT INTO compliance_attestations (org_id, question_key, questionnaire_version, answer, "
                         "owner_user_id, expires_at, evidence_link) VALUES (%s, 'breach.response_plan', 'v', %s, %s, "
                         "now(), 'http://insecure.example')", (org_id, json.dumps({"value": "yes"}), owner))


def test_an_insecure_evidence_link_is_refused_before_anything_is_written(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    with pytest.raises(truth.AnswerError, match="https"):
        _record(world, org_id, owner, evidence_link="http://insecure.example/policy")
    assert world.rows("SELECT count(*) AS n FROM compliance_attestations WHERE org_id = %s", (org_id,))[0]["n"] == 0


def test_removing_the_owner_clears_the_owner_without_changing_the_answer(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    row = _record(world, org_id, owner, value="yes")
    world.setup.execute("DELETE FROM profiles WHERE id = %s", (owner,))
    world.setup.commit()
    after = world.rows("SELECT owner_user_id, answer FROM compliance_attestations WHERE id = %s", (row["id"],))[0]
    assert after["owner_user_id"] is None and after["answer"]["value"] == "yes"


# ── Owners, scope and audit ──────────────────────────────────────────────


def test_a_cross_tenant_owner_is_refused_and_nothing_is_written(world):
    org_a, org_b = world.make_org(), world.make_org()
    owner_a = world.make_person(org_a, "owner")
    outsider = world.make_person(org_b, "member")
    with pytest.raises(truth.AnswerError, match="member of this organization"):
        _record(world, org_a, owner_a, owner=outsider)
    assert world.rows("SELECT count(*) AS n FROM compliance_attestations WHERE org_id = %s", (org_a,))[0]["n"] == 0
    assert world.rows("SELECT count(*) AS n FROM audit_log WHERE org_id = %s AND action = %s",
                      (org_a, ACTION))[0]["n"] == 0


def test_a_profile_that_belongs_to_no_organization_cannot_own_an_answer(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    stranger = world.make_person(None)
    with pytest.raises(truth.AnswerError, match="member of this organization"):
        _record(world, org_id, owner, owner=stranger)


def test_every_write_is_audited_without_answer_text_or_notes(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    written = store.record({"id": org_id}, owner, question_key="dpo.designated",
                           answer={"value": "yes", "text": "Ada Okafor, DPO"}, owner_user_id=owner,
                           notes="internal reference only")
    audit = world.rows("SELECT org_id, user_id, action, resource_type, resource_id, metadata FROM audit_log "
                       "WHERE org_id = %s AND action = %s", (org_id, ACTION))
    assert len(audit) == 1
    assert audit[0]["resource_id"] == written["id"] and audit[0]["resource_type"] == "compliance_attestation"
    assert str(audit[0]["user_id"]) == owner
    serialised = json.dumps(audit[0]["metadata"])
    assert "Okafor" not in serialised and "internal reference" not in serialised
    assert audit[0]["metadata"]["question_key"] == "dpo.designated"


def test_a_question_that_is_not_shown_cannot_be_answered(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    with pytest.raises(truth.AnswerError, match="not shown"):
        store.record({"id": org_id}, owner, question_key="registration.tier", answer={"value": "ohl"},
                     owner_user_id=owner)


# ── Expiry (D12) ─────────────────────────────────────────────────────────


def test_an_expired_answer_reads_as_renewal_due_never_present(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    then = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _record(world, org_id, owner, value="yes", now=then)
    later = then + timedelta(days=400)
    view = store.questionnaire({"id": org_id, "display_timezone": "Africa/Lagos"}, now=later)
    question = next(q for q in view["questions"] if q["key"] == "breach.response_plan")
    assert question["answer_state"] == "expired"
    assert question["status"] == "awaiting_input" and question["reason"] == "answer_expired"
    assert question["current"]["expired"] is True


def test_history_keeps_superseded_answers_in_order(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    _record(world, org_id, owner, value="yes")
    _record(world, org_id, owner, value="no")
    history = store.history(org_id, "breach.response_plan")
    assert [h["value"] for h in history] == ["no", "yes"]
    assert [h["superseded"] for h in history] == [False, True]


# ── API: roles, plan gate, tenancy ───────────────────────────────────────


def test_members_cannot_write_and_nothing_is_audited(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    member = world.make_person(org_id, "member")
    body = {"question_key": "breach.response_plan", "answer": {"value": "yes"}, "owner_user_id": owner}
    response = world.client.post("/api/v1/compliance/attestations", json=body,
                                 headers=world.headers(member, org_id))
    assert response.status_code == 403
    assert world.rows("SELECT count(*) AS n FROM compliance_attestations WHERE org_id = %s", (org_id,))[0]["n"] == 0
    assert world.rows("SELECT count(*) AS n FROM audit_log WHERE org_id = %s AND action = %s",
                      (org_id, ACTION))[0]["n"] == 0


def test_owner_and_admin_write_through_the_api_and_every_write_is_audited(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    admin = world.make_person(org_id, "admin")
    member = world.make_person(org_id, "member")
    body = {"question_key": "breach.response_plan", "answer": {"value": "yes"}, "owner_user_id": member,
            "evidence_link": "https://example.com/incident-policy", "notes": "reviewed in March"}
    first = world.client.post("/api/v1/compliance/attestations", json=body, headers=world.headers(owner, org_id))
    assert first.status_code == 201, first.text
    body2 = {**body, "answer": {"value": "no"}}
    second = world.client.post("/api/v1/compliance/attestations", json=body2, headers=world.headers(admin, org_id))
    assert second.status_code == 201, second.text
    assert second.json()["superseded_id"] == first.json()["id"]
    audit = world.rows("SELECT user_id, resource_id FROM audit_log WHERE org_id = %s AND action = %s "
                       "ORDER BY created_at", (org_id, ACTION))
    assert [str(a["user_id"]) for a in audit] == [owner, admin]


def test_api_refuses_an_owner_outside_the_organization_and_an_invalid_answer(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    outsider = world.make_person(world.make_org(), "member")
    headers = world.headers(owner, org_id)
    cross = world.client.post("/api/v1/compliance/attestations", headers=headers, json={
        "question_key": "breach.response_plan", "answer": {"value": "yes"}, "owner_user_id": outsider})
    assert cross.status_code == 422
    bad = world.client.post("/api/v1/compliance/attestations", headers=headers, json={
        "question_key": "breach.response_plan", "answer": {"value": "maybe"}, "owner_user_id": owner})
    assert bad.status_code == 422
    unknown = world.client.post("/api/v1/compliance/attestations", headers=headers, json={
        "question_key": "nope", "answer": {"value": "yes"}, "owner_user_id": owner})
    assert unknown.status_code == 422
    extra = world.client.post("/api/v1/compliance/attestations", headers=headers, json={
        "question_key": "breach.response_plan", "answer": {"value": "yes"}, "owner_user_id": owner, "role": "owner"})
    assert extra.status_code == 422


def test_tenant_scope_hides_another_organizations_answers(world):
    org_a, org_b = world.make_org(), world.make_org()
    owner_a = world.make_person(org_a, "owner")
    reader_b = world.make_person(org_b, "member")
    _record(world, org_a, owner_a, value="yes")
    response = world.client.get("/api/v1/compliance/questionnaire", headers=world.headers(reader_b, org_b))
    assert response.status_code == 200
    question = next(q for q in response.json()["questions"] if q["key"] == "breach.response_plan")
    assert question["current"] is None and question["answer_state"] == "unanswered"


def test_members_can_read_the_questionnaire_and_history_on_growth(world):
    org_id = world.make_org("growth")
    owner = world.make_person(org_id, "owner")
    member = world.make_person(org_id, "member")
    _record(world, org_id, owner, value="yes")
    headers = world.headers(member, org_id)
    questionnaire = world.client.get("/api/v1/compliance/questionnaire", headers=headers)
    assert questionnaire.status_code == 200
    body = questionnaire.json()
    assert body["display_timezone"] == "Africa/Lagos" and len(body["questions"]) == 20
    assert "not legal advice" in body["disclaimer"]
    history = world.client.get("/api/v1/compliance/attestations/breach.response_plan", headers=headers)
    assert history.status_code == 200 and history.json()["history"][0]["value"] == "yes"
    assert world.client.get("/api/v1/compliance/attestations/not.a.question", headers=headers).status_code == 404


def test_starter_is_gated_from_the_questionnaire_and_history(world):
    org_id = world.make_org("starter")
    member = world.make_person(org_id, "member")
    headers = world.headers(member, org_id)
    assert world.client.get("/api/v1/compliance/questionnaire", headers=headers).status_code == 403
    assert world.client.get("/api/v1/compliance/attestations/breach.response_plan", headers=headers).status_code == 403


def test_queued_writers_are_stamped_in_supersede_order(world):
    import time

    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    _record(world, org_id, owner, value="yes")  # an existing current answer to supersede
    key = f"compliance:{org_id}:breach.response_plan"
    holder = psycopg.connect(world.url, row_factory=dict_row)
    try:
        # A third session holds the per-question lock, so both writers queue behind it.
        holder.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_record, world, org_id, owner, value=v) for v in ("no", "yes")]
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                waiting = world.rows("SELECT count(*) AS n FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
                                     "AND datname = current_database()")[0]["n"]
                if waiting >= 2:
                    break
                time.sleep(0.05)
            assert waiting >= 2, "both writers should be queued behind the lock"
            holder.commit()
            for future in futures:
                future.result(timeout=30)
    finally:
        holder.close()
    current = _current(world, org_id)
    assert len(current) == 1
    attested = world.rows("SELECT id, attested_at FROM compliance_attestations WHERE org_id = %s "
                          "AND question_key = 'breach.response_plan' ORDER BY attested_at", (org_id,))
    assert len(attested) == 3 and str(attested[-1]["id"]) == str(current[0]["id"])
    history = store.history(org_id, "breach.response_plan")
    assert history[0]["superseded"] is False and history[0]["id"] == str(current[0]["id"])
    assert all(h["superseded"] for h in history[1:])


def test_a_current_answer_cannot_point_at_another_question_at_commit(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    current_a = _record(world, org_id, owner, key="breach.response_plan", value="yes")
    other = _record(world, org_id, owner, key="breach.notification_process", value="yes")
    with pytest.raises(psycopg.errors.RaiseException, match="newer answer to the same question"):
        with psycopg.connect(world.url) as conn:
            with conn.transaction():
                conn.execute("UPDATE compliance_attestations SET superseded_by = %s WHERE id = %s",
                             (other["id"], current_a["id"]))
    assert str(_current(world, org_id)[0]["id"]) == current_a["id"]


def test_a_superseding_pointer_cannot_name_an_older_answer(world):
    org_id = world.make_org()
    owner = world.make_person(org_id, "owner")
    older = _record(world, org_id, owner, value="yes")
    newer = _record(world, org_id, owner, value="no")
    with pytest.raises(psycopg.errors.RaiseException, match="newer answer to the same question"):
        with psycopg.connect(world.url) as conn:
            with conn.transaction():
                conn.execute("UPDATE compliance_attestations SET superseded_by = %s WHERE id = %s",
                             (older["id"], newer["id"]))
    assert str(_current(world, org_id)[0]["id"]) == newer["id"]
