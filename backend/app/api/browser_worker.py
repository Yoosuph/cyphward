"""Outbound-only protocol for the separate cookie-consent browser worker (packet C2b).

Everything here answers 503 until BROWSER_CONSENT_ENABLED is on and a
BROWSER_WORKER_API_KEY is set. The key is not the scanner's key, and every call
must carry the `privacy_browser` capability, so neither worker can use the
other's endpoints. Jobs come from `privacy_browser_jobs`, which the scanner
claim never reads.
"""
import logging
import secrets
import time
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from backend.app.core import browser_jobs, config
from backend.app.core.auth import log_audit, require_admin
from backend.app.core.database import execute_one
from backend.app.core.execution_fence import ClaimLost
from shared.browser_contracts import (
    BROWSER_PROTOCOL_VERSION, BrowserJob, CAPABILITIES_HEADER, ConsentObservation, JobFailure,
    MAX_RESULT_BODY_BYTES, PRIVACY_BROWSER_CAPABILITY,
)

logger = logging.getLogger("cyphward.browser_worker")
router = APIRouter(prefix="/api/v1/browser-worker", tags=["Browser Worker"])
customer_router = APIRouter(prefix="/api/v1/domains", tags=["Domains"])
_TIMESTAMP_SKEW_SECONDS = 300


def require_browser_worker(
    authorization: Annotated[Optional[str], Header()] = None,
    x_scanner_id: Annotated[Optional[str], Header(alias="X-Scanner-Id")] = None,
    x_timestamp: Annotated[Optional[str], Header(alias="X-Timestamp")] = None,
    x_browser_protocol: Annotated[Optional[str], Header(alias="X-Browser-Protocol")] = None,
    x_capabilities: Annotated[Optional[str], Header(alias=CAPABILITIES_HEADER)] = None,
) -> str:
    key = config.BROWSER_WORKER_API_KEY
    if not config.BROWSER_CONSENT_ENABLED or not key:
        raise HTTPException(503, "Browser worker interface disabled.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token.encode(), key.encode()):
        raise HTTPException(401, "Invalid browser worker credentials")
    worker = (x_scanner_id or "").strip()
    if not worker or len(worker) > 64:
        raise HTTPException(400, "Valid X-Scanner-Id header required")
    if worker == "core-recovery" or worker.startswith("local:"):
        raise HTTPException(400, "Reserved worker identity")
    try:
        ts = int(x_timestamp or "")
    except ValueError:
        raise HTTPException(400, "X-Timestamp header (unix seconds) required")
    if abs(int(time.time()) - ts) > _TIMESTAMP_SKEW_SECONDS:
        raise HTTPException(401, "Timestamp outside allowed window")
    if x_browser_protocol != str(BROWSER_PROTOCOL_VERSION):
        raise HTTPException(426, "Browser protocol v1 is required.")
    capabilities = {c.strip() for c in (x_capabilities or "").split(",") if c.strip()}
    if PRIVACY_BROWSER_CAPABILITY not in capabilities:
        raise HTTPException(403, "The privacy_browser capability is required.")
    return worker


Worker = Annotated[str, Depends(require_browser_worker)]


def _job_claim(job_id: str, worker: str, generation: int, token: str) -> browser_jobs.JobClaim:
    try:
        UUID(job_id)
    except ValueError:
        raise HTTPException(404, "Job not found.")
    return browser_jobs.JobClaim(job_id, worker, generation, token)


def _claim_headers(
    job_id: str,
    worker: Worker,
    x_claim_generation: Annotated[int, Header(alias="X-Claim-Generation", ge=1)],
    x_claim_token: Annotated[str, Header(alias="X-Claim-Token", min_length=32, max_length=128,
                                         pattern=r"^[A-Za-z0-9_-]+$")],
) -> browser_jobs.JobClaim:
    return _job_claim(job_id, worker, x_claim_generation, x_claim_token)


JobAuthority = Annotated[browser_jobs.JobClaim, Depends(_claim_headers)]


def _guard(fn, *args):
    try:
        return fn(*args)
    except ClaimLost as exc:
        raise HTTPException(409, "Job claim is expired, revoked or superseded.") from exc


@router.get("/protocol")
def protocol(worker: Worker) -> dict:
    return {"version": BROWSER_PROTOCOL_VERSION, "capabilities": [PRIVACY_BROWSER_CAPABILITY],
            "job_types": ["cookie_consent_observation"]}


_last_claim: dict = {}


def _claim_rate_limit(worker: str) -> None:
    """At most one claim attempt per worker every BROWSER_CLAIM_MIN_INTERVAL_SECONDS (per API process)."""
    interval = config.BROWSER_CLAIM_MIN_INTERVAL_SECONDS
    now = time.monotonic()
    if interval > 0:
        if len(_last_claim) > 1000:
            _last_claim.clear()
        previous = _last_claim.get(worker)
        if previous is not None and now - previous < interval:
            raise HTTPException(429, "Claiming too often.", headers={"Retry-After": str(max(1, int(interval)))})
    _last_claim[worker] = now


@router.post("/claim", response_model=BrowserJob, responses={204: {"description": "Queue empty"}})
def claim_job(worker: Worker):
    _claim_rate_limit(worker)
    job = browser_jobs.claim(worker)
    if job is None:
        return Response(status_code=204)
    return job


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat(job_id: str, claim: JobAuthority) -> dict:
    _guard(browser_jobs.heartbeat, job_id, claim)
    return {"ok": True}


@router.post("/jobs/{job_id}/result", status_code=202)
async def submit_result(job_id: str, request: Request, claim: JobAuthority) -> dict:
    # FastAPI does not cap bodies: refuse a large one before parsing it.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_RESULT_BODY_BYTES:
        raise HTTPException(413, "Result too large.")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_RESULT_BODY_BYTES:
            raise HTTPException(413, "Result too large.")
    try:
        observation = ConsentObservation.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "Result does not match the observation schema.")
    # complete() takes a pooled connection and waits on database locks: never run it on the event loop.
    rows = await run_in_threadpool(_guard, browser_jobs.complete, job_id, claim, observation)
    if rows == 0:
        raise HTTPException(409, "The domain is no longer eligible; the observation was not stored.")
    return {"ok": True, "evidence_rows": rows}


@router.post("/jobs/{job_id}/fail")
def fail_job(job_id: str, body: JobFailure, claim: JobAuthority) -> dict:
    _guard(browser_jobs.fail, job_id, claim, f"{body.reason}: {body.error}")
    return {"ok": True, "status": "failed"}


@customer_router.post("/{domain_id}/consent-observation", status_code=202)
def request_observation(domain_id: str, org: dict = Depends(require_admin)) -> dict:
    """Owner/admin asks for a first-visit cookie observation of a verified domain."""
    if not config.BROWSER_CONSENT_ENABLED:
        raise HTTPException(404, "Not found.")
    try:
        UUID(domain_id)
    except ValueError:
        raise HTTPException(404, "Domain not found.")
    domain = execute_one("SELECT id, verification_status, revoked_at FROM domains WHERE id = %s AND org_id = %s",
                         (domain_id, org["id"]))
    if not domain:
        raise HTTPException(404, "Domain not found.")
    if domain["verification_status"] != "verified" or domain["revoked_at"] is not None:
        raise HTTPException(400, "Verify the domain before requesting a browser observation.")
    job_id = browser_jobs.enqueue(str(org["id"]), domain_id, cooldown_hours=1)
    if job_id is None:
        raise HTTPException(409, "An observation is already queued, running or was requested recently.")
    log_audit(str(org["id"]), org.get("current_user_id"), "browser_consent.requested", "domain", domain_id, {"job_id": job_id})
    return {"status": "queued", "job_id": job_id}
