"""Transactional scan claims and bounded execution, shared by worker and Core."""

import asyncio
import copy
import json
import logging
import secrets
from contextlib import contextmanager
from typing import Any, Callable

from backend.app.core.database import get_db
from backend.app.core.execution_fence import (
    ClaimLost,
    ExecutionClaim,
    execution_scope,
    lock_claim,
)
from shared.contracts import CORE_STAGES, empty_stage_progress

logger = logging.getLogger("cyphward.execution")
CORE_LEASE_SECONDS = 900
LOCAL_LEASE_SECONDS = 120


def claim_from_row(row: dict) -> ExecutionClaim:
    return ExecutionClaim(
        str(row["id"]),
        row["claimed_by"],
        row["claim_generation"],
        row["claim_token"],
        row["observation_generation"],
        row["execution_phase"],
    )


@contextmanager
def owned_transaction(claim: ExecutionClaim):
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                row = lock_claim(cur, claim)
                yield cur, row


def claim_recon(
    owner: str, phase: str, lease_seconds: int, scan_id: str | None = None
) -> dict | None:
    if phase not in {"worker", "local"} or lease_seconds < 1:
        raise ValueError("Invalid recon claim")
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '5s'")
                cur.execute("SET LOCAL statement_timeout = '15s'")
                cur.execute(
                    """
                    SELECT s.*, d.domain FROM scans s JOIN domains d ON d.id=s.domain_id AND d.org_id=s.org_id
                    WHERE (s.status='queued' OR (s.status='running' AND s.execution_phase=%s
                           AND s.claim_token IS NOT NULL AND s.lease_expires_at < clock_timestamp()))
                      AND (s.execution_phase IS NULL OR s.execution_phase=%s)
                      AND (s.current_stage IS NULL OR NOT (s.current_stage = ANY(%s)))
                      AND d.verification_status='verified'
                      AND (%s::uuid IS NULL OR s.id=%s::uuid)
                    ORDER BY s.created_at, s.id FOR UPDATE OF s SKIP LOCKED LIMIT 1
                """,
                    (phase, phase, CORE_STAGES, scan_id, scan_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute(
                    "SELECT verification_status FROM domains WHERE id=%s AND org_id=%s FOR SHARE",
                    (row["domain_id"], row["org_id"]),
                )
                domain = cur.fetchone()
                if not domain or domain["verification_status"] != "verified":
                    return None
                cur.execute(
                    """
                    UPDATE scans SET status='running', current_stage='discovery',
                        started_at=COALESCE(started_at,clock_timestamp()), completed_at=NULL,
                        stage_progress=%s::jsonb, error_message=NULL, claimed_by=%s,
                        execution_phase=%s, claim_generation=claim_generation+1,
                        observation_generation=claim_generation+1, claim_token=%s,
                        lease_expires_at=clock_timestamp()+make_interval(secs => %s)
                    WHERE id=%s RETURNING *
                """,
                    (
                        json.dumps(empty_stage_progress()),
                        owner,
                        phase,
                        secrets.token_urlsafe(32),
                        lease_seconds,
                        row["id"],
                    ),
                )
                held = cur.fetchone()
                held["domain"] = row["domain"]
                cur.execute(
                    "SELECT hostname FROM monitored_hosts WHERE org_id=%s AND domain_id=%s",
                    (held["org_id"], held["domain_id"]),
                )
                held["seed_hosts"] = [h["hostname"] for h in cur.fetchall()]
                return held


def claim_core_recovery(limit: int = 2) -> list[ExecutionClaim]:
    claimed = []
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '5s'")
                cur.execute("SET LOCAL statement_timeout = '15s'")
                cur.execute(
                    """SELECT id FROM scans WHERE status='running' AND execution_phase='core'
                    AND claim_token IS NOT NULL AND lease_expires_at < clock_timestamp()
                    ORDER BY lease_expires_at FOR UPDATE SKIP LOCKED LIMIT %s""",
                    (limit,),
                )
                rows = cur.fetchall()
                for row in rows:
                    cur.execute(
                        """UPDATE scans SET claimed_by='core-recovery',
                        claim_generation=claim_generation+1, claim_token=%s,
                        lease_expires_at=clock_timestamp()+make_interval(secs => %s)
                        WHERE id=%s RETURNING *""",
                        (secrets.token_urlsafe(32), CORE_LEASE_SECONDS, row["id"]),
                    )
                    claimed.append(claim_from_row(cur.fetchone()))
    return claimed


def handoff_to_core(claim: ExecutionClaim) -> ExecutionClaim:
    if claim.phase not in {"worker", "local"}:
        raise ClaimLost("Only recon ownership can be handed to Core")
    with owned_transaction(claim) as (cur, _):
        cur.execute(
            """UPDATE scans SET claimed_by='core-recovery', execution_phase='core',
            current_stage='security_checks', claim_generation=claim_generation+1, claim_token=%s,
            lease_expires_at=clock_timestamp()+make_interval(secs => %s)
            WHERE id=%s RETURNING *""",
            (secrets.token_urlsafe(32), CORE_LEASE_SECONDS, claim.scan_id),
        )
        return claim_from_row(cur.fetchone())


def renew_claim(claim: ExecutionClaim, lease_seconds: int) -> None:
    with owned_transaction(claim) as (cur, _):
        cur.execute(
            """UPDATE scans SET lease_expires_at=clock_timestamp()+make_interval(secs => %s)
            WHERE id=%s""",
            (lease_seconds, claim.scan_id),
        )


def store_observation(claim: ExecutionClaim, stage: str, data: Any) -> None:
    with owned_transaction(claim) as (cur, _):
        cur.execute(
            """INSERT INTO scan_results (scan_id, stage, raw_data, attempt_generation)
            VALUES (%s,%s,%s::jsonb,%s)
            ON CONFLICT (scan_id,attempt_generation,stage) WHERE attempt_generation IS NOT NULL
            DO UPDATE SET raw_data=EXCLUDED.raw_data, created_at=clock_timestamp()""",
            (claim.scan_id, stage, json.dumps(data), claim.observation_generation),
        )


def report_progress(
    claim: ExecutionClaim, stage: str, state: dict, lease_seconds: int
) -> None:
    with owned_transaction(claim) as (cur, row):
        progress = copy.deepcopy(row.get("stage_progress") or {})
        if not isinstance(progress, dict):
            progress = {}
        for key, val in empty_stage_progress().items():
            progress.setdefault(key, val)
        progress[stage] = state
        cur.execute(
            """UPDATE scans SET stage_progress=%s::jsonb, current_stage=%s,
            lease_expires_at=clock_timestamp()+make_interval(secs => %s) WHERE id=%s""",
            (json.dumps(progress), stage, lease_seconds, claim.scan_id),
        )


def fail_claim(claim: ExecutionClaim, error: str, progress: dict | None = None) -> None:
    with owned_transaction(claim) as (cur, row):
        cur.execute(
            """UPDATE scans SET status='failed', error_message=%s, stage_progress=%s::jsonb,
            completed_at=clock_timestamp(), claimed_by=NULL, lease_expires_at=NULL, claim_token=NULL,
            execution_phase=NULL, claim_generation=claim_generation+1 WHERE id=%s""",
            (
                error[:2000],
                json.dumps(
                    progress
                    if progress is not None
                    else row.get("stage_progress") or {}
                ),
                claim.scan_id,
            ),
        )


def finish_assessment(
    claim: ExecutionClaim,
    org_id: str,
    score: dict,
    progress: dict,
    audit_metadata: dict,
    notification: dict,
) -> None:
    """All mandatory terminal records commit together, while ownership is held."""
    with owned_transaction(claim) as (cur, row):
        if str(row["org_id"]) != str(org_id) or claim.phase != "core":
            raise ClaimLost("Invalid assessment authority")
        cur.execute(
            """INSERT INTO score_snapshots
            (org_id,domain_id,score,subscores,factors,model,scope,risk_points,scan_id)
            VALUES (%s,NULL,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s)
            ON CONFLICT (scan_id) WHERE scan_id IS NOT NULL DO UPDATE SET
                score=EXCLUDED.score,subscores=EXCLUDED.subscores,factors=EXCLUDED.factors,
                model=EXCLUDED.model,scope=EXCLUDED.scope,risk_points=EXCLUDED.risk_points""",
            (
                org_id,
                score["score"],
                json.dumps(score["subscores"]),
                json.dumps(score["factors"]),
                notification["model"],
                notification["scope"],
                score.get("risk_points"),
                claim.scan_id,
            ),
        )
        cur.execute(
            """INSERT INTO notifications (org_id,type,title,body,severity,link)
            VALUES (%s,'scan_completed',%s,%s,%s,'/scans')""",
            (
                org_id,
                notification["title"],
                notification["body"],
                notification["severity"],
            ),
        )
        cur.execute(
            """INSERT INTO audit_log (org_id,user_id,action,resource_type,resource_id,metadata)
            VALUES (%s,NULL,'scan.completed','scan',%s,%s::jsonb)""",
            (org_id, claim.scan_id, json.dumps(audit_metadata, default=str)),
        )
        cur.execute(
            """UPDATE scans SET status='completed',current_stage='completed',score=%s,
            stage_progress=%s::jsonb,completed_at=clock_timestamp(),claimed_by=NULL,
            lease_expires_at=NULL,claim_token=NULL,execution_phase=NULL,
            claim_generation=claim_generation+1 WHERE id=%s""",
            (score["score"], json.dumps(progress), claim.scan_id),
        )


def inspect_status(scan_id: str) -> str:
    # A read after authority was lost must not attempt a pipeline mutation.
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM scans WHERE id=%s", (scan_id,))
                row = cur.fetchone()
                return row["status"] if row else "missing"


async def run_owned(
    claim: ExecutionClaim, factory: Callable, lease_seconds: int
) -> dict:
    async def heartbeat():
        while True:
            await asyncio.sleep(max(0.1, min(30.0, lease_seconds / 3)))
            try:
                await asyncio.to_thread(renew_claim, claim, lease_seconds)
            except ClaimLost:
                raise
            except Exception:
                logger.warning(
                    "scan=%s heartbeat unavailable; database writes remain fenced",
                    claim.scan_id,
                )

    with execution_scope(claim):
        work = asyncio.create_task(factory())
        beat = asyncio.create_task(heartbeat())
        try:
            done, _ = await asyncio.wait(
                {work, beat}, return_when=asyncio.FIRST_COMPLETED
            )
            if work in done:
                return await work
            await beat
            raise ClaimLost("Execution heartbeat stopped")
        except ClaimLost:
            status = await asyncio.to_thread(inspect_status, claim.scan_id)
            return {
                "scan_id": claim.scan_id,
                "status": status,
                "claim_lost": True,
                "cancelled": status == "cancelled",
            }
        finally:
            for task in (work, beat):
                if not task.done():
                    task.cancel()
            await asyncio.gather(work, beat, return_exceptions=True)
