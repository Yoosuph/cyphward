"""Plan enforcement (review P1 — plan enforcement, line 33).

The onboarding plan selector used to be sent as `sector` while the server
left `organizations.plan` at its database default — advertised plans had
no server meaning. Now creation validates against the server allowlist,
scan/domain/report/invite paths enforce per-plan quotas (402), and the
daily sweep skips orgs at their scan limit. Billing-provider subscription
state is the follow-up; quotas are the server entitlement until then.
"""
from datetime import datetime, timezone

import backend.app.api.members as members_mod
import backend.app.api.scans as scans_mod
from backend.app.core.plans import entitlements_for
from conftest import ADMI, ALICE, BOB, DOM_A1, ORG_A


def _h(auth_headers, user_id, org=None):
    return auth_headers(user_id, email=f"{user_id[:8]}@acme.test", org=org)


def _verify(store, user_id):
    store.profiles[user_id]["email_verified_at"] = datetime.now(timezone.utc)


def _now_scan(store, org_id, i):
    store.scans.append({
        "id": f"quota-scan-{i}", "org_id": org_id, "domain_id": DOM_A1,
        "status": "completed", "created_at": datetime.now(timezone.utc),
    })


class _NoopInngest:
    def __init__(self):
        self.events = []

    async def send(self, event):
        self.events.append(event)
        return {"ok": True}


def test_create_org_stores_plan_not_sector(client, auth_headers, store):
    _verify(store, BOB)
    resp = client.post("/api/v1/organizations",
                       json={"name": "Plan Corp", "plan": "Growth", "sector": "Fintech"},
                       headers=_h(auth_headers, BOB))
    assert resp.status_code == 201
    org = resp.json()["organization"]
    assert org["plan"] == "growth"
    assert org["sector"] == "Fintech"


def test_create_org_rejects_unknown_plan_and_defaults_growth(client, auth_headers, store):
    _verify(store, BOB)
    bad = client.post("/api/v1/organizations", json={"name": "Bad Plan Co", "plan": "Platinum"},
                      headers=_h(auth_headers, BOB))
    assert bad.status_code == 422
    default = client.post("/api/v1/organizations", json={"name": "Default Plan Co"},
                          headers=_h(auth_headers, BOB))
    assert default.status_code == 201
    assert default.json()["organization"]["plan"] == "growth"


def test_current_org_reports_entitlements_and_usage(client, auth_headers, store):
    resp = client.get("/api/v1/organizations/current", headers=_h(auth_headers, ALICE, ORG_A))
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_entitlements"]["plan"] in ("growth", "scale", "sovereign")
    assert set(body["plan_usage"]) == {"monthly_scans", "monthly_reports", "domains", "members"}


def test_legacy_plan_text_falls_back(client, auth_headers, store):
    store.organizations[ORG_A]["plan"] = "Scale"
    resp = client.get("/api/v1/organizations/current", headers=_h(auth_headers, ALICE, ORG_A))
    assert resp.status_code == 200
    assert resp.json()["plan_entitlements"]["plan"] == "growth"


def test_scan_launch_enforces_monthly_quota(client, auth_headers, store, monkeypatch):
    store.organizations[ORG_A]["plan"] = "growth"
    for i in range(300):
        _now_scan(store, ORG_A, i)
    monkeypatch.setattr(scans_mod, "inngest_client", _NoopInngest())
    resp = client.post("/api/v1/scans/launch", json={"domain_id": DOM_A1},
                       headers=_h(auth_headers, ADMI, ORG_A))
    assert resp.status_code == 402
    assert "quota" in resp.json()["detail"].lower()


def test_scan_launch_under_quota_succeeds(client, auth_headers, store, monkeypatch):
    store.organizations[ORG_A]["plan"] = "growth"
    monkeypatch.setattr(scans_mod, "inngest_client", _NoopInngest())
    resp = client.post("/api/v1/scans/launch", json={"domain_id": DOM_A1},
                       headers=_h(auth_headers, ADMI, ORG_A))
    assert resp.status_code == 200


def test_scan_launch_retries_return_same_job_without_redispatch(client, auth_headers, store, monkeypatch):
    provider = _NoopInngest()
    monkeypatch.setattr(scans_mod, "inngest_client", provider)
    headers = {**_h(auth_headers, ADMI, ORG_A), "Idempotency-Key": "browser-intent-123"}
    first = client.post("/api/v1/scans/launch", json={"domain_id": DOM_A1}, headers=headers)
    replay = client.post("/api/v1/scans/launch", json={"domain_id": DOM_A1}, headers=headers)
    assert first.status_code == replay.status_code == 200
    assert first.json()["scan"]["id"] == replay.json()["scan"]["id"]
    assert replay.json()["replayed"] is True
    assert len(provider.events) == 1


def test_scan_launch_rejects_reused_key_with_different_domain(client, auth_headers, store, monkeypatch):
    provider = _NoopInngest()
    monkeypatch.setattr(scans_mod, "inngest_client", provider)
    other_domain = "d1111111-0000-4000-8000-000000000002"
    store.domains.append({"id": other_domain, "org_id": ORG_A, "domain": "other.acme.test",
                          "verification_status": "verified", "created_at": datetime.now(timezone.utc)})
    headers = {**_h(auth_headers, ADMI, ORG_A), "Idempotency-Key": "same-key"}
    first = client.post("/api/v1/scans/launch", json={"domain_id": DOM_A1}, headers=headers)
    conflict = client.post("/api/v1/scans/launch", json={"domain_id": other_domain}, headers=headers)
    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_key_reused"
    assert len(provider.events) == 1


def test_scan_launch_active_domain_conflict_returns_existing_scan(client, auth_headers, store, monkeypatch):
    provider = _NoopInngest()
    monkeypatch.setattr(scans_mod, "inngest_client", provider)
    first = client.post("/api/v1/scans/launch", json={"domain_id": DOM_A1},
                        headers={**_h(auth_headers, ADMI, ORG_A), "Idempotency-Key": "first-intent"})
    second = client.post("/api/v1/scans/launch", json={"domain_id": DOM_A1},
                         headers={**_h(auth_headers, ADMI, ORG_A), "Idempotency-Key": "second-intent"})
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "scan_already_active"
    assert second.json()["scan_id"] == first.json()["scan"]["id"]
    assert len(provider.events) == 1


def test_scan_launch_keeps_verified_domain_tenant_boundary(client, auth_headers, store, monkeypatch):
    provider = _NoopInngest()
    monkeypatch.setattr(scans_mod, "inngest_client", provider)
    store.domains.append({"id": "d2222222-0000-4000-8000-000000000002", "org_id": "22222222-bbbb-4bbb-8bbb-222222222222",
                          "domain": "other.test", "verification_status": "verified"})
    response = client.post("/api/v1/scans/launch",
                           json={"domain_id": "d2222222-0000-4000-8000-000000000002"},
                           headers=_h(auth_headers, ADMI, ORG_A))
    assert response.status_code == 404
    assert provider.events == []


def test_scan_launch_rejects_unverified_domain_without_consuming_quota(client, auth_headers, store, monkeypatch):
    provider = _NoopInngest()
    monkeypatch.setattr(scans_mod, "inngest_client", provider)
    pending_id = "d1111111-0000-4000-8000-000000000003"
    scan_count = len(store.scans)
    store.domains.append({"id": pending_id, "org_id": ORG_A, "domain": "pending.acme.test",
                          "verification_status": "pending"})
    response = client.post("/api/v1/scans/launch", json={"domain_id": pending_id},
                           headers=_h(auth_headers, ADMI, ORG_A))
    assert response.status_code == 403
    assert len(store.scans) == scan_count
    assert provider.events == []


def test_domain_add_enforces_limit(client, auth_headers, store):
    store.organizations[ORG_A]["plan"] = "growth"
    for i in range(10):
        store.domains.append({"id": f"dom-q{i}", "org_id": ORG_A, "domain": f"q{i}.acme.test",
                              "verification_status": "verified"})
    resp = client.post("/api/v1/domains", json={"domain": "new.acme.test"},
                       headers=_h(auth_headers, ADMI, ORG_A))
    assert resp.status_code == 402


def test_report_create_enforces_monthly_quota(client, auth_headers, store):
    store.organizations[ORG_A]["plan"] = "growth"
    now = datetime.now(timezone.utc)
    for i in range(300):
        store.reports.append({"id": f"r-{i}", "org_id": ORG_A, "domain_id": DOM_A1,
                              "title": "t", "status": "ready", "summary": {},
                              "created_at": now})
    resp = client.post("/api/v1/reports", json={"domain_id": DOM_A1},
                       headers=_h(auth_headers, ADMI, ORG_A))
    assert resp.status_code == 402


def test_invite_enforces_member_limit(client, auth_headers, store, monkeypatch):
    async def fake_send(*a, **k):
        return {"success": True}
    monkeypatch.setattr(members_mod, "send_email_async", fake_send)
    store.organizations[ORG_A]["plan"] = "starter"
    # starter allows only the owner: 4 existing memberships already exceed it

    resp = client.post("/api/v1/members/invite",
                       json={"email": "newbie@example.com", "full_name": "Newbie"},
                       headers=_h(auth_headers, ADMI, ORG_A))
    assert resp.status_code == 402


def test_patch_plan_change_validated_and_audited(client, auth_headers, store):
    store.organizations[ORG_A]["plan"] = "starter"
    resp = client.patch("/api/v1/organizations/current", json={"plan": "Growth"},
                        headers=_h(auth_headers, ALICE, ORG_A))
    assert resp.status_code == 200
    assert resp.json()["organization"]["plan"] == "growth"
    bad = client.patch("/api/v1/organizations/current", json={"plan": "Platinum"},
                       headers=_h(auth_headers, ALICE, ORG_A))
    assert bad.status_code == 422
    assert store.organizations[ORG_A]["plan"] == "growth"


def test_entitlements_for_legacy_text():
    ent = entitlements_for({"plan": "Enterprise Defense"})
    assert ent["plan"] == "growth" and ent["monthly_scans"] == 300
    assert entitlements_for({"plan": "Scale"})["plan"] == "growth"
    assert entitlements_for({"plan": "starter"})["max_domains"] == 1
    assert entitlements_for({"plan": "growth"})["max_members"] == 25
