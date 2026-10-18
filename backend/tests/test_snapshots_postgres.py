"""Assessment snapshots and report integrity against the real, migrated test database (Packet 04).

Runs only against the owned loopback `cyphward_test` database through the restricted `cyphward_app`
role. Covers: the frozen content and its hash; immutability after later scans, findings and
attestations; append-only grants and guard triggers; a report rendered from its snapshot; legacy
reports labelled and not backfilled; cross-tenant ids; domain mismatch; concurrent generation;
unassessed results; Starter filtering; deletion of a domain, a profile and an organisation.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from backend.app.compliance import attestation_store as store
from backend.app.core import database
from backend.app.core.security import hash_password
from backend.app.core.sessions import issue_session
from backend.app.main import app
from backend.app.snapshots import builder
from backend.tests.test_scan_admission_postgres import disposable_postgres_url  # noqa: F401 (fixture)

PASSWORD = "snapshot-pass-1"
COVERAGE = {"version": 2, "check_set": "cyphward-checks-v1", "state": "complete", "evaluated_checks": 5,
            "requested_checks": 5, "missing": [], "omitted_checks": [], "label": "x.test: all declared checks complete on 1 host",
            "targets": {"selected": 1, "in_scope": 1, "assessed": 1}, "nuclei": {"state": "not_run"}}


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

    def make_org(plan="growth", name="Snapshot Test"):
        oid = str(uuid4())
        setup.execute("INSERT INTO organizations (id, name, slug, sector, plan) VALUES (%s, %s, %s, 'Technology', %s)",
                      (oid, name, f"snap-{oid}", plan))
        setup.commit()
        orgs.append(oid)
        return oid

    def make_person(org_id, role="member"):
        uid = str(uuid4())
        setup.execute("INSERT INTO profiles (id, email, full_name, role, password_hash, provider, email_verified_at) "
                      "VALUES (%s, %s, 'Snapshot Tester', 'Member', %s, 'email', now())",
                      (uid, f"snap-{uid[:8]}@snapshot.test", hash_password(PASSWORD)))
        setup.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s, %s, %s)", (uid, org_id, role))
        setup.commit()
        people.append(uid)
        return uid

    def headers(uid, org_id):
        token = issue_session({"id": uid, "email": f"snap-{uid[:8]}@snapshot.test", "full_name": "Snapshot Tester",
                               "role": "Member"})["access_token"]
        return {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}

    def make_domain(org_id, name=None, verified=True):
        did = str(uuid4())
        setup.execute("INSERT INTO domains (id, org_id, domain, verification_status, verification_token) "
                      "VALUES (%s, %s, %s, %s, %s)",
                      (did, org_id, name or f"d{did[:8]}.snapshot.test", "verified" if verified else "pending", f"t-{did}"))
        setup.commit()
        return did

    def make_scan(org_id, domain_id, coverage=COVERAGE):
        sid = str(uuid4())
        progress = {"scoring": {"status": "completed", "coverage": coverage}} if coverage else {}
        setup.execute("INSERT INTO scans (id, org_id, domain_id, status, stage_progress, completed_at) "
                      "VALUES (%s, %s, %s, 'completed', %s, now())", (sid, org_id, domain_id, json.dumps(progress)))
        setup.commit()
        return sid

    def make_finding(org_id, domain_id, scan_id, title="HSTS Missing", severity="high"):
        asset = setup.execute("INSERT INTO assets (org_id, domain_id, hostname, status, last_seen) "
                              "VALUES (%s, %s, %s, 'active', now()) RETURNING id",
                              (org_id, domain_id, f"h{uuid4().hex[:6]}.snapshot.test")).fetchone()["id"]
        fid = setup.execute("INSERT INTO findings (org_id, asset_id, scan_id, title, description, severity, category, "
                            "evidence, remediation, status) VALUES (%s, %s, %s, %s, 'desc', %s, 'HTTP Headers', %s, 'fix', 'open') "
                            "RETURNING id", (org_id, asset, scan_id, title, severity, json.dumps({"secret": "RAW-EVIDENCE-MARKER"}))).fetchone()["id"]
        setup.commit()
        return str(fid)

    def rows(sql, params=()):
        with psycopg.connect(disposable_postgres_url, row_factory=dict_row) as conn:
            return conn.execute(sql, params).fetchall()

    def as_app(sql, params=()):
        with psycopg.connect(disposable_postgres_url, row_factory=dict_row) as conn:
            conn.execute(sql, params)

    yield SimpleNamespace(setup=setup, make_org=make_org, make_person=make_person, headers=headers, make_domain=make_domain,
                          make_scan=make_scan, make_finding=make_finding, rows=rows, as_app=as_app,
                          url=disposable_postgres_url, client=TestClient(app))
    setup.rollback()
    for oid in orgs:
        setup.execute("DELETE FROM organizations WHERE id = %s", (oid,))
    for uid in people:
        setup.execute("DELETE FROM profiles WHERE id = %s", (uid,))
    setup.commit()
    setup.close()


def _assessed_org(world, plan="growth", **kw):
    org = world.make_org(plan, **kw)
    owner = world.make_person(org, "owner")
    domain = world.make_domain(org, "assessed.snapshot.test")
    scan = world.make_scan(org, domain)
    finding = world.make_finding(org, domain, scan)
    return org, owner, domain, scan, finding


def _create(world, org, user, **body):
    return world.client.post("/api/v1/snapshots", json=body, headers=world.headers(user, org))


def _stored(world, snapshot_id):
    return world.rows("SELECT * FROM assessment_snapshots WHERE id = %s", (snapshot_id,))[0]


# ── Content, hash and provenance ─────────────────────────────────────────


def test_snapshot_freezes_scope_findings_scoring_provenance_and_compliance(world):
    org, owner, domain, scan, finding = _assessed_org(world)
    resp = _create(world, org, owner)
    assert resp.status_code == 201, resp.text
    row = _stored(world, resp.json()["snapshot"]["id"])
    content = row["content"]
    assert content["scope"]["type"] == "organization"
    assert [d["domain"] for d in content["scope"]["domains"]] == ["assessed.snapshot.test"]
    assert content["scope"]["domains"][0]["scan_id"] == scan
    assert content["scoring"]["model"] == "cyphward-risk-v3" and content["scoring"]["assessed"] is True
    assert content["dates"]["generated_at"] and content["dates"]["latest_observation"]
    assert [f["id"] for f in content["findings"]["open"]] == [finding]
    assert "evidence" not in content["findings"]["open"][0] and "RAW-EVIDENCE-MARKER" not in json.dumps(content)
    assert content["provenance"]["check_set"] == "cyphward-checks-v1" and content["provenance"]["register_version"]
    readiness = content["compliance"]["readiness"]
    assert set(readiness) >= {"with_evidence", "present", "gap", "awaiting_input", "not_assessed", "applicable"}
    assert "percent" not in json.dumps(readiness).lower()
    assert content["compliance"]["register"]["version"] == content["compliance"]["register"]["version"]
    assert all(r["clause_verified"] is False for r in content["compliance"]["requirements"])


def test_stored_hash_matches_a_fresh_canonicalisation_of_the_stored_json(world):
    org, owner, *_ = _assessed_org(world)
    row = _stored(world, _create(world, org, owner).json()["snapshot"]["id"])
    assert builder.sha256_of(builder.canonical(row["content"])) == row["content_sha256"]
    body = world.client.get(f"/api/v1/snapshots/{row['id']}", headers=world.headers(owner, org)).json()["snapshot"]
    assert body["intact"] is True and body["content_sha256"] == row["content_sha256"]


def test_attestations_carry_owner_dates_and_no_free_text(world):
    org, owner, *_ = _assessed_org(world)
    store.record({"id": org}, owner, question_key="breach.response_plan", answer={"value": "yes"},
                 owner_user_id=owner, notes="SECRET-NOTE")
    content = _stored(world, _create(world, org, owner).json()["snapshot"]["id"])["content"]
    att = content["compliance"]["attestations"]
    assert [a["question_key"] for a in att] == ["breach.response_plan"]
    assert att[0]["owner_user_id"] == owner and att[0]["attested_at"] and att[0]["expires_at"] and att[0]["value"] == "yes"
    assert "SECRET-NOTE" not in json.dumps(content)
    assert att[0]["source"] == "customer_attested"


# ── Immutability ─────────────────────────────────────────────────────────


def test_later_scans_findings_and_attestations_do_not_rewrite_an_issued_snapshot_or_report(world):
    org, owner, domain, scan, finding = _assessed_org(world)
    report = world.client.post("/api/v1/reports", json={}, headers=world.headers(owner, org)).json()["report"]
    before = world.rows("SELECT html, summary FROM reports WHERE id = %s", (report["id"],))[0]
    snap_before = _stored(world, report["snapshot_id"])

    scan2 = world.make_scan(org, domain, coverage=None)  # a newer scan with no recorded coverage
    world.make_finding(org, domain, scan2, title="New critical", severity="critical")
    world.setup.execute("UPDATE findings SET status = 'resolved', resolved_at = now() WHERE id = %s", (finding,))
    world.setup.commit()
    store.record({"id": org}, owner, question_key="breach.response_plan", answer={"value": "no"}, owner_user_id=owner)

    after = world.rows("SELECT html, summary FROM reports WHERE id = %s", (report["id"],))[0]
    assert after == before
    snap_after = _stored(world, report["snapshot_id"])
    assert snap_after["content"] == snap_before["content"] and snap_after["content_sha256"] == snap_before["content_sha256"]
    # A new snapshot reflects the new state; the old one is unchanged.
    newer = _stored(world, _create(world, org, owner).json()["snapshot"]["id"])
    assert newer["content_sha256"] != snap_before["content_sha256"] and newer["seq"] == snap_before["seq"] + 1
    assert [f["title"] for f in newer["content"]["findings"]["open"]] == ["New critical"]


def test_the_app_role_can_neither_update_nor_delete_a_snapshot(world):
    org, owner, *_ = _assessed_org(world)
    sid = _create(world, org, owner).json()["snapshot"]["id"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        world.as_app("UPDATE assessment_snapshots SET content = '{}'::jsonb WHERE id = %s", (sid,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        world.as_app("DELETE FROM assessment_snapshots WHERE id = %s", (sid,))


def test_even_the_table_owner_cannot_edit_snapshot_content(world):
    org, owner, *_ = _assessed_org(world)
    sid = _create(world, org, owner).json()["snapshot"]["id"]
    admin_url = os.environ.get("CYPHWARD_TEST_DATABASE_ADMIN_URL")
    if not admin_url:
        pytest.skip("needs the table owner connection")
    with psycopg.connect(admin_url) as owner_conn:
        for column, value in (("content", "'{}'::jsonb"), ("content_sha256", "repeat('a', 64)"), ("seq", "99")):
            with pytest.raises(psycopg.errors.RaiseException):
                owner_conn.execute(f"UPDATE assessment_snapshots SET {column} = {value} WHERE id = %s", (sid,))
            owner_conn.rollback()


def test_a_report_issued_from_a_snapshot_cannot_be_edited(world):
    org, owner, *_ = _assessed_org(world)
    report = world.client.post("/api/v1/reports", json={}, headers=world.headers(owner, org)).json()["report"]
    admin_url = os.environ.get("CYPHWARD_TEST_DATABASE_ADMIN_URL")
    if not admin_url:
        pytest.skip("needs the table owner connection")
    with psycopg.connect(admin_url) as owner_conn:
        with pytest.raises(psycopg.errors.RaiseException):
            owner_conn.execute("UPDATE reports SET html = 'edited' WHERE id = %s", (report["id"],))


# ── Reports: rendered from the snapshot, legacy labelled ──────────────────


def test_report_is_rendered_from_its_snapshot_and_references_it(world):
    org, owner, domain, *_ = _assessed_org(world)
    resp = world.client.post("/api/v1/reports", json={"domain_id": domain}, headers=world.headers(owner, org))
    assert resp.status_code == 201, resp.text
    report = resp.json()["report"]
    snap = _stored(world, report["snapshot_id"])
    assert report["integrity"] == "snapshot" and report["report_version"] == "cyphward-report-v2"
    html = world.rows("SELECT html FROM reports WHERE id = %s", (report["id"],))[0]["html"]
    assert f"assessment snapshot {snap['seq']}" in html and snap["content_sha256"][:12] in html
    assert "organisation-wide, not a score for this domain alone" in html
    assert report["summary"]["snapshot"]["sha256"] == snap["content_sha256"]
    assert len(world.rows("SELECT id FROM assessment_snapshots WHERE org_id = %s", (org,))) == 1


def test_legacy_reports_are_labelled_and_never_backfilled(world):
    org, owner, *_ = _assessed_org(world)
    rid = world.setup.execute("INSERT INTO reports (org_id, title, html) VALUES (%s, 'Old', '<p>old</p>') RETURNING id",
                              (org,)).fetchone()["id"]
    world.setup.commit()
    listing = world.client.get("/api/v1/reports", headers=world.headers(owner, org)).json()["reports"]
    old = next(r for r in listing if r["id"] == str(rid))
    assert old["integrity"] == "legacy" and "Legacy report" in old["integrity_label"] and old["snapshot_id"] is None
    one = world.client.get(f"/api/v1/reports/{rid}", headers=world.headers(owner, org)).json()["report"]
    assert one["integrity"] == "legacy"
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["n"] == 0


def test_a_retried_request_key_returns_the_first_report(world):
    org, owner, *_ = _assessed_org(world)
    first = world.client.post("/api/v1/reports", json={"request_key": "retry-key-0001"}, headers=world.headers(owner, org))
    second = world.client.post("/api/v1/reports", json={"request_key": "retry-key-0001"}, headers=world.headers(owner, org))
    assert first.status_code == 201 and second.status_code == 201
    assert second.json()["report"]["id"] == first.json()["report"]["id"] and second.json()["created"] is False
    assert world.rows("SELECT count(*) AS n FROM reports WHERE org_id = %s", (org,))[0]["n"] == 1
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["n"] == 1
    bad = world.client.post("/api/v1/reports", json={"request_key": "x"}, headers=world.headers(owner, org))
    assert bad.status_code == 422


# ── Tenants, roles, domains ──────────────────────────────────────────────


def test_another_organisations_snapshot_and_report_are_not_found(world):
    org_a, owner_a, *_ = _assessed_org(world)
    org_b, owner_b, *_ = _assessed_org(world)
    sid = _create(world, org_a, owner_a).json()["snapshot"]["id"]
    rid = world.client.post("/api/v1/reports", json={}, headers=world.headers(owner_a, org_a)).json()["report"]["id"]
    assert world.client.get(f"/api/v1/snapshots/{sid}", headers=world.headers(owner_b, org_b)).status_code == 404
    assert world.client.get(f"/api/v1/reports/{rid}", headers=world.headers(owner_b, org_b)).status_code == 404
    assert world.client.get("/api/v1/snapshots/not-a-uuid", headers=world.headers(owner_b, org_b)).status_code == 404
    assert world.client.get("/api/v1/snapshots", headers=world.headers(owner_b, org_b)).json()["total"] == 0
    # a member of B cannot read A's data by naming A's org
    assert world.client.get(f"/api/v1/snapshots/{sid}", headers=world.headers(owner_b, org_a)).status_code in (403, 404)


def test_the_database_refuses_a_report_that_points_at_another_organisations_snapshot(world):
    org_a, owner_a, *_ = _assessed_org(world)
    org_b = world.make_org()
    sid = _create(world, org_a, owner_a).json()["snapshot"]["id"]
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        world.setup.execute("INSERT INTO reports (org_id, title, snapshot_id) VALUES (%s, 'x', %s)", (org_b, sid))
    world.setup.rollback()


def test_domain_mismatch_is_refused(world):
    org_a, owner_a, *_ = _assessed_org(world)
    org_b, _, domain_b, *_ = _assessed_org(world)
    pending = world.make_domain(org_a, "pending.snapshot.test", verified=False)
    headers = world.headers(owner_a, org_a)
    assert world.client.post("/api/v1/reports", json={"domain_id": domain_b}, headers=headers).status_code == 404
    assert world.client.post("/api/v1/reports", json={"domain_id": pending}, headers=headers).status_code == 422
    assert world.client.post("/api/v1/reports", json={"domain_id": str(uuid4())}, headers=headers).status_code == 404
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org_a,))[0]["n"] == 0


def test_members_read_and_only_owners_and_admins_generate(world):
    org, owner, *_ = _assessed_org(world)
    member = world.make_person(org, "member")
    admin = world.make_person(org, "admin")
    assert _create(world, org, member).status_code == 403
    assert world.client.post("/api/v1/reports", json={}, headers=world.headers(member, org)).status_code == 403
    sid = _create(world, org, admin).json()["snapshot"]["id"]
    assert world.client.get("/api/v1/snapshots", headers=world.headers(member, org)).json()["total"] == 1
    assert world.client.get(f"/api/v1/snapshots/{sid}", headers=world.headers(member, org)).status_code == 200


def test_starter_reads_the_security_group_only(world):
    org, owner, *_ = _assessed_org(world, plan="starter")
    sid = _create(world, org, owner).json()["snapshot"]["id"]
    content = world.client.get(f"/api/v1/snapshots/{sid}", headers=world.headers(owner, org)).json()["snapshot"]["content"]
    assert content["compliance"]["locked"] is True and content["compliance"]["attestations"] == []
    assert {r["group"] for r in content["compliance"]["requirements"]} <= {"security"}
    assert _stored(world, sid)["content"]["compliance"].get("locked") is None  # stored whole, filtered on read


# ── Concurrency ──────────────────────────────────────────────────────────


def test_concurrent_generation_makes_one_snapshot_per_request(world):
    org, owner, *_ = _assessed_org(world)
    headers = world.headers(owner, org)

    def one(_):
        return world.client.post("/api/v1/snapshots", json={}, headers=headers)

    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(one, range(6)))
    assert [r.status_code for r in results] == [201] * 6, [r.text for r in results]
    seqs = sorted(r["seq"] for r in world.rows("SELECT seq FROM assessment_snapshots WHERE org_id = %s", (org,)))
    assert seqs == [1, 2, 3, 4, 5, 6]


def test_concurrent_requests_with_one_key_share_one_snapshot_and_one_report(world):
    org, owner, *_ = _assessed_org(world)
    headers = world.headers(owner, org)

    def one(_):
        return world.client.post("/api/v1/reports", json={"request_key": "same-key-0001"}, headers=headers)

    with ThreadPoolExecutor(5) as pool:
        results = list(pool.map(one, range(5)))
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert len({r.json()["report"]["id"] for r in results}) == 1
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["n"] == 1
    assert world.rows("SELECT count(*) AS n FROM reports WHERE org_id = %s", (org,))[0]["n"] == 1


def test_a_failed_report_insert_leaves_no_snapshot(world):
    org, owner, *_ = _assessed_org(world)
    from backend.app.snapshots import store as snapshots
    def boom(conn, snapshot):
        raise RuntimeError("render failed")
    with pytest.raises(RuntimeError):
        snapshots.create({"id": org, "name": "x"}, owner, on_insert=boom)
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["n"] == 0


# ── Unassessed ───────────────────────────────────────────────────────────


def test_an_organisation_with_no_scan_gets_an_honest_unassessed_snapshot_and_report(world):
    org = world.make_org()
    owner = world.make_person(org, "owner")
    world.make_domain(org, "never.snapshot.test")
    resp = world.client.post("/api/v1/reports", json={}, headers=world.headers(owner, org))
    assert resp.status_code == 201
    content = _stored(world, resp.json()["report"]["snapshot_id"])["content"]
    assert content["scoring"]["assessed"] is False and content["scoring"]["score"] is None
    assert content["scope"]["domains"][0]["scan_id"] is None
    assert all(r["status"] != "present" for r in content["compliance"]["requirements"])
    html = world.rows("SELECT html FROM reports WHERE id = %s", (resp.json()["report"]["id"],))[0]["html"].lower()
    assert "not assessed" in html and "never.snapshot.test: not scanned" in html


# ── Deletion ─────────────────────────────────────────────────────────────


def test_deleting_a_domain_keeps_the_snapshot_and_report(world):
    org, owner, domain, *_ = _assessed_org(world)
    report = world.client.post("/api/v1/reports", json={"domain_id": domain}, headers=world.headers(owner, org)).json()["report"]
    before = _stored(world, report["snapshot_id"])
    world.setup.execute("DELETE FROM domains WHERE id = %s AND org_id = %s", (domain, org))
    world.setup.commit()
    kept = world.rows("SELECT domain_id, html FROM reports WHERE id = %s", (report["id"],))[0]
    assert kept["domain_id"] is None and kept["html"]
    assert _stored(world, report["snapshot_id"])["content"] == before["content"]


def test_deleting_a_profile_clears_created_by_without_touching_content(world):
    org, owner, *_ = _assessed_org(world)
    admin = world.make_person(org, "admin")
    sid = _create(world, org, admin).json()["snapshot"]["id"]
    before = _stored(world, sid)
    world.setup.execute("DELETE FROM organization_members WHERE user_id = %s", (admin,))
    world.setup.execute("DELETE FROM profiles WHERE id = %s", (admin,))
    world.setup.commit()
    after = _stored(world, sid)
    assert after["created_by"] is None and after["content"] == before["content"]


def test_deleting_the_organisation_removes_its_snapshots_and_reports(world):
    org, owner, *_ = _assessed_org(world)
    other, other_owner, *_ = _assessed_org(world)
    world.client.post("/api/v1/reports", json={}, headers=world.headers(owner, org))
    world.client.post("/api/v1/reports", json={}, headers=world.headers(other_owner, other))
    world.setup.execute("DELETE FROM organizations WHERE id = %s", (org,))
    world.setup.commit()
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["n"] == 0
    assert world.rows("SELECT count(*) AS n FROM reports WHERE org_id = %s", (org,))[0]["n"] == 0
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (other,))[0]["n"] == 1


# ── Claim language ───────────────────────────────────────────────────────

BANNED = ("compliant", "certified", "satisfies", "satisfied", "passes audit", "pass the audit", "compliance score",
          "fully meets", "meets the requirement", "is met", "partial compliance", "fully compliant", "is compliant",
          "satisfy ndpa", "ndpa 2023 compliant", "cbn compliant")


def test_snapshot_content_and_report_never_claim_compliance(world):
    org, owner, *_ = _assessed_org(world)
    report = world.client.post("/api/v1/reports", json={}, headers=world.headers(owner, org)).json()["report"]
    content = json.dumps(_stored(world, report["snapshot_id"])["content"]).lower()
    html = world.rows("SELECT html FROM reports WHERE id = %s", (report["id"],))[0]["html"].lower()
    for phrase in BANNED:
        assert phrase not in content, f"snapshot content: {phrase}"
        assert phrase not in html, f"report html: {phrase}"


# ── Quota: a snapshot is one report-sized unit of the monthly reports quota ───────────────────────────


def _limit(monkeypatch, n):
    from backend.app.core import plans
    monkeypatch.setitem(plans.PLANS["growth"], "monthly_reports", n)


def _usage(org):
    from backend.app.core.plans import usage_for_org
    return usage_for_org(org)["monthly_reports"]


def test_snapshots_count_against_the_monthly_reports_quota(world, monkeypatch):
    _limit(monkeypatch, 2)
    org, owner, *_ = _assessed_org(world)
    assert _create(world, org, owner).status_code == 201
    assert _create(world, org, owner).status_code == 201
    blocked = _create(world, org, owner)
    assert blocked.status_code == 402 and "quota reached" in blocked.json()["detail"]
    assert _usage(org) == 2
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["n"] == 2
    assert world.rows("SELECT count(*) AS n FROM audit_log WHERE org_id = %s AND action = 'snapshot.created'", (org,))[0]["n"] == 2


def test_a_retried_request_key_is_not_charged_twice(world, monkeypatch):
    _limit(monkeypatch, 1)
    org, owner, *_ = _assessed_org(world)
    first = _create(world, org, owner, request_key="retry-key-0001")
    again = _create(world, org, owner, request_key="retry-key-0001")
    assert first.status_code == 201 and again.status_code == 201 and again.json()["created"] is False
    assert _usage(org) == 1


def test_a_report_and_its_snapshot_count_once(world, monkeypatch):
    _limit(monkeypatch, 5)
    org, owner, *_ = _assessed_org(world)
    assert world.client.post("/api/v1/reports", json={}, headers=world.headers(owner, org)).status_code == 201
    assert _usage(org) == 1, "the report counts; the snapshot it belongs to is not added again"
    assert _create(world, org, owner).status_code == 201
    assert _usage(org) == 2


def test_the_last_unit_goes_to_exactly_one_of_two_concurrent_requests(world, monkeypatch):
    _limit(monkeypatch, 1)
    org, owner, *_ = _assessed_org(world)
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(f.result().status_code for f in [pool.submit(_create, world, org, owner) for _ in range(2)])
    assert codes == [201, 402]
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["n"] == 1


def test_another_organisations_snapshots_do_not_use_up_this_ones_quota(world, monkeypatch):
    _limit(monkeypatch, 1)
    org_a, owner_a, *_ = _assessed_org(world, name="Quota A")
    org_b, owner_b, *_ = _assessed_org(world, name="Quota B")
    assert _create(world, org_a, owner_a).status_code == 201
    assert _create(world, org_b, owner_b).status_code == 201
    assert _create(world, org_a, owner_a).status_code == 402


# ── Retention: a recorded period, 36 months by default, owner-set ─────────────────────────────────────


def test_retention_defaults_to_three_years_and_each_snapshot_shows_its_date(world):
    from datetime import datetime
    org, owner, *_ = _assessed_org(world)
    made = _create(world, org, owner).json()["snapshot"]
    listing = world.client.get("/api/v1/snapshots", headers=world.headers(owner, org)).json()
    assert listing["retention_months"] == 36 and "36 months" in listing["retention"]
    created = datetime.fromisoformat(made["created_at"])
    until = datetime.fromisoformat(made["retain_until"])
    assert until.year == created.year + 3 and until.month == created.month
    assert "never deletes" in listing["retention"] and "Names of answer owners" in listing["retention"]


def test_only_the_owner_sets_retention_and_it_is_range_checked_and_audited(world):
    org, owner, *_ = _assessed_org(world)
    admin, member = world.make_person(org, "admin"), world.make_person(org, "member")
    put = lambda user, months: world.client.put("/api/v1/snapshots/retention", json={"months": months}, headers=world.headers(user, org))
    assert put(member, 60).status_code == 403 and put(admin, 60).status_code == 403
    for bad in (11, 121, 0, -5):
        assert put(owner, bad).status_code == 422
    assert world.client.put("/api/v1/snapshots/retention", json={"months": "sixty"}, headers=world.headers(owner, org)).status_code == 422
    assert put(owner, 60).status_code == 200
    assert world.rows("SELECT evidence_retention_months AS m FROM organizations WHERE id = %s", (org,))[0]["m"] == 60
    audit = world.rows("SELECT metadata FROM audit_log WHERE org_id = %s AND action = 'snapshot.retention_set'", (org,))
    assert len(audit) == 1 and audit[0]["metadata"] == {"previous_months": 36, "months": 60}
    assert world.client.get("/api/v1/snapshots", headers=world.headers(member, org)).json()["retention_months"] == 60


def test_retention_is_per_organisation_and_the_database_checks_the_range(world):
    org_a, owner_a, *_ = _assessed_org(world, name="Retention A")
    org_b, owner_b, *_ = _assessed_org(world, name="Retention B")
    assert world.client.put("/api/v1/snapshots/retention", json={"months": 24}, headers=world.headers(owner_a, org_a)).status_code == 200
    assert world.rows("SELECT evidence_retention_months AS m FROM organizations WHERE id = %s", (org_b,))[0]["m"] == 36
    with pytest.raises(psycopg.errors.CheckViolation):
        world.setup.execute("UPDATE organizations SET evidence_retention_months = 6 WHERE id = %s", (org_a,))
    world.setup.rollback()


def test_add_months_handles_month_ends_and_leap_years():
    from datetime import datetime, timezone
    from backend.app.snapshots.store import add_months
    utc = lambda *a: datetime(*a, tzinfo=timezone.utc)
    assert add_months(utc(2026, 1, 31), 1) == utc(2026, 2, 28)
    assert add_months(utc(2027, 12, 31), 2) == utc(2028, 2, 29)
    assert add_months(utc(2026, 10, 18), 36) == utc(2029, 10, 18)
    assert add_months(utc(2028, 2, 29), 12) == utc(2029, 2, 28)
    assert add_months(utc(2026, 11, 30), 3) == utc(2027, 2, 28)


# ── Review round 1: the shared pool, honest errors, and the gaps the reviewer named ───────────────────


def test_a_busy_build_slot_gives_a_clean_503_and_writes_nothing(world, monkeypatch):
    import threading
    from backend.app.snapshots import store as snapshot_store
    monkeypatch.setattr(snapshot_store, "_BUILD_SLOTS", threading.BoundedSemaphore(1))
    monkeypatch.setattr(snapshot_store, "BUSY_WAIT_SECONDS", 0.2)
    org, owner, *_ = _assessed_org(world)
    snapshot_store._BUILD_SLOTS.acquire()
    busy = _create(world, org, owner)
    assert busy.status_code == 503 and busy.headers["Retry-After"] == "5"
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["n"] == 0
    snapshot_store._BUILD_SLOTS.release()
    assert _create(world, org, owner).status_code == 201


def test_a_held_organisation_lock_is_waited_for_only_briefly(world, monkeypatch):
    import time
    from backend.app.snapshots import store as snapshot_store
    monkeypatch.setattr(snapshot_store, "LOCK_WAIT_MS", 300)
    org, owner, *_ = _assessed_org(world)
    holder = psycopg.connect(world.url, row_factory=dict_row)
    try:
        holder.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"snapshot:{org}",))
        started = time.monotonic()
        busy = _create(world, org, owner)
        assert busy.status_code == 503 and time.monotonic() - started < 5
    finally:
        holder.rollback()
        holder.close()
    assert _create(world, org, owner).status_code == 201


def test_at_most_a_few_builds_run_at_once_so_waiters_never_hold_pool_connections(world, monkeypatch):
    import threading
    import time
    from backend.app.snapshots import builder, store as snapshot_store
    orgs = [_assessed_org(world, name=f"Pool {i}")[:2] for i in range(8)]
    running, peak, guard = [0], [0], threading.Lock()
    real_build = builder.build

    def counting_build(org, now=None):
        with guard:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.15)
        try:
            return real_build(org, now)
        finally:
            with guard:
                running[0] -= 1

    monkeypatch.setattr(builder, "build", counting_build)
    monkeypatch.setattr(snapshot_store, "BUSY_WAIT_SECONDS", 30)
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = [f.result().status_code for f in [pool.submit(_create, world, o, u) for o, u in orgs]]
    assert codes == [201] * 8
    assert 1 < peak[0] <= 3, f"builds ran {peak[0]} at once; the agreed ceiling is 3"


def test_data_that_keeps_changing_is_a_409_and_leaves_nothing(world, monkeypatch):
    from itertools import count
    from backend.app.snapshots import builder
    ticker = count()
    monkeypatch.setattr(builder, "fence", lambda org_id: str(next(ticker)))
    org, owner, *_ = _assessed_org(world)
    assert _create(world, org, owner).status_code == 409
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["n"] == 0


def test_retrying_a_report_at_the_quota_limit_returns_the_first_report(world, monkeypatch):
    _limit(monkeypatch, 1)
    org, owner, *_ = _assessed_org(world)
    body = {"request_key": "report-retry-0001"}
    first = world.client.post("/api/v1/reports", json=body, headers=world.headers(owner, org))
    again = world.client.post("/api/v1/reports", json=body, headers=world.headers(owner, org))
    assert first.status_code == 201 and again.status_code == 201
    assert again.json()["created"] is False and again.json()["report"]["id"] == first.json()["report"]["id"]
    assert world.client.post("/api/v1/reports", json={}, headers=world.headers(owner, org)).status_code == 402


def test_owner_names_recorded_at_answer_time_stay_in_the_issued_snapshot(world):
    org, owner, *_ = _assessed_org(world)
    store.record({"id": org}, owner, question_key="breach.response_plan", answer={"value": "yes"}, owner_user_id=owner)
    made = _create(world, org, owner).json()["snapshot"]
    attestations = _stored(world, made["id"])["content"]["compliance"]["attestations"]
    assert [a["owner_name"] for a in attestations] == ["Snapshot Tester"]


def test_retain_until_follows_the_organisations_retention_period(world):
    from datetime import datetime
    org, owner, *_ = _assessed_org(world)
    _create(world, org, owner)
    put = world.client.put("/api/v1/snapshots/retention", json={"months": 12}, headers=world.headers(owner, org))
    assert put.status_code == 200
    listing = world.client.get("/api/v1/snapshots", headers=world.headers(owner, org)).json()
    only = listing["snapshots"][0]
    created, until = datetime.fromisoformat(only["created_at"]), datetime.fromisoformat(only["retain_until"])
    assert listing["retention_months"] == 12 and until.year == created.year + 1 and until.month == created.month
    assert world.client.get("/api/v1/snapshots/retention", headers=world.headers(owner, org)).json()["retention_months"] == 12


def test_the_snapshot_list_reports_the_real_total_and_a_bad_id_is_a_404(world):
    org, owner, *_ = _assessed_org(world)
    for _ in range(3):
        assert _create(world, org, owner).status_code == 201
    listing = world.client.get("/api/v1/snapshots", headers=world.headers(owner, org)).json()
    assert listing["total"] == 3 and len(listing["snapshots"]) == 3
    assert world.client.get("/api/v1/snapshots/not-a-uuid", headers=world.headers(owner, org)).status_code == 404


def test_every_content_column_of_an_issued_report_is_guarded(world):
    org, owner, *_ = _assessed_org(world)
    other = world.client.post("/api/v1/reports", json={}, headers=world.headers(owner, org)).json()["report"]
    report = world.client.post("/api/v1/reports", json={}, headers=world.headers(owner, org)).json()["report"]
    admin_url = os.environ.get("CYPHWARD_TEST_DATABASE_ADMIN_URL")
    if not admin_url:
        pytest.skip("needs the table owner connection")
    with psycopg.connect(admin_url) as owner_conn:
        for change in ("title = 'edited'", "summary = '{}'::jsonb", "report_version = 'edited'",
                       f"snapshot_id = '{other['snapshot_id']}'"):
            with pytest.raises(psycopg.errors.RaiseException):
                owner_conn.execute(f"UPDATE reports SET {change} WHERE id = %s", (report["id"],))
            owner_conn.rollback()


def test_retention_text_and_report_labels_never_claim_compliance(world):
    from backend.app.api.snapshots import retention_note
    org, owner, *_ = _assessed_org(world)
    report = world.client.post("/api/v1/reports", json={}, headers=world.headers(owner, org)).json()["report"]
    texts = [retention_note(36).lower(), retention_note(120).lower(), report["integrity_label"].lower(),
             json.dumps(world.client.get("/api/v1/snapshots", headers=world.headers(owner, org)).json()).lower()]
    for text in texts:
        for phrase in BANNED + ("certification", "adequate", "adequacy", "guarantee", "meets the requirement"):
            assert phrase not in text, phrase
