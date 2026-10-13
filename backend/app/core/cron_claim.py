"""Generation-bound periodic run claims; stale owners cannot finish/release."""

from datetime import date
import secrets

from backend.app.core.database import execute_one
from backend.app.core.execution_fence import ClaimLost

DAILY_SCAN_CRON_NAME = "daily-scans"
STALE_CLAIM_MINUTES = 30


def claim_cron_run(
    cron_name: str,
    run_day: date,
    claimed_by: str,
    stale_minutes: int = STALE_CLAIM_MINUTES,
) -> dict | None:
    return execute_one(
        """INSERT INTO cron_runs
        (cron_name,run_day,claimed_by,status,claimed_at,claim_generation,claim_token,lease_expires_at)
        VALUES (%s,%s,%s,'running',clock_timestamp(),1,%s,clock_timestamp()+make_interval(mins => %s))
        ON CONFLICT (cron_name,run_day) DO UPDATE SET
            claimed_by=EXCLUDED.claimed_by,claimed_at=clock_timestamp(),status='running',finished_at=NULL,
            claim_generation=cron_runs.claim_generation+1,claim_token=EXCLUDED.claim_token,
            lease_expires_at=EXCLUDED.lease_expires_at
        WHERE cron_runs.status='failed' OR (cron_runs.status='running' AND
            COALESCE(cron_runs.lease_expires_at,cron_runs.claimed_at+make_interval(mins => %s)) < clock_timestamp())
        RETURNING *""",
        (
            cron_name,
            run_day,
            claimed_by,
            secrets.token_urlsafe(32),
            stale_minutes,
            stale_minutes,
        ),
    )


def complete_cron_run(cron_name: str, run_day: date, claim: dict) -> bool:
    return bool(
        execute_one(
            """UPDATE cron_runs SET status='completed',finished_at=clock_timestamp()
        WHERE cron_name=%s AND run_day=%s AND status='running' AND claimed_by=%s
          AND claim_generation=%s AND claim_token=%s AND lease_expires_at > clock_timestamp()
        RETURNING *""",
            (
                cron_name,
                run_day,
                claim["claimed_by"],
                claim["claim_generation"],
                claim["claim_token"],
            ),
        )
    )


def release_cron_run(cron_name: str, run_day: date, claim: dict) -> bool:
    return bool(
        execute_one(
            """UPDATE cron_runs SET status='failed',finished_at=clock_timestamp()
        WHERE cron_name=%s AND run_day=%s AND status='running' AND claimed_by=%s
          AND claim_generation=%s AND claim_token=%s AND lease_expires_at > clock_timestamp()
        RETURNING *""",
            (
                cron_name,
                run_day,
                claim["claimed_by"],
                claim["claim_generation"],
                claim["claim_token"],
            ),
        )
    )


def lock_cron_claim(cur, claim: dict) -> None:
    cur.execute(
        "SELECT * FROM cron_runs WHERE cron_name=%s AND run_day=%s FOR SHARE",
        (claim["cron_name"], claim["run_day"]),
    )
    row = cur.fetchone()
    cur.execute("SELECT clock_timestamp() AS claim_now")
    now = cur.fetchone()["claim_now"]
    if (
        not row
        or row["status"] != "running"
        or row["claimed_by"] != claim["claimed_by"]
        or row["claim_generation"] != claim["claim_generation"]
        or row["claim_token"] != claim["claim_token"]
        or not row["lease_expires_at"]
        or row["lease_expires_at"] <= now
    ):
        raise ClaimLost("Scheduler claim is no longer current")


def cron_run_completed(cron_name: str, run_day: date) -> bool:
    return bool(
        execute_one(
            "SELECT 1 AS ok FROM cron_runs WHERE cron_name=%s AND run_day=%s AND status='completed'",
            (cron_name, run_day),
        )
    )
