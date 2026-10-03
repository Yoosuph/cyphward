"""Tests for the in-process daily scan scheduler (06:00 UTC sweep).

No real database access: DATABASE_URL points at production, so the schedule
function is exercised with monkeypatched query/audit primitives and the loop
is exercised with a faked wake policy.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import backend.app.workflows.inngest_workflow as wf
from backend.app.scheduler import (
    CRON_RAN_ACTION,
    DAILY_SCAN_HOUR_UTC,
    daily_scan_scheduler,
    next_wake_at,
)


# ---------------------------------------------------------------------------
# next_wake_at — pure wake-time policy
# ---------------------------------------------------------------------------

def test_daily_scan_hour_is_06_utc():
    assert DAILY_SCAN_HOUR_UTC == 6


def test_wake_before_six_targets_today():
    now = datetime(2026, 10, 3, 5, 0, tzinfo=timezone.utc)
    assert next_wake_at(now, ran_today=False) == datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)


def test_wake_exactly_at_six_runs_now():
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=timezone.utc)
    assert next_wake_at(now, ran_today=False) == now


def test_wake_after_six_not_ran_catches_up_immediately():
    now = datetime(2026, 10, 3, 7, 30, tzinfo=timezone.utc)
    assert next_wake_at(now, ran_today=False) == now


def test_wake_after_six_already_ran_waits_until_tomorrow():
    now = datetime(2026, 10, 3, 7, 30, tzinfo=timezone.utc)
    assert next_wake_at(now, ran_today=True) == datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)


def test_wake_before_six_already_ran_waits_until_tomorrow():
    # Marker flag wins: e.g. a catch-up run just after midnight.
    now = datetime(2026, 10, 3, 0, 30, tzinfo=timezone.utc)
    assert next_wake_at(now, ran_today=True) == datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)


def test_wake_naive_datetime_treated_as_utc():
    now = datetime(2026, 10, 3, 5, 0)  # naive
    assert next_wake_at(now, ran_today=False) == datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)


def test_wake_non_utc_offset_normalized():
    lagos = timezone(timedelta(hours=1))  # WAT = UTC+1
    now = datetime(2026, 10, 3, 6, 30, tzinfo=lagos)  # 05:30 UTC
    assert next_wake_at(now, ran_today=False) == datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# run_daily_scan_schedule — shared schedule body (all DB primitives faked)
# ---------------------------------------------------------------------------

DUE_ROWS = [
    {"org_id": uuid.UUID("11111111-aaaa-4aaa-4aaa-111111111111"),
     "domain_id": uuid.UUID("d1111111-aaaa-4aaa-4aaa-d11111111111"),
     "domain": "one.example.com"},
    {"org_id": uuid.UUID("22222222-bbbb-4bbb-4bbb-222222222222"),
     "domain_id": uuid.UUID("d2222222-bbbb-4bbb-4bbb-d22222222222"),
     "domain": "two.example.com"},
]


class _ScheduleHarness:
    """Monkeypatched capture of every DB/side-effect primitive the schedule touches."""

    def __init__(self, monkeypatch, due_rows, send_raises=False, scanner_mode="remote"):
        self.due_rows = due_rows
        self.sent_events = []
        self.audits = []
        self.pipeline_calls = []
        self.inserted_params = []

        def fake_execute_query(sql, params=()):
            if "FROM domains" in sql:
                return list(self.due_rows)
            return None  # failure-path UPDATE etc.

        def fake_execute_one(sql, params=()):
            if "INSERT INTO scans" in sql:
                self.inserted_params.append(params)
                return {"id": uuid.uuid4()}
            return None

        async def fake_send(event):
            if send_raises:
                raise RuntimeError("event gateway down")
            self.sent_events.append(dict(event.data))

        async def fake_pipeline(scan_id):
            self.pipeline_calls.append(scan_id)
            return {"scan_id": scan_id}

        def fake_audit(*args, **kwargs):
            self.audits.append((args, kwargs))

        monkeypatch.setattr(wf, "execute_query", fake_execute_query)
        monkeypatch.setattr(wf, "execute_one", fake_execute_one)
        monkeypatch.setattr(wf, "log_audit", fake_audit)
        monkeypatch.setattr(wf, "execute_scan_pipeline", fake_pipeline)
        monkeypatch.setattr(wf.inngest_client, "send", fake_send)
        monkeypatch.setattr(wf, "SCANNER_MODE", scanner_mode)

    @property
    def audit_actions(self):
        return [args[2] for args, _ in self.audits]


def test_schedule_sends_one_scan_per_due_domain_and_audits(monkeypatch):
    h = _ScheduleHarness(monkeypatch, DUE_ROWS)

    result = asyncio.run(wf.run_daily_scan_schedule())

    assert result == {"due_domains": 2, "scheduled": 2}
    assert len(h.sent_events) == 2
    assert all(e["trigger"] == "cron" for e in h.sent_events)
    assert all(e["organization_id"] for e in h.sent_events)
    assert h.audit_actions.count("scan.scheduled") == 2
    assert h.audit_actions.count(CRON_RAN_ACTION) == 1
    assert len(h.inserted_params) == 2


def test_schedule_with_no_due_domains_writes_only_run_marker(monkeypatch):
    h = _ScheduleHarness(monkeypatch, [])

    result = asyncio.run(wf.run_daily_scan_schedule())

    assert result == {"due_domains": 0, "scheduled": 0}
    assert h.sent_events == []
    assert h.audit_actions == [CRON_RAN_ACTION]


def test_schedule_remote_mode_survives_event_send_failure(monkeypatch):
    h = _ScheduleHarness(monkeypatch, DUE_ROWS, send_raises=True, scanner_mode="remote")

    result = asyncio.run(wf.run_daily_scan_schedule())

    # Queued rows are the dispatch — worker polls; counts still recorded.
    assert result == {"due_domains": 2, "scheduled": 2}
    assert h.pipeline_calls == []
    assert h.audit_actions.count("scan.scheduled") == 2
    assert h.audit_actions.count(CRON_RAN_ACTION) == 1


def test_schedule_local_mode_falls_back_to_inline_pipeline(monkeypatch):
    h = _ScheduleHarness(monkeypatch, DUE_ROWS, send_raises=True, scanner_mode="local")

    result = asyncio.run(wf.run_daily_scan_schedule())

    assert result["scheduled"] == 2
    assert len(h.pipeline_calls) == 2


# ---------------------------------------------------------------------------
# daily_scan_scheduler loop
# ---------------------------------------------------------------------------

def test_loop_returns_immediately_when_already_stopped():
    stop = asyncio.Event()
    stop.set()
    asyncio.run(asyncio.wait_for(daily_scan_scheduler(stop), timeout=5))


def test_loop_runs_schedule_once_then_stops(monkeypatch):
    import backend.app.scheduler as sched

    stop = asyncio.Event()
    runs = []

    async def fake_run():
        runs.append(1)
        stop.set()
        return {"due_domains": 1, "scheduled": 1}

    monkeypatch.setattr(sched, "schedule_ran_since", lambda moment: False)
    monkeypatch.setattr(sched, "next_wake_at", lambda now, ran: now)  # force immediate wake
    monkeypatch.setattr(sched, "run_daily_scan_schedule", fake_run)

    asyncio.run(asyncio.wait_for(daily_scan_scheduler(stop), timeout=5))

    assert runs == [1]


def test_marker_constant_is_cron_ran():
    assert CRON_RAN_ACTION == "cron.ran"
