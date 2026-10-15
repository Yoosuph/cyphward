"""Scheduler/recovery loops never start from a non-production process on a remote DB."""
import asyncio
import logging

import pytest

from backend.app import main
from backend.app.core import runtime_guard
from backend.app.core.runtime_guard import background_work_allowed, database_is_local

REMOTE = "postgresql://app:secret@db.example-cloud.com:6543/postgres"


@pytest.mark.parametrize("url", [
    "postgresql://app:pw@127.0.0.1:5432/cyphward_dev",
    "postgresql://app:pw@localhost/cyphward_dev",
    "postgresql://app:pw@[::1]:5432/cyphward_dev",
    "postgresql://app:pw@127.0.0.53/cyphward_dev",
    "host=/var/run/postgresql dbname=cyphward_dev",
    "postgresql:///cyphward_dev",
])
def test_loopback_and_socket_databases_are_local(url):
    assert database_is_local(url)


@pytest.mark.parametrize("url", [
    REMOTE,
    "postgresql://app:pw@10.0.0.5/db",
    "postgresql://app:pw@127.0.0.1,db.example-cloud.com/db",
    "host=localhost hostaddr=203.0.113.9 dbname=db",
    "not a connection string ===",
])
def test_remote_mixed_or_unparseable_databases_are_not_local(url):
    assert not database_is_local(url)


def test_remote_database_outside_production_is_refused_loudly(caplog):
    with caplog.at_level(logging.CRITICAL, logger="cyphward.runtime_guard"):
        assert not background_work_allowed("daily scan scheduler", database_url=REMOTE, environment="development")
    assert "REFUSING TO START DAILY SCAN SCHEDULER" in caplog.text
    assert "secret" not in caplog.text  # The URL and credentials are never logged.


@pytest.mark.parametrize("environment", ["", "staging", "Production-ish", "dev"])
def test_only_exact_production_permits_a_remote_database(environment):
    assert not background_work_allowed("x", database_url=REMOTE, environment=environment)


def test_production_and_local_databases_are_allowed():
    assert background_work_allowed("x", database_url=REMOTE, environment=" Production ")
    assert background_work_allowed("x", database_url="postgresql://a@127.0.0.1/db", environment="development")


@pytest.fixture
def refused(monkeypatch):
    """Point the guard at a remote DB in development, and fail if any loop body starts."""
    monkeypatch.setattr(runtime_guard, "DATABASE_URL", REMOTE)
    monkeypatch.setattr(runtime_guard, "CYPHWARD_ENV", "development")
    monkeypatch.setattr(main, "SCHEDULER_ENABLED", True)
    monkeypatch.setattr("backend.app.core.config.EXECUTION_RECOVERY_ENABLED", True)

    def forbidden(*args, **kwargs):
        raise AssertionError("background database work started")

    monkeypatch.setattr("backend.app.core.scan_recovery.recover_interrupted_scans", forbidden)
    monkeypatch.setattr("backend.app.core.scan_recovery.recover_scan_queue", forbidden)
    monkeypatch.setattr("backend.app.scheduler.daily_scan_scheduler", forbidden)
    monkeypatch.setattr(main, "_execution_task", None)
    monkeypatch.setattr(main, "_scheduler_task", None)


def test_startup_hooks_start_nothing_when_refused(refused, caplog):
    async def run():
        await main.recover_interrupted_scans_on_startup()
        await main.start_execution_recovery()
        await main.start_daily_scan_scheduler()

    with caplog.at_level(logging.CRITICAL, logger="cyphward.runtime_guard"):
        asyncio.run(run())
    assert main._execution_task is None and main._scheduler_task is None
    for task in ("STARTUP SCAN RECOVERY", "EXECUTION RECOVERY LOOP", "DAILY SCAN SCHEDULER"):
        assert f"REFUSING TO START {task}" in caplog.text


@pytest.fixture
def clean_status(monkeypatch):
    monkeypatch.setattr(runtime_guard, "_status", {"scheduler": "not started", "recovery": "not started"})
    monkeypatch.setattr(runtime_guard, "_tasks", {})


def test_health_reports_refused_loops_without_urls(refused, clean_status, client):
    async def run():
        await main.start_execution_recovery()
        await main.start_daily_scan_scheduler()

    asyncio.run(run())
    body = client.get("/health").json()
    expected = f"refused ({runtime_guard.REFUSAL_REASON})"
    assert body["background"] == {"scheduler": expected, "recovery": expected}
    text = str(body)
    assert "example-cloud" not in text and "secret" not in text and "postgres" not in text


def test_health_reports_disabled_running_and_stopped_loops(clean_status, client, monkeypatch):
    monkeypatch.setattr(main, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr("backend.app.core.config.EXECUTION_RECOVERY_ENABLED", False)

    async def run():
        await main.start_execution_recovery()
        await main.start_daily_scan_scheduler()

    asyncio.run(run())
    assert client.get("/health").json()["background"] == {
        "scheduler": "disabled (CYPHWARD_SCHEDULER_ENABLED=false)",
        "recovery": "disabled (CYPHWARD_EXECUTION_RECOVERY_ENABLED=false)",
    }

    async def tracked():
        stop = asyncio.Event()
        alive = asyncio.create_task(stop.wait())
        runtime_guard.track_background_task("scheduler", alive)
        finished = asyncio.create_task(asyncio.sleep(0, result=None))
        runtime_guard.track_background_task("recovery", finished)
        await finished
        status = runtime_guard.background_status()
        stop.set()
        await alive
        return status

    assert asyncio.run(tracked()) == {"scheduler": "running", "recovery": "stopped"}
