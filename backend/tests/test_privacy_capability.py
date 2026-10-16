"""Privacy-stage capability negotiation (C2a): old and new workers and APIs interoperate.

* The deployed worker (scanner image built from c043223, contract vendored
  under fixtures/) must accept a claim payload from the new API.
* A new worker against an API that doesn't advertise the capability (older
  API) never sends the stage, which that API would reject with 422.
* A new worker against a new API runs the stage as an optional stage.
"""
import asyncio
import importlib.util
import pathlib
from types import SimpleNamespace

import httpx

from scanner import client as worker_client, runner
from shared.contracts import PRIVACY_CAPABILITY, RECON_STAGES, ScanJob, ScanJobLimits

DEPLOYED = pathlib.Path(__file__).parent / "fixtures" / "deployed_contracts" / "contracts_c043223.py"


def _deployed_contracts():
    spec = importlib.util.spec_from_file_location("deployed_contracts_c043223", DEPLOYED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _new_claim_payload():
    return ScanJob(scan_id="s", organization_id="o", domain_id="d", target="acme.example.test",
                   scope=["acme.example.test"], created_at="now", lease_expires_at="later", claim_generation=1,
                   claim_token="test-claim-token-0000000000000000000000",
                   limits=ScanJobLimits(privacy_max_hosts=5, privacy_max_pages=10)).model_dump()


def test_the_deployed_worker_accepts_the_new_claim_payload():
    old = _deployed_contracts()
    assert "privacy" not in old.RECON_STAGES, "snapshot is the pre-C2a contract"
    job = old.ScanJob.model_validate(_new_claim_payload())
    assert job.limits.max_hosts == 500 and not hasattr(job.limits, "privacy_max_hosts")


def test_privacy_is_a_recon_stage_after_http():
    assert RECON_STAGES.index("privacy") == RECON_STAGES.index("http") + 1


def _client_against(protocol_body):
    def handler(request):
        if request.url.path.endswith("/protocol"):
            return httpx.Response(200, json=protocol_body)
        seen.append(dict(request.headers))
        return httpx.Response(204)
    seen = []
    cfg = SimpleNamespace(core_url="https://core.example.test", http_timeout_seconds=5, scanner_id="w1",
                          api_key="k")
    c = worker_client.CoreClient(cfg)
    c._http = httpx.AsyncClient(base_url=cfg.core_url, transport=httpx.MockTransport(handler))
    return c, seen


def test_new_worker_against_an_older_api_does_not_advertise_or_run_privacy():
    c, seen = _client_against({"version": 2, "claim_authority": "required", "observation_attempts": True})
    assert asyncio.run(c.claim()) is None
    assert c.supports(PRIVACY_CAPABILITY) is False
    assert "x-scanner-capabilities" not in seen[0]


def test_new_worker_against_a_new_api_advertises_privacy_on_claim():
    c, seen = _client_against({"version": 2, "capabilities": ["privacy_v1", "future_thing"]})
    asyncio.run(c.claim())
    assert c.supports(PRIVACY_CAPABILITY) and not c.supports("future_thing"), "unknown capabilities ignored"
    assert seen[0]["x-scanner-capabilities"] == "privacy_v1"


def _job():
    return ScanJob.model_validate(_new_claim_payload())


def _run_job(monkeypatch, client):
    async def discover(domain):
        return ["acme.example.test"], []

    async def dns(host):
        return {"hostname": host, "primary_ip": "93.184.216.34", "records": {}}

    async def http(host, **kwargs):
        return {"hostname": host, "http_status": 200, "url": "https://" + host}

    monkeypatch.setattr(runner, "discover_subdomains_with_health", discover)
    monkeypatch.setattr(runner, "resolve_host_dns", dns)
    monkeypatch.setattr(runner, "probe_http_service", http)
    monkeypatch.setattr(runner, "_tool", lambda binary: False)
    return asyncio.run(runner.execute_job(client, SimpleNamespace(heartbeat_seconds=30, http_probe_concurrency=5), _job()))


class FakeCore:
    def __init__(self, capabilities):
        self.capabilities, self.stages, self.progress_calls = frozenset(capabilities), {}, []

    def supports(self, capability):
        return capability in self.capabilities

    async def progress(self, job, stage, status, **kwargs):
        self.progress_calls.append((stage, status))

    async def observations(self, job, stage, data):
        self.stages[stage] = data


def test_runner_skips_privacy_entirely_without_the_capability(monkeypatch):
    core = FakeCore([])
    _run_job(monkeypatch, core)
    assert "privacy" not in core.stages and all(stage != "privacy" for stage, _ in core.progress_calls)


def test_runner_runs_privacy_as_an_optional_stage_with_the_capability(monkeypatch):
    core = FakeCore([PRIVACY_CAPABILITY])
    stats = _run_job(monkeypatch, core)
    assert stats["privacy"] == 0 and core.stages["privacy"]["attempted_hosts"] == ["acme.example.test"]
    assert ("privacy", "completed") in core.progress_calls


def test_a_privacy_crash_never_aborts_the_job(monkeypatch):
    async def crash(*args, **kwargs):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(runner, "run_privacy_batch", crash)
    core = FakeCore([PRIVACY_CAPABILITY])
    stats = _run_job(monkeypatch, core)
    assert ("privacy", "failed") in core.progress_calls
    assert core.stages["privacy"]["failed_hosts"] == {"acme.example.test": "probe exploded"}
    assert "nuclei" in stats, "later stages still ran"
