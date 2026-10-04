"""Platform-staff authorization (review P1 — workspace authorization).

Organization roles must never confer cross-tenant platform rights: every
/internal route requires a separate live `platform_staff` grant plus a
verified email, tenant-touching routes require a support reason, and each
such access writes an immutable audit event. Responses carry identifiers
and counts only — never scan evidence or member personal data.
"""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from conftest import ORG_A, ORG_B, ALICE, ADMI, BOB


def _h(auth_headers, user_id, org=None):
    return auth_headers(user_id, email=f"{user_id[:8]}@acme.test", org=org)


def _verify(store, user_id):
    store.profiles[user_id]["email_verified_at"] = datetime.now(timezone.utc)


def _grant(store, user_id, scopes=("platform:read",), **kw):
    g = {
        "id": str(uuid4()), "user_id": user_id, "scopes": list(scopes),
        "granted_by": None, "reason": "support onboarding",
        "expires_at": None, "revoked_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    g.update(kw)
    store.staff_grants.append(g)
    return g


def _audit(store, action):
    return [a for a in store.audit if a["params"][2] == action]


def test_health_denies_org_owner_without_grant(client, auth_headers, store):
    _verify(store, ALICE)  # owner of ORG_A — still no platform rights
    resp = client.get("/api/v1/platform/health", headers=_h(auth_headers, ALICE))
    assert resp.status_code == 403


def test_health_denies_unverified_email_with_live_grant(client, auth_headers, store):
    _grant(store, BOB)
    resp = client.get("/api/v1/platform/health", headers=_h(auth_headers, BOB))
    assert resp.status_code == 403


def test_health_allows_granted_verified_staff(client, auth_headers, store):
    _verify(store, ADMI)
    _grant(store, ADMI)
    resp = client.get("/api/v1/platform/health", headers=_h(auth_headers, ADMI))
    assert resp.status_code == 200
    body = resp.json()
    assert body["database"]["connected"] is True
    assert body["scans_active"] == 0


def test_expired_and_revoked_grants_denied(client, auth_headers, store):
    _verify(store, BOB)
    _grant(store, BOB, expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    assert client.get("/api/v1/platform/health",
                      headers=_h(auth_headers, BOB)).status_code == 403
    store.staff_grants.clear()
    _grant(store, BOB, revoked_at=datetime.now(timezone.utc))
    assert client.get("/api/v1/platform/health",
                      headers=_h(auth_headers, BOB)).status_code == 403


def test_missing_scope_denied(client, auth_headers, store):
    _verify(store, BOB)
    _grant(store, BOB, scopes=[])
    resp = client.get("/api/v1/platform/health", headers=_h(auth_headers, BOB))
    assert resp.status_code == 403


def test_tenant_lookup_cross_org_allowed_for_staff(client, auth_headers, store):
    _verify(store, ALICE)  # owner of A looking at B — allowed ONLY via grant
    _grant(store, ALICE)
    resp = client.get(f"/api/v1/platform/tenants/{ORG_B}?reason=support+triage+request",
                      headers=_h(auth_headers, ALICE))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == ORG_B and body["name"] == "Other Holdings"
    assert body["member_count"] == 2 and body["domain_count"] == 0
    assert "email" not in json.dumps(body)  # no member personal data
    events = _audit(store, "platform.tenant_lookup")
    assert len(events) == 1
    meta = json.loads(events[0]["params"][5])
    assert meta["reason"] == "support triage request"
    assert events[0]["params"][0] == ORG_B  # target tenant on the event


def test_tenant_lookup_requires_reason_and_known_org(client, auth_headers, store):
    _verify(store, ALICE)
    _grant(store, ALICE)
    assert client.get(f"/api/v1/platform/tenants/{ORG_B}",
                      headers=_h(auth_headers, ALICE)).status_code == 422
    assert client.get(
        "/api/v1/platform/tenants/00000000-0000-4000-8000-000000000000"
        "?reason=support+triage+request",
        headers=_h(auth_headers, ALICE)).status_code == 404


def test_overdue_scans_returns_only_stuck(client, auth_headers, store):
    _verify(store, ADMI)
    _grant(store, ADMI)
    now = datetime.now(timezone.utc)
    store.scans.append({
        "id": "stuck-1", "org_id": ORG_A, "domain_id": None, "status": "running",
        "created_at": now - timedelta(hours=5),
        "lease_expires_at": now - timedelta(hours=3),
    })
    store.scans.append({
        "id": "fresh-1", "org_id": ORG_B, "domain_id": None, "status": "running",
        "created_at": now - timedelta(minutes=5),
        "lease_expires_at": now + timedelta(hours=1),
    })
    resp = client.get("/api/v1/platform/scans/overdue?reason=queue+triage+morning",
                      headers=_h(auth_headers, ADMI))
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["scans"][0]["id"] == "stuck-1"
    assert body["scans"][0]["org_name"] == "Acme Traders"
    assert "error_message" not in body["scans"][0]
    assert len(_audit(store, "platform.overdue_scans")) == 1
    # reason required here too
    assert client.get("/api/v1/platform/scans/overdue",
                      headers=_h(auth_headers, ADMI)).status_code == 422


def test_platform_routes_require_auth(client):
    assert client.get("/api/v1/platform/health").status_code == 401
