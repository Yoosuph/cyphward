"""Owner console phase 1 (docs/admin-2026-10-29) against the isolated, migrated PostgreSQL database, as the real
app role: analytics, management lists, CSV exports, suspension and member removal.

Reuses the owner-views fixtures (an owner, a customer who owns "Views Org <tag>", a verified domain and a queued
scan) and adds a second organization, a second member and a finding with a recognisable title.
"""
import csv
import io
import json
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.core import owner as owner_mod
from backend.app.core import owner_reads
from backend.app.core import sessions
from backend.app.main import app
from test_owner_views_postgres import ORIGIN, _signed_in, urls, world  # noqa: F401 (fixtures)

REASON = "Customer asked by email, ticket 42"
OWNER = "/api/v1/owner"


def _admin(urls):
    return psycopg.connect(urls[1], row_factory=dict_row, autocommit=True)


@pytest.fixture
def more(world, urls):
    """Org B (its own owner and domain), a plain member of org A, and a finding in org A."""
    tag = world["tag"]
    ids = {"org_b": str(uuid4()), "user_b": str(uuid4()), "member": str(uuid4()), "domain_b": str(uuid4()),
           "finding": str(uuid4()), "finding_title": f"Leaky finding title {tag}",
           "org_b_name": f"=HYPERLINK(\"https://evil.example\") {tag}",
           "user_b_email": f"orgb-{tag}@views.test", "member_email": f"member-{tag}@views.test",
           "domain_b_name": f"orgb-{tag}.test"}
    with _admin(urls) as conn:
        for uid, email in ((ids["user_b"], ids["user_b_email"]), (ids["member"], ids["member_email"])):
            conn.execute("INSERT INTO profiles (id, email, full_name, role, provider, email_verified_at) "
                         "VALUES (%s,%s,'Someone','Member','email',now())", (uid, email))
        conn.execute("INSERT INTO organizations (id, name, slug, sector, plan) VALUES (%s,%s,%s,'Retail','starter')",
                     (ids["org_b"], ids["org_b_name"], f"orgb-{tag}"))
        conn.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s,%s,'owner')",
                     (ids["user_b"], ids["org_b"]))
        conn.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s,%s,'member')",
                     (ids["member"], world["org"]))
        conn.execute("INSERT INTO domains (id, org_id, domain, verification_status, verification_token) "
                     "VALUES (%s,%s,%s,'pending','tok')", (ids["domain_b"], ids["org_b"], ids["domain_b_name"]))
        conn.execute("INSERT INTO findings (id, scan_id, org_id, title, description, severity, remediation) "
                     "VALUES (%s,%s,%s,%s,'desc','high','fix')",
                     (ids["finding"], world["scan"], world["org"], ids["finding_title"]))
    yield ids
    with _admin(urls) as conn:
        conn.execute("DELETE FROM findings WHERE id = %s", (ids["finding"],))
        conn.execute("DELETE FROM audit_log WHERE org_id IN (%s, %s)", (world["org"], ids["org_b"]))
        conn.execute("DELETE FROM organizations WHERE id = %s", (ids["org_b"],))
        conn.execute("DELETE FROM platform_staff WHERE user_id = %s", (world["customer"],))
        conn.execute("DELETE FROM auth_sessions WHERE user_id IN (%s, %s, %s)",
                     (world["customer"], ids["user_b"], ids["member"]))
        conn.execute("DELETE FROM profiles WHERE id IN (%s, %s)", (ids["user_b"], ids["member"]))


def _customer_token(world, urls, staff_scopes=None):
    """A real customer access token (session row + JWT), optionally with a live platform-staff grant."""
    with _admin(urls) as conn:
        profile = conn.execute("SELECT * FROM profiles WHERE id = %s", (world["customer"],)).fetchone()
        if staff_scopes:
            conn.execute("INSERT INTO platform_staff (user_id, scopes, reason) VALUES (%s, %s, 'phase 1 test')",
                         (world["customer"], staff_scopes))
    return sessions.issue_session(profile)["access_token"]


def _owner_audit(urls, world, action):
    with _admin(urls) as conn:
        return conn.execute(
            "SELECT outcome, target_type, target_id, metadata FROM owner_audit "
            "WHERE actor_user_id = %s AND action = %s ORDER BY created_at", (world["owner"], action)).fetchall()


def _reads(world, more):
    return [
        f"{OWNER}/analytics/summary", f"{OWNER}/analytics/timeseries",
        f"{OWNER}/organizations", f"{OWNER}/users", f"{OWNER}/subscriptions",
        f"{OWNER}/organizations/{world['org']}",
        f"{OWNER}/exports/organizations.csv", f"{OWNER}/exports/users.csv", f"{OWNER}/exports/subscriptions.csv",
    ]


def _mutations(world, more):
    named = {"reason": REASON, "confirm_name": world["org_name"]}
    org = f"{OWNER}/organizations/{world['org']}"
    return [
        (f"{org}/suspend", named), (f"{org}/unsuspend", named),
        (f"{org}/members/{more['member']}/remove", named),
        (f"{org}/plan", {**named, "plan": "starter"}), (f"{org}/trial", {**named, "days": 7}),
    ]


# ── Access ─────────────────────────────────────────────────────────────────
def test_every_endpoint_refuses_non_owners_and_staff_tokens(world, more, urls):
    customer = _customer_token(world, urls)
    staff = _customer_token(world, urls, staff_scopes=["platform:read", "platform:newsletter"])
    anonymous = TestClient(app)
    owner = _signed_in(world)
    # The tokens are real: the customer's own API accepts them.
    assert anonymous.get("/api/v1/organizations/current",
                         headers={"Authorization": f"Bearer {customer}"}).status_code == 200
    for path in _reads(world, more):
        assert anonymous.get(path).status_code == 401, path
        for token in (customer, staff):
            assert anonymous.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 401, path
            # A bearer token is refused even next to a valid owner cookie.
            assert owner.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 401, path
    for path, body in _mutations(world, more):
        assert anonymous.post(path, json=body, headers=ORIGIN).status_code == 401, path
        for token in (customer, staff):
            assert anonymous.post(path, json=body, headers={**ORIGIN, "Authorization": f"Bearer {token}"}).status_code == 401
            assert owner.post(path, json=body, headers={**ORIGIN, "Authorization": f"Bearer {token}"}).status_code == 401
        assert owner.post(path, json=body, headers={"Origin": "https://evil.example"}).status_code == 403, path
        assert owner.post(path, json=body).status_code == 403, path
    with _admin(urls) as conn:
        assert conn.execute("SELECT count(*) AS n FROM organization_suspensions WHERE org_id = %s",
                            (world["org"],)).fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM organization_members WHERE org_id = %s",
                            (world["org"],)).fetchone()["n"] == 2


# ── Analytics ──────────────────────────────────────────────────────────────
def test_analytics_returns_aggregates_only(world, more, urls):
    client = _signed_in(world)
    with _admin(urls) as conn:
        conn.execute("INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, "
                     "current_period_end) VALUES (%s, 'growth', 'active', 'manual', now(), now() + interval '30 days')",
                     (world["org"],))
    for days in ("7", "30", "90"):
        summary = client.get(f"{OWNER}/analytics/summary", params={"range": days})
        series = client.get(f"{OWNER}/analytics/timeseries", params={"range": days})
        assert summary.status_code == 200 and series.status_code == 200, (summary.text, series.text)
        s, t = summary.json(), series.json()
        assert s["range_days"] == int(days) and len(t["scans_per_day"]) == int(days)
        assert len(t["findings_per_day"]) == int(days)
        assert s["organizations"]["total"] >= 2 and s["billing"]["paid"] >= 1
        assert s["scans"]["queued"] >= 1 and t["scans_per_day"][-1]["queued"] >= 1
        assert t["findings_per_day"][-1]["high"] >= 1
        assert set(s["billing"]) == {"paid", "trialing", "free"}
        text = json.dumps(s) + json.dumps(t)
        for secret in (more["finding_title"], world["tag"], world["customer_email"], world["owner_email"],
                       more["domain_b_name"], f"views-{world['tag']}.test", world["org"], more["org_b"], world["scan"]):
            assert secret not in text, secret
        assert "@" not in text
    rows = _owner_audit(urls, world, "owner.view.analytics_summary")
    assert [r["metadata"]["range_days"] for r in rows] == [7, 30, 90]
    assert len(_owner_audit(urls, world, "owner.view.analytics_timeseries")) == 3


def test_range_and_page_size_validation(world, more):
    client = _signed_in(world)
    for bad in ("14", "0", "abc", "-7", "365"):
        assert client.get(f"{OWNER}/analytics/summary", params={"range": bad}).status_code == 422
        assert client.get(f"{OWNER}/analytics/timeseries", params={"range": bad}).status_code == 422
    for path in ("/organizations", "/users", "/subscriptions"):
        assert client.get(f"{OWNER}{path}", params={"limit": 0}).status_code == 422
        assert client.get(f"{OWNER}{path}", params={"offset": -1}).status_code == 422
        assert client.get(f"{OWNER}{path}", params={"sort": "password_hash"}).status_code == 422
        assert client.get(f"{OWNER}{path}", params={"dir": "sideways"}).status_code == 422
        assert client.get(f"{OWNER}{path}", params={"q": "x" * 101}).status_code == 422
        capped = client.get(f"{OWNER}{path}", params={"limit": 500})
        assert capped.status_code == 200 and capped.json()["limit"] == 100
        assert client.get(f"{OWNER}{path}", params={"limit": 100}).json()["limit"] == 100
    assert client.get(f"{OWNER}/organizations", params={"billing": "gold"}).status_code == 422
    assert client.get(f"{OWNER}/users", params={"mfa": "sms"}).status_code == 422
    assert client.get(f"{OWNER}/subscriptions", params={"status": "expired"}).status_code == 422
    assert client.get(f"{OWNER}/exports/users.csv", params={"sort": "nope"}).status_code == 422


def test_statement_timeout_answers_503_with_reviewed_wording(world, monkeypatch):
    monkeypatch.setattr(owner_reads, "STATEMENT_TIMEOUT", "50ms")
    with pytest.raises(HTTPException) as caught:
        owner_reads.bounded_read([("SELECT pg_sleep(1)", ())])
    assert caught.value.status_code == 503 and caught.value.detail == owner_reads.SLOW_READ_DETAIL


# ── Lists ──────────────────────────────────────────────────────────────────
def test_lists_search_filter_sort_and_page(world, more):
    client = _signed_in(world)
    orgs = client.get(f"{OWNER}/organizations", params={"q": world["tag"], "sort": "name", "dir": "asc"}).json()
    assert orgs["total"] == 2 and [o["id"] for o in orgs["items"]] == [more["org_b"], world["org"]]
    by_members = client.get(f"{OWNER}/organizations", params={"q": world["tag"], "sort": "members"}).json()
    assert [o["members"] for o in by_members["items"]] == [2, 1]
    starter = client.get(f"{OWNER}/organizations", params={"q": world["tag"], "plan": "starter"}).json()
    assert [o["id"] for o in starter["items"]] == [more["org_b"]]
    free = client.get(f"{OWNER}/organizations", params={"q": world["tag"], "billing": "free"}).json()
    assert free["total"] == 2 and all(o["billing"] == "free" for o in free["items"])
    page2 = client.get(f"{OWNER}/organizations", params={"q": world["tag"], "sort": "name", "dir": "asc",
                                                          "limit": 1, "offset": 1}).json()
    assert [o["id"] for o in page2["items"]] == [world["org"]] and page2["total"] == 2

    users = client.get(f"{OWNER}/users", params={"q": world["tag"], "sort": "email", "dir": "asc"}).json()
    emails = [u["email"] for u in users["items"]]
    assert emails == sorted(emails) and world["customer_email"] in emails
    cust = next(u for u in users["items"] if u["email"] == world["customer_email"])
    assert cust["memberships"] == [{"org_id": world["org"], "name": world["org_name"], "role": "owner"}]
    assert cust["mfa"] == "none" and cust["email_verified"] is True
    auth = client.get(f"{OWNER}/users", params={"q": world["tag"], "mfa": "authenticator"}).json()
    assert [u["email"] for u in auth["items"]] == [world["owner_email"]]

    subs = client.get(f"{OWNER}/subscriptions", params={"q": world["tag"]}).json()
    assert subs["total"] == 0 and "invoices" in subs


# ── Exports ────────────────────────────────────────────────────────────────
def test_csv_export_matches_the_filter_is_escaped_capped_and_audited(world, more, urls, monkeypatch):
    client = _signed_in(world)
    resp = client.get(f"{OWNER}/exports/organizations.csv", params={"q": world["tag"], "sort": "name", "dir": "asc"})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["cache-control"] == "no-store" and "attachment" in resp.headers["content-disposition"]
    assert resp.headers["x-export-truncated"] == "false" and resp.headers["x-export-rows"] == "2"
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert [r["id"] for r in rows] == [more["org_b"], world["org"]]
    assert rows[0]["name"] == "'" + more["org_b_name"], "a formula-looking name is written as text"
    assert rows[1]["owner_email"] == world["customer_email"]

    users = client.get(f"{OWNER}/exports/users.csv", params={"q": world["tag"]})
    assert world["org_name"] in users.text and "password" not in users.text.lower()

    monkeypatch.setattr(owner_reads, "EXPORT_MAX", 1)
    cut = client.get(f"{OWNER}/exports/users.csv", params={"q": world["tag"]})
    assert cut.headers["x-export-truncated"] == "true" and cut.headers["x-export-rows"] == "1"
    assert len(list(csv.DictReader(io.StringIO(cut.text)))) == 1

    audits = _owner_audit(urls, world, "owner.export.users")
    assert audits[-1]["metadata"] == {"filters": {"q": world["tag"], "sort": "created", "dir": "desc"},
                                      "rows": 1, "truncated": True}
    org_audit = _owner_audit(urls, world, "owner.export.organizations")
    assert org_audit[-1]["metadata"]["rows"] == 2 and org_audit[-1]["metadata"]["truncated"] is False

    def failing_audit(*_a, **_k):
        raise HTTPException(status_code=503, detail="Owner console is temporarily unavailable.")

    monkeypatch.setattr(owner_mod, "audit", failing_audit)
    blocked = client.get(f"{OWNER}/exports/organizations.csv", params={"q": world["tag"]})
    assert blocked.status_code == 503 and world["customer_email"] not in blocked.text


# ── Suspension ─────────────────────────────────────────────────────────────
def test_suspend_and_unsuspend_need_the_typed_name_are_audited_and_reversible(world, more, urls):
    client = _signed_in(world)
    org = f"{OWNER}/organizations/{world['org']}"
    assert client.post(f"{org}/suspend", json={"reason": REASON}, headers=ORIGIN).status_code == 422
    for wrong in (world["org_name"] + " ", world["org_name"].lower(), more["org_b_name"]):
        resp = client.post(f"{org}/suspend", json={"reason": REASON, "confirm_name": wrong}, headers=ORIGIN)
        assert resp.status_code == 409 and "does not match" in resp.json()["detail"]
    with _admin(urls) as conn:
        assert conn.execute("SELECT count(*) AS n FROM organization_suspensions WHERE org_id = %s",
                            (world["org"],)).fetchone()["n"] == 0

    named = {"reason": REASON, "confirm_name": world["org_name"]}
    done = client.post(f"{org}/suspend", json=named, headers=ORIGIN)
    assert done.status_code == 200, done.text
    assert done.json()["suspended"] is True and done.json()["organization_id"] == world["org"]
    assert client.post(f"{org}/suspend", json=named, headers=ORIGIN).status_code == 409
    assert client.get(org).json()["organization"]["suspended"] is True
    listed = client.get(f"{OWNER}/organizations", params={"q": world["tag"], "suspended": "yes"}).json()
    assert [o["id"] for o in listed["items"]] == [world["org"]]

    lifted = client.post(f"{org}/unsuspend", json=named, headers=ORIGIN)
    assert lifted.status_code == 200 and lifted.json()["suspended"] is False
    assert client.post(f"{org}/unsuspend", json=named, headers=ORIGIN).status_code == 409
    with _admin(urls) as conn:
        row = conn.execute("SELECT status, changed_by::text AS changed_by FROM organization_suspensions WHERE org_id = %s",
                           (world["org"],)).fetchone()
        customer_log = conn.execute("SELECT count(*) AS n FROM audit_log WHERE org_id = %s AND action LIKE '%%suspend%%'",
                                    (world["org"],)).fetchone()["n"]
    assert row == {"status": "active", "changed_by": world["owner"]}, "lifting keeps the row (no delete)"
    assert customer_log == 0, "phase 1: suspension is not written to the customer's activity log"
    suspend_audit = _owner_audit(urls, world, "owner.action.suspend")
    assert [r["outcome"] for r in suspend_audit] == ["rejected"] * 3 + ["success", "rejected"]
    assert suspend_audit[3]["metadata"] == {"reason": REASON, "from": "active", "to": "suspended"}
    assert [r["outcome"] for r in _owner_audit(urls, world, "owner.action.unsuspend")] == ["success", "rejected"]
    owner_actions = client.get(org).json()["owner_actions"]
    assert {"owner.action.suspend", "owner.action.unsuspend"} <= {a["action"] for a in owner_actions}


def test_customer_reads_are_unchanged_and_writes_refused_while_suspended(world, more, urls):
    """The phase 2 rule (core/suspension.py; this replaced phase 1's "unchanged" test): reads answer as before
    apart from the new `suspended` flag, writes are refused with 403 organization_suspended, and unsuspending
    restores them."""
    token = _customer_token(world, urls)
    customer = TestClient(app)
    auth = {"Authorization": f"Bearer {token}"}

    def snapshot():
        return {path: customer.get(path, headers=auth) for path in
                ("/api/v1/organizations/current", "/api/v1/members", "/api/v1/domains", "/api/v1/settings")}

    def without_flag(body):
        return {k: v for k, v in body.items() if k != "suspended"} if isinstance(body, dict) else body

    before = snapshot()
    assert before["/api/v1/organizations/current"].json()["suspended"] is False
    owner = _signed_in(world)
    named = {"reason": REASON, "confirm_name": world["org_name"]}
    assert owner.post(f"{OWNER}/organizations/{world['org']}/suspend", json=named, headers=ORIGIN).status_code == 200
    during = snapshot()
    for path, resp in during.items():
        assert resp.status_code == before[path].status_code == 200, (path, resp.text)
        assert without_flag(resp.json()) == without_flag(before[path].json()), path
    assert during["/api/v1/organizations/current"].json()["suspended"] is True
    write = customer.patch("/api/v1/organizations/current", json={"sector": "Logistics"}, headers=auth)
    assert write.status_code == 403 and write.json()["detail"]["code"] == "organization_suspended", write.text
    assert owner.post(f"{OWNER}/organizations/{world['org']}/unsuspend", json=named, headers=ORIGIN).status_code == 200
    write = customer.patch("/api/v1/organizations/current", json={"sector": "Logistics"}, headers=auth)
    assert write.status_code == 200, write.text


# ── Members ────────────────────────────────────────────────────────────────
def test_remove_member_needs_the_typed_name_keeps_the_last_owner_and_is_audited(world, more, urls):
    client = _signed_in(world)
    org = f"{OWNER}/organizations/{world['org']}"
    path = f"{org}/members/{more['member']}/remove"
    named = {"reason": REASON, "confirm_name": world["org_name"]}
    assert client.post(path, json={"reason": REASON}, headers=ORIGIN).status_code == 422
    assert client.post(path, json={**named, "confirm_name": "Views Org"}, headers=ORIGIN).status_code == 409

    done = client.post(path, json=named, headers=ORIGIN)
    assert done.status_code == 200, done.text
    assert done.json() == {"organization_id": world["org"], "removed_user_id": more["member"], "role": "member",
                           "members": 1}
    assert client.post(path, json=named, headers=ORIGIN).status_code == 404
    last_owner = client.post(f"{org}/members/{world['customer']}/remove", json=named, headers=ORIGIN)
    assert last_owner.status_code == 409 and "at least one owner" in last_owner.json()["detail"]
    with _admin(urls) as conn:
        assert conn.execute("SELECT id FROM profiles WHERE id = %s", (more["member"],)).fetchone(), \
            "the person's account stays"
        members = conn.execute("SELECT user_id::text AS u FROM organization_members WHERE org_id = %s",
                               (world["org"],)).fetchall()
        log = conn.execute("SELECT user_id, metadata FROM audit_log WHERE org_id = %s AND action = 'member.removed'",
                           (world["org"],)).fetchall()
    assert [m["u"] for m in members] == [world["customer"]]
    assert len(log) == 1 and log[0]["user_id"] is None and log[0]["metadata"] == {"by": "cyphward", "role": "member"}
    audit = _owner_audit(urls, world, "owner.action.remove_member")
    assert [r["outcome"] for r in audit] == ["rejected", "success", "rejected", "rejected"]
    meta = audit[1]["metadata"]
    assert meta["user_id"] == more["member"] and meta["role"] == "member" and meta["email"] == more["member_email"]
    assert meta["joined_at"] and meta["members_after"] == 1, "enough to restore the membership"


def test_member_and_domain_views_and_removal_are_isolated_per_organization(world, more, urls):
    client = _signed_in(world)
    a = client.get(f"{OWNER}/organizations/{world['org']}").json()
    b = client.get(f"{OWNER}/organizations/{more['org_b']}").json()
    assert {m["id"] for m in a["members"]} == {world["customer"], more["member"]}
    assert {m["id"] for m in b["members"]} == {more["user_b"]}
    assert {d["id"] for d in a["domains"]} == {world["domain"]}
    assert {d["id"] for d in b["domains"]} == {more["domain_b"]}

    # Org B's owner through org A's path, and org A's owner through org B's path: not found, nothing changes.
    cross = client.post(f"{OWNER}/organizations/{world['org']}/members/{more['user_b']}/remove",
                        json={"reason": REASON, "confirm_name": world["org_name"]}, headers=ORIGIN)
    assert cross.status_code == 404
    cross = client.post(f"{OWNER}/organizations/{more['org_b']}/members/{world['customer']}/remove",
                        json={"reason": REASON, "confirm_name": more["org_b_name"]}, headers=ORIGIN)
    assert cross.status_code == 404
    # Org B's name never unlocks an action on org A.
    assert client.post(f"{OWNER}/organizations/{world['org']}/members/{more['member']}/remove",
                       json={"reason": REASON, "confirm_name": more["org_b_name"]}, headers=ORIGIN).status_code == 409
    with _admin(urls) as conn:
        count = conn.execute("SELECT count(*) AS n FROM organization_members WHERE org_id IN (%s, %s)",
                             (world["org"], more["org_b"])).fetchone()["n"]
    assert count == 3


# ── Typed name on the remaining organization actions ───────────────────────
NAME_MISMATCH = "The name you typed does not match this organization. Nothing was changed."


def _assert_refused(resp, urls, world, action):
    assert resp.status_code == 409, resp.text
    assert "does not match" in resp.json()["detail"]
    rows = _owner_audit(urls, world, action)
    assert rows and rows[-1]["outcome"] == "rejected", rows
    assert rows[-1]["metadata"]["detail"] == NAME_MISMATCH and rows[-1]["metadata"]["reason"] == REASON
    assert all(r["outcome"] == "rejected" for r in rows), "a wrong name never records a success"


@pytest.mark.parametrize("wrong", ["{name} ", "{lower}", "Views Org"])
def test_change_plan_refuses_a_wrong_name_and_changes_nothing(world, more, urls, wrong):
    client = _signed_in(world)
    typed = wrong.format(name=world["org_name"], lower=world["org_name"].lower())
    resp = client.post(f"{OWNER}/organizations/{world['org']}/plan",
                       json={"reason": REASON, "confirm_name": typed, "plan": "starter"}, headers=ORIGIN)
    _assert_refused(resp, urls, world, "owner.action.change_plan")
    with _admin(urls) as conn:
        assert conn.execute("SELECT plan FROM organizations WHERE id = %s", (world["org"],)).fetchone()["plan"] == "growth"
        assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE org_id = %s AND action = 'billing.plan_changed'",
                            (world["org"],)).fetchone()["n"] == 0


def test_extend_trial_refuses_a_wrong_name_and_changes_nothing(world, more, urls):
    with _admin(urls) as conn:
        conn.execute("INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, current_period_end, "
                     "trial_ends_at) VALUES (%s, 'growth', 'trialing', 'manual', now(), now() + interval '10 days', "
                     "now() + interval '10 days')", (world["org"],))
        before = conn.execute("SELECT trial_ends_at, current_period_end FROM subscriptions WHERE org_id = %s",
                              (world["org"],)).fetchone()
    client = _signed_in(world)
    resp = client.post(f"{OWNER}/organizations/{world['org']}/trial",
                       json={"reason": REASON, "confirm_name": more["org_b_name"], "days": 7}, headers=ORIGIN)
    _assert_refused(resp, urls, world, "owner.action.extend_trial")
    with _admin(urls) as conn:
        after = conn.execute("SELECT trial_ends_at, current_period_end FROM subscriptions WHERE org_id = %s",
                             (world["org"],)).fetchone()
        logged = conn.execute("SELECT count(*) AS n FROM audit_log WHERE org_id = %s AND action = 'billing.trial_extended'",
                              (world["org"],)).fetchone()["n"]
    assert after == before and logged == 0


def test_unsuspend_refuses_a_wrong_name_and_changes_nothing(world, more, urls):
    client = _signed_in(world)
    org = f"{OWNER}/organizations/{world['org']}"
    assert client.post(f"{org}/suspend", json={"reason": REASON, "confirm_name": world["org_name"]},
                       headers=ORIGIN).status_code == 200
    with _admin(urls) as conn:
        before = conn.execute("SELECT status, changed_at FROM organization_suspensions WHERE org_id = %s",
                              (world["org"],)).fetchone()
    resp = client.post(f"{org}/unsuspend", json={"reason": REASON, "confirm_name": world["org_name"].upper()},
                       headers=ORIGIN)
    _assert_refused(resp, urls, world, "owner.action.unsuspend")
    with _admin(urls) as conn:
        after = conn.execute("SELECT status, changed_at FROM organization_suspensions WHERE org_id = %s",
                             (world["org"],)).fetchone()
    assert before["status"] == "suspended" and after == before
    assert client.get(org).json()["organization"]["suspended"] is True


# ── Migration grants, read back from PostgreSQL ───────────────────────────
MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20261030100000_organization_suspension.sql"


@pytest.fixture
def scratch_db(urls):
    """A throwaway database on the same local server with Supabase-style defaults: every new table in public grants
    ALL to PUBLIC, anon, authenticated and cyphward_app. Only the tables the migration needs exist."""
    admin_url = urls[1]
    name = f"cyphward_acl_{uuid4().hex[:10]}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_conninfo(admin_url, dbname=name)
    assert conninfo_to_dict(url).get("host") in {"127.0.0.1", "localhost", "::1"}
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            for role in ("anon", "authenticated", "cyphward_app"):
                assert conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone(), role
            conn.execute("CREATE TABLE organizations (id uuid PRIMARY KEY)")
            conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                         "GRANT ALL ON TABLES TO PUBLIC, anon, authenticated, cyphward_app")
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def _grants(url):
    with psycopg.connect(url, row_factory=dict_row) as conn:
        owner = conn.execute("SELECT pg_get_userbyid(relowner) AS o FROM pg_class "
                             "WHERE oid = 'organization_suspensions'::regclass").fetchone()["o"]
        table = conn.execute(
            """
            SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END AS grantee,
                   a.privilege_type AS priv
            FROM pg_class c, aclexplode(c.relacl) a WHERE c.oid = 'organization_suspensions'::regclass
            """).fetchall()
        columns = conn.execute(
            """
            SELECT att.attname AS col,
                   CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END AS grantee,
                   a.privilege_type AS priv
            FROM pg_attribute att, aclexplode(att.attacl) a
            WHERE att.attrelid = 'organization_suspensions'::regclass AND att.attacl IS NOT NULL
            """).fetchall()
        can = {role: {p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
                      if conn.execute("SELECT has_table_privilege(%s, 'organization_suspensions', %s) AS ok",
                                      (role, p)).fetchone()["ok"]}
               for role in ("anon", "authenticated", "cyphward_app")}
        public = conn.execute("SELECT has_table_privilege('public', 'organization_suspensions', 'SELECT') AS ok").fetchone()["ok"]
        rls = conn.execute("SELECT relrowsecurity AS on FROM pg_class WHERE oid = 'organization_suspensions'::regclass").fetchone()["on"]
        policies = conn.execute("SELECT policyname, roles::text[] AS roles FROM pg_policies "
                                "WHERE tablename = 'organization_suspensions'").fetchall()
    return owner, table, columns, can, public, rls, policies


def test_migration_grants_are_exactly_owner_plus_app_select_insert(scratch_db):
    text = MIGRATION.read_text()
    body = [s.strip() for s in "\n".join(l for l in text.splitlines() if not l.startswith("--")).split(";") if s.strip()]
    assert body[:3] == ["BEGIN", "SET LOCAL lock_timeout = '5s'", "SET LOCAL statement_timeout = '60s'"]

    for attempt in (1, 2):  # idempotent: the second run leaves the same grants
        with psycopg.connect(scratch_db, autocommit=True) as conn:
            conn.execute(text)
        owner, table, columns, can, public, rls, policies = _grants(scratch_db)
        others = {(r["grantee"], r["priv"]) for r in table if r["grantee"] != owner}
        assert {r["grantee"] for r in table} == {owner, "cyphward_app"}, (attempt, table)
        assert others == {("cyphward_app", "SELECT"), ("cyphward_app", "INSERT")}, (attempt, others)
        assert {(r["col"], r["grantee"], r["priv"]) for r in columns} == {
            ("status", "cyphward_app", "UPDATE"), ("changed_at", "cyphward_app", "UPDATE"),
            ("changed_by", "cyphward_app", "UPDATE")}, (attempt, columns)
        assert can["anon"] == set() and can["authenticated"] == set() and public is False, (attempt, can)
        assert can["cyphward_app"] == {"SELECT", "INSERT"}, "UPDATE only per column, never DELETE"
        assert rls is True and [(p["policyname"], p["roles"]) for p in policies] == [("cyphward_app_all", ["cyphward_app"])]
