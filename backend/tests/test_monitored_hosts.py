"""Manually monitored hosts (scan-scope registration).

Passive discovery misses real hosts (no CT footprint, wildcard certs,
fresh DNS). Owners/admins register hostnames under a VERIFIED domain;
every scan then probes them regardless of passive discovery. Scope is
enforced at registration (domain or its subdomain only) and re-checked
by the worker's scope filter; unresolved registered hosts still appear
as 'discovered' inventory without clobbering assessed rows.
"""
from conftest import ADMI, ALICE, BOB, DOM_A1, ORG_A, ORG_B


def _h(auth_headers, user_id, org=None):
    return auth_headers(user_id, email=f"{user_id[:8]}@acme.test", org=org)


def test_register_and_list_hosts(client, auth_headers, store):
    resp = client.post(f"/api/v1/domains/{DOM_A1}/hosts", json={"hostname": "Shop.ACME.test "},
                       headers=_h(auth_headers, ADMI, ORG_A))
    assert resp.status_code == 201
    assert resp.json()["host"]["hostname"] == "shop.acme.test"
    listed = client.get(f"/api/v1/domains/{DOM_A1}/hosts", headers=_h(auth_headers, BOB, ORG_A))
    assert [h["hostname"] for h in listed.json()["hosts"]] == ["shop.acme.test"]


def test_register_rejects_out_of_scope_and_duplicates(client, auth_headers, store):
    evil = client.post(f"/api/v1/domains/{DOM_A1}/hosts", json={"hostname": "evil.other.test"},
                       headers=_h(auth_headers, ADMI, ORG_A))
    assert evil.status_code == 400
    client.post(f"/api/v1/domains/{DOM_A1}/hosts", json={"hostname": "dup.acme.test"},
                headers=_h(auth_headers, ADMI, ORG_A))
    dup = client.post(f"/api/v1/domains/{DOM_A1}/hosts", json={"hostname": "dup.acme.test"},
                      headers=_h(auth_headers, ADMI, ORG_A))
    assert dup.status_code == 400
    bad = client.post(f"/api/v1/domains/{DOM_A1}/hosts", json={"hostname": "not a host!!"},
                      headers=_h(auth_headers, ADMI, ORG_A))
    assert bad.status_code == 400


def test_register_requires_member_admin_and_verified_domain(client, auth_headers, store):
    store.domains.append({"id": "dom-pending", "org_id": ORG_A, "domain": "pending.test",
                          "verification_status": "pending"})
    pending = client.post("/api/v1/domains/dom-pending/hosts", json={"hostname": "x.pending.test"},
                          headers=_h(auth_headers, ADMI, ORG_A))
    assert pending.status_code == 400
    member = client.post(f"/api/v1/domains/{DOM_A1}/hosts", json={"hostname": "m.acme.test"},
                         headers=_h(auth_headers, BOB, ORG_A))
    assert member.status_code == 403


def test_register_shares_domain_budget(client, auth_headers, store):
    store.organizations[ORG_A]["plan"] = "starter"  # 1-domain budget, 1 domain used
    over_first = client.post(f"/api/v1/domains/{DOM_A1}/hosts", json={"hostname": "h0.acme.test"},
                               headers=_h(auth_headers, ADMI, ORG_A))
    assert over_first.status_code == 402
    over = client.post(f"/api/v1/domains/{DOM_A1}/hosts", json={"hostname": "over.acme.test"},
                       headers=_h(auth_headers, ADMI, ORG_A))
    assert over.status_code == 402


def test_remove_host(client, auth_headers, store):
    created = client.post(f"/api/v1/domains/{DOM_A1}/hosts", json={"hostname": "gone.acme.test"},
                          headers=_h(auth_headers, ADMI, ORG_A)).json()["host"]
    assert client.delete(f"/api/v1/domains/{DOM_A1}/hosts/{created['id']}",
                         headers=_h(auth_headers, ADMI, ORG_A)).json() == {"removed": True}
    assert client.get(f"/api/v1/domains/{DOM_A1}/hosts",
                      headers=_h(auth_headers, ADMI, ORG_A)).json() == {"hosts": []}
    assert client.delete(f"/api/v1/domains/{DOM_A1}/hosts/{created['id']}",
                         headers=_h(auth_headers, ADMI, ORG_A)).status_code == 404


def test_registered_hosts_union_into_discovery():
    from backend.app.workflows.inngest_workflow import _registered_hosts
    import backend.app.workflows.inngest_workflow as wf_mod

    calls = []
    orig = wf_mod.execute_query
    wf_mod.execute_query = lambda sql, params=(): (
        calls.append(params) or [{"hostname": "portal.acme.test"}])
    try:
        assert _registered_hosts(ORG_A, DOM_A1) == ["portal.acme.test"]
    finally:
        wf_mod.execute_query = orig
    assert calls[0] == (ORG_A, DOM_A1)


def test_cross_tenant_domain_rejected(client, auth_headers, store):
    resp = client.post(f"/api/v1/domains/{DOM_A1}/hosts", json={"hostname": "x.acme.test"},
                       headers=_h(auth_headers, ALICE, ORG_B))
    assert resp.status_code in (403, 404)
