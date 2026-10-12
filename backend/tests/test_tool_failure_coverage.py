"""Tool failures must not masquerade as completed, clean host assessments."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.scanner import naabu_runner, nuclei_runner, sslyze_runner
from backend.app.scanner.tool_results import ToolBatchResult, ToolExecutionError
from scanner.runner import run_stage
from scanner.client import JobLost
import scanner.runner as worker


class Process:
    def __init__(self, code=0, stdout=b"", timeout=False):
        self.returncode = None if timeout else code
        self.stdout = stdout
        self.timeout = timeout
        self.killed = False

    async def communicate(self):
        if self.timeout:
            raise asyncio.TimeoutError()
        return self.stdout, b"tool diagnostic"

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


def setup_process(monkeypatch, module, process, tls_json=None):
    monkeypatch.setattr(module.ip_guard, "resolve_connect_ip", lambda host: "8.8.8.8")
    monkeypatch.setattr(module.shutil, "which", lambda binary: f"/fake/{binary}")

    async def spawn(*args, **kwargs):
        for arg in args:
            if str(arg).startswith("--json_out="):
                Path(str(arg).split("=", 1)[1]).write_text(json.dumps(tls_json or {}))
        return process

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)


@pytest.mark.parametrize("module,batch", [
    (nuclei_runner, "run_nuclei_batch"),
    (naabu_runner, "run_naabu_batch"),
    (sslyze_runner, "run_sslyze_batch"),
])
@pytest.mark.parametrize("timeout", [False, True])
def test_crash_or_timeout_records_failed_host(monkeypatch, module, batch, timeout):
    process = Process(code=1, timeout=timeout)
    setup_process(monkeypatch, module, process)
    result = asyncio.run(getattr(module, batch)(["www.acme.test"]))
    assert result == []
    assert result.successful_hosts == []
    assert "www.acme.test" in result.failed_hosts
    assert result.progress()["status"] == "failed"
    if timeout:
        assert process.killed, "a timed-out tool must not remain running"


@pytest.mark.parametrize("module,batch", [
    (nuclei_runner, "run_nuclei_batch"),
    (naabu_runner, "run_naabu_batch"),
])
def test_successful_empty_output_is_clean_but_malformed_output_is_not(monkeypatch, module, batch):
    setup_process(monkeypatch, module, Process())
    result = asyncio.run(getattr(module, batch)(["www.acme.test"]))
    assert result.successful_hosts == ["www.acme.test"]
    assert result.progress()["status"] == "completed"
    setup_process(monkeypatch, module, Process(stdout=b"{broken-json"))
    result = asyncio.run(getattr(module, batch)(["www.acme.test"]))
    assert result.successful_hosts == []
    assert result.progress()["status"] == "failed"


def test_nuclei_exit_one_is_inconclusive_for_remediation(monkeypatch):
    setup_process(monkeypatch, nuclei_runner, Process(code=1))
    result = asyncio.run(nuclei_runner.run_nuclei_template("www.acme.test", "exposed-panel"))
    assert result["ok"] is False
    assert "code 1" in result["error"]


def test_nuclei_subprocess_limits_and_environment(monkeypatch):
    monkeypatch.setenv("SCANNER_API_KEY", "test-worker-key")
    monkeypatch.setenv("AUTH_JWT_SECRET", "test-signing-secret")
    monkeypatch.setenv("DATABASE_URL", "test-db-credentials")
    setup_process(monkeypatch, nuclei_runner, Process())
    captured = {}

    async def spawn(*args, **kwargs):
        captured.update({"args": args, "env": kwargs.get("env")})
        return Process()

    monkeypatch.setattr(nuclei_runner.asyncio, "create_subprocess_exec", spawn)
    asyncio.run(nuclei_runner.run_nuclei("www.acme.test", strict=True))
    env = captured["env"]
    assert not any(key in env for key in ["SCANNER_API_KEY", "AUTH_JWT_SECRET", "DATABASE_URL"])
    assert env["GOMEMLIMIT"] == "384MiB"
    args = captured["args"]
    assert args[args.index("-concurrency") + 1] == "4"
    assert args[args.index("-template-loading-concurrency") + 1] == "1"
    assert args[args.index("-js-concurrency") + 1] == "1"
    asyncio.run(nuclei_runner.run_nuclei_template("www.acme.test", "exposed-panel"))
    assert captured["env"]["GOMEMLIMIT"] == "384MiB"
    assert "SCANNER_API_KEY" not in captured["env"]
    monkeypatch.setenv("SCANNER_NUCLEI_TEMPLATE_CONCURRENCY", "0")
    with pytest.raises(ValueError):
        nuclei_runner._nuclei_resource_args()


def test_nuclei_sigkill_produces_actionable_failure(monkeypatch):
    setup_process(monkeypatch, nuclei_runner, Process(code=-9))
    result = asyncio.run(nuclei_runner.run_nuclei_batch(["www.acme.test"]))
    assert "memory limits" in result.failed_hosts["www.acme.test"]


def test_partial_batch_retains_positive_findings_and_actual_coverage(monkeypatch):
    async def scan(host, *args, **kwargs):
        if host == "bad.acme.test":
            raise ToolExecutionError("tool crashed")
        return [{"_hostname": host, "title": "Exposed panel"}]

    monkeypatch.setattr(nuclei_runner, "run_nuclei", scan)
    result = asyncio.run(nuclei_runner.run_nuclei_batch(["good.acme.test", "bad.acme.test"]))
    assert len(result) == 1
    assert result.successful_hosts == ["good.acme.test"]
    assert result.failed_hosts == {"bad.acme.test": "tool crashed"}
    assert result.progress()["status"] == "failed"


def test_sslyze_command_error_does_not_claim_unsupported_protocol(monkeypatch):
    raw = {"server_scan_results": [{"scan_result": {
        "tls_1_2_cipher_suites": {"status": "ERROR", "result": None},
    }}]}
    setup_process(monkeypatch, sslyze_runner, Process(), tls_json=raw)
    result = asyncio.run(sslyze_runner.run_sslyze_batch(["www.acme.test"]))
    assert result.successful_hosts == []
    assert result.progress()["status"] == "failed"
    parsed = sslyze_runner._parse_sslyze_json(raw, "www.acme.test", 443)
    assert parsed["tls_versions"] == {}


def test_sslyze_unrequested_commands_do_not_fail_requested_assessment(monkeypatch):
    raw = {"server_scan_results": [{"scan_status": "COMPLETED", "scan_result": {
        "certificate_info": {"status": "COMPLETED", "result": {"certificate_deployments": []}},
        "tls_1_0_cipher_suites": {"status": "COMPLETED", "result": {"accepted_cipher_suites": []}},
        "tls_1_1_cipher_suites": {"status": "COMPLETED", "result": {"accepted_cipher_suites": []}},
        "tls_1_2_cipher_suites": {"status": "COMPLETED", "result": {"accepted_cipher_suites": [{"cipher_suite": {"name": "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256"}}]}},
        "tls_1_3_cipher_suites": {"status": "COMPLETED", "result": {"accepted_cipher_suites": []}},
        "heartbleed": {"status": "NOT_SCHEDULED", "result": None},
        "robot": {"status": "NOT_SCHEDULED", "result": None},
    }}]}
    setup_process(monkeypatch, sslyze_runner, Process(), tls_json=raw)
    result = asyncio.run(sslyze_runner.run_sslyze_batch(["www.acme.test"]))
    assert result.successful_hosts == ["www.acme.test"]
    assert not result.failed_hosts
    assert result[0]["tls_versions"]["tls_1_0"]["supported"] is False
    assert result[0]["tls_versions"]["tls_1_2"]["supported"] is True


def test_sslyze_missing_requested_command_does_not_complete_host(monkeypatch):
    raw = {"server_scan_results": [{"scan_result": {
        "tls_1_2_cipher_suites": {"status": "COMPLETED", "result": {"accepted_cipher_suites": []}},
    }}]}
    setup_process(monkeypatch, sslyze_runner, Process(), tls_json=raw)
    result = asyncio.run(sslyze_runner.run_sslyze_batch(["www.acme.test"]))
    assert not result.successful_hosts
    assert result.progress()["status"] == "failed"


def test_sslyze_legacy_tls10_key_is_still_supported():
    raw = {"tls_1_cipher_suites": {"status": "COMPLETED", "result": {"accepted_cipher_suites": [{"cipher_suite": {"name": "legacy"}}]}}}
    assert sslyze_runner._parse_sslyze_json(raw, "www.acme.test", 443)["tls_versions"]["tls_1_0"]["supported"] is True


def test_remote_stage_posts_coverage_even_without_findings():
    calls, observations = [], []

    async def progress(scan_id, stage, status, **kwargs):
        calls.append(status)

    async def observe(scan_id, stage, data):
        observations.append(data)

    async def scan():
        return ToolBatchResult([], ["www.acme.test"], [], {"www.acme.test": "timeout"})

    client = SimpleNamespace(progress=progress, observations=observe)
    cfg, job = SimpleNamespace(heartbeat_seconds=300), SimpleNamespace(scan_id="scan-1")
    asyncio.run(run_stage(client, cfg, job, "nuclei", scan, optional=True))
    assert calls == ["running", "failed"]
    assert observations[0]["successful_hosts"] == []
    assert observations[0]["failed_hosts"] == {"www.acme.test": "timeout"}


def test_empty_target_batch_is_skipped():
    result = asyncio.run(nuclei_runner.run_nuclei_batch([]))
    assert result.progress()["status"] == "skipped"


def test_revoked_lease_cancels_running_work_and_posts_no_results(monkeypatch):
    cancelled, observed = [], []

    async def revoked(*args):
        await asyncio.sleep(0)
        raise JobLost("cancelled by owner")

    async def progress(*args, **kwargs):
        pass

    async def observations(*args):
        observed.append(args)

    async def recon():
        try:
            await asyncio.Future()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(worker, "_heartbeat", revoked)
    client = SimpleNamespace(progress=progress, observations=observations)
    with pytest.raises(JobLost):
        asyncio.run(run_stage(client, SimpleNamespace(heartbeat_seconds=300), SimpleNamespace(scan_id="scan-1"), "nuclei", recon, optional=True))
    assert cancelled == [True]
    assert observed == []
