"""Scope intent must explain caps and cannot invent successful assessments."""
import asyncio
from types import SimpleNamespace

import pytest

from shared.contracts import ScanJob, ScanJobLimits
from shared.scan_scope import select_targets
from scanner import runner


def test_registered_and_apex_priority_survive_passive_cap_and_order_changes():
    passive = [f"a{i:03}.acme.test" for i in range(60)] + ["evil.test", "*.acme.test"]
    def plan(values):
        return select_targets("Acme.Test.", ["acme.test"], values,
                              ["z.acme.test", "Z.ACME.TEST."], max_hosts=50, dns_max_hosts=40)
    selection = plan(passive)
    assert selection == plan(reversed(passive))
    assert selection.selected_hosts[:2] == ["acme.test", "z.acme.test"]
    assert len(selection.selected_hosts) == 40
    assert selection.omitted_hosts["a038.acme.test"] == "dns_max_hosts"
    assert selection.omitted_hosts["a048.acme.test"] == "max_hosts"
    assert selection.omitted_hosts["evil.test"] == "outside_authorised_scope"
    assert selection.omitted_hosts["*.acme.test"] == "invalid_hostname"
    assert "successful_hosts" not in selection.payload()


@pytest.mark.parametrize("target,scope", [("evil.test", ["acme.test"]),
                                         ("acme.test:443", ["acme.test"]),
                                         ("acme.test", [])])
def test_invalid_authority_cannot_produce_plan(target, scope):
    with pytest.raises(ValueError):
        select_targets(target, scope, [], [], max_hosts=500, dns_max_hosts=40)


def test_smaller_total_cap_is_explained_and_apex_does_not_mean_discovered():
    plan = select_targets("acme.test", ["acme.test"], ["a.acme.test"],
                          ["z.acme.test"], max_hosts=1, dns_max_hosts=40)
    assert plan.selected_hosts == ["acme.test"]
    assert plan.omitted_hosts == {"z.acme.test": "max_hosts", "a.acme.test": "max_hosts"}


def test_worker_probes_only_selected_publicly_resolved_hosts(monkeypatch):
    posted, resolved, probed = {}, [], []
    async def discover(target):
        return ["a.acme.test", "private.acme.test", "outside.test"], []
    async def dns(host):
        resolved.append(host)
        return {"hostname": host, "primary_ip": None if host.startswith("private") else "8.8.8.8"}
    async def http(host, **kwargs):
        probed.append(host)
        return {"hostname": host, "http_status": 200}
    class Client:
        async def progress(self, *args, **kwargs):
            pass
        async def observations(self, job, stage, data):
            posted[stage] = data
    monkeypatch.setattr(runner, "discover_subdomains_with_health", discover)
    monkeypatch.setattr(runner, "resolve_host_dns", dns)
    monkeypatch.setattr(runner, "probe_http_service", http)
    monkeypatch.setattr(runner, "_tool", lambda binary: False)
    job = ScanJob(scan_id="s1", organization_id="o1", domain_id="d1", target="acme.test",
                  scope=["acme.test"], seed_hosts=["z.acme.test", "private.acme.test"],
                  created_at="now", lease_expires_at="later", claim_generation=1,
                  claim_token="test-claim-token-0000000000000000000000",
                  limits=ScanJobLimits(dns_max_hosts=3))
    asyncio.run(runner.execute_job(Client(), SimpleNamespace(heartbeat_seconds=30,
                                                           http_probe_concurrency=2), job))
    assert resolved == ["acme.test", "private.acme.test", "z.acme.test"]
    assert probed == ["acme.test", "z.acme.test"]
    assert posted["discovery"]["target_selection"]["omitted_hosts"] == {
        "a.acme.test": "dns_max_hosts", "outside.test": "outside_authorised_scope"}


def test_local_recon_persists_same_selection_before_probing(store, monkeypatch):
    from backend.app.workflows import inngest_workflow as wf
    from conftest import prepare_execution_claim
    from test_scan_cancel_fencing import _add_scan
    sid = _add_scan(store)
    resolved = []
    async def discover(target):
        return ["a.acme.test", "outside.test"], []
    async def dns(host):
        resolved.append(host)
        return {"hostname": host, "primary_ip": None, "records": {}}
    monkeypatch.setattr(wf, "SCANNER_MODE", "local")
    monkeypatch.setattr(wf, "SCANNER_DNS_MAX_HOSTS", 2)
    monkeypatch.setattr(wf, "_registered_hosts", lambda *args: ["z.acme.test"])
    monkeypatch.setattr(wf, "discover_subdomains_with_health", discover)
    monkeypatch.setattr(wf, "resolve_host_dns", dns)
    monkeypatch.setattr(wf, "_tool_available", lambda binary: False)
    asyncio.run(wf.execute_recon_local(sid, prepare_execution_claim(store, sid, "local")))
    observation = next(r for r in store.scan_results if r["scan_id"] == sid and r["stage"] == "discovery")
    expected = select_targets("acme.test", ["acme.test"], ["a.acme.test", "outside.test"],
                              ["z.acme.test"], max_hosts=wf.SCANNER_MAX_HOSTS, dns_max_hosts=2)
    assert observation["raw_data"]["target_selection"] == expected.payload()
    assert resolved == expected.selected_hosts == ["acme.test", "z.acme.test"]
