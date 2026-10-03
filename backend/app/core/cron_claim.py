"""Atomic Postgres claims for periodic cron runs (review P1 — durable jobs).

The daily scan sweep used to check a `cron.ran` audit marker and only then
select/create scans: two API replicas could both pass the check before any
write landed and both sweep the same day. cron_runs turns the entire run
into one atomic statement — INSERT ... ON CONFLICT DO UPDATE ... RETURNING
hands the claim to exactly one caller per (cron_name, run_day):

- fresh insert                 -> caller owns the run
- status = 'failed'            -> a retry takes over a failed run
- running and stale (> stale)  -> takeover after a crashed owner
- running, fresh               -> another owner is mid-run (denied)
- completed                    -> never re-run (denied)

Release on failure deletes only a still-running claim, so an in-process
retry can re-claim immediately while a crash leaves the claim to age into
the stale-takeover window.
"""
from datetime import date
from typing import Any, Dict, Optional

from backend.app.core.database import execute_one

DAILY_SCAN_CRON_NAME = "daily-scans"
STALE_CLAIM_MINUTES = 30


def claim_cron_run(
    cron_name: str,
    run_day: date,
    claimed_by: str,
    stale_minutes: int = STALE_CLAIM_MINUTES,
) -> Optional[Dict[str, Any]]:
    """Atomically claim (cron_name, run_day). Returns the claim row iff this
    caller now owns the run, else None (someone else owns it or it already
    completed)."""
    return execute_one(
        """
        INSERT INTO cron_runs (cron_name, run_day, claimed_by, status, claimed_at)
        VALUES (%s, %s, %s, 'running', now())
        ON CONFLICT (cron_name, run_day) DO UPDATE
           SET claimed_by = EXCLUDED.claimed_by,
               claimed_at = now(),
               status = 'running',
               finished_at = NULL
         WHERE cron_runs.status = 'failed'
            OR (cron_runs.status = 'running'
                AND cron_runs.claimed_at < now() - make_interval(mins => %s))
        RETURNING *
        """,
        (cron_name, run_day, claimed_by, stale_minutes),
    )


def complete_cron_run(cron_name: str, run_day: date) -> None:
    """Mark a claim completed. Completed claims are never re-claimed."""
    execute_one(
        """
        UPDATE cron_runs SET status = 'completed', finished_at = now()
        WHERE cron_name = %s AND run_day = %s AND status = 'running'
        RETURNING *
        """,
        (cron_name, run_day),
    )


def release_cron_run(cron_name: str, run_day: date) -> None:
    """Drop a still-running claim so a retry can take over immediately.
    Completed rows are left untouched (release-after-success is a no-op)."""
    execute_one(
        """
        DELETE FROM cron_runs
        WHERE cron_name = %s AND run_day = %s AND status = 'running'
        RETURNING *
        """,
        (cron_name, run_day),
    )


def cron_run_completed(cron_name: str, run_day: date) -> bool:
    """True when this (cron_name, run_day) already ran to completion."""
    return bool(
        execute_one(
            """
            SELECT 1 AS ok FROM cron_runs
            WHERE cron_name = %s AND run_day = %s AND status = 'completed'
            """,
            (cron_name, run_day),
        )
    )
