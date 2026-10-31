"""Queue, claim and result handling for browser consent jobs (packet C2b).

Jobs live in `privacy_browser_jobs`, never in `scans`. The scanner worker's claim
query reads `scans` only, so it cannot receive one; this module reads the jobs
table only, so the browser worker cannot receive a scan.

Every write that needs authority locks the job row, then re-checks owner,
generation, token, status and the lease against the database clock. No
transaction is held across the worker's browsing: the worker holds a lease and
heartbeats it, and each call here is one short transaction.
"""
import json
import logging
import secrets
from urllib.parse import urlsplit
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.app.compliance import browser_observation
from backend.app.core import config
from backend.app.core.database import get_db
from backend.app.core.execution_fence import ClaimLost
from shared.browser_contracts import (
    BrowserJob, BrowserLimits, ConsentObservation, JOB_TYPE_CONSENT,
)

logger = logging.getLogger("cyphward.browser_jobs")
FAILED_RETRY_HOURS = 1


@dataclass(frozen=True)
class JobClaim:
    job_id: str
    owner: str
    generation: int
    token: str


def _timeouts(cur) -> None:
    cur.execute("SET LOCAL lock_timeout = '5s'")
    cur.execute("SET LOCAL statement_timeout = '15s'")


def enqueue(org_id: str, domain_id: str, scan_id: Optional[str] = None,
            cooldown_hours: Optional[int] = None) -> Optional[str]:
    """Queue one observation for a verified, unrevoked domain; returns the job id or None.

    None means: not eligible (unverified or revoked), a job is already queued or running, a
    recent job exists inside the cooldown, or a recent failure is still inside its retry delay.
    """
    hours = config.BROWSER_JOB_COOLDOWN_HOURS if cooldown_hours is None else cooldown_hours
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                _timeouts(cur)
                cur.execute(
                    """INSERT INTO privacy_browser_jobs (org_id, domain_id, scan_id)
                    SELECT d.org_id, d.id, %s FROM domains d
                    WHERE d.id = %s AND d.org_id = %s AND d.verification_status = 'verified' AND d.revoked_at IS NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM privacy_browser_jobs j WHERE j.org_id = d.org_id AND j.domain_id = d.id
                        AND ((j.status <> 'failed' AND j.requested_at > clock_timestamp() - make_interval(hours => %s))
                             OR (j.status = 'failed' AND j.requested_at > clock_timestamp() - make_interval(hours => %s))))
                    ON CONFLICT DO NOTHING RETURNING id""",
                    (scan_id, domain_id, org_id, hours, FAILED_RETRY_HOURS),
                )
                row = cur.fetchone()
                return str(row["id"]) if row else None


def enqueue_after_scan(scan_id: str) -> Optional[str]:
    """Called after a scan completes, only when the feature is on."""
    if not config.BROWSER_CONSENT_ENABLED:
        return None
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                _timeouts(cur)
                cur.execute("SELECT org_id, domain_id FROM scans WHERE id = %s AND status = 'completed'", (scan_id,))
                scan = cur.fetchone()
    if not scan:
        return None
    return enqueue(str(scan["org_id"]), str(scan["domain_id"]), scan_id)


def claim(worker_id: str, lease_seconds: Optional[int] = None) -> Optional[BrowserJob]:
    lease = lease_seconds or config.BROWSER_LEASE_SECONDS
    if lease < 10:
        raise ValueError("lease too short")
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                _timeouts(cur)
                # A global cap on live jobs. It cannot be raised by presenting another worker id.
                cur.execute("SELECT count(*) AS n FROM privacy_browser_jobs WHERE status = 'running' "
                            "AND lease_expires_at > clock_timestamp()")
                if cur.fetchone()["n"] >= config.BROWSER_MAX_RUNNING_JOBS:
                    return None
                # Housekeeping first: jobs that can never succeed leave the queue.
                cur.execute(
                    """UPDATE privacy_browser_jobs j SET status='failed', completed_at=clock_timestamp(),
                    claimed_by=NULL, claim_token=NULL, lease_expires_at=NULL, error_message=%s
                    WHERE j.status IN ('queued','running')
                      AND (j.status='queued' OR j.lease_expires_at < clock_timestamp())
                      AND (j.attempts >= %s OR NOT EXISTS (
                            SELECT 1 FROM domains d WHERE d.id=j.domain_id AND d.org_id=j.org_id
                            AND d.verification_status='verified' AND d.revoked_at IS NULL))""",
                    ("No longer eligible: domain not verified or too many attempts", config.BROWSER_MAX_ATTEMPTS),
                )
                cur.execute(
                    """SELECT j.id, d.domain FROM privacy_browser_jobs j
                    JOIN domains d ON d.id = j.domain_id AND d.org_id = j.org_id
                    WHERE (j.status='queued' OR (j.status='running' AND j.lease_expires_at < clock_timestamp()))
                      AND d.verification_status='verified' AND d.revoked_at IS NULL
                      AND NOT EXISTS (SELECT 1 FROM organization_suspensions os
                                      WHERE os.org_id = j.org_id AND os.status = 'suspended')
                    ORDER BY j.requested_at, j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1"""
                )
                pick = cur.fetchone()
                if not pick:
                    return None
                cur.execute(
                    """UPDATE privacy_browser_jobs SET status='running', attempts=attempts+1, claimed_by=%s,
                    claim_generation=claim_generation+1, claim_token=%s, started_at=COALESCE(started_at, clock_timestamp()),
                    lease_expires_at=clock_timestamp()+make_interval(secs => %s)
                    WHERE id=%s RETURNING *""",
                    (worker_id, secrets.token_urlsafe(32), lease, pick["id"]),
                )
                job = cur.fetchone()
    domain = pick["domain"]
    return BrowserJob(
        job_type=JOB_TYPE_CONSENT, job_id=str(job["id"]), organization_id=str(job["org_id"]),
        domain_id=str(job["domain_id"]), target=domain, scope=[domain], url=f"https://{domain}/",
        authorization_context={"verification_status": "verified", "verified_at_claim_time": True},
        limits=BrowserLimits(), lease_expires_at=str(job["lease_expires_at"]),
        claim_generation=job["claim_generation"], claim_token=job["claim_token"],
    )


def _lock(cur, job_id: str, claim_: JobClaim) -> Dict[str, Any]:
    _timeouts(cur)
    cur.execute("SELECT * FROM privacy_browser_jobs WHERE id = %s FOR UPDATE", (job_id,))
    row = cur.fetchone()
    if (row is None or row["status"] != "running" or row["claimed_by"] != claim_.owner
            or row["claim_generation"] != claim_.generation or not row["claim_token"]
            or not secrets.compare_digest(row["claim_token"].encode(), claim_.token.encode())):
        raise ClaimLost("Browser job claim is not held")
    cur.execute("SELECT clock_timestamp() < %s AS live", (row["lease_expires_at"],))
    if not cur.fetchone()["live"]:
        raise ClaimLost("Browser job lease expired")
    return row


def heartbeat(job_id: str, claim_: JobClaim, lease_seconds: Optional[int] = None) -> None:
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                _lock(cur, job_id, claim_)
                cur.execute("UPDATE privacy_browser_jobs SET lease_expires_at = clock_timestamp() + make_interval(secs => %s) "
                            "WHERE id = %s", (lease_seconds or config.BROWSER_LEASE_SECONDS, job_id))


def _ineligible(cur, row, observation: ConsentObservation) -> Optional[str]:
    """Why a finished observation must not become evidence: the domain was revoked or unverified while the
    browser was working, or the page ended up outside the verified domain. Checked under the job lock."""
    cur.execute("SELECT domain, verification_status, revoked_at FROM domains WHERE id = %s AND org_id = %s FOR SHARE",
                (row["domain_id"], row["org_id"]))
    domain = cur.fetchone()
    if not domain or domain["verification_status"] != "verified" or domain["revoked_at"] is not None:
        return "domain no longer verified"
    if "\\" in observation.final_url:
        return "final address is malformed"
    parts = urlsplit(observation.final_url)
    if parts.username is not None or parts.password is not None or parts.scheme not in ("http", "https"):
        return "final address is malformed"
    host = (parts.hostname or "").lower().rstrip(".")
    name = domain["domain"].lower().rstrip(".")
    if host != name and not host.endswith("." + name):
        return "final address outside the verified domain"
    return None


def complete(job_id: str, claim_: JobClaim, observation: ConsentObservation) -> int:
    """Store the validated result and the evidence rows in one transaction; returns the row count.

    Returns 0 (and fails the job) when the domain is no longer eligible or the page ended outside it."""
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                row = _lock(cur, job_id, claim_)
                reason = _ineligible(cur, row, observation)
                if reason:
                    cur.execute(
                        """UPDATE privacy_browser_jobs SET status='failed', error_message=%s, completed_at=clock_timestamp(),
                        claimed_by=NULL, claim_token=NULL, lease_expires_at=NULL WHERE id=%s""", (reason, job_id))
                    return 0
                now = datetime.now(timezone.utc)
                rows = browser_observation.evidence_rows(
                    observation, org_id=str(row["org_id"]), domain_id=str(row["domain_id"]),
                    job_id=str(row["id"]), observed_at=now)
                cur.execute(
                    """UPDATE privacy_browser_jobs SET status='completed', result=%s::jsonb,
                    completed_at=clock_timestamp(), claimed_by=NULL, claim_token=NULL, lease_expires_at=NULL,
                    error_message=NULL WHERE id=%s""",
                    (observation.model_dump_json(), job_id),
                )
                for item in rows:
                    cur.execute(
                        """INSERT INTO compliance_evidence
                        (org_id,domain_id,requirement_key,register_version,source,status,observed_at,expires_at,
                         scan_id,finding_ids,details)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,'{}',%s::jsonb)""",
                        (item["org_id"], item["domain_id"], item["requirement_key"], item["register_version"],
                         item["source"], item["status"], item["observed_at"], item["expires_at"],
                         json.dumps(item["details"], default=str)),
                    )
                cur.execute(
                    """INSERT INTO audit_log (org_id,user_id,action,resource_type,resource_id,metadata)
                    VALUES (%s,NULL,'browser_consent.observed','privacy_browser_job',%s,%s::jsonb)""",
                    (row["org_id"], job_id, json.dumps({"evidence_rows": len(rows)})),
                )
                return len(rows)


def fail(job_id: str, claim_: JobClaim, error: str) -> None:
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                _lock(cur, job_id, claim_)
                cur.execute(
                    """UPDATE privacy_browser_jobs SET status='failed', error_message=%s, completed_at=clock_timestamp(),
                    claimed_by=NULL, claim_token=NULL, lease_expires_at=NULL WHERE id=%s""",
                    ((error or "unknown error")[:600], job_id),
                )
