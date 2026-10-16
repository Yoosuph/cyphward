"""Work deadlines preserve finished evidence and reap unfinished subprocesses."""
import asyncio
from pathlib import Path
import sys

import pytest

from shared.scan_budget import ReconBudget, gather_with_deadline
from backend.app.scanner.recon_policy import THIRD_PARTY_SERVICE, stage_plan, evaluate_stage, collect_http_results
from backend.app.scanner.tool_results import collect_tool_results
from backend.app.scanner import naabu_runner, sslyze_runner, nuclei_runner, discovery

HOSTS = ["acme.test", "registered.acme.test", "a.acme.test"]


def test_stage_caps_preserve_order_and_explain_missing_tools_and_ineligible_targets():
    dns = [{"hostname": host, "primary_ip": "8.8.8.8"} for host in HOSTS]
    http = [{"hostname": host, "http_status": 200, "url": "https://" + host} for host in HOSTS]
    plan = stage_plan("tls", HOSTS, ["acme.test"], dns, http, cap=2)
    assert plan["selected_hosts"] == HOSTS[:2]
    assert plan["omitted_hosts"] == {HOSTS[2]: "stage_host_cap"}
    plan = stage_plan("nuclei", HOSTS, ["acme.test"], dns, http, cap=0)
    assert plan["selected_hosts"] == []
    assert set(plan["omitted_hosts"].values()) == {"stage_host_cap"}
    plan = stage_plan("ports", HOSTS, ["acme.test"], dns, available=False)
    assert set(plan["omitted_hosts"].values()) == {"tool_unavailable"}
    dns[0]["primary_ip"] = None
    assert stage_plan("http", HOSTS, ["acme.test"], dns)["omitted_hosts"][HOSTS[0]] == "no_public_dns_address"
    http[0]["url"] = "http://acme.test"
    http[1]["error"] = "redirect blocked"
    plan = stage_plan("tls", HOSTS, ["acme.test"], dns, http)
    assert plan["omitted_hosts"] == {HOSTS[0]: "no_https_response", HOSTS[1]: "no_usable_http_response"}


def test_exhausted_budget_does_not_invoke_stage_and_persists_omissions():
    clock = [0.0]
    budget = ReconBudget(10, 5, clock=lambda: clock[0])
    clock[0] = 11
    async def no_call():
        raise AssertionError("no stage may start after budget exhaustion")
    plan = stage_plan("dns", HOSTS, ["acme.test"])
    batch = asyncio.run(evaluate_stage(budget, plan, no_call))
    assert batch.attempted_hosts == []
    assert batch.progress()["status"] == "skipped"
    assert batch.coverage()["omitted_hosts"] == {host: "recon_budget_exhausted" for host in HOSTS}
    assert batch.coverage()["execution_budget"]["remaining_seconds"] == 0


def test_deadline_keeps_completed_observations_and_cancels_unfinished_work():
    cancelled = []
    async def run():
        budget = ReconBudget(1, 0.03)
        async def fast():
            return {"hostname": HOSTS[0], "http_status": 200}
        async def slow():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)
        async def work():
            return collect_http_results(HOSTS[:2], await gather_with_deadline([fast(), slow()]))
        return await evaluate_stage(budget, stage_plan("dns", HOSTS[:2], ["acme.test"]), work)
    batch = asyncio.run(run())
    assert batch[0]["hostname"] == HOSTS[0]
    assert batch.successful_hosts == [HOSTS[0]]
    assert batch.failed_hosts == {HOSTS[1]: "recon_stage_deadline"}
    assert cancelled == [True]


def test_queued_host_is_cancelled_before_it_starts_tool_work():
    invoked = []
    async def run():
        semaphore = asyncio.Semaphore(1)
        async def one(host):
            async with semaphore:
                invoked.append(host)
                await asyncio.Event().wait()
        async def work():
            return collect_tool_results(HOSTS[:2], await gather_with_deadline([one(host) for host in HOSTS[:2]]))
        return await ReconBudget(1, 0.03).run(work)
    batch = asyncio.run(run())
    assert invoked == HOSTS[:1]
    assert set(batch.failed_hosts) == set(HOSTS[:2])


@pytest.mark.parametrize("module,batch_name", [
    (naabu_runner, "run_naabu_batch"), (sslyze_runner, "run_sslyze_batch"),
    (nuclei_runner, "run_nuclei_batch"),
])
def test_deadline_reaps_real_synthetic_subprocess(module, batch_name, monkeypatch):
    spawned, temporary_files = [], []
    original_spawn = asyncio.create_subprocess_exec
    async def spawn(*args, **kwargs):
        temporary_files.extend(str(arg).split("=", 1)[1] for arg in args if str(arg).startswith("--json_out="))
        process = await original_spawn(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        spawned.append(process)
        return process
    async def no_version():
        return None
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module.shutil, "which", lambda binary: "/synthetic/" + binary)
    monkeypatch.setattr(module.ip_guard, "resolve_connect_ip", lambda host: "8.8.8.8")
    monkeypatch.setattr(nuclei_runner, "_nuclei_version", no_version)
    async def run():
        return await ReconBudget(1, 0.1).run(lambda: getattr(module, batch_name)(HOSTS[:1]))
    result = asyncio.run(run())
    assert len(spawned) == 1
    assert spawned[0].returncode is not None
    assert result.failed_hosts[HOSTS[0]] == "recon_stage_deadline"
    assert all(not Path(path).exists() for path in temporary_files)


def test_discovery_deadline_reaps_subfinder_and_reports_failed_source(monkeypatch):
    spawned = []
    original_spawn = asyncio.create_subprocess_exec
    async def spawn(*args, **kwargs):
        process = await original_spawn(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        spawned.append(process)
        return process
    async def empty(domain):
        return set()
    for name in ("query_crt_sh", "query_hackertarget", "query_certspotter"):
        monkeypatch.setattr(discovery, name, empty)
    monkeypatch.setattr(discovery.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(discovery.shutil, "which", lambda binary: "/synthetic/" + binary)
    async def run():
        return await ReconBudget(1, 0.1).run(lambda: discovery.discover_subdomains_with_health(HOSTS[0]))
    hosts, failed = asyncio.run(run())
    assert hosts == [HOSTS[0]]
    assert failed == ["subfinder"]
    assert len(spawned) == 1 and spawned[0].returncode is not None


def test_http_failure_keeps_observation_but_never_claims_success():
    batch = collect_http_results(HOSTS[:1], [{"hostname": HOSTS[0], "http_status": None, "error": "blocked"}])
    assert len(batch) == 1
    assert batch.successful_hosts == []
    assert batch.failed_hosts == {HOSTS[0]: "blocked"}


def test_third_party_handoff_is_omitted_not_failed_and_flows_downstream():
    handoff = {"hostname": HOSTS[1], "http_status": 302, "error": "redirect blocked: img.mailin.fr out of scope",
               "third_party_redirect": "img.mailin.fr"}
    ok = {"hostname": HOSTS[0], "http_status": 200, "error": None}

    async def work():
        return collect_http_results(HOSTS[:2], [ok, handoff])

    budget = ReconBudget(60, 30)
    batch = asyncio.run(evaluate_stage(budget, stage_plan("http", HOSTS[:2], ["acme.test"],
                                                          [{"hostname": h, "primary_ip": "203.0.113.5"} for h in HOSTS[:2]]), work))
    assert batch.failed_hosts == {}
    assert batch.successful_hosts == [HOSTS[0]]
    assert batch.omitted_hosts == {HOSTS[1]: THIRD_PARTY_SERVICE}
    assert batch.progress()["status"] == "completed"

    nuclei = stage_plan("nuclei", HOSTS[:2], ["acme.test"], http_records=[ok, handoff])
    assert nuclei["selected_hosts"] == [HOSTS[0]]
    assert nuclei["omitted_hosts"] == {HOSTS[1]: THIRD_PARTY_SERVICE}


def test_blocked_redirect_without_a_response_still_fails():
    blocked = {"hostname": HOSTS[0], "http_status": None, "error": "redirect blocked: x out of scope",
               "third_party_redirect": "x"}
    batch = collect_http_results(HOSTS[:1], [blocked])
    assert batch.failed_hosts == {HOSTS[0]: "redirect blocked: x out of scope"}
    assert batch.omitted_hosts == {}


def test_local_and_remote_persist_identical_stage_plans_and_omissions(store, monkeypatch):
    from types import SimpleNamespace
    from scanner import runner
    from backend.app.workflows import inngest_workflow as wf
    from shared.contracts import ScanJob
    from conftest import prepare_execution_claim
    from test_scan_cancel_fencing import _add_scan
    async def discover(domain):
        return [HOSTS[0], HOSTS[2]], []
    async def dns(host):
        return {"hostname": host, "primary_ip": "8.8.8.8", "records": {}}
    async def http(host, **kwargs):
        return {"hostname": host, "http_status": 200, "url": "https://" + host}
    for module in (runner, wf):
        monkeypatch.setattr(module, "discover_subdomains_with_health", discover)
        monkeypatch.setattr(module, "resolve_host_dns", dns)
        monkeypatch.setattr(module, "probe_http_service", http)
    monkeypatch.setattr(runner, "_tool", lambda binary: False)
    monkeypatch.setattr(wf, "_tool_available", lambda binary: False)
    monkeypatch.setattr(wf, "_registered_hosts", lambda *args: [HOSTS[1]])
    sid = _add_scan(store)
    asyncio.run(wf.execute_recon_local(sid, prepare_execution_claim(store, sid, "local")))
    local = {item["stage"]: item["raw_data"] for item in store.scan_results if item["scan_id"] == sid}
    remote = {}
    class Client:
        async def progress(self, *args, **kwargs):
            pass
        async def observations(self, job, stage, data):
            remote[stage] = data
    job = ScanJob(scan_id="s", organization_id="o", domain_id="d", target=HOSTS[0], scope=[HOSTS[0]],
                  seed_hosts=[HOSTS[1]], created_at="now", lease_expires_at="later", claim_generation=1,
                  claim_token="test-claim-token-0000000000000000000000")
    asyncio.run(runner.execute_job(Client(), SimpleNamespace(heartbeat_seconds=30, http_probe_concurrency=25), job))
    for stage in ("dns", "http", "ports", "tls", "nuclei"):
        assert local[stage]["stage_plan"] == remote[stage]["stage_plan"]
        assert local[stage]["omitted_hosts"] == remote[stage]["omitted_hosts"]
    assert local["ports"]["omitted_hosts"] == {host: "tool_unavailable" for host in HOSTS}


def test_worker_does_not_start_dns_after_discovery_consumes_recon_budget(monkeypatch):
    from types import SimpleNamespace
    from scanner import runner
    from shared.contracts import ScanJob
    clock, posted = [0.0], {}
    monkeypatch.setattr(runner, "ReconBudget", lambda total, stage: ReconBudget(total, stage, clock=lambda: clock[0]))
    async def discover(domain):
        clock[0] = 1000
        return [domain], []
    async def no_dns(host):
        raise AssertionError("work cannot start after the recon budget")
    class Client:
        async def progress(self, *args, **kwargs):
            pass
        async def observations(self, job, stage, data):
            posted[stage] = data
    monkeypatch.setattr(runner, "discover_subdomains_with_health", discover)
    monkeypatch.setattr(runner, "resolve_host_dns", no_dns)
    monkeypatch.setattr(runner, "_tool", lambda binary: False)
    job = ScanJob(scan_id="s", organization_id="o", domain_id="d", target=HOSTS[0], scope=[HOSTS[0]],
                  created_at="now", lease_expires_at="later", claim_generation=1,
                  claim_token="test-claim-token-0000000000000000000000")
    result = asyncio.run(runner.execute_job(Client(), SimpleNamespace(heartbeat_seconds=30, http_probe_concurrency=25), job))
    assert result["dns"] == 0
    assert posted["dns"]["omitted_hosts"] == {HOSTS[0]: "recon_budget_exhausted"}


def test_stage_deadline_does_not_leak_into_later_unscoped_work():
    async def run():
        async def fast():
            return "first"
        assert await ReconBudget(1, 0.01).run(lambda: gather_with_deadline([fast()])) == ["first"]
        async def later():
            await asyncio.sleep(0.02)
            return "later"
        return await gather_with_deadline([later()])
    assert asyncio.run(run()) == ["later"]


def test_late_native_dns_thread_cannot_start_tls_connection_after_deadline(monkeypatch):
    from threading import Event
    from backend.app.scanner import http_probe
    release = Event()
    connected = []
    def delayed_dns(host):
        release.wait(timeout=2)
        return "8.8.8.8"
    def no_connection(*args, **kwargs):
        connected.append(True)
        raise AssertionError("expired native work must not open a target connection")
    monkeypatch.setattr(http_probe.ip_guard, "resolve_connect_ip", delayed_dns)
    monkeypatch.setattr(http_probe.socket, "create_connection", no_connection)
    async def run():
        async def work():
            return await asyncio.to_thread(http_probe.inspect_tls_certificate, HOSTS[0])
        result = await ReconBudget(1, 0.03).run(lambda: gather_with_deadline([work()]))
        release.set()
        return result
    asyncio.run(run())
    assert connected == []
