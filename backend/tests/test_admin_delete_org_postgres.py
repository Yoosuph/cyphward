"""Delete organisation (docs/admin-delete-org/README.md) against the isolated, migrated PostgreSQL database, as the
real app role.

* Soft delete hides the organisation from its customers (404, gone from sign-in and their lists) and from the owner's
  lists by default, cancels its queued scans, and keeps the scheduled sweep and the worker claim away from it.
* Restore works inside the 30-day window (back to the status it had) and is refused after it.
* Purge is refused inside the window and while any compliance record is retained (counts only), works after the
  window with the name and the word DELETE, removes the tenant data in one transaction and queues stored files.
* A wrong name or word changes nothing; non-owners are refused; the demo and InnovaTech organisations are refused
  unless the override is set; an active paid subscription refuses the soft delete; every step is audited.
* The migration: added columns, replaced CHECK, index and the exact grants, applied twice on a Supabase-style
  database (the phase 1 grants test pattern).

Reuses the owner-views fixtures (an owner, a customer who owns "Views Org <tag>", a verified domain and a queued
scan) and the phase 1 and phase 2 helpers.
"""
import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from backend.app.core import org_guard
from backend.app.core.demo_org import DEMO_ORG_ID
from backend.app.main import app
from backend.app.snapshots.store import add_months
from test_admin_phase2_postgres import sweep  # noqa: F401 (fixture)
from test_owner_phase1_postgres import OWNER, REASON, _admin, _customer_token, _grants, more, scratch_db  # noqa: F401
from test_owner_views_postgres import ORIGIN, _signed_in, urls, world  # noqa: F401 (fixtures)
from test_suspension_gate import gated_routes

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
DELETE_MIGRATION = MIGRATIONS / "20261101100000_org_delete.sql"
SUSPENSION_MIGRATION = MIGRATIONS / "20261030100000_organization_suspension.sql"
SHA = "a" * 64


def _named(world, name=None):
    return {"reason": REASON, "confirm_name": world["org_name"] if name is None else name}


def _org_url(world, action=""):
    return f"{OWNER}/organizations/{world['org']}" + (f"/{action}" if action else "")


def _delete(client, world, expect=200):
    resp = client.post(_org_url(world, "delete"), json=_named(world), headers=ORIGIN)
    assert resp.status_code == expect, resp.text
    return resp


def _status(urls, org_id):
    with _admin(urls) as conn:
        row = conn.execute("SELECT status, deleted_at, deleted_by FROM organization_suspensions WHERE org_id = %s",
                           (org_id,)).fetchone()
    return row


def _org_exists(urls, org_id):
    with _admin(urls) as conn:
        return conn.execute("SELECT 1 FROM organizations WHERE id = %s", (org_id,)).fetchone() is not None


def _audits(urls, world, action):
    with _admin(urls) as conn:
        return conn.execute(
            "SELECT outcome, target_id, metadata FROM owner_audit WHERE actor_user_id = %s AND action = %s "
            "ORDER BY created_at", (world["owner"], action)).fetchall()


def _age_deletion(urls, org_id, days):
    """Move deleted_at back, as if the soft delete happened `days` ago."""
    with _admin(urls) as conn:
        conn.execute("UPDATE organization_suspensions SET deleted_at = now() - make_interval(days => %s) "
                     "WHERE org_id = %s AND status = 'deleted'", (days, org_id))


def _purge_body(world, name=None, word="DELETE"):
    return {**_named(world, name), "confirm_word": word}


def _customer(world, urls, with_header=True):
    token = _customer_token(world, urls)
    headers = {"Authorization": f"Bearer {token}"}
    if with_header:
        headers["X-Organization-Id"] = world["org"]
    return TestClient(app), headers


# ── Soft delete ────────────────────────────────────────────────────────────
def test_soft_delete_hides_the_organisation_from_customers(world, more, urls):
    owner = _signed_in(world)
    customer, headers = _customer(world, urls)
    assert customer.get("/api/v1/organizations/current", headers=headers).status_code == 200
    resp = _delete(owner, world)
    body = resp.json()
    assert body["deleted"] is True and body["queued_scans_cancelled"] == 1
    row = _status(urls, world["org"])
    assert row["status"] == "deleted" and row["deleted_at"] is not None and str(row["deleted_by"]) == world["owner"]

    # Reads answer 404, with the organisation named or not; sign-in no longer offers it.
    for path in ("/api/v1/organizations/current", "/api/v1/scans", f"/api/v1/scans/{world['scan']}",
                 "/api/v1/findings", "/api/v1/domains", "/api/v1/members", "/api/v1/overview", "/api/v1/reports",
                 "/api/v1/compliance/overview", "/api/v1/settings", "/api/v1/snapshots", "/api/v1/packs"):
        for h in (headers, {"Authorization": headers["Authorization"], "X-Organization-Id": f"views-{world['tag']}"},
                  {"Authorization": headers["Authorization"]}):
            r = customer.get(path, headers=h)
            assert r.status_code == 404, (path, h.keys(), r.status_code, r.text[:200])
            assert r.json()["detail"] == "Organization not found."
    boot = customer.get("/api/v1/auth/bootstrap", headers={"Authorization": headers["Authorization"]})
    assert boot.status_code == 200 and boot.json()["memberships"] == []
    assert customer.get("/api/v1/organizations", headers={"Authorization": headers["Authorization"]}).json() == []

    # Every gated write is refused (404 before the suspension gate), creating a new organisation too.
    leaks = []
    for method, path in gated_routes():
        if "/compliance/reviewer/" in path:
            continue  # those need a reviewer grant (test_reviewer_access_ends_with_the_deletion)
        url = re.sub(r"\{[^}]+\}", str(uuid4()), path)
        r = customer.request(method, url, headers=headers, json={})
        if path == "/api/v1/organizations" and method == "POST":
            ok = r.status_code == 403 and "has been closed by Cyphward" in r.text
        else:
            ok = r.status_code == 404
        if not ok:
            leaks.append((method, path, r.status_code, r.text[:120]))
    assert not leaks, leaks
    with _admin(urls) as conn:
        assert conn.execute("SELECT status FROM scans WHERE id = %s", (world["scan"],)).fetchone()["status"] == "cancelled"
        rows = conn.execute("SELECT action FROM audit_log WHERE org_id = %s AND user_id = %s AND action <> 'scan.launched'",
                            (world["org"], world["customer"])).fetchall()
    assert rows == [], rows
    audit = _audits(urls, world, "owner.action.delete_org")
    assert [a["outcome"] for a in audit] == ["success"]
    meta = audit[0]["metadata"]
    assert meta["reason"] == REASON and meta["from"] == "active" and meta["to"] == "deleted"
    assert meta["queued_scans_cancelled"] == [world["scan"]]


def test_invitation_to_a_deleted_organisation_answers_404(world, more, urls):
    from backend.app.core import suspension
    owner = _signed_in(world)
    _delete(owner, world)
    with pytest.raises(Exception) as refused:
        suspension.ensure_active(world["org"])
    assert getattr(refused.value, "status_code", None) == 404


def test_owner_lists_hide_deleted_organisations_by_default(world, more, urls):
    owner = _signed_in(world)
    with _admin(urls) as conn:
        conn.execute("INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, "
                     "current_period_end) VALUES (%s, 'growth', 'canceled', 'manual', now() - interval '40 days', "
                     "now() - interval '10 days')", (world["org"],))
    _delete(owner, world)
    q = {"q": world["org_name"]}
    assert owner.get(f"{OWNER}/organizations", params=q).json()["items"] == []
    only = owner.get(f"{OWNER}/organizations", params={**q, "deleted": "only"}).json()
    assert [o["id"] for o in only["items"]] == [world["org"]] and only["items"][0]["deleted"] is True
    assert [o["id"] for o in owner.get(f"{OWNER}/organizations", params={**q, "deleted": "include"}).json()["items"]] \
        == [world["org"]]
    assert owner.get(f"{OWNER}/organizations", params={**q, "deleted": "yes"}).status_code == 422
    assert owner.get(f"{OWNER}/subscriptions", params=q).json()["items"] == []
    assert len(owner.get(f"{OWNER}/subscriptions", params={**q, "deleted": "include"}).json()["items"]) == 1
    assert owner.get(f"{OWNER}/scans", params=q).json()["items"] == []
    assert len(owner.get(f"{OWNER}/scans", params={**q, "deleted": "include"}).json()["items"]) == 1
    users = owner.get(f"{OWNER}/users", params={"q": world["customer_email"]}).json()["items"]
    assert users and users[0]["memberships"] == []
    csv_default = owner.get(f"{OWNER}/exports/organizations.csv", params=q)
    csv_deleted = owner.get(f"{OWNER}/exports/organizations.csv", params={**q, "deleted": "only"})
    assert world["org"] not in csv_default.text and world["org"] in csv_deleted.text
    # The organisation page still opens for the owner, with its lifecycle.
    detail = owner.get(_org_url(world)).json()["organization"]
    assert detail["deleted"] is True and detail["status"] == "deleted" and detail["restorable"] is True
    assert detail["purge_window_passed"] is False and detail["deleted_by_email"] == world["owner_email"]
    with _admin(urls) as conn:
        conn.execute("DELETE FROM subscriptions WHERE org_id = %s", (world["org"],))


def test_scheduled_scans_and_worker_claims_skip_a_deleted_organisation(world, more, urls, sweep):
    from backend.app.core import scan_execution
    from backend.app.core.scan_admission import admit_scan
    run, sent = sweep
    owner = _signed_in(world)
    _delete(owner, world)
    queued = str(uuid4())
    with _admin(urls) as conn:  # a queued scan written after the delete (it cannot be, but the claim must not take it)
        conn.execute("INSERT INTO scans (id, org_id, domain_id, status, scan_type) "
                     "VALUES (%s,%s,%s,'queued','EXTERNAL_ASSESSMENT')", (queued, world["org"], world["domain"]))
    assert scan_execution.claim_recon("delete-test-worker", "worker", 60, scan_id=queued) is None
    assert admit_scan(world["org"], world["domain"], request_scope="test:delete").outcome == "suspended"
    run(date(2099, 2, 1))
    assert world["org"] not in {str(e["organization_id"]) for e in sent}
    with _admin(urls) as conn:
        conn.execute("DELETE FROM scans WHERE id = %s", (queued,))


def test_a_running_scan_is_left_to_finish(world, more, urls):
    from backend.app.core import scan_execution
    held = scan_execution.claim_recon("delete-test-worker", "worker", 60, scan_id=world["scan"])
    assert held is not None
    owner = _signed_in(world)
    assert _delete(owner, world).json()["queued_scans_cancelled"] == 0
    with _admin(urls) as conn:
        row = conn.execute("SELECT status, claim_token FROM scans WHERE id = %s", (world["scan"],)).fetchone()
    assert row["status"] == "running" and row["claim_token"] == held["claim_token"], "the running claim is not fenced"


def test_reviewer_access_ends_with_the_deletion(world, more, urls):
    from backend.app.compliance import reviewer
    reviewer_id = str(uuid4())
    email = f"rev-{world['tag']}@reviewer.test"
    with _admin(urls) as conn:
        conn.execute("INSERT INTO profiles (id, email, full_name, role, provider, email_verified_at) "
                     "VALUES (%s,%s,'Reviewer','Member','email',now())", (reviewer_id, email))
        conn.execute("INSERT INTO compliance_reviewer_grants (org_id, reviewer_email, purpose, granted_by, expires_at) "
                     "VALUES (%s,%s,'Annual review',%s, now() + interval '10 days')",
                     (world["org"], email, world["customer"]))
        profile = conn.execute("SELECT * FROM profiles WHERE id = %s", (reviewer_id,)).fetchone()
    from backend.app.core import sessions
    sid = sessions.issue_session(profile)
    session_id = sid.get("session_id") or sid.get("sid")
    if session_id is None:
        with _admin(urls) as conn:
            session_id = str(conn.execute("SELECT id FROM auth_sessions WHERE user_id = %s ORDER BY created_at DESC "
                                          "LIMIT 1", (reviewer_id,)).fetchone()["id"])
    assert len(reviewer.active_grants(reviewer_id, session_id)) == 1
    owner = _signed_in(world)
    _delete(owner, world)
    assert reviewer.active_grants(reviewer_id, session_id) == []
    with _admin(urls) as conn:
        conn.execute("DELETE FROM compliance_reviewer_grants WHERE org_id = %s", (world["org"],))
        conn.execute("DELETE FROM auth_sessions WHERE user_id = %s", (reviewer_id,))
        conn.execute("DELETE FROM profiles WHERE id = %s", (reviewer_id,))


def test_other_owner_actions_refuse_a_deleted_organisation(world, more, urls):
    owner = _signed_in(world)
    _delete(owner, world)
    named = _named(world)
    for action, body in (("suspend", named), ("unsuspend", named), ("plan", {**named, "plan": "starter"}),
                         ("trial", {**named, "days": 7}), (f"members/{more['member']}/remove", named),
                         ("members/restore", {**named, "audit_id": str(uuid4())}), ("delete", named)):
        resp = owner.post(_org_url(world, action), json=body, headers=ORIGIN)
        assert resp.status_code == 409, (action, resp.text)
    assert _status(urls, world["org"])["status"] == "deleted", "nothing flipped the deletion"
    assert [a["outcome"] for a in _audits(urls, world, "owner.action.suspend")] == ["rejected"]
    assert [a["outcome"] for a in _audits(urls, world, "owner.action.delete_org")] == ["success", "rejected"]


# ── Restore ────────────────────────────────────────────────────────────────
def test_restore_within_the_window_brings_it_back(world, more, urls):
    owner = _signed_in(world)
    customer, headers = _customer(world, urls)
    _delete(owner, world)
    _age_deletion(urls, world["org"], 29)
    resp = owner.post(_org_url(world, "restore"), json=_named(world), headers=ORIGIN)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    row = _status(urls, world["org"])
    assert row["status"] == "active" and row["deleted_at"] is None and row["deleted_by"] is None
    assert customer.get("/api/v1/organizations/current", headers=headers).status_code == 200
    assert owner.get(f"{OWNER}/organizations", params={"q": world["org_name"]}).json()["total"] == 1
    audit = _audits(urls, world, "owner.action.restore_org")
    assert [a["outcome"] for a in audit] == ["success"] and audit[0]["metadata"]["to"] == "active"
    assert owner.post(_org_url(world, "restore"), json=_named(world), headers=ORIGIN).status_code == 409


def test_a_suspended_organisation_is_restored_suspended(world, more, urls):
    owner = _signed_in(world)
    assert owner.post(_org_url(world, "suspend"), json=_named(world), headers=ORIGIN).status_code == 200
    _delete(owner, world)
    assert _audits(urls, world, "owner.action.delete_org")[0]["metadata"]["from"] == "suspended"
    resp = owner.post(_org_url(world, "restore"), json=_named(world), headers=ORIGIN)
    assert resp.status_code == 200 and resp.json()["status"] == "suspended"
    assert _status(urls, world["org"])["status"] == "suspended"


def test_restore_is_refused_after_the_window(world, more, urls):
    owner = _signed_in(world)
    _delete(owner, world)
    _age_deletion(urls, world["org"], 31)
    resp = owner.post(_org_url(world, "restore"), json=_named(world), headers=ORIGIN)
    assert resp.status_code == 409 and "restore window" in resp.json()["detail"]
    assert _status(urls, world["org"])["status"] == "deleted"
    assert [a["outcome"] for a in _audits(urls, world, "owner.action.restore_org")] == ["rejected"]
    detail = owner.get(_org_url(world)).json()["organization"]
    assert detail["restorable"] is False and detail["purge_window_passed"] is True


# ── Purge ──────────────────────────────────────────────────────────────────
def test_purge_is_refused_inside_the_window(world, more, urls):
    owner = _signed_in(world)
    _delete(owner, world)
    _age_deletion(urls, world["org"], 29)
    resp = owner.post(_org_url(world, "purge"), json=_purge_body(world), headers=ORIGIN)
    assert resp.status_code == 409 and "has not passed yet" in resp.json()["detail"]
    assert _org_exists(urls, world["org"])
    assert [a["outcome"] for a in _audits(urls, world, "owner.action.purge_org")] == ["rejected"]


def test_purge_is_refused_for_an_organisation_that_is_not_deleted(world, more, urls):
    owner = _signed_in(world)
    resp = owner.post(_org_url(world, "purge"), json=_purge_body(world), headers=ORIGIN)
    assert resp.status_code == 409 and resp.json()["detail"] == "This organization is not deleted. Nothing was changed."
    assert _org_exists(urls, world["org"])


def _compliance_records(urls, world, age: str, retention_months: int = 12):
    """One reviewer grant (with a practitioner review and a clause verification), a snapshot and a pack on it, a
    document with an approval, and an evidence file, all dated `age` ago. Written as the database owner with
    triggers off, since the guards refuse back-dated or post-expiry rows (they stay on for the purge itself)."""
    org = world["org"]
    ids = {k: str(uuid4()) for k in ("grant", "snapshot", "pack", "document", "file", "reviewer")}
    with _admin(urls) as conn:
        conn.execute("UPDATE organizations SET evidence_retention_months = %s WHERE id = %s", (retention_months, org))
        conn.execute("INSERT INTO profiles (id, email, full_name, role, provider, email_verified_at) "
                     "VALUES (%s,%s,'Reviewer','Member','email',now())",
                     (ids["reviewer"], f"rev-{ids['reviewer'][:8]}@reviewer.test"))
        conn.execute("SET session_replication_role = replica")
        try:
            at = f"now() - interval '{age}'"
            conn.execute(f"INSERT INTO compliance_reviewer_grants (id, org_id, reviewer_email, purpose, granted_by, "
                         f"granted_at, expires_at) VALUES (%s,%s,%s,'Review',%s,{at},{at} + interval '30 days')",
                         (ids["grant"], org, f"rev-{ids['reviewer'][:8]}@reviewer.test", world["customer"]))
            conn.execute(f"INSERT INTO compliance_practitioner_reviews (org_id, requirement_key, grant_id, "
                         f"reviewer_user_id, reviewer_name, reviewed_at, outcome, reviewer_domain) "
                         f"VALUES (%s,'ndpa.s24',%s,%s,'Reviewer',{at} + interval '1 day','reviewed','reviewer.test')",
                         (org, ids["grant"], ids["reviewer"]))
            conn.execute(f"INSERT INTO compliance_clause_verifications (org_id, requirement_key, verified, grant_id, "
                         f"reviewer_user_id, reviewer_name, verified_at, reviewer_domain) "
                         f"VALUES (%s,'ndpa.s24',true,%s,%s,'Reviewer',{at} + interval '1 day','reviewer.test')",
                         (org, ids["grant"], ids["reviewer"]))
            conn.execute(f"INSERT INTO assessment_snapshots (id, org_id, seq, schema_version, content, content_sha256, "
                         f"created_at) VALUES (%s,%s,1,1,'{{}}'::jsonb,%s,{at})", (ids["snapshot"], org, SHA))
            conn.execute(f"INSERT INTO evidence_packs (id, org_id, snapshot_id, kind, pack_version, issued_at, html, "
                         f"html_sha256, pdf, pdf_sha256) VALUES (%s,%s,%s,'readiness_pack','t',{at},'<p>x</p>',%s,"
                         f"'\\x00'::bytea,%s)", (ids["pack"], org, ids["snapshot"], SHA, SHA))
            conn.execute(f"INSERT INTO compliance_documents (id, org_id, kind, version, generated_at, generator, "
                         f"inputs_hash, text_sha256, text, questionnaire_version) VALUES (%s,%s,'privacy_policy',1,"
                         f"{at},'template',%s,%s,'Draft — not legal advice. Text.','t')",
                         (ids["document"], org, SHA, SHA))
            conn.execute(f"INSERT INTO compliance_document_approvals (org_id, document_id, approved_at, text_sha256, "
                         f"open_placeholders) VALUES (%s,%s,{at} + interval '1 day',%s,0)", (org, ids["document"], SHA))
            conn.execute(f"INSERT INTO compliance_evidence_files (id, org_id, question_key, display_name, content_type, "
                         f"size_bytes, sha256, storage_path, uploaded_at) VALUES (%s,%s,'q1','policy.pdf',"
                         f"'application/pdf',10,%s,%s,{at})", (ids["file"], org, SHA, f"org/{org}/{ids['file']}"))
        finally:
            conn.execute("SET session_replication_role = origin")
    return ids


def _cleanup_reviewer(urls, ids):
    with _admin(urls) as conn:
        conn.execute("DELETE FROM profiles WHERE id = %s", (ids["reviewer"],))
        conn.execute("DELETE FROM compliance_evidence_purge_queue WHERE org_id NOT IN (SELECT id FROM organizations)")


def test_purge_is_refused_while_records_are_retained_and_shows_counts(world, more, urls):
    ids = _compliance_records(urls, world, "6 months", retention_months=12)
    owner = _signed_in(world)
    _delete(owner, world)
    _age_deletion(urls, world["org"], 31)
    resp = owner.post(_org_url(world, "purge"), json=_purge_body(world), headers=ORIGIN)
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "retention_hold" and detail["retention_months"] == 12
    assert detail["counts"] == {"reviewer_grants": 1, "packs": 1, "snapshots": 1, "documents": 1, "evidence_files": 1}
    assert detail["message"].startswith("Some records of this organization are still inside")
    assert "ndpa" not in resp.text and "policy.pdf" not in resp.text, "counts only, no record contents"
    assert _org_exists(urls, world["org"])
    audit = _audits(urls, world, "owner.action.purge_org")
    assert [a["outcome"] for a in audit] == ["rejected"]
    assert audit[0]["metadata"]["detail"]["counts"]["packs"] == 1
    with _admin(urls) as conn:
        assert conn.execute("SELECT count(*) AS n FROM compliance_evidence_purge_queue WHERE org_id = %s",
                            (world["org"],)).fetchone()["n"] == 0, "a refusal queues nothing"
    _cleanup_reviewer(urls, ids)


def test_one_retained_record_type_is_enough_to_refuse(world, more, urls):
    ids = _compliance_records(urls, world, "13 months", retention_months=12)
    with _admin(urls) as conn:  # one recent snapshot: the rest is past its period
        conn.execute("INSERT INTO assessment_snapshots (org_id, seq, schema_version, content, content_sha256, created_at) "
                     "VALUES (%s, 2, 1, '{}'::jsonb, %s, now() - interval '11 months')", (world["org"], SHA))
    owner = _signed_in(world)
    _delete(owner, world)
    _age_deletion(urls, world["org"], 31)
    resp = owner.post(_org_url(world, "purge"), json=_purge_body(world), headers=ORIGIN)
    assert resp.status_code == 409
    assert resp.json()["detail"]["counts"] == {"reviewer_grants": 0, "packs": 0, "snapshots": 1, "documents": 0,
                                               "evidence_files": 0}
    _cleanup_reviewer(urls, ids)


def test_purge_after_the_window_with_both_confirmations_removes_the_data(world, more, urls):
    ids = _compliance_records(urls, world, "13 months", retention_months=12)
    with _admin(urls) as conn:
        conn.execute("INSERT INTO findings (scan_id, org_id, title, description, severity, remediation) "
                     "VALUES (%s,%s,'Old finding','d','low','r')", (world["scan"], world["org"]))
    owner = _signed_in(world)
    _delete(owner, world)
    _age_deletion(urls, world["org"], 31)
    # The word must be DELETE exactly, and the name exact; neither changes anything.
    for body in (_purge_body(world, word="delete"), _purge_body(world, word="DELETE "), _purge_body(world, word="yes"),
                 _purge_body(world, name=world["org_name"].lower())):
        r = owner.post(_org_url(world, "purge"), json=body, headers=ORIGIN)
        assert r.status_code == 409, r.text
        assert _org_exists(urls, world["org"])
    assert owner.post(_org_url(world, "purge"), json={**_named(world)}, headers=ORIGIN).status_code == 422
    resp = owner.post(_org_url(world, "purge"), json=_purge_body(world), headers=ORIGIN)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"organization_id": world["org"], "purged": True, "evidence_files_queued": True}
    assert not _org_exists(urls, world["org"])
    with _admin(urls) as conn:
        for table in ("organization_members", "domains", "scans", "findings", "audit_log", "organization_suspensions",
                      "compliance_reviewer_grants", "compliance_practitioner_reviews", "compliance_clause_verifications",
                      "assessment_snapshots", "evidence_packs", "compliance_documents", "compliance_document_approvals",
                      "compliance_evidence_files"):
            n = conn.execute(f"SELECT count(*) AS n FROM {table} WHERE org_id = %s", (world["org"],)).fetchone()["n"]
            assert n == 0, table
        # The stored files wait in the purge queue for the reconcile script; nothing was deleted inline.
        assert conn.execute("SELECT count(*) AS n FROM compliance_evidence_purge_queue WHERE org_id = %s",
                            (world["org"],)).fetchone()["n"] == 1
        # People keep their accounts.
        assert conn.execute("SELECT count(*) AS n FROM profiles WHERE id = %s", (world["customer"],)).fetchone()["n"] == 1
    audit = _audits(urls, world, "owner.action.purge_org")
    assert [a["outcome"] for a in audit] == ["rejected"] * 4 + ["success"]
    meta = audit[-1]["metadata"]
    assert meta["to"] == "purged" and meta["name"] == world["org_name"] and meta["evidence_files_queued"] is True
    assert meta["removed"]["members"] == 2 and meta["removed"]["findings"] >= 1 and meta["removed"]["evidence_files"] == 1
    _cleanup_reviewer(urls, ids)


def test_purge_rolls_back_whole_on_a_failure(world, more, urls, monkeypatch):
    from backend.app.api import owner_actions
    owner = _signed_in(world)
    _delete(owner, world)
    _age_deletion(urls, world["org"], 31)
    # A statement timeout far too short for anything: the transaction fails and nothing is removed or queued.
    monkeypatch.setattr(owner_actions, "PURGE_STATEMENT_TIMEOUT", "1ms")
    file_id = str(uuid4())
    with _admin(urls) as conn:
        conn.execute("INSERT INTO compliance_evidence_files (id, org_id, question_key, display_name, content_type, "
                     "size_bytes, sha256, storage_path, uploaded_at) VALUES (%s, %s, 'q', 'f.pdf', 'application/pdf', "
                     "1, %s, %s, now() - interval '5 years')",
                     (file_id, world["org"], SHA, f"org/{world['org']}/{file_id}"))
    resp = owner.post(_org_url(world, "purge"), json=_purge_body(world), headers=ORIGIN)
    if resp.status_code == 200:  # a very fast machine can finish inside 1 ms; then there is nothing to check here
        pytest.skip("purge finished inside the 1 ms timeout")
    assert resp.status_code in (409, 503), resp.text
    assert _org_exists(urls, world["org"])
    with _admin(urls) as conn:
        assert conn.execute("SELECT count(*) AS n FROM compliance_evidence_purge_queue WHERE org_id = %s",
                            (world["org"],)).fetchone()["n"] == 0


# ── Typed name, owner only ─────────────────────────────────────────────────
def test_a_wrong_name_changes_nothing_on_any_step(world, more, urls):
    owner = _signed_in(world)
    for wrong in (world["org_name"].lower(), f"{world['org_name']} ", "Views Org"):
        assert owner.post(_org_url(world, "delete"), json=_named(world, wrong), headers=ORIGIN).status_code == 409
    assert _status(urls, world["org"]) is None
    _delete(owner, world)
    _age_deletion(urls, world["org"], 10)
    assert owner.post(_org_url(world, "restore"), json=_named(world, "nope"), headers=ORIGIN).status_code == 409
    assert _status(urls, world["org"])["status"] == "deleted"
    _age_deletion(urls, world["org"], 40)
    assert owner.post(_org_url(world, "purge"), json=_purge_body(world, "nope"), headers=ORIGIN).status_code == 409
    assert _org_exists(urls, world["org"])
    outcomes = {a: [x["outcome"] for x in _audits(urls, world, f"owner.action.{a}")]
                for a in ("delete_org", "restore_org", "purge_org")}
    assert outcomes == {"delete_org": ["rejected"] * 3 + ["success"], "restore_org": ["rejected"],
                        "purge_org": ["rejected"]}
    for a in ("restore_org", "purge_org"):
        assert _audits(urls, world, f"owner.action.{a}")[0]["metadata"]["detail"].startswith("The name you typed")


def test_non_owners_are_refused(world, more, urls):
    owner = _signed_in(world)
    customer = _customer_token(world, urls)
    staff = _customer_token(world, urls, staff_scopes=["platform:read"])
    anonymous = TestClient(app)
    for action, body in (("delete", _named(world)), ("restore", _named(world)), ("purge", _purge_body(world))):
        path = _org_url(world, action)
        assert anonymous.post(path, json=body, headers=ORIGIN).status_code == 401
        for token in (customer, staff):
            assert anonymous.post(path, json=body, headers={**ORIGIN, "Authorization": f"Bearer {token}"}).status_code == 401
            assert owner.post(path, json=body, headers={**ORIGIN, "Authorization": f"Bearer {token}"}).status_code == 401
        assert owner.post(path, json=body).status_code == 403  # no console Origin
        assert owner.post(path, json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert _status(urls, world["org"]) is None and _org_exists(urls, world["org"])


# ── Guardrails ─────────────────────────────────────────────────────────────
def test_an_active_paid_subscription_refuses_the_soft_delete(world, more, urls):
    owner = _signed_in(world)
    with _admin(urls) as conn:
        conn.execute("INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, "
                     "current_period_end) VALUES (%s, 'growth', 'active', 'manual', now(), now() + interval '20 days')",
                     (world["org"],))
    resp = owner.post(_org_url(world, "delete"), json=_named(world), headers=ORIGIN)
    assert resp.status_code == 409 and "active paid subscription" in resp.json()["detail"]
    assert _status(urls, world["org"]) is None
    with _admin(urls) as conn:
        assert conn.execute("SELECT status FROM scans WHERE id = %s", (world["scan"],)).fetchone()["status"] == "queued"
    assert owner.get(_org_url(world)).json()["organization"]["paid_subscription_active"] is True
    # The customer's owner cancels it (allowed while suspended too); the soft delete is then allowed.
    assert owner.post(_org_url(world, "suspend"), json=_named(world), headers=ORIGIN).status_code == 200
    customer, headers = _customer(world, urls)
    assert customer.post("/api/v1/billing/subscription/cancel", headers=headers).status_code == 200
    _delete(owner, world)
    meta = _audits(urls, world, "owner.action.delete_org")[-1]["metadata"]
    assert meta["cancel_at_period_end"] is True and meta["subscription_status"] == "active"
    assert [a["outcome"] for a in _audits(urls, world, "owner.action.delete_org")] == ["rejected", "success"]
    with _admin(urls) as conn:
        conn.execute("DELETE FROM subscriptions WHERE org_id = %s", (world["org"],))


def test_a_trial_or_lapsed_subscription_does_not_block(world, more, urls):
    owner = _signed_in(world)
    with _admin(urls) as conn:
        conn.execute("INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, "
                     "current_period_end) VALUES (%s, 'growth', 'active', 'manual', now() - interval '40 days', "
                     "now() - interval '1 day')", (world["org"],))
    _delete(owner, world)
    with _admin(urls) as conn:
        conn.execute("DELETE FROM subscriptions WHERE org_id = %s", (world["org"],))


@pytest.fixture
def demo_org(urls):
    with _admin(urls) as conn:
        existed = conn.execute("SELECT 1 FROM organizations WHERE id = %s", (DEMO_ORG_ID,)).fetchone() is not None
        if not existed:
            conn.execute("INSERT INTO organizations (id, name, slug, plan) VALUES (%s, 'Fintech Org (SAMPLE DATA)', "
                         "%s, 'growth')", (DEMO_ORG_ID, f"demo-{uuid4().hex[:8]}"))
        name = conn.execute("SELECT name FROM organizations WHERE id = %s", (DEMO_ORG_ID,)).fetchone()["name"]
    yield {"org": DEMO_ORG_ID, "org_name": name}
    with _admin(urls) as conn:
        conn.execute("DELETE FROM organization_suspensions WHERE org_id = %s", (DEMO_ORG_ID,))
        if not existed:
            conn.execute("DELETE FROM organizations WHERE id = %s", (DEMO_ORG_ID,))


def test_the_demo_organisation_is_refused_without_the_override(world, more, urls, demo_org, monkeypatch):
    monkeypatch.delenv(org_guard.OVERRIDE_ENV, raising=False)
    owner = _signed_in(world)
    resp = owner.post(_org_url(demo_org, "delete"), json=_named(demo_org), headers=ORIGIN)
    assert resp.status_code == 409 and "protected" in resp.json()["detail"]
    assert _status(urls, DEMO_ORG_ID) is None
    monkeypatch.setenv(org_guard.OVERRIDE_ENV, "true")
    assert owner.post(_org_url(demo_org, "delete"), json=_named(demo_org), headers=ORIGIN).status_code == 200
    assert _audits(urls, world, "owner.action.delete_org")[-1]["metadata"]["protected_override"] is True
    monkeypatch.setenv(org_guard.OVERRIDE_ENV, "false")
    _age_deletion(urls, DEMO_ORG_ID, 31)
    resp = owner.post(_org_url(demo_org, "purge"), json=_purge_body(demo_org), headers=ORIGIN)
    assert resp.status_code == 409 and "protected" in resp.json()["detail"]
    assert _org_exists(urls, DEMO_ORG_ID)


def test_innovatech_is_refused_by_id_and_by_name_without_the_override(world, more, urls, monkeypatch):
    monkeypatch.delenv(org_guard.OVERRIDE_ENV, raising=False)
    owner = _signed_in(world)
    monkeypatch.setenv(org_guard.INNOVATECH_ENV, world["org"])
    assert owner.post(_org_url(world, "delete"), json=_named(world), headers=ORIGIN).status_code == 409
    monkeypatch.delenv(org_guard.INNOVATECH_ENV)
    monkeypatch.setenv("DEMO_LOGIN_ORG_ID", world["org"])
    assert owner.post(_org_url(world, "delete"), json=_named(world), headers=ORIGIN).status_code == 409
    monkeypatch.delenv("DEMO_LOGIN_ORG_ID")
    named = f"InnovaTech Nigeria {world['tag']}"
    with _admin(urls) as conn:
        conn.execute("UPDATE organizations SET name = %s WHERE id = %s", (named, world["org"]))
    assert owner.post(_org_url(world, "delete"), json=_named(world, named), headers=ORIGIN).status_code == 409
    assert _status(urls, world["org"]) is None
    assert owner.get(_org_url(world)).json()["organization"]["protected"] is True
    assert [a["outcome"] for a in _audits(urls, world, "owner.action.delete_org")] == ["rejected"] * 3
    monkeypatch.setenv(org_guard.OVERRIDE_ENV, "true")
    assert owner.post(_org_url(world, "delete"), json=_named(world, named), headers=ORIGIN).status_code == 200


# ── Retention arithmetic: the SQL period matches snapshots.store.add_months ─
def test_the_retention_period_in_sql_matches_add_months(urls):
    moments = [datetime(2024, 1, 31, 23, 30, tzinfo=timezone.utc), datetime(2024, 2, 29, 0, 15, tzinfo=timezone.utc),
               datetime(2023, 3, 31, 12, 0, tzinfo=timezone.utc), datetime(2025, 8, 31, 23, 59, tzinfo=timezone.utc),
               datetime(2026, 10, 31, 22, 0, tzinfo=timezone.utc)]
    with psycopg.connect(urls[0], row_factory=dict_row) as conn:
        conn.execute("SET TimeZone = 'UTC'")
        for moment in moments:
            for months in (12, 13, 36, 120):
                got = conn.execute("SELECT %s::timestamptz + make_interval(months => %s) AS t",
                                   (moment, months)).fetchone()["t"]
                assert got == add_months(moment, months), (moment, months, got)


# ── Migration: columns, CHECK, index and exact grants, applied twice ───────
def test_migration_adds_columns_check_index_and_only_the_two_column_grants(scratch_db):
    text = DELETE_MIGRATION.read_text()
    body = [s.strip() for s in "\n".join(l for l in text.splitlines() if not l.startswith("--")).split(";") if s.strip()]
    assert body[:3] == ["BEGIN", "SET LOCAL lock_timeout = '5s'", "SET LOCAL statement_timeout = '60s'"]
    assert "DEFAULT" not in "\n".join(l for l in text.splitlines() if "ADD COLUMN" in l), "no default on new columns"
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute(SUSPENSION_MIGRATION.read_text())
        conn.execute("INSERT INTO organizations (id) VALUES (gen_random_uuid())")
        conn.execute("INSERT INTO organization_suspensions (org_id, status) SELECT id, 'suspended' FROM organizations")
    before = _grants(scratch_db)
    for attempt in (1, 2):
        with psycopg.connect(scratch_db, autocommit=True) as conn:
            conn.execute(text)
        owner, table, columns, can, public, rls, policies = _grants(scratch_db)
        assert sorted(map(str, table)) == sorted(map(str, before[1])), "table grants unchanged"
        assert {(r["col"], r["grantee"], r["priv"]) for r in columns} == {
            ("status", "cyphward_app", "UPDATE"), ("changed_at", "cyphward_app", "UPDATE"),
            ("changed_by", "cyphward_app", "UPDATE"), ("deleted_at", "cyphward_app", "UPDATE"),
            ("deleted_by", "cyphward_app", "UPDATE")}, (attempt, columns)
        assert can["anon"] == set() and can["authenticated"] == set() and public is False, (attempt, can)
        assert can["cyphward_app"] == {"SELECT", "INSERT"}, "UPDATE only per column, never DELETE"
        assert (rls, policies) == (before[5], before[6]), "RLS and policies unchanged"
        with psycopg.connect(scratch_db, row_factory=dict_row, autocommit=True) as conn:
            checks = {r["conname"]: r["def"] for r in conn.execute(
                "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint "
                "WHERE conrelid = 'organization_suspensions'::regclass AND contype = 'c'").fetchall()}
            assert set(checks) == {"organization_suspensions_status_check", "organization_suspensions_deleted_check"}
            assert "'deleted'" in checks["organization_suspensions_status_check"]
            cols = {r["attname"]: r for r in conn.execute(
                "SELECT a.attname, a.attnotnull, pg_get_expr(d.adbin, d.adrelid) AS dflt FROM pg_attribute a "
                "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
                "WHERE a.attrelid = 'organization_suspensions'::regclass AND a.attname IN ('deleted_at', 'deleted_by')"
            ).fetchall()}
            assert {k: (v["attnotnull"], v["dflt"]) for k, v in cols.items()} == {
                "deleted_at": (False, None), "deleted_by": (False, None)}
            index = conn.execute("SELECT pg_get_indexdef(indexrelid) AS d FROM pg_index "
                                 "WHERE indexrelid = 'idx_organization_suspensions_deleted'::regclass").fetchone()["d"]
            assert "(deleted_at)" in index and "WHERE (status = 'deleted'::text)" in index
            # The existing row is untouched; the CHECKs hold.
            assert conn.execute("SELECT status, deleted_at FROM organization_suspensions").fetchall() == [
                {"status": "suspended", "deleted_at": None}]
            for bad in ("UPDATE organization_suspensions SET status = 'gone'",
                        "UPDATE organization_suspensions SET status = 'deleted'",
                        "UPDATE organization_suspensions SET deleted_at = now()"):
                with pytest.raises(psycopg.errors.CheckViolation):
                    conn.execute(bad)
            conn.execute("UPDATE organization_suspensions SET status = 'deleted', deleted_at = now()")
            conn.execute("UPDATE organization_suspensions SET status = 'suspended', deleted_at = NULL")


def test_migration_file_sha256_is_recorded():
    digest = hashlib.sha256(DELETE_MIGRATION.read_bytes()).hexdigest()
    readme = (Path(__file__).resolve().parents[2] / "docs" / "admin-delete-org" / "README.md").read_text()
    assert digest in readme, f"record the migration sha256 in the README: {digest}"
