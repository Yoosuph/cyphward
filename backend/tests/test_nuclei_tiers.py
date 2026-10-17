"""Tiered Nuclei: daily = critical+high at 20 req/s; weekly = full safe set at 25 req/s with a
one-hour budget. A tier's budget is shared equally between hosts, and a host that never starts
inside the budget is not assessed (omitted), never counted as failed.
"""
import asyncio

import pytest

from backend.app.scanner import ip_guard, nuclei_runner


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


def _recording_run(calls, clock=None, seconds_per_call=0.0):
    async def run(host, templates, severity, timeout, strict=False, rate_limit=None):
        calls.append({"host": host, "severity": severity, "timeout": timeout, "rate_limit": rate_limit})
        if clock is not None:
            clock.now += seconds_per_call
        return []
    return run


def _batch(monkeypatch, hosts, tier, calls, clock=None, seconds_per_call=0.0, timeout=300):
    async def version():
        return "3.11.1"
    monkeypatch.setattr(nuclei_runner, "_nuclei_version", version)
    monkeypatch.setattr(nuclei_runner, "run_nuclei", _recording_run(calls, clock, seconds_per_call))
    return asyncio.run(nuclei_runner.run_nuclei_batch(hosts, tier=tier, timeout=timeout))


def test_tier_settings_match_the_agreed_defaults():
    daily = nuclei_runner.nuclei_tier_settings("daily")
    weekly = nuclei_runner.nuclei_tier_settings("weekly")
    assert daily == {"severities": ["critical", "high"], "rate_limit": 20, "budget_seconds": 1500}
    assert weekly == {"severities": ["critical", "high", "medium", "low"], "rate_limit": 25, "budget_seconds": 3600}


def test_unknown_tier_is_rejected():
    with pytest.raises(ValueError):
        nuclei_runner.nuclei_tier_settings("hourly")


def test_daily_runs_only_critical_and_high_at_20_requests_per_second(monkeypatch):
    calls = []
    batch = _batch(monkeypatch, ["acme.example.test"], "daily", calls)
    assert [c["severity"] for c in calls] == ["critical", "high"]
    assert {c["rate_limit"] for c in calls} == {20}
    coverage = batch.coverage()["tool_coverage"]
    assert coverage["tier"] == "daily"
    assert coverage["safety_policy"]["rate_limit_per_second"] == 20


def test_weekly_runs_the_full_safe_set_at_25_requests_per_second_with_an_hour(monkeypatch):
    calls = []
    batch = _batch(monkeypatch, ["acme.example.test"], "weekly", calls, timeout=10)
    assert [c["severity"] for c in calls] == ["critical", "high", "medium", "low"]
    assert {c["rate_limit"] for c in calls} == {25}
    coverage = batch.coverage()["tool_coverage"]
    assert coverage["budget_seconds"] == 3600
    assert coverage["safety_policy"]["rate_limit_per_second"] == 25


def test_hosts_share_the_tier_budget_equally(monkeypatch):
    calls = []
    hosts = [f"h{i}.example.test" for i in range(5)]
    batch = _batch(monkeypatch, hosts, "daily", calls)
    coverage = batch.coverage()["tool_coverage"]
    assert coverage["host_budget_seconds"] == 1500 // 5
    first_pass = {c["host"]: c["timeout"] for c in calls if c["severity"] == "critical"}
    assert set(first_pass) == set(hosts)
    assert all(t <= 300 for t in first_pass.values()), "no host may take more than its equal share"


def test_hosts_that_never_start_inside_the_budget_are_not_assessed_not_failed(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(nuclei_runner, "time", clock)
    calls = []
    hosts = [f"h{i}.example.test" for i in range(5)]
    # Each Nuclei call takes 400 s of the fake clock: the first four hosts use their shares, the fifth never starts.
    batch = _batch(monkeypatch, hosts, "daily", calls, clock=clock, seconds_per_call=400)

    assert "h4.example.test" in batch.omitted_hosts
    assert batch.failed_hosts == {}, "an unreached host is not a failed assessment"
    assert batch.coverage()["tool_coverage"]["targets"]["h4.example.test"]["process_status"] == "not_reached"
    assert {c["host"] for c in calls} == set(hosts[:4])


def test_rate_limit_reaches_the_nuclei_command_exactly_once(monkeypatch):
    captured = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

        async def wait(self):
            return 0

    async def fake_exec(*cmd, **kwargs):
        captured.append(list(cmd))
        return Proc()

    monkeypatch.setattr(nuclei_runner.ip_guard, "resolve_connect_ip", lambda host: "93.184.216.34")
    monkeypatch.setattr(nuclei_runner.shutil, "which", lambda name: "/usr/bin/nuclei")
    monkeypatch.setattr(nuclei_runner.asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(nuclei_runner.run_nuclei("acme.example.test", "http/", "critical", 60, rate_limit=20))
    cmd = captured[0]
    assert cmd.count("-rate-limit") == 1
    assert cmd[cmd.index("-rate-limit") + 1] == "20"


def test_weekly_jobs_get_the_time_a_weekly_run_needs():
    from backend.app.core.nuclei_tier import timeouts_for
    assert timeouts_for("daily", 300, 900) == (300, 900), "a daily job keeps the configured timeouts"
    stage, recon = timeouts_for("weekly", 300, 900)
    assert stage == 3600 and recon == 3600 + 900
    assert timeouts_for("weekly", 5000, 9000) == (5000, 9000), "larger configured values are kept"


def test_the_job_names_its_tier_and_older_workers_can_ignore_it():
    from shared.contracts import ScanJob
    base = dict(scan_id="s", organization_id="o", domain_id="d", target="acme.test", scope=["acme.test"],
                created_at="2026-10-17T00:00:00Z", lease_expires_at="2026-10-17T01:00:00Z",
                claim_generation=1, claim_token="t" * 40)
    assert ScanJob(**base).nuclei_tier == "daily"
    assert ScanJob(**base, nuclei_tier="weekly").nuclei_tier == "weekly"


def test_the_tier_budget_is_cut_from_the_stage_time_that_is_really_left(monkeypatch):
    from shared.scan_budget import ReconBudget
    calls = []
    hosts = [f"h{i}.example.test" for i in range(5)]

    async def run():
        return await ReconBudget(1000, 40).run(lambda: _async_batch(monkeypatch, hosts, calls))

    async def _async_batch(monkeypatch, hosts, calls):
        async def version():
            return "3.11.1"
        monkeypatch.setattr(nuclei_runner, "_nuclei_version", version)
        monkeypatch.setattr(nuclei_runner, "run_nuclei", _recording_run(calls))
        return await nuclei_runner.run_nuclei_batch(hosts, tier="weekly")

    batch = asyncio.run(run())
    coverage = batch.coverage()["tool_coverage"]
    assert coverage["budget_seconds"] <= 40, "a weekly budget never exceeds the stage deadline"
    assert coverage["host_budget_seconds"] <= 8
    assert all(c["timeout"] <= 8 for c in calls if c["severity"] == "critical")
