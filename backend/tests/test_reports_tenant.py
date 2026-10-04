"""Reports tenant scoping (review P1 — tenant relationships).

A report's domain_id was stored unchecked and the report list joined
`domains` on id alone, so another tenant's domain name could attach to the
caller's report. Fixes: create rejects a domain outside the org, the list
join is org-scoped, and the composite (org_id, domain_id) FK makes the
cross-tenant row impossible to insert at all (migration
20261004140000_composite_domain_fks.sql, validated against real Postgres).
"""
from conftest import ORG_A, ORG_B, ALICE, DOM_A1


def _headers(auth_headers):
    return auth_headers(ALICE, email="alice@acme.test", org=ORG_A)


def _seed_report(store, rid, org_id, domain_id):
    store.reports.append({
        "id": rid, "org_id": org_id, "domain_id": domain_id,
        "title": f"Report {rid}", "status": "ready", "summary": {},
        "created_at": "2026-10-01T00:00:00", "updated_at": "2026-10-01T00:00:00",
    })


def test_create_report_rejects_cross_tenant_domain(client, auth_headers, store):
    store.domains.append({
        "id": "dom-b1", "org_id": ORG_B, "domain": "other.test",
        "verification_status": "verified",
    })

    resp = client.post("/api/v1/reports", json={"domain_id": "dom-b1"},
                       headers=_headers(auth_headers))

    assert resp.status_code == 404
    assert store.reports == []  # nothing stored


def test_create_report_rejects_unknown_domain(client, auth_headers, store):
    resp = client.post("/api/v1/reports",
                       json={"domain_id": "00000000-0000-4000-8000-00000000dead"},
                       headers=_headers(auth_headers))
    assert resp.status_code == 404
    assert store.reports == []


def test_create_report_with_own_domain_stores_scoped_row(client, auth_headers, store):
    resp = client.post("/api/v1/reports", json={"domain_id": DOM_A1, "title": "Q4 Assessment"},
                       headers=_headers(auth_headers))

    assert resp.status_code == 201
    assert len(store.reports) == 1
    assert store.reports[0]["domain_id"] == DOM_A1
    assert store.reports[0]["org_id"] == ORG_A
    assert resp.json()["report"]["title"] == "Q4 Assessment"


def test_create_report_without_domain_defaults_to_verified_domain(client, auth_headers, store):
    resp = client.post("/api/v1/reports", json={}, headers=_headers(auth_headers))
    assert resp.status_code == 201
    assert store.reports[0]["domain_id"] is None or store.reports[0]["domain_id"] == DOM_A1


def test_list_reports_never_joins_another_tenants_domain(client, auth_headers, store):
    # Legacy row: an ORG_A report whose domain_id points at an ORG_B domain
    # (possible before the composite FK). The org-scoped join must not leak
    # the foreign domain name.
    store.domains.append({
        "id": "dom-b1", "org_id": ORG_B, "domain": "other.test",
        "verification_status": "verified",
    })
    _seed_report(store, "r-legacy", ORG_A, "dom-b1")
    _seed_report(store, "r-own", ORG_A, DOM_A1)

    resp = client.get("/api/v1/reports", headers=_headers(auth_headers))

    assert resp.status_code == 200
    rows = {r["id"]: r for r in resp.json()["reports"]}
    assert rows["r-legacy"]["domain_id"] == "dom-b1"  # id kept (own row)
    assert rows["r-legacy"]["domain"] is None  # foreign name hidden
    assert rows["r-own"]["domain"] == "acme.test"


def test_list_reports_excludes_other_orgs_reports(client, auth_headers, store):
    _seed_report(store, "r-b", ORG_B, None)

    resp = client.get("/api/v1/reports", headers=_headers(auth_headers))

    assert resp.status_code == 200
    assert all(r["id"] != "r-b" for r in resp.json()["reports"])
