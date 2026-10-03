"""Tests for the in-process daily scan scheduler (06:00 UTC sweep) and the
atomic cron claim that guards the daily sweep (review P1 — durable jobs).

No real database access: DATABASE_URL points at production, so the schedule
function is exercised with monkeypatched query/audit/claim primitives and the
loop is exercised with a faked wake policy.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import backend.app.core.cron_claim as cron_claim
import backend.app.workflows.inngest_workflow as wf
from backend.app.scheduler import (
    CRON_RAN_ACTION,
    DAILY_SCAN_HOUR_UTC,
    daily_scan_scheduler,
    next_wake_at,
    schedule_ran_since,
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
        self.queries = []
        self.claim_sqls = []
        self.claim_denied = False
        self.claimed = []
        self.completed = []
        self.released = []

        def fake_execute_query(sql, params=()):
            self.queries.append((" ".join(sql.split()), params))
            if "FROM domains" in sql:
                if self.due_query_error:
                    raise self.due_query_error
                return list(self.due_rows)
            return None  # failure-path UPDATE etc.

        def fake_execute_one(sql, params=()):
            if "INSERT INTO scans" in sql:
                self.inserted_params.append(params)
                return {"id": uuid.uuid4()}
            return None

        def fake_claim_execute_one(sql, params=()):
            flat = " ".join(sql.split())
            self.claim_sqls.append((flat, params))
            if "INSERT INTO cron_runs" in flat:
                if self.claim_denied:
                    return None
                self.claimed.append(params)
                return {"cron_name": params[0], "run_day": params[1],
                        "claimed_by": params[2], "status": "running"}
            if "UPDATE cron_runs" in flat:
                self.completed.append(params)
                return {"status": "completed"}
            if "DELETE FROM cron_runs" in flat:
                self.released.append(params)
                return {"status": "running"}
            if "FROM cron_runs" in flat:
                return {"ok": 1} if self.cron_completed else None
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
        monkeypatch.setattr(cron_claim, "execute_one", fake_claim_execute_one)
        monkeypatch.setattr(wf, "log_audit", fake_audit)
        monkeypatch.setattr(wf, "execute_scan_pipeline", fake_pipeline)
        monkeypatch.setattr(wf.inngest_client, "send", fake_send)
        monkeypatch.setattr(wf, "SCANNER_MODE", scanner_mode)
        self.due_query_error = None
        self.cron_completed = False

    @property
    def audit_actions(self):
        return [args[2] for args, _ in self.audits]


def test_schedule_sends_one_scan_per_due_domain_and_audits(monkeypatch):
    h = _ScheduleHarness(monkeypatch, DUE_ROWS)

    result = asyncio.run(wf.run_daily_scan_schedule())

    assert result == {"due_domains": 2, "scheduled": 2, "claimed": True}
    assert len(h.sent_events) == 2
    assert all(e["trigger"] == "cron" for e in h.sent_events)
    assert all(e["organization_id"] for e in h.sent_events)
    assert h.audit_actions.count("scan.scheduled") == 2
    assert h.audit_actions.count(CRON_RAN_ACTION) == 1
    assert len(h.inserted_params) == 2
    # Claim lifecycle: acquired and completed, never released.
    assert len(h.claimed) == 1
    assert len(h.completed) == 1
    assert h.released == []


def test_schedule_with_no_due_domains_writes_only_run_marker(monkeypatch):
    h = _ScheduleHarness(monkeypatch, [])

    result = asyncio.run(wf.run_daily_scan_schedule())

    assert result == {"due_domains": 0, "scheduled": 0, "claimed": True}
    assert h.sent_events == []
    assert h.audit_actions == [CRON_RAN_ACTION]


def test_schedule_remote_mode_survives_event_send_failure(monkeypatch):
    h = _ScheduleHarness(monkeypatch, DUE_ROWS, send_raises=True, scanner_mode="remote")

    result = asyncio.run(wf.run_daily_scan_schedule())

    # Queued rows are the dispatch — worker polls; counts still recorded.
    assert result == {"due_domains": 2, "scheduled": 2, "claimed": True}
    assert h.pipeline_calls == []
    assert h.audit_actions.count("scan.scheduled") == 2
    assert h.audit_actions.count(CRON_RAN_ACTION) == 1


def test_schedule_local_mode_falls_back_to_inline_pipeline(monkeypatch):
    h = _ScheduleHarness(monkeypatch, DUE_ROWS, send_raises=True, scanner_mode="local")

    result = asyncio.run(wf.run_daily_scan_schedule())

    assert result["scheduled"] == 2
    assert len(h.pipeline_calls) == 2


# ---------------------------------------------------------------------------
# Atomic cron claim — exactly-once sweep across replicas
# ---------------------------------------------------------------------------

def test_claim_denied_returns_without_touching_rows(monkeypatch):
    """Another owner holds today's claim: no due query, no inserts, no audit."""
    h = _ScheduleHarness(monkeypatch, DUE_ROWS)
    h.claim_denied = True

    result = asyncio.run(wf.run_daily_scan_schedule())

    assert result == {"claimed": False, "due_domains": 0, "scheduled": 0}
    assert not any("FROM domains" in sql for sql, _ in h.queries)
    assert h.inserted_params == []
    assert h.audits == []
    assert h.completed == []
    assert h.released == []


def test_claim_sql_is_one_atomic_statement(monkeypatch):
    """The claim must be a single INSERT ... ON CONFLICT ... RETURNING —
    check-then-act across statements is the race the review flagged."""
    h = _ScheduleHarness(monkeypatch, DUE_ROWS)
    asyncio.run(wf.run_daily_scan_schedule())

    insert_sqls = [sql for sql, _ in h.claim_sqls if sql.startswith("INSERT INTO cron_runs")]
    assert len(insert_sqls) == 1
    sql = insert_sqls[0]
    assert "ON CONFLICT (cron_name, run_day)" in sql
    assert sql.rstrip().endswith("RETURNING *")
    assert "cron_runs.status = 'failed'" in sql  # failed-run takeover
    assert "claimed_at < now()" in sql  # stale-owner takeover


def test_schedule_releases_claim_when_sweep_raises(monkeypatch):
    h = _ScheduleHarness(monkeypatch, DUE_ROWS)
    h.due_query_error = RuntimeError("db down")

    try:
        asyncio.run(wf.run_daily_scan_schedule())
        raised = False
    except RuntimeError:
        raised = True

    assert raised
    assert len(h.claimed) == 1
    assert h.completed == []  # never completed
    assert len(h.released) == 1  # released so the retry can take over


def test_claim_helpers_single_statement_shapes():
    """Direct guard: each lifecycle helper is one atomic statement."""
    captured = []

    def fake_execute_one(sql, params=()):
        captured.append(" ".join(sql.split()))
        return None

    orig = cron_claim.execute_one
    cron_claim.execute_one = fake_execute_one
    try:
        from datetime import date as _date
        cron_claim.claim_cron_run("daily-scans", _date(2026, 10, 4), "api:1")
        cron_claim.complete_cron_run("daily-scans", _date(2026, 10, 4))
        cron_claim.release_cron_run("daily-scans", _date(2026, 10, 4))
        assert cron_claim.cron_run_completed("daily-scans", _date(2026, 10, 4)) is False
    finally:
        cron_claim.execute_one = orig

    assert "INSERT INTO cron_runs" in captured[0] and "ON CONFLICT" in captured[0]
    assert captured[1].startswith("UPDATE cron_runs") and "status = 'completed'" in captured[1]
    assert captured[2].startswith("DELETE FROM cron_runs") and "status = 'running'" in captured[2]
    assert "FROM cron_runs" in captured[3]


# ---------------------------------------------------------------------------
# schedule_ran_since — claim state first, legacy audit marker as fallback
# ---------------------------------------------------------------------------

def test_schedule_ran_since_true_when_claim_completed(monkeypatch):
    import backend.app.scheduler as sched

    audited = []
    monkeypatch.setattr(sched, "cron_run_completed", lambda name, day: True)
    monkeypatch.setattr(
        sched, "execute_query", lambda sql, params=(): audited.append(sql) or None
    )

    assert schedule_ran_since(datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)) is True
    assert audited == []  # completed claim short-circuits the legacy check


def test_schedule_ran_since_falls_back_to_legacy_audit(monkeypatch):
    import backend.app.scheduler as sched

    monkeypatch.setattr(sched, "cron_run_completed", lambda name, day: False)
    monkeypatch.setattr(sched, "execute_query", lambda sql, params=(): [{"ok": 1}])
    assert schedule_ran_since(datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)) is True

    monkeypatch.setattr(sched, "execute_query", lambda sql, params=(): [])
    assert schedule_ran_since(datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)) is False


def test_schedule_ran_since_naive_moment_treated_as_utc(monkeypatch):
    import backend.app.scheduler as sched

    seen = {}

    def fake_completed(name, day):
        seen["day"] = day
        return False

    monkeypatch.setattr(sched, "cron_run_completed", fake_completed)
    monkeypatch.setattr(sched, "execute_query", lambda sql, params=(): [])

    schedule_ran_since(datetime(2026, 10, 3, 6, 0))  # naive
    assert seen["day"] == datetime(2026, 10, 3).date()


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
        return {"due_domains": 1, "scheduled": 1, "claimed": True}

    monkeypatch.setattr(sched, "schedule_ran_since", lambda moment: False)
    monkeypatch.setattr(sched, "next_wake_at", lambda now, ran: now)  # force immediate wake
    monkeypatch.setattr(sched, "run_daily_scan_schedule", fake_run)

    asyncio.run(asyncio.wait_for(daily_scan_scheduler(stop), timeout=5))

    assert runs == [1]


def test_loop_backs_off_when_claim_denied(monkeypatch):
    """A denied claim (another replica mid-sweep) must not busy-loop: the
    loop waits the claim backoff before rechecking."""
    import backend.app.scheduler as sched

    stop = asyncio.Event()
    runs = []

    async def fake_run():
        runs.append(1)
        if len(runs) >= 2:
            stop.set()
        return {"claimed": False, "due_domains": 0, "scheduled": 0}

    monkeypatch.setattr(sched, "schedule_ran_since", lambda moment: False)
    monkeypatch.setattr(sched, "next_wake_at", lambda now, ran: now)
    monkeypatch.setattr(sched, "run_daily_scan_schedule", fake_run)
    monkeypatch.setattr(sched, "_CLAIM_BACKOFF_SECONDS", 0.05)

    asyncio.run(asyncio.wait_for(daily_scan_scheduler(stop), timeout=5))

    assert len(runs) == 2  # exactly one backoff between the two attempts


def test_marker_constant_is_cron_ran():
    assert CRON_RAN_ACTION == "cron.ran"
