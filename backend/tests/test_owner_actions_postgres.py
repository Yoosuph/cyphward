"""Owner console actions (stage 3) against the isolated, migrated PostgreSQL
database, as the real app role. Reuses the owner-views fixtures: an owner,
a customer in their own organization (no subscription row, plan growth) and
a queued scan.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient

from backend.app.core import owner as owner_mod
from backend.app.main import app
from test_owner_views_postgres import ORIGIN, _signed_in, urls, world  # noqa: F401 (fixtures)

REASON = {"reason": "Customer asked by email, ticket 42"}


def _admin(urls):
    return psycopg.connect(urls[1], row_factory=dict_row, autocommit=True)


def _owner_audit(urls, world, action):
    with _admin(urls) as conn:
        return conn.execute(
            "SELECT outcome, target_type, target_id, metadata FROM owner_audit "
            "WHERE actor_user_id = %s AND action = %s ORDER BY created_at", (world["owner"], action)).fetchall()


@pytest.fixture
def cleanup(urls, world):
    yield
    with _admin(urls) as conn:
        conn.execute("DELETE FROM audit_log WHERE user_id = %s", (world["customer"],))


def _endpoints(world):
    return [
        (f"/api/v1/owner/organizations/{world['org']}/plan", {**REASON, "plan": "starter"}),
        (f"/api/v1/owner/organizations/{world['org']}/trial", {**REASON, "days": 7}),
        (f"/api/v1/owner/scans/{world['scan']}/cancel", REASON),
        (f"/api/v1/owner/users/{world['customer']}/sign-out", REASON),
    ]


def test_actions_need_an_owner_session_and_the_console_origin(world, urls):
    anonymous = TestClient(app)
    signed_in = _signed_in(world)
    for path, body in _endpoints(world):
        assert anonymous.post(path, json=body, headers=ORIGIN).status_code == 401
        assert signed_in.post(path, json=body, headers={**ORIGIN, "Authorization": "Bearer x"}).status_code == 401
        assert signed_in.post(path, json=body, headers={"Origin": "https://evil.example"}).status_code == 403
        assert signed_in.post(path, json=body).status_code == 403  # no Origin at all
    with _admin(urls) as conn:
        assert conn.execute("SELECT status FROM scans WHERE id = %s", (world["scan"],)).fetchone()["status"] == "queued"
        assert conn.execute("SELECT plan FROM organizations WHERE id = %s", (world["org"],)).fetchone()["plan"] == "growth"


def test_actions_need_a_written_reason(world):
    client = _signed_in(world)
    for path, body in _endpoints(world):
        assert client.post(path, json={k: v for k, v in body.items() if k != "reason"}, headers=ORIGIN).status_code == 422
        assert client.post(path, json={**body, "reason": "   ok  "}, headers=ORIGIN).status_code == 422


def test_unknown_targets_are_404_and_audited_as_rejected(world, urls):
    client = _signed_in(world)
    ghost = str(uuid4())
    assert client.post(f"/api/v1/owner/scans/{ghost}/cancel", json=REASON, headers=ORIGIN).status_code == 404
    assert client.post(f"/api/v1/owner/users/{ghost}/sign-out", json=REASON, headers=ORIGIN).status_code == 404
    assert client.post("/api/v1/owner/organizations/nope/plan", json={**REASON, "plan": "starter"},
                       headers=ORIGIN).status_code == 404
    rows = _owner_audit(urls, world, "owner.action.cancel_scan")
    assert rows[-1]["outcome"] == "rejected" and rows[-1]["metadata"]["reason"] == REASON["reason"]


def test_change_plan_without_and_with_a_subscription(world, urls):
    client = _signed_in(world)
    path = f"/api/v1/owner/organizations/{world['org']}/plan"
    resp = client.post(path, json={**REASON, "plan": "starter"}, headers=ORIGIN)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"plan": "starter", "previous_plan": "growth"}
    again = client.post(path, json={**REASON, "plan": "starter"}, headers=ORIGIN)
    assert again.status_code == 409
    assert client.post(path, json={**REASON, "plan": "platinum"}, headers=ORIGIN).status_code == 422

    with _admin(urls) as conn:
        assert conn.execute("SELECT plan FROM organizations WHERE id = %s", (world["org"],)).fetchone()["plan"] == "starter"
        conn.execute("INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, "
                     "current_period_end, trial_ends_at) VALUES (%s, 'starter', 'trialing', 'manual', now(), "
                     "now() + interval '30 days', now() + interval '30 days')", (world["org"],))
    resp = client.post(path, json={**REASON, "plan": "growth"}, headers=ORIGIN)
    assert resp.status_code == 200, resp.text
    with _admin(urls) as conn:
        sub = conn.execute("SELECT plan, status FROM subscriptions WHERE org_id = %s", (world["org"],)).fetchone()
        org = conn.execute("SELECT plan FROM organizations WHERE id = %s", (world["org"],)).fetchone()
        customer_log = conn.execute("SELECT user_id, metadata FROM audit_log WHERE org_id = %s AND "
                                    "action = 'billing.plan_changed' ORDER BY created_at", (world["org"],)).fetchall()
    assert sub == {"plan": "growth", "status": "trialing"} and org["plan"] == "growth"
    assert [r["metadata"]["plan"] for r in customer_log] == ["starter", "growth"]
    assert all(r["user_id"] is None and r["metadata"]["by"] == "cyphward" for r in customer_log)
    assert all("reason" not in r["metadata"] for r in customer_log), "the owner's reason stays internal"

    audit = _owner_audit(urls, world, "owner.action.change_plan")
    assert [r["outcome"] for r in audit] == ["success", "rejected", "success"]
    assert audit[0]["target_id"] == world["org"]
    assert audit[0]["metadata"] == {"reason": REASON["reason"], "from": "growth", "to": "starter",
                                    "subscription": False}


def test_extend_trial(world, urls):
    client = _signed_in(world)
    path = f"/api/v1/owner/organizations/{world['org']}/trial"
    assert client.post(path, json={**REASON, "days": 7}, headers=ORIGIN).status_code == 409  # no subscription

    lapsed = datetime.now(timezone.utc) - timedelta(days=3)
    with _admin(urls) as conn:
        conn.execute("INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, "
                     "current_period_end, trial_ends_at) VALUES (%s, 'growth', 'trialing', 'manual', %s, %s, %s)",
                     (world["org"], lapsed - timedelta(days=30), lapsed, lapsed))
    resp = client.post(path, json={**REASON, "days": 14}, headers=ORIGIN)
    assert resp.status_code == 200, resp.text
    with _admin(urls) as conn:
        sub = conn.execute("SELECT trial_ends_at, current_period_end FROM subscriptions WHERE org_id = %s",
                           (world["org"],)).fetchone()
    # A lapsed trial extends from today, and the period end moves with it.
    expected = datetime.now(timezone.utc) + timedelta(days=14)
    assert abs((sub["trial_ends_at"] - expected).total_seconds()) < 120
    assert sub["current_period_end"] == sub["trial_ends_at"]

    assert client.post(path, json={**REASON, "days": 61}, headers=ORIGIN).status_code == 422
    for _ in range(4):  # 14 + 4×20 days would pass the 90-day horizon
        last = client.post(path, json={**REASON, "days": 20}, headers=ORIGIN)
    assert last.status_code == 409 and "90 days" in last.json()["detail"]

    with _admin(urls) as conn:
        conn.execute("UPDATE subscriptions SET status = 'active' WHERE org_id = %s", (world["org"],))
    assert client.post(path, json={**REASON, "days": 7}, headers=ORIGIN).status_code == 409


def test_cancel_scan_fences_the_worker_and_is_logged(world, urls):
    client = _signed_in(world)
    with _admin(urls) as conn:
        conn.execute("UPDATE scans SET status = 'running', claimed_by = 'worker-1', claim_generation = 3, "
                     "lease_expires_at = now() - interval '5 minutes' WHERE id = %s", (world["scan"],))
    path = f"/api/v1/owner/scans/{world['scan']}/cancel"
    resp = client.post(path, json=REASON, headers=ORIGIN)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "cancelled", "previous_status": "running"}
    with _admin(urls) as conn:
        scan = conn.execute("SELECT status, claimed_by, claim_token, lease_expires_at, claim_generation, completed_at "
                            "FROM scans WHERE id = %s", (world["scan"],)).fetchone()
        logged = conn.execute("SELECT user_id, metadata FROM audit_log WHERE org_id = %s AND action = 'scan.cancelled'",
                              (world["org"],)).fetchall()
    assert scan["status"] == "cancelled" and scan["claimed_by"] is None and scan["claim_token"] is None
    assert scan["lease_expires_at"] is None and scan["claim_generation"] == 4 and scan["completed_at"] is not None
    assert logged == [{"user_id": None, "metadata": {"by": "cyphward"}}]

    second = client.post(path, json=REASON, headers=ORIGIN)
    assert second.status_code == 409 and "already cancelled" in second.json()["detail"]
    audit = _owner_audit(urls, world, "owner.action.cancel_scan")
    assert [r["outcome"] for r in audit] == ["success", "rejected"]
    assert audit[0]["metadata"]["from"] == "running" and audit[0]["metadata"]["claimed_by"] == "worker-1"


def test_sign_out_everywhere(world, urls, cleanup):
    client = _signed_in(world)
    future = datetime.now(timezone.utc) + timedelta(days=7)
    with _admin(urls) as conn:
        for i in range(2):
            conn.execute("INSERT INTO auth_sessions (user_id, refresh_token_hash, expires_at) VALUES (%s, %s, %s)",
                         (world["customer"], f"hash-{world['tag']}-{i}", future))
        conn.execute("INSERT INTO auth_sessions (user_id, refresh_token_hash, expires_at, revoked_at) "
                     "VALUES (%s, %s, %s, now())", (world["customer"], f"hash-{world['tag']}-old", future))
        conn.execute("INSERT INTO trusted_browsers (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                     (world["customer"], f"tb-{world['tag']}", future))
    resp = client.post(f"/api/v1/owner/users/{world['customer']}/sign-out", json=REASON, headers=ORIGIN)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"sessions_revoked": 2, "remembered_browsers_cleared": 1}
    with _admin(urls) as conn:
        live = conn.execute("SELECT count(*) AS n FROM auth_sessions WHERE user_id = %s AND revoked_at IS NULL",
                            (world["customer"],)).fetchone()["n"]
        browsers = conn.execute("SELECT count(*) AS n FROM trusted_browsers WHERE user_id = %s",
                                (world["customer"],)).fetchone()["n"]
        owner_sessions = conn.execute("SELECT count(*) AS n FROM owner_sessions WHERE user_id = %s "
                                      "AND revoked_at IS NULL", (world["owner"],)).fetchone()["n"]
    assert live == 0 and browsers == 0 and owner_sessions >= 1

    own = client.post(f"/api/v1/owner/users/{world['owner']}/sign-out", json=REASON, headers=ORIGIN)
    assert own.status_code == 409
    assert client.get("/api/v1/owner/me").status_code == 200, "the owner's console session is untouched"


def test_a_failed_audit_write_leaves_nothing_changed(world, urls, monkeypatch):
    client = _signed_in(world)
    monkeypatch.setattr(owner_mod, "client_ip", lambda request: "bad\x00ip")  # owner_audit insert fails
    resp = client.post(f"/api/v1/owner/scans/{world['scan']}/cancel", json=REASON, headers=ORIGIN)
    assert resp.status_code == 503
    with _admin(urls) as conn:
        assert conn.execute("SELECT status FROM scans WHERE id = %s", (world["scan"],)).fetchone()["status"] == "queued"
        assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE org_id = %s AND action = 'scan.cancelled'",
                            (world["org"],)).fetchone()["n"] == 0
    assert not [r for r in _owner_audit(urls, world, "owner.action.cancel_scan") if r["outcome"] == "success"]
