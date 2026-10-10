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


def test_set_plan_creates_subscription_and_invoice(client, auth_headers, store):
    resp = client.post("/api/v1/billing/subscription", json={"plan": "Growth"},
                       headers=_h(auth_headers, ALICE, ORG_A))
    assert resp.status_code == 200
    body = resp.json()
    assert body["subscription"]["plan"] == "growth"
    assert body["subscription"]["status"] == "active"
    assert body["invoice"]["amount_kobo"] == 1_500_000
    assert body["invoice"]["currency"] == "NGN"

    got = client.get("/api/v1/billing/subscription", headers=_h(auth_headers, ALICE, ORG_A))
    assert got.status_code == 200
    assert got.json()["effective_status"] == "active"
    assert got.json()["entitlements"]["plan"] == "growth"
    inv = client.get("/api/v1/billing/invoices", headers=_h(auth_headers, ALICE, ORG_A))
    assert len(inv.json()["invoices"]) == 1


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


def test_cancel_and_renew_lifecycle(client, auth_headers, store):
    client.post("/api/v1/billing/subscription", json={"plan": "growth"},
                headers=_h(auth_headers, ALICE, ORG_A))
    cancel = client.post("/api/v1/billing/subscription/cancel",
                         headers=_h(auth_headers, ALICE, ORG_A))
    assert cancel.json()["subscription"]["cancel_at_period_end"] is True
    renew = client.post("/api/v1/billing/subscription/renew",
                        headers=_h(auth_headers, ALICE, ORG_A))
    sub = renew.json()["subscription"]
    assert sub["cancel_at_period_end"] is False and sub["status"] == "active"
    assert len(store.invoices) == 2  # set + renew


def test_past_due_and_lapsed_fall_back_to_growth_floor():
    from backend.app.billing.subscriptions import effective_status, resolve_plan
    org = {"id": "x", "plan": "growth"}
    past = {"plan": "growth", "status": "past_due",
            "current_period_end": datetime.now(timezone.utc).isoformat(),
            "cancel_at_period_end": False}
    assert resolve_plan(org, past)["plan"] == "starter"
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
