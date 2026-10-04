"""
Cyphward Scanner Worker API (spec §14 Option A — outbound-only job protocol).

The Azure scanner worker polls these endpoints over outbound HTTPS; the VM's
inbound firewall stays SSH-only. Endpoints are disabled unless
SCANNER_MODE=remote AND SCANNER_API_KEY is set (fail closed).

Security model:
    Authorization: Bearer <SCANNER_API_KEY>     (constant-time compare)
    X-Scanner-Id:   <worker identity>            (job lease owner)
    X-Timestamp:    unix seconds                 (±300s replay window)

Jobs are claimed atomically from the scans table (SKIP LOCKED) with a
time-boxed lease; progress updates refresh the lease (heartbeat). Observation
submissions are idempotent per (scan_id, stage).
"""
import json
import logging
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, BackgroundTasks, Response

from backend.app.core.config import (
    SCANNER_API_KEY,
    SCANNER_LEASE_SECONDS,
    SCANNER_MAX_HOSTS,
    SCANNER_MAX_PORTS,
    SCANNER_MODE,
    SCANNER_NUCLEI_CONCURRENCY,
    SCANNER_NUCLEI_MAX_HOSTS,
    SCANNER_STAGE_TIMEOUT_SECONDS,
)
from backend.app.core.database import execute_one, execute_query
from shared.contracts import (
    CORE_STAGES,
    JobComplete,
    JobFail,
    ObservationSubmit,
    ProgressUpdate,
    ScanJob,
    ScanJobLimits,
    empty_stage_progress,
)

logger = logging.getLogger("cyphward.scanner")

router = APIRouter(prefix="/api/v1/scanner", tags=["Scanner Worker"])

_TIMESTAMP_SKEW_SECONDS = 300


def _scanner_enabled() -> None:
    """Fail closed: remote mode + configured key are both required."""
    if SCANNER_MODE != "remote":
        raise HTTPException(status_code=503, detail="Scanner interface disabled (SCANNER_MODE != remote).")
    if not SCANNER_API_KEY:
        raise HTTPException(status_code=503, detail="Scanner interface disabled (SCANNER_API_KEY not set).")


def require_scanner(
    authorization: Optional[str] = Header(None),
    x_scanner_id: Optional[str] = Header(None, alias="X-Scanner-Id"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
) -> str:
    """Authenticate the scanner worker. Returns the scanner identity."""
    _scanner_enabled()

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token.encode("utf-8"), SCANNER_API_KEY.encode("utf-8")):
        logger.warning("Scanner auth failure from id=%s", x_scanner_id or "unknown")
        raise HTTPException(status_code=401, detail="Invalid scanner credentials")

    if not x_scanner_id or not x_scanner_id.strip():
        raise HTTPException(status_code=400, detail="X-Scanner-Id header required")
    if len(x_scanner_id) > 64:
        raise HTTPException(status_code=400, detail="X-Scanner-Id too long")

    # Replay window: reject stale or far-future timestamps.
    try:
        ts = int(x_timestamp or "")
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Timestamp header (unix seconds) required")
    if abs(int(time.time()) - ts) > _TIMESTAMP_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="Timestamp outside allowed window")

    return x_scanner_id.strip()


def _held_job(scan_id: str, scanner_id: str) -> Dict[str, Any]:
    """Verify this scanner currently holds a running lease on the job."""
    scan = execute_one(
        "SELECT id, status, claimed_by, lease_expires_at FROM scans WHERE id = %s",
        (scan_id,),
    )
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found.")
    if scan["status"] != "running" or scan["claimed_by"] != scanner_id:
        raise HTTPException(status_code=409, detail="Job not held by this scanner.")
    return scan


@router.post("/claim")
def claim_job(
    background_tasks: BackgroundTasks,
    scanner_id: str = Depends(require_scanner),
) -> Any:
    """
    Atomically claim the next authorized queued scan (or a running scan whose
    lease expired — crash recovery). Returns 204 when the queue is empty.
    """
    # ------------------------------------------------------------------
    # Core-finalize crash recovery. finalize_scan runs as a background task;
    # if the process dies mid-run (restart/OOM/deploy) the scan would stay
    # 'running' forever. Re-claim those (atomically) and re-trigger finalize.
    # Must run BEFORE the worker claim below so the worker's lease-expired
    # branch never steals a core-stage scan.
    # ------------------------------------------------------------------
    stuck_rows = execute_query(
        """
        UPDATE scans
        SET claimed_by = 'core-recovery',
            lease_expires_at = now() + make_interval(secs => 900)
        WHERE status = 'running'
          AND current_stage = ANY(%s)
          AND COALESCE(started_at, created_at) < now() - make_interval(mins => 15)
          AND (claimed_by IS NULL
               OR (claimed_by = 'core-recovery'
                   AND lease_expires_at IS NOT NULL AND lease_expires_at < now()))
        RETURNING id
        """,
        (CORE_STAGES,),
    ) or []
    if stuck_rows:
        from backend.app.workflows.inngest_workflow import finalize_scan

        for row in stuck_rows:
            logger.warning("scan=%s finalize interrupted — recovery re-trigger", row["id"])
            background_tasks.add_task(finalize_scan, str(row["id"]))

    job_row = execute_one(
        """
        UPDATE scans
        SET status = 'running',
            current_stage = 'discovery',
            started_at = COALESCE(started_at, now()),
            stage_progress = %s::jsonb,
            error_message = NULL,
            claimed_by = %s,
            lease_expires_at = now() + make_interval(secs => %s)
        WHERE id = (
            SELECT s.id
            FROM scans s
            JOIN domains d ON d.id = s.domain_id
            WHERE (s.status = 'queued'
                   OR (s.status = 'running' AND s.lease_expires_at IS NOT NULL
                       AND s.lease_expires_at < now()))
              AND d.verification_status = 'verified'
            ORDER BY s.created_at ASC
            FOR UPDATE OF s SKIP LOCKED
            LIMIT 1
        )
        RETURNING id
        """,
        (json.dumps(empty_stage_progress()), scanner_id, SCANNER_LEASE_SECONDS),
    )
    if not job_row:
        return Response(status_code=204)  # queue empty — worker backs off

    scan = execute_one(
        """
        SELECT s.id, s.org_id, s.domain_id, s.created_at, s.lease_expires_at, d.domain
        FROM scans s
        JOIN domains d ON d.id = s.domain_id
        WHERE s.id = %s
        """,
        (job_row["id"],),
    )
    if not scan:
        raise HTTPException(status_code=409, detail="Claimed scan vanished.")

    logger.info("scan=%s claimed by %s", scan["id"], scanner_id)

    seed_hosts = [
        r["hostname"] for r in (
            execute_query(
                "SELECT hostname FROM monitored_hosts WHERE org_id = %s AND domain_id = %s",
                (scan["org_id"], scan["domain_id"]),
            )
            or []
        )
    ]

    return ScanJob(
        scan_id=str(scan["id"]),
        organization_id=str(scan["org_id"]),
        domain_id=str(scan["domain_id"]),
        target=scan["domain"],
        target_type="domain",
        scope=[scan["domain"]],
        seed_hosts=seed_hosts,
        created_at=str(scan["created_at"]),
        authorization_context={
            "verification_status": "verified",
            "verified_at_claim_time": True,
        },
        limits=ScanJobLimits(
            max_hosts=SCANNER_MAX_HOSTS,
            max_ports=SCANNER_MAX_PORTS,
            stage_timeout_seconds=SCANNER_STAGE_TIMEOUT_SECONDS,
            nuclei_concurrency=SCANNER_NUCLEI_CONCURRENCY,
            nuclei_max_hosts=SCANNER_NUCLEI_MAX_HOSTS,
        ),
        lease_expires_at=str(scan["lease_expires_at"]),
    )


@router.post("/jobs/{scan_id}/progress")
def report_progress(
    scan_id: str,
    update: ProgressUpdate,
    scanner_id: str = Depends(require_scanner),
) -> Dict[str, Any]:
    """Update stage progress for a held job. Also refreshes the lease (heartbeat)."""
    _held_job(scan_id, scanner_id)

    scan = execute_one("SELECT stage_progress FROM scans WHERE id = %s", (scan_id,))
    progress: Dict[str, Any] = (scan and scan.get("stage_progress")) or {}
    if not isinstance(progress, dict):
        progress = {}
    # Backfill template keys (older rows) before merging.
    for key, val in empty_stage_progress().items():
        progress.setdefault(key, val)

    progress[update.stage] = {
        "status": update.status,
        "items": update.items,
        "duration_ms": update.duration_ms,
        **({"error": update.error} if update.error else {}),
        **(
            {"score": progress[update.stage].get("score")}
            if update.stage == "scoring" and isinstance(progress.get(update.stage), dict)
            else {}
        ),
    }

    execute_one(
        """
        UPDATE scans
        SET stage_progress = %s::jsonb,
            current_stage = %s,
            lease_expires_at = now() + make_interval(secs => %s)
        WHERE id = %s AND claimed_by = %s AND status = 'running'
        """,
        (json.dumps(progress), update.stage, SCANNER_LEASE_SECONDS, scan_id, scanner_id),
    )
    return {"ok": True, "stage": update.stage, "status": update.status}


@router.post("/jobs/{scan_id}/observations")
def submit_observations(
    scan_id: str,
    obs: ObservationSubmit,
    scanner_id: str = Depends(require_scanner),
) -> Dict[str, Any]:
    """
    Store raw observations for a stage (§19 — no risk decisions here).
    Idempotent: re-submitting a stage replaces its previous payload.
    """
    _held_job(scan_id, scanner_id)

    execute_one("DELETE FROM scan_results WHERE scan_id = %s AND stage = %s", (scan_id, obs.stage))
    execute_one(
        "INSERT INTO scan_results (scan_id, stage, raw_data) VALUES (%s, %s, %s::jsonb)",
        (scan_id, obs.stage, json.dumps(obs.data)),
    )
    return {"ok": True, "stage": obs.stage}


@router.post("/jobs/{scan_id}/complete", status_code=202)
def complete_job(
    scan_id: str,
    body: JobComplete,
    background_tasks: BackgroundTasks,
    scanner_id: str = Depends(require_scanner),
) -> Dict[str, Any]:
    """
    Worker finished recon. Release the lease and hand off to Core finalize
    (security_checks → normalize → diff → risk → AI). Scan stays 'running'
    until finalize sets the terminal status.
    """
    _held_job(scan_id, scanner_id)

    # Hand ownership to Core under a finalize lease: the worker no longer
    # holds the job, and the claim-endpoint sweeper can re-trigger finalize
    # (after lease expiry) if this process dies mid-run.
    # CAS: requires the worker to still hold a running job — a cancel that
    # landed after _held_job must not hand a cancelled scan to finalize.
    handed_off = execute_one(
        """
        UPDATE scans SET claimed_by = 'core-recovery',
                         lease_expires_at = now() + make_interval(secs => 900)
        WHERE id = %s AND claimed_by = %s AND status = 'running'
        RETURNING id
        """,
        (scan_id, scanner_id),
    )
    if not handed_off:
        raise HTTPException(status_code=409, detail="Job not held by this scanner.")

    # Imported here to avoid a module-level circular import.
    from backend.app.workflows.inngest_workflow import finalize_scan

    background_tasks.add_task(finalize_scan, scan_id)

    logger.info("scan=%s recon complete by %s, finalizing", scan_id, scanner_id)
    return {"ok": True, "status": "finalizing", "stats": body.stats}


@router.post("/jobs/{scan_id}/fail")
def fail_job(
    scan_id: str,
    body: JobFail,
    scanner_id: str = Depends(require_scanner),
) -> Dict[str, Any]:
    """Terminal failure from the worker. Releases the lease."""
    _held_job(scan_id, scanner_id)

    error = f"{body.stage}: {body.error}" if body.stage else body.error
    execute_one(
        """
        UPDATE scans
        SET status = 'failed', error_message = %s, completed_at = now(),
            claimed_by = NULL, lease_expires_at = NULL
        WHERE id = %s AND claimed_by = %s AND status = 'running'
        """,
        (error[:2000], scan_id, scanner_id),
    )
    logger.warning("scan=%s failed on worker %s: %s", scan_id, scanner_id, error[:200])
    return {"ok": True, "status": "failed"}
