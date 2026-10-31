"""Admin phase 2 against the isolated, migrated PostgreSQL database, as the real app role.

* Suspension enforcement (core/suspension.py): every gated write route refuses a suspended organisation's owner
  with 403 organization_suspended, reads still work, the scheduled sweep and the worker claim skip the suspended
  organisation (and pick it up again once lifted), and owner actions keep working on it.
* Failure codes (core/scan_failures.py): the app role writes scans.failure_code when a scan fails, and the
  customer API shows the reviewed sentence, never the stored raw text.
* Restoring a removed member from the owner audit row: works once, a second restore is refused, a wrong name
  changes nothing, a suspended organisation is refused, and non-owners are refused.

Reuses the owner-views fixtures (an owner, a customer who owns "Views Org <tag>", a verified domain and a queued
scan) and the phase 1 helpers.
"""
import asyncio
import re
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from test_owner_phase1_postgres import OWNER, REASON, _admin, _customer_token, _owner_audit, more  # noqa: F401
from test_owner_views_postgres import ORIGIN, _signed_in, urls, world  # noqa: F401 (fixtures)
from test_suspension_gate import gated_routes

RAW = "Traceback ConnectError [Errno 111] 10.9.8.7 PHASE2-RAW-WORKER-TEXT"


def _named(world):
    return {"reason": REASON, "confirm_name": world["org_name"]}


def _suspend(client, world):
    resp = client.post(f"{OWNER}/organizations/{world['org']}/suspend", json=_named(world), headers=ORIGIN)
    assert resp.status_code == 200, resp.text


def _unsuspend(client, world):
    resp = client.post(f"{OWNER}/organizations/{world['org']}/unsuspend", json=_named(world), headers=ORIGIN)
    assert resp.status_code == 200, resp.text


def _refused(resp):
    detail = resp.json().get("detail")
    return resp.status_code == 403 and isinstance(detail, dict) and detail.get("code") == "organization_suspended"


# ── Suspension ─────────────────────────────────────────────────────────────
def test_every_gated_route_refuses_a_suspended_organisation(world, more, urls):
    token = _customer_token(world, urls)
    owner = _signed_in(world)
    _suspend(owner, world)
    customer = TestClient(app)
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": world["org"]}
    leaks = []
    routes = [r for r in gated_routes() if "/compliance/reviewer/" not in r[1]]  # those need a reviewer grant
    assert len(routes) == 32
    for method, path in routes:
        url = re.sub(r"\{[^}]+\}", str(uuid4()), path)
        resp = customer.request(method, url, headers=headers, json={})
        if not _refused(resp):
            leaks.append((method, path, resp.status_code, resp.text[:160]))
    assert not leaks, leaks
    # Nothing was written: the activity log holds no customer action since the suspension.
    with _admin(urls) as conn:
        rows = conn.execute("SELECT action FROM audit_log WHERE org_id = %s AND user_id = %s AND action <> 'scan.launched'",
                            (world["org"], world["customer"])).fetchall()
    assert rows == [], rows


def test_reads_still_work_while_suspended(world, more, urls):
    token = _customer_token(world, urls)
    owner = _signed_in(world)
    _suspend(owner, world)
    customer = TestClient(app)
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": world["org"]}
    for path in ("/api/v1/organizations/current", "/api/v1/scans", f"/api/v1/scans/{world['scan']}",
                 "/api/v1/findings", "/api/v1/domains", "/api/v1/members", "/api/v1/overview", "/api/v1/reports",
                 "/api/v1/compliance/overview", "/api/v1/settings", "/api/v1/auth/bootstrap"):
        resp = customer.get(path, headers=headers)
        assert resp.status_code == 200, (path, resp.status_code, resp.text[:200])
    boot = customer.get("/api/v1/auth/bootstrap", headers=headers).json()
    assert [m["org"]["suspended"] for m in boot["memberships"]] == [True]


def test_scan_launch_and_admission_are_refused_then_restored(world, more, urls):
    from backend.app.core.scan_admission import admit_scan
    token = _customer_token(world, urls)
    owner = _signed_in(world)
    customer = TestClient(app)
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": world["org"]}
    with _admin(urls) as conn:  # free the domain so a launch could be admitted
        conn.execute("UPDATE scans SET status = 'cancelled' WHERE id = %s", (world["scan"],))
    _suspend(owner, world)
    assert _refused(customer.post("/api/v1/scans/launch", headers=headers, json={"domain_id": world["domain"]}))
    # The shared admission re-checks under the organization row lock (the scheduled path does not use the route).
    assert admit_scan(world["org"], world["domain"], request_scope="test:phase2").outcome == "suspended"
    with _admin(urls) as conn:
        assert conn.execute("SELECT count(*) AS n FROM scans WHERE org_id = %s AND status = 'queued'",
                            (world["org"],)).fetchone()["n"] == 0
    _unsuspend(owner, world)
    admitted = admit_scan(world["org"], world["domain"], request_scope="test:phase2")
    assert admitted.outcome == "created"
    with _admin(urls) as conn:
        conn.execute("DELETE FROM scans WHERE id = %s", (admitted.scan["id"],))


@pytest.fixture
def sweep(monkeypatch, urls):
    """Run the real daily sweep against the test database; dispatch is recorded, never sent."""
    from backend.app.workflows import inngest_workflow as wf
    sent = []

    async def fake_send(event):
        sent.append(event.data)

    monkeypatch.setattr(wf.inngest_client, "send", fake_send)
    monkeypatch.setattr(wf, "SCANNER_MODE", "remote")
    run_days = []

    def run(day):
        run_days.append(day)
        return asyncio.run(wf._daily_scan_sweep(day))

    yield run, sent
    with _admin(urls) as conn:
        for day in run_days:
            scope = f"scheduled:{day.isoformat()}"
            ids = [r["scan_id"] for r in conn.execute(
                "SELECT scan_id FROM scan_launch_requests WHERE request_scope = %s", (scope,)).fetchall()]
            conn.execute("DELETE FROM scan_launch_requests WHERE request_scope = %s", (scope,))
            if ids:
                conn.execute("DELETE FROM scans WHERE id = ANY(%s)", (ids,))


def test_the_scheduled_sweep_skips_a_suspended_organisation_and_resumes(world, more, urls, sweep):
    run, sent = sweep
    owner = _signed_in(world)
    with _admin(urls) as conn:
        conn.execute("UPDATE scans SET status = 'cancelled' WHERE id = %s", (world["scan"],))
    _suspend(owner, world)
    run(date(2099, 1, 1))
    assert world["org"] not in {str(e["organization_id"]) for e in sent}
    with _admin(urls) as conn:
        assert conn.execute("SELECT count(*) AS n FROM scans WHERE org_id = %s AND status = 'queued'",
                            (world["org"],)).fetchone()["n"] == 0
        # The domain row is untouched, so the schedule resumes.
        assert conn.execute("SELECT verification_status FROM domains WHERE id = %s",
                            (world["domain"],)).fetchone()["verification_status"] == "verified"
    _unsuspend(owner, world)
    run(date(2099, 1, 2))
    assert world["org"] in {str(e["organization_id"]) for e in sent}


def test_queued_scans_wait_while_suspended_and_run_after(world, more, urls):
    from backend.app.core import scan_execution
    owner = _signed_in(world)
    _suspend(owner, world)
    assert scan_execution.claim_recon("phase2-test-worker", "worker", 60, scan_id=world["scan"]) is None
    with _admin(urls) as conn:
        assert conn.execute("SELECT status FROM scans WHERE id = %s", (world["scan"],)).fetchone()["status"] == "queued"
    _unsuspend(owner, world)
    held = scan_execution.claim_recon("phase2-test-worker", "worker", 60, scan_id=world["scan"])
    assert held is not None and str(held["id"]) == world["scan"]


def test_owner_actions_still_work_on_a_suspended_organisation(world, more, urls):
    owner = _signed_in(world)
    _suspend(owner, world)
    org = f"{OWNER}/organizations/{world['org']}"
    assert owner.post(f"{org}/plan", json={**_named(world), "plan": "starter"}, headers=ORIGIN).status_code == 200
    assert owner.post(f"{org}/members/{more['member']}/remove", json=_named(world), headers=ORIGIN).status_code == 200
    assert owner.post(f"{OWNER}/scans/{world['scan']}/cancel", json={"reason": REASON},
                      headers=ORIGIN).status_code == 200
    detail = owner.get(f"{org}").json()
    assert detail["organization"]["suspended"] is True


# ── Failure codes ──────────────────────────────────────────────────────────
def test_a_failed_scan_stores_its_code_and_customers_see_only_the_sentence(world, more, urls):
    from backend.app.core import scan_execution
    held = scan_execution.claim_recon("phase2-test-worker", "worker", 60, scan_id=world["scan"])
    assert held is not None
    scan_execution.fail_claim(scan_execution.claim_from_row(held), f"http: {RAW}",
                              {"error": RAW, "http": {"status": "failed", "error": RAW}})
    with _admin(urls) as conn:
        row = conn.execute("SELECT status, failure_code, error_message FROM scans WHERE id = %s",
                           (world["scan"],)).fetchone()
        conn.execute("INSERT INTO scan_results (scan_id, stage, raw_data, attempt_generation) "
                     "VALUES (%s, 'http', %s::jsonb, %s)",
                     (world["scan"], '{"failed_hosts": {"www.views.test": "%s"}}' % RAW, held["observation_generation"]))
    assert row["status"] == "failed" and row["failure_code"] == "unreachable" and RAW in row["error_message"]

    token = _customer_token(world, urls)
    customer = TestClient(app)
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": world["org"]}
    for path in ("/api/v1/scans", f"/api/v1/scans/{world['scan']}", "/api/v1/overview"):
        resp = customer.get(path, headers=headers)
        assert resp.status_code == 200 and "PHASE2-RAW" not in resp.text and "Errno" not in resp.text, path
    detail = customer.get(f"/api/v1/scans/{world['scan']}", headers=headers).json()
    assert detail["scan"]["failure"] == {"code": "unreachable", "message": "We could not reach the site."}

    owner = _signed_in(world)
    seen = owner.get(f"{OWNER}/scans/{world['scan']}").json()["scan"]
    assert RAW in seen["error_message"] and seen["failure"]["message"] == "We could not reach the site."
    with _admin(urls) as conn:
        conn.execute("DELETE FROM scan_results WHERE scan_id = %s", (world["scan"],))


def test_the_failure_code_column_refuses_free_text(world, urls):
    import psycopg
    with _admin(urls) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE scans SET failure_code = %s WHERE id = %s", ("Connection refused!", world["scan"]))


# ── Restore a removed member ───────────────────────────────────────────────
def _remove(owner, world, more):
    resp = owner.post(f"{OWNER}/organizations/{world['org']}/members/{more['member']}/remove", json=_named(world),
                      headers=ORIGIN)
    assert resp.status_code == 200, resp.text
    detail = owner.get(f"{OWNER}/organizations/{world['org']}").json()
    removed = detail["removed_members"]
    assert removed and removed[0]["email"] == more["member_email"] and removed[0]["restored"] is False
    return removed[0]["audit_id"]


def _membership(urls, world, user_id):
    with _admin(urls) as conn:
        return conn.execute("SELECT role FROM organization_members WHERE org_id = %s AND user_id = %s",
                            (world["org"], user_id)).fetchone()


def test_restore_works_once_and_is_audited(world, more, urls):
    owner = _signed_in(world)
    audit_id = _remove(owner, world, more)
    path = f"{OWNER}/organizations/{world['org']}/members/restore"
    body = {**_named(world), "audit_id": audit_id}

    done = owner.post(path, json=body, headers=ORIGIN)
    assert done.status_code == 200, done.text
    assert done.json() == {"organization_id": world["org"], "restored_user_id": more["member"], "role": "member",
                           "members": 2}
    assert _membership(urls, world, more["member"])["role"] == "member"

    again = owner.post(path, json=body, headers=ORIGIN)
    assert again.status_code == 409 and "already been restored" in again.json()["detail"]

    # Removed again, the old record still cannot restore: each removal restores at most once.
    second_audit = _remove(owner, world, more)
    stale = owner.post(path, json=body, headers=ORIGIN)
    assert stale.status_code == 409 and _membership(urls, world, more["member"]) is None
    assert owner.post(path, json={**body, "audit_id": second_audit}, headers=ORIGIN).status_code == 200

    rows = _owner_audit(urls, world, "owner.action.restore_member")
    assert [r["outcome"] for r in rows] == ["success", "rejected", "rejected", "success"]
    assert rows[0]["metadata"]["restored_from"] == audit_id and rows[0]["metadata"]["reason"] == REASON
    with _admin(urls) as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE org_id = %s AND action = 'member.restored'",
                            (world["org"],)).fetchone()["n"] == 2
    detail = owner.get(f"{OWNER}/organizations/{world['org']}").json()
    assert [r["restored"] for r in detail["removed_members"]] == [True, True]


def test_restore_refuses_an_existing_member(world, more, urls):
    owner = _signed_in(world)
    audit_id = _remove(owner, world, more)
    with _admin(urls) as conn:  # the person rejoined another way (an invitation)
        conn.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s, %s, 'admin')",
                     (more["member"], world["org"]))
    resp = owner.post(f"{OWNER}/organizations/{world['org']}/members/restore",
                      json={**_named(world), "audit_id": audit_id}, headers=ORIGIN)
    assert resp.status_code == 409 and "already a member" in resp.json()["detail"]
    assert _membership(urls, world, more["member"])["role"] == "admin"  # unchanged


def test_restore_with_a_wrong_name_changes_nothing(world, more, urls):
    owner = _signed_in(world)
    audit_id = _remove(owner, world, more)
    path = f"{OWNER}/organizations/{world['org']}/members/restore"
    for wrong in ("Views Org", world["org_name"].upper(), world["org_name"] + " "):
        resp = owner.post(path, json={**_named(world), "confirm_name": wrong, "audit_id": audit_id}, headers=ORIGIN)
        assert resp.status_code == 409, resp.text
    assert owner.post(path, json={"reason": REASON, "audit_id": audit_id}, headers=ORIGIN).status_code == 422
    assert _membership(urls, world, more["member"]) is None
    assert {r["outcome"] for r in _owner_audit(urls, world, "owner.action.restore_member")} == {"rejected"}


def test_restore_is_refused_while_suspended(world, more, urls):
    owner = _signed_in(world)
    audit_id = _remove(owner, world, more)
    _suspend(owner, world)
    resp = owner.post(f"{OWNER}/organizations/{world['org']}/members/restore",
                      json={**_named(world), "audit_id": audit_id}, headers=ORIGIN)
    assert resp.status_code == 409 and "suspended" in resp.json()["detail"]
    assert _membership(urls, world, more["member"]) is None
    _unsuspend(owner, world)
    assert owner.post(f"{OWNER}/organizations/{world['org']}/members/restore",
                      json={**_named(world), "audit_id": audit_id}, headers=ORIGIN).status_code == 200


def test_restore_refuses_records_of_other_organisations_and_non_removals(world, more, urls):
    owner = _signed_in(world)
    audit_id = _remove(owner, world, more)
    other = owner.post(f"{OWNER}/organizations/{more['org_b']}/members/restore",
                       json={"reason": REASON, "confirm_name": more["org_b_name"], "audit_id": audit_id},
                       headers=ORIGIN)
    assert other.status_code == 404
    with _admin(urls) as conn:
        row = conn.execute("SELECT id FROM owner_audit WHERE action = 'owner.action.remove_member' "
                           "AND outcome = 'success' AND target_id = %s", (world["org"],)).fetchone()
        conn.execute("UPDATE owner_audit SET action = 'owner.action.change_plan' WHERE id = %s", (row["id"],))
    not_removal = owner.post(f"{OWNER}/organizations/{world['org']}/members/restore",
                             json={**_named(world), "audit_id": str(row["id"])}, headers=ORIGIN)
    assert not_removal.status_code == 404


def test_restore_refuses_non_owners(world, more, urls):
    owner = _signed_in(world)
    audit_id = _remove(owner, world, more)
    path = f"{OWNER}/organizations/{world['org']}/members/restore"
    body = {**_named(world), "audit_id": audit_id}
    customer = _customer_token(world, urls)
    staff = _customer_token(world, urls, staff_scopes=["platform:read", "platform:newsletter"])
    anonymous = TestClient(app)
    assert anonymous.post(path, json=body, headers=ORIGIN).status_code == 401
    for token in (customer, staff):
        assert anonymous.post(path, json=body, headers={**ORIGIN, "Authorization": f"Bearer {token}"}).status_code == 401
        assert owner.post(path, json=body, headers={**ORIGIN, "Authorization": f"Bearer {token}"}).status_code == 401
    assert owner.post(path, json=body).status_code in (401, 403)  # no console Origin
    assert _membership(urls, world, more["member"]) is None


# ── Founder decisions (2026-10-31) against the real database ──────────────
def _customer(world, urls):
    token = _customer_token(world, urls)
    return TestClient(app), {"Authorization": f"Bearer {token}", "X-Organization-Id": world["org"]}


def test_billing_cancel_allowed_and_cost_changes_refused_while_suspended(world, more, urls):
    with _admin(urls) as conn:
        conn.execute("INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, "
                     "current_period_end) VALUES (%s, 'growth', 'active', 'manual', now(), now() + interval '20 days')",
                     (world["org"],))
    _suspend(_signed_in(world), world)
    customer, headers = _customer(world, urls)
    cancel = customer.post("/api/v1/billing/subscription/cancel", headers=headers)
    assert cancel.status_code == 200 and cancel.json()["subscription"]["cancel_at_period_end"] is True, cancel.text
    assert _refused(customer.post("/api/v1/billing/subscription", headers=headers, json={"plan": "growth"}))
    assert _refused(customer.post("/api/v1/billing/subscription/renew", headers=headers))


def test_reviewer_revoke_allowed_and_grant_refused_while_suspended(world, more, urls):
    _suspend(_signed_in(world), world)
    customer, headers = _customer(world, urls)
    revoke = customer.post(f"/api/v1/compliance/reviewer-grants/{uuid4()}/revoke", headers=headers)
    assert revoke.status_code == 404, revoke.text  # past the suspension check; no such grant
    grant = customer.post("/api/v1/compliance/reviewer-grants", headers=headers,
                          json={"email": f"rev-{world['tag']}@outside.test", "days": 7,
                                "purpose": "Review our readiness answers"})
    assert _refused(grant)


def test_member_downgrade_allowed_and_promotion_refused_while_suspended(world, more, urls):
    with _admin(urls) as conn:
        conn.execute("UPDATE organization_members SET role = 'admin' WHERE org_id = %s AND user_id = %s",
                     (world["org"], more["member"]))
    _suspend(_signed_in(world), world)
    customer, headers = _customer(world, urls)
    down = customer.patch(f"/api/v1/members/{more['member']}", headers=headers, json={"role": "member"})
    assert down.status_code == 200, down.text
    assert _membership(urls, world, more["member"])["role"] == "member"
    up = customer.patch(f"/api/v1/members/{more['member']}", headers=headers, json={"role": "admin"})
    assert _refused(up) and _membership(urls, world, more["member"])["role"] == "member"
    assert _refused(customer.post("/api/v1/members/invite", headers=headers,
                                  json={"email": f"new-{world['tag']}@views.test", "full_name": "New", "role": "member"}))
    withdraw = customer.delete(f"/api/v1/members/invites/{uuid4()}", headers=headers)
    assert withdraw.status_code == 404, withdraw.text  # past the suspension check; no such invitation


def test_new_organisation_refused_only_for_owners_of_a_suspended_organisation(world, more, urls):
    from backend.app.core import sessions
    _suspend(_signed_in(world), world)
    customer, headers = _customer(world, urls)
    refused = customer.post("/api/v1/organizations", headers={"Authorization": headers["Authorization"]},
                            json={"name": f"Fresh Start {world['tag']}"})
    assert _refused(refused) and "An organisation you own is suspended" in refused.json()["detail"]["message"]
    with _admin(urls) as conn:  # the owner of an active organisation (org B) is unaffected
        profile = conn.execute("SELECT * FROM profiles WHERE id = %s", (more["user_b"],)).fetchone()
    other = sessions.issue_session(profile)["access_token"]
    made = customer.post("/api/v1/organizations", headers={"Authorization": f"Bearer {other}"},
                         json={"name": f"Second Org {world['tag']}"})
    assert made.status_code == 201, made.text
    with _admin(urls) as conn:
        assert conn.execute("SELECT count(*) AS n FROM organizations WHERE name = %s",
                            (f"Fresh Start {world['tag']}",)).fetchone()["n"] == 0
        conn.execute("DELETE FROM organizations WHERE id = %s", (made.json()["organization"]["id"],))
        conn.execute("DELETE FROM audit_log WHERE resource_id = %s", (str(made.json()["organization"]["id"]),))


# ── Review follow-ups: local queue, browser claim, new-organisation rule ──
def test_a_suspended_organisations_old_queued_scan_does_not_block_local_recovery(world, more, urls):
    """Local mode takes the oldest runnable scans; a suspended organisation's must not hold those slots."""
    from backend.app.core.database import execute_query
    from backend.app.core.scan_recovery import LOCAL_QUEUE_SQL
    other_scan = str(uuid4())
    with _admin(urls) as conn:
        conn.execute("UPDATE domains SET verification_status = 'verified', verified_at = now() WHERE id = %s",
                     (more["domain_b"],))
        conn.execute("INSERT INTO scans (id, org_id, domain_id, status, scan_type, created_at) "
                     "VALUES (%s, %s, %s, 'queued', 'EXTERNAL_ASSESSMENT', now() - interval '1 minute')",
                     (other_scan, more["org_b"], more["domain_b"]))
        # Only these two runnable scans may be in the way: world's (20 minutes old) and org B's (1 minute old).
        older = conn.execute(
            "SELECT count(*) AS n FROM scans s JOIN domains d ON d.id = s.domain_id WHERE s.status = 'queued' "
            "AND d.verification_status = 'verified' AND s.created_at < now() - interval '1 minute' "
            "AND s.id NOT IN (%s, %s)", (world["scan"], other_scan)).fetchone()["n"]
    assert older == 0, "leftover queued scans in the test database"
    assert [str(r["id"]) for r in execute_query(LOCAL_QUEUE_SQL, (1,))] == [world["scan"]]  # oldest first
    owner = _signed_in(world)
    _suspend(owner, world)
    assert [str(r["id"]) for r in execute_query(LOCAL_QUEUE_SQL, (1,))] == [other_scan]
    _unsuspend(owner, world)
    assert [str(r["id"]) for r in execute_query(LOCAL_QUEUE_SQL, (1,))] == [world["scan"]]
    with _admin(urls) as conn:
        conn.execute("DELETE FROM scans WHERE id = %s", (other_scan,))


def test_a_suspended_organisations_browser_job_waits_until_unsuspended(world, more, urls):
    from backend.app.core import browser_jobs
    with _admin(urls) as conn:
        job = conn.execute("INSERT INTO privacy_browser_jobs (org_id, domain_id) VALUES (%s, %s) RETURNING id",
                           (world["org"], world["domain"])).fetchone()["id"]
    owner = _signed_in(world)
    _suspend(owner, world)
    seen = []
    try:
        while (claimed := browser_jobs.claim("phase2-browser-test")) is not None:  # drain anyone else's jobs
            seen.append(claimed.job_id)
        assert str(job) not in seen
        with _admin(urls) as conn:
            assert conn.execute("SELECT status FROM privacy_browser_jobs WHERE id = %s", (job,)).fetchone()["status"] == "queued"
        _unsuspend(owner, world)
        claimed = browser_jobs.claim("phase2-browser-test")
        assert claimed is not None and claimed.job_id == str(job)
    finally:
        with _admin(urls) as conn:
            conn.execute("DELETE FROM privacy_browser_jobs WHERE id = %s OR id = ANY(%s::uuid[])", (job, seen))


def test_new_organisation_member_of_suspended_allowed_and_owner_allowed_after_unsuspend(world, more, urls):
    """Both halves of refuse_suspended_owner's condition: the person must be an owner (a plain member may still
    create one) and the suspension must be in force (status 'active' after unsuspend no longer refuses)."""
    from backend.app.core import sessions
    owner = _signed_in(world)
    _suspend(owner, world)
    client = TestClient(app)
    created = []

    def create(user_id, name):
        with _admin(urls) as conn:
            profile = conn.execute("SELECT * FROM profiles WHERE id = %s", (user_id,)).fetchone()
        token = sessions.issue_session(profile)["access_token"]
        resp = client.post("/api/v1/organizations", headers={"Authorization": f"Bearer {token}"}, json={"name": name})
        if resp.status_code == 201:
            created.append(resp.json()["organization"]["id"])
        return resp

    try:
        member = create(more["member"], f"Member Side Org {world['tag']}")  # plain member of the suspended org
        assert member.status_code == 201, member.text
        assert _refused(create(world["customer"], f"Owner Org {world['tag']}"))
        _unsuspend(owner, world)
        again = create(world["customer"], f"Owner Org {world['tag']}")
        assert again.status_code == 201, again.text
    finally:
        with _admin(urls) as conn:
            for org_id in created:
                conn.execute("DELETE FROM audit_log WHERE resource_id = %s", (str(org_id),))
                conn.execute("DELETE FROM organizations WHERE id = %s", (org_id,))
