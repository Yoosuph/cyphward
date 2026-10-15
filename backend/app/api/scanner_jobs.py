"""Outbound-only scanner protocol v2 with mandatory per-attempt authority."""

import logging
import secrets
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Response
from backend.app.core.config import (
    SCANNER_API_KEY,
    SCANNER_CLAIMS_ENABLED,
    SCANNER_LEASE_SECONDS,
    SCANNER_MAX_HOSTS,
    SCANNER_DNS_MAX_HOSTS,
    SCANNER_MAX_PORTS,
    SCANNER_MODE,
    SCANNER_NUCLEI_CONCURRENCY,
    SCANNER_NUCLEI_MAX_HOSTS,
    SCANNER_STAGE_TIMEOUT_SECONDS,
    SCANNER_RECON_TIMEOUT_SECONDS,
    SCANNER_TLS_MAX_HOSTS,
)
from backend.app.core.execution_fence import ClaimLost, ExecutionClaim
from backend.app.core import scan_execution as execution
from shared.contracts import (
    JobComplete,
    JobFail,
    ObservationSubmit,
    ProgressUpdate,
    ScanJob,
    ScanJobLimits,
    RECON_STAGES,
)

logger = logging.getLogger("cyphward.scanner")
router = APIRouter(prefix="/api/v1/scanner", tags=["Scanner Worker"])
_TIMESTAMP_SKEW_SECONDS = 300


def require_scanner(
    authorization: Annotated[str | None, Header()] = None,
    x_scanner_id: Annotated[str | None, Header(alias="X-Scanner-Id")] = None,
    x_timestamp: Annotated[str | None, Header(alias="X-Timestamp")] = None,
    x_scanner_protocol: Annotated[
        str | None, Header(alias="X-Scanner-Protocol")
    ] = None,
) -> str:
    if SCANNER_MODE != "remote" or not SCANNER_API_KEY:
        raise HTTPException(503, "Scanner interface disabled.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token.encode(), SCANNER_API_KEY.encode()):
        raise HTTPException(401, "Invalid scanner credentials")
    if not x_scanner_id or not x_scanner_id.strip() or len(x_scanner_id) > 64:
        raise HTTPException(400, "Valid X-Scanner-Id header required")
    if x_scanner_id.strip() == "core-recovery" or x_scanner_id.strip().startswith(
        "local:"
    ):
        raise HTTPException(400, "Reserved scanner identity")
    try:
        ts = int(x_timestamp or "")
    except ValueError:
        raise HTTPException(400, "X-Timestamp header (unix seconds) required")
    if abs(int(time.time()) - ts) > _TIMESTAMP_SKEW_SECONDS:
        raise HTTPException(401, "Timestamp outside allowed window")
    if x_scanner_protocol != "2":
        raise HTTPException(426, "Scanner protocol v2 is required.")
    return x_scanner_id.strip()


Scanner = Annotated[str, Depends(require_scanner)]


def require_job_claim(
    scan_id: UUID,
    scanner_id: Scanner,
    x_claim_generation: Annotated[int, Header(alias="X-Claim-Generation", ge=1)],
    x_claim_token: Annotated[
        str,
        Header(
            alias="X-Claim-Token",
            min_length=32,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ],
) -> ExecutionClaim:
    return ExecutionClaim(
        str(scan_id),
        scanner_id,
        x_claim_generation,
        x_claim_token,
        x_claim_generation,
        "worker",
    )


WorkerClaim = Annotated[ExecutionClaim, Depends(require_job_claim)]


def _write(fn, *args):
    try:
        return fn(*args)
    except ClaimLost as exc:
        raise HTTPException(
            409, "Job claim is expired, revoked or superseded."
        ) from exc


@router.get("/protocol")
def scanner_protocol(scanner_id: Scanner) -> dict:
    """Workers negotiate before allocating a job during a coordinated rollout."""
    return {"version": 2, "claim_authority": "required", "observation_attempts": True}


@router.post(
    "/claim",
    response_model=ScanJob,
    responses={204: {"description": "Queue empty or claims paused"}},
)
def claim_job(scanner_id: Scanner) -> Any:
    if not SCANNER_CLAIMS_ENABLED:
        return Response(status_code=204)
    row = execution.claim_recon(scanner_id, "worker", SCANNER_LEASE_SECONDS)
    if row is None:
        return Response(status_code=204)
    return ScanJob(
        scan_id=str(row["id"]),
        organization_id=str(row["org_id"]),
        domain_id=str(row["domain_id"]),
        target=row["domain"],
        scope=[row["domain"]],
        seed_hosts=row["seed_hosts"],
        created_at=str(row["created_at"]),
        lease_expires_at=str(row["lease_expires_at"]),
        claim_generation=row["claim_generation"],
        claim_token=row["claim_token"],
        authorization_context={
            "verification_status": "verified",
            "verified_at_claim_time": True,
        },
        limits=ScanJobLimits(
            max_hosts=SCANNER_MAX_HOSTS,
            dns_max_hosts=SCANNER_DNS_MAX_HOSTS,
            max_ports=SCANNER_MAX_PORTS,
            stage_timeout_seconds=SCANNER_STAGE_TIMEOUT_SECONDS,
            recon_timeout_seconds=SCANNER_RECON_TIMEOUT_SECONDS,
            tls_max_hosts=SCANNER_TLS_MAX_HOSTS,
            nuclei_concurrency=SCANNER_NUCLEI_CONCURRENCY,
            nuclei_max_hosts=SCANNER_NUCLEI_MAX_HOSTS,
        ),
    )


@router.post("/jobs/{scan_id}/progress")
def report_progress(scan_id: UUID, update: ProgressUpdate, claim: WorkerClaim) -> dict:
    if update.stage not in RECON_STAGES:
        raise HTTPException(422, "Workers may update only recon stages.")
    state = {
        "status": update.status,
        "items": update.items,
        "duration_ms": update.duration_ms,
        **({"error": update.error} if update.error else {}),
    }
    stored_status = _write(
        execution.report_progress, claim, update.stage, state, SCANNER_LEASE_SECONDS
    )
    return {"ok": True, "stage": update.stage, "status": stored_status}


@router.post("/jobs/{scan_id}/observations")
def submit_observations(
    scan_id: UUID, obs: ObservationSubmit, claim: WorkerClaim
) -> dict:
    _write(execution.store_observation, claim, obs.stage, obs.data)
    return {"ok": True, "stage": obs.stage}


@router.post("/jobs/{scan_id}/complete", status_code=202)
def complete_job(
    scan_id: UUID,
    body: JobComplete,
    background_tasks: BackgroundTasks,
    claim: WorkerClaim,
) -> dict:
    core_claim = _write(execution.handoff_to_core, claim)
    from backend.app.workflows.inngest_workflow import finalize_scan

    background_tasks.add_task(finalize_scan, str(scan_id), core_claim)
    return {"ok": True, "status": "finalizing", "stats": body.stats}


@router.post("/jobs/{scan_id}/fail")
def fail_job(scan_id: UUID, body: JobFail, claim: WorkerClaim) -> dict:
    error = f"{body.stage}: {body.error}" if body.stage else body.error
    _write(execution.fail_claim, claim, error)
    return {"ok": True, "status": "failed"}
