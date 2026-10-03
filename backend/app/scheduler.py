"""In-process daily scan scheduler (06:00 UTC sweep).

Why this exists: the platform also declares an Inngest cron trigger, but the
Inngest platform never synced our serve endpoint (zero /api/inngest traffic in
Render logs), so that trigger never fired. This loop runs inside the
always-on cyphward-core service and calls the exact same shared
``run_daily_scan_schedule()`` implementation — no external dependency, no
account to register, failures visible in the same logs.

Restart safety: wake time is always recomputed from the wall clock against
today's claim state — a completed `cron_runs` row or the legacy `cron.ran`
audit marker (both mean "today's sweep ran"), so
  - restart before today's 06:00        -> sleeps until 06:00
  - restart after 06:00, already ran    -> sleeps until tomorrow 06:00
  - restart after 06:00, sweep missed   -> catches up immediately
Exactly-once per day even across deploys and API replicas: the sweep itself
runs under an atomic `cron_runs` claim (backend.app.core.cron_claim), so
racing replicas/Inngest cron cannot double-sweep; when another owner holds
the claim the loop backs off and rechecks instead of spinning.

Only one trigger should be enabled: if the Inngest platform is ever wired up,
set CYPHWARD_SCHEDULER_ENABLED=false on the service.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from backend.app.core.auth import log_audit
from backend.app.core.database import execute_query
from backend.app.core.cron_claim import DAILY_SCAN_CRON_NAME, cron_run_completed
from backend.app.workflows.inngest_workflow import run_daily_scan_schedule

logger = logging.getLogger("cyphward.scheduler")

DAILY_SCAN_HOUR_UTC = 6
CRON_RAN_ACTION = "cron.ran"
_RETRY_SECONDS = 300  # failed runs are retried after 5 minutes
_CLAIM_BACKOFF_SECONDS = 60  # another owner holds today's claim — recheck soon


def _at_six(now: datetime) -> datetime:
    return now.replace(hour=DAILY_SCAN_HOUR_UTC, minute=0, second=0, microsecond=0)


def next_wake_at(now: datetime, ran_today: bool) -> datetime:
    """Next wake instant for the daily 06:00 UTC scan sweep.

    - ``ran_today`` True -> tomorrow 06:00 UTC (today's sweep is done).
    - Before today's 06:00 -> today's 06:00 UTC.
    - At/after today's 06:00 and not yet ran -> ``now`` (catch-up: the sweep
      was missed because the service was restarting at the boundary).
    Naive datetimes are treated as UTC.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    six = _at_six(now)
    if ran_today:
        return six + timedelta(days=1)
    if now < six:
        return six
    return now


def schedule_ran_since(moment: datetime) -> bool:
    """True if today's sweep already ran at/after ``moment``.

    Primary signal: a completed ``cron_runs`` claim for the run day (the
    atomic guard). Secondary: the legacy ``cron.ran`` audit marker — kept so
    rows written before the claim migration (or when the audit write itself
    is the last thing that failed) still count as "already ran".
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    run_day = moment.astimezone(timezone.utc).date()
    if cron_run_completed(DAILY_SCAN_CRON_NAME, run_day):
        return True
    rows = execute_query(
        "SELECT 1 AS ok FROM audit_log WHERE action = %s AND created_at >= %s LIMIT 1",
        (CRON_RAN_ACTION, moment),
    )
    return bool(rows)


async def daily_scan_scheduler(stop: asyncio.Event) -> None:
    """Background loop: wake at each 06:00 UTC (with catch-up) and run the
    shared daily scan schedule until ``stop`` is set."""
    logger.info("daily scan scheduler started (06:00 UTC sweep)")
    while not stop.is_set():
        try:
            now = datetime.now(timezone.utc)
            ran_today = schedule_ran_since(_at_six(now))
            wake_at = next_wake_at(now, ran_today)
            delay = max((wake_at - now).total_seconds(), 0.0)
            if delay > 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                    break  # shutdown requested while sleeping
                except asyncio.TimeoutError:
                    pass
            result: Dict[str, Any] = await run_daily_scan_schedule()
            logger.info("daily scan schedule complete: %s", result)
            if isinstance(result, dict) and result.get("claimed") is False:
                # Another replica/process owns today's claim (mid-sweep).
                # Back off and recheck instead of spinning on a denied claim.
                try:
                    await asyncio.wait_for(stop.wait(), timeout=_CLAIM_BACKOFF_SECONDS)
                    break  # shutdown requested while backing off
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "daily scan scheduler run failed; retrying in %d minutes", _RETRY_SECONDS // 60
            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=_RETRY_SECONDS)
                break  # shutdown requested during retry backoff
            except asyncio.TimeoutError:
                pass
    logger.info("daily scan scheduler stopped")
