"""Process success and a missing match cannot prove exact-template coverage."""
import asyncio
import json

import pytest

from backend.app.scanner import nuclei_runner as runner
from backend.app.scanner.tool_results import ToolExecutionError
from test_tool_failure_coverage import Process, setup_process

HOST = "www.acme.test"


def event(**extra):
    return {"template-id": "exposed-panel", "info": {"name": "Exposed panel", "severity": "high"}, **extra}


@pytest.mark.parametrize("stdout", [b"", json.dumps(event(**{"matcher-status": False})).encode()])
def test_empty_or_negative_match_is_not_clean_template_proof(monkeypatch, stdout):
    setup_process(monkeypatch, runner, Process(stdout=stdout))
    result = asyncio.run(runner.run_nuclei_template(HOST, "exposed-panel"))
    assert result["ok"] is False
    assert result["findings"] == []
    assert "not proven" in result["error"]


def test_positive_match_can_reproduce_exact_template(monkeypatch):
    setup_process(monkeypatch, runner, Process(stdout=json.dumps(event(**{"matcher-status": True})).encode()))
    result = asyncio.run(runner.run_nuclei_template(HOST, "exposed-panel"))
    assert result["ok"] is True
    assert result["findings"][0]["evidence"]["template_id"] == "exposed-panel"


def test_other_template_match_cannot_verify_requested_template(monkeypatch):
    setup_process(monkeypatch, runner, Process(stdout=json.dumps(event()).encode()))
    result = asyncio.run(runner.run_nuclei_template(HOST, "different-template"))
    assert result["ok"] is False


@pytest.mark.parametrize("extra", [{"error": "request timeout"}, {"matcher-status": "false"}, {"template-id": ""}])
def test_invalid_or_failed_event_does_not_become_assessment_evidence(extra):
    with pytest.raises(ToolExecutionError):
        runner._parse_nuclei_stdout(json.dumps(event(**extra)).encode(), HOST, strict=True)


def test_batch_retains_requested_selector_version_and_explicit_unknown_evaluation(monkeypatch):
    async def version():
        return "3.4.10"
    async def scan(host, *args, **kwargs):
        if host == "failed.acme.test":
            raise ToolExecutionError("request timeout")
        return runner._parse_nuclei_stdout(json.dumps(event()).encode(), host, strict=True)
    monkeypatch.setattr(runner, "_nuclei_version", version)
    monkeypatch.setattr(runner, "run_nuclei", scan)
    batch = asyncio.run(runner.run_nuclei_batch([HOST, "failed.acme.test"], templates="http/", timeout=30))
    coverage = batch.coverage()["tool_coverage"]
    assert coverage["version"] == 1
    assert coverage["tool_version"] == "3.4.10"
    assert coverage["requested_selector"] == "http/"
    assert coverage["template_set_version"] == "v10.4.9"  # pinned, from the exclusion policy
    assert coverage["evaluated_templates"] is None
    assert coverage["negative_verification"] == "unknown"
    assert coverage["safety_policy"]["rate_limit_per_second"] == 10
    assert coverage["safety_policy"]["excluded_templates"] == 2516
    assert "default-login" in coverage["safety_policy"]["exclude_tags"]
    assert coverage["severity_order"] == ["critical", "high", "medium", "low"]
    target = coverage["targets"][HOST]
    assert target["process_status"] == "completed" and target["matched_templates"] == ["exposed-panel"]
    assert target["evaluation_status"] == "unknown"
    # Four severity passes ran in order, each recorded.
    assert [target["severity_passes"][s]["status"] for s in ("critical", "high", "medium", "low")] == ["completed"] * 4
    assert coverage["targets"]["failed.acme.test"]["process_status"] == "failed"
    assert coverage["per_host_timeout_seconds"] == 30
    assert coverage["started_at"] <= coverage["completed_at"]


@pytest.mark.parametrize("output,code,expected", [
    (b"[INF] Nuclei Engine Version: v3.4.10", 0, "3.4.10"),
    (b"unexpected output", 0, None),
    (b"[INF] Nuclei Engine Version: v3.4.10", 1, None),
])
def test_version_is_observed_from_successful_version_command(monkeypatch, output, code, expected):
    setup_process(monkeypatch, runner, Process(stdout=output, code=code))
    assert asyncio.run(runner._nuclei_version()) == expected


def test_version_timeout_is_bounded_and_reaps_process(monkeypatch):
    process = Process(timeout=True)
    setup_process(monkeypatch, runner, process)
    assert asyncio.run(runner._nuclei_version()) is None
    assert process.killed


def test_empty_batch_does_not_spawn_version_or_scan_process(monkeypatch):
    async def no_process(*args, **kwargs):
        raise AssertionError("empty batch must not spawn tools")
    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", no_process)
    result = asyncio.run(runner.run_nuclei_batch([]))
    assert result == []
    assert result.tool_coverage["tool_version"] is None
    assert result.tool_coverage["evaluated_templates"] is None
