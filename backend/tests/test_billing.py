"""Billing model (provider NOT wired).

Subscriptions govern entitlements when live, else the org plan text
applies. past_due/canceled (or a lapsed period) falls back to the growth
floor. Plan sets/renews raise dated open invoices for growth/scale (never
for custom sovereign); cancel is at period end. The provider seam only
records — no payment network is called.
"""
from datetime import datetime, timedelta, timezone

from conftest import ADMI, ALICE, BOB, ORG_A


def _h(auth_headers, user_id, org=None):
    return auth_headers(user_id, email=f"{user_id[:8]}@acme.test", org=org)


def test_customer_cannot_self_activate_or_renew(client, auth_headers, store):
    before_subs = list(store.subscriptions)
    for path, body in [("/api/v1/billing/subscription", {"plan": "Growth"}),
                       ("/api/v1/billing/subscription/renew", None)]:
        resp = client.post(path, json=body, headers=_h(auth_headers, ALICE, ORG_A))
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "manual_billing_review_required"
    assert store.subscriptions == before_subs
    assert store.invoices == []


def test_retired_plan_rejected(client, auth_headers, store):
    assert client.post("/api/v1/billing/subscription", json={"plan": "Sovereign"},
                       headers=_h(auth_headers, ALICE, ORG_A)).status_code == 422
    assert store.invoices == []


def test_invalid_plan_rejected_and_member_forbidden(client, auth_headers, store):
    assert client.post("/api/v1/billing/subscription", json={"plan": "Platinum"},
                       headers=_h(auth_headers, ALICE, ORG_A)).status_code == 422
    assert client.post("/api/v1/billing/subscription", json={"plan": "growth"},
                       headers=_h(auth_headers, BOB, ORG_A)).status_code == 403
    assert client.get("/api/v1/billing/invoices",
                      headers=_h(auth_headers, ADMI, ORG_A)).status_code == 403


def test_cancel_keeps_period_and_renew_does_not_restart_trial(client, auth_headers, store):
    end = datetime.now(timezone.utc) + timedelta(days=9)
    store.subscriptions.append({"id": "sub", "org_id": ORG_A, "plan": "growth", "status": "trialing",
                                "current_period_end": end, "trial_ends_at": end, "cancel_at_period_end": False})
    cancel = client.post("/api/v1/billing/subscription/cancel", headers=_h(auth_headers, ALICE, ORG_A))
    assert cancel.status_code == 200
    assert cancel.json()["subscription"]["cancel_at_period_end"] is True
    assert client.post("/api/v1/billing/subscription/renew", headers=_h(auth_headers, ALICE, ORG_A)).status_code == 409
    assert store.subscriptions[0]["status"] == "trialing"
    assert store.subscriptions[0]["current_period_end"] == end
    assert store.invoices == []


def test_expiry_stops_new_work_without_hiding_subscription_state():
    from backend.app.billing.subscriptions import effective_status, resolve_plan
    org = {"id": "x", "plan": "growth"}
    past = {"plan": "growth", "status": "past_due",
            "current_period_end": datetime.now(timezone.utc).isoformat(),
            "cancel_at_period_end": False}
    assert resolve_plan(org, past)["plan"] == "starter"
    assert resolve_plan(org, past)["monthly_scans"] == 0
    assert resolve_plan(org, past)["monthly_reports"] == 0
    live = {"plan": "growth", "status": "active",
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
            "cancel_at_period_end": False}
    assert resolve_plan(org, live)["plan"] == "growth"
    assert resolve_plan({"id": "x", "plan": "Enterprise Defense"}, None)["plan"] == "growth"
    lapsed = {"plan": "growth", "status": "active",
              "current_period_end": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
              "cancel_at_period_end": False}
    assert effective_status(lapsed) == "past_due"
    assert resolve_plan(org, lapsed)["plan"] == "starter"


def test_expired_trial_cannot_be_reactivated_by_plan_selection(client, auth_headers, store):
    end = datetime.now(timezone.utc) - timedelta(days=2)
    store.subscriptions.append({"id": "sub", "org_id": ORG_A, "plan": "growth", "status": "trialing", "current_period_end": end})
    response = client.post("/api/v1/billing/subscription", json={"plan": "starter"}, headers=_h(auth_headers, ALICE, ORG_A))
    assert response.status_code == 409
    assert store.subscriptions[0]["current_period_end"] == end
    assert store.subscriptions[0]["plan"] == "growth"
    response = client.get("/api/v1/billing/subscription", headers=_h(auth_headers, ALICE, ORG_A))
    assert response.status_code == 200
    assert response.json()["entitlements"]["monthly_scans"] == 0
    assert response.json()["billing_mode"] == "manual_confirmation"
