"""Workspace data lifecycle (review P2 — data lifecycle).

Export (data portability) and closure (right to be forgotten) are
owner-only. Closure cascades the whole tenant subtree in one DELETE while
a NULL-org tombstone keeps the closure itself on record; other tenants
are untouched. Secret material must never appear in an export.
"""
import json

from conftest import ADMI, ALICE, BOB, ORG_A, ORG_B


def _h(auth_headers, user_id, org=None):
    return auth_headers(user_id, email=f"{user_id[:8]}@acme.test", org=org)


def test_export_returns_full_bundle_without_secrets(client, auth_headers, store):
    resp = client.get("/api/v1/organizations/export", headers=_h(auth_headers, ALICE, ORG_A))
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")
    body = resp.json()
    assert set(body) == {"exported_at", "organization", "members", "domains", "assets",
                         "findings", "scans", "score_snapshots", "reports", "invitations"}
    assert body["organization"]["id"] == ORG_A
    assert len(body["members"]) == 4  # ALICE owner, BOB + DAVE members, ADMI admin
    assert len(body["findings"]) == 3
    text = json.dumps(body)
    assert "token_hash" not in text and "password_hash" not in text
    assert "refresh_token" not in text
    events = [a for a in store.audit if a["params"][2] == "org.exported"]
    assert len(events) == 1 and events[0]["params"][0] == ORG_A


def test_export_forbidden_for_non_owners(client, auth_headers, store):
    assert client.get("/api/v1/organizations/export",
                      headers=_h(auth_headers, ADMI, ORG_A)).status_code == 403
    assert client.get("/api/v1/organizations/export",
                      headers=_h(auth_headers, BOB, ORG_A)).status_code == 403


def test_close_rejects_wrong_slug_and_non_owner(client, auth_headers, store):
    bad = client.post("/api/v1/organizations/close", json={"slug": "nope"},
                      headers=_h(auth_headers, ALICE, ORG_A))
    assert bad.status_code == 400
    assert ORG_A in store.organizations
    assert client.post("/api/v1/organizations/close", json={"slug": "acme-traders"},
                       headers=_h(auth_headers, ADMI, ORG_A)).status_code == 403


def test_close_cascades_tenant_subtree_and_leaves_tombstone(client, auth_headers, store):
    slug = store.organizations[ORG_A]["slug"]
    resp = client.post("/api/v1/organizations/close", json={"slug": slug},
                       headers=_h(auth_headers, ALICE, ORG_A))
    assert resp.status_code == 200
    assert resp.json() == {"closed": True, "org_id": ORG_A}

    assert ORG_A not in store.organizations
    assert all(m["org_id"] != ORG_A for m in store.memberships)
    assert all(d["org_id"] != ORG_A for d in store.domains)
    assert all(a["org_id"] != ORG_A for a in store.assets)
    assert all(f["org_id"] != ORG_A for f in store.findings)
    assert all(x["org_id"] != ORG_A for x in store.scans)
    assert all(r["org_id"] != ORG_A for r in store.reports)
    assert all(i["org_id"] != ORG_A for i in store.organization_invites)

    # other tenant untouched (org, memberships, findings)
    assert ORG_B in store.organizations
    assert any(m["org_id"] == ORG_B for m in store.memberships)
    assert any(f["org_id"] == ORG_B for f in store.findings)

    # tombstone survives with NULL org (tenant audit rows cascaded away)
    tombs = [a for a in store.audit if a["params"][2] == "org.closed"]
    assert len(tombs) == 1
    assert tombs[0]["params"][0] is None
    assert json.loads(tombs[0]["params"][5])["slug"] == slug
    assert all(a["params"][0] != ORG_A for a in store.audit)
