"""
Core API client for the scanner worker (spec §14/§22).

Outbound HTTPS only. Every request carries:
    Authorization: Bearer <SCANNER_API_KEY>   (constant-time compared server-side)
    X-Scanner-Id:   <worker identity>         (job lease owner)
    X-Timestamp:    unix seconds              (±300s replay window)

Errors:
    CoreError  — server-side failure (5xx / malformed); retry via poll loop.
    JobLost    — 409: lease revoked (cancel, re-claim, or expiry takeover).
"""
import asyncio
import logging
import time
from typing import Any, Dict, Optional

import httpx

from scanner.config import WorkerConfig
from shared.contracts import ScanJob

logger = logging.getLogger("cyphward.scanner.client")

CLAIM_URL = "/api/v1/scanner/claim"


class CoreError(Exception):
    """Core returned an error that warrants backoff (not a job-scoped failure)."""


class JobLost(Exception):
    """This scanner no longer holds the job lease."""


class CoreClient:
    def __init__(self, cfg: WorkerConfig):
        self._cfg = cfg
        self._http = httpx.AsyncClient(
            base_url=cfg.core_url,
            timeout=cfg.http_timeout_seconds,
            headers={"User-Agent": f"cyphward-scanner/{cfg.scanner_id}"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _headers(self, job: Optional[ScanJob] = None) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "X-Scanner-Id": self._cfg.scanner_id,
            "X-Timestamp": str(int(time.time())),
            "X-Scanner-Protocol": "2",
        }
        if job is not None:
            headers['X-Claim-Generation'] = str(job.claim_generation)
            headers['X-Claim-Token'] = job.claim_token
        return headers

    async def _post(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        retry: bool = True,
        job: Optional[ScanJob] = None,
    ) -> httpx.Response:
        """POST with bounded retry for transport errors and 5xx.

        Retries are safe for idempotent endpoints (progress/observations upsert,
        complete/fail guarded by stage status). claim() passes retry=False: if a
        claim response is lost the job stays leased and is reclaimed by lease
        expiry rather than double-dispatched.
        """
        attempts = 3 if retry else 1
        delay = 1.5
        for attempt in range(1, attempts + 1):
            try:
                resp = await self._http.post(path, json=json, headers=self._headers(job))
            except httpx.TransportError as e:
                if attempt >= attempts:
                    raise CoreError(f"network error on {path}: {e}") from e
                logger.warning(
                    "network error on %s (attempt %d/%d): %s; retrying in %.1fs",
                    path, attempt, attempts, e, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if resp.status_code >= 500 and attempt < attempts:
                logger.warning(
                    "server error %d on %s (attempt %d/%d); retrying in %.1fs",
                    resp.status_code, path, attempt, attempts, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return resp
        raise CoreError(f"post failed on {path}")  # pragma: no cover

    @staticmethod
    def _raise_for_status(resp: httpx.Response, path: str) -> None:
        if resp.status_code == 409:
            raise JobLost(f"{path}: 409 lease not held")
        if resp.status_code >= 500:
            raise CoreError(f"{path}: HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise CoreError(f"{path}: HTTP {resp.status_code}")

    async def claim(self) -> Optional[ScanJob]:
        """Claim the next queued job. Returns None when the queue is empty."""
        # An old API ignores the v2 header. Negotiate before POST so a new
        # worker cannot allocate an unfenced v1 job during deployment.
        path = "/api/v1/scanner/protocol"
        try:
            protocol = await self._http.get(path, headers=self._headers())
        except httpx.TransportError as exc:
            raise CoreError("Scanner protocol negotiation unavailable") from exc
        self._raise_for_status(protocol, path)
        try:
            metadata = protocol.json()
            compatible = isinstance(metadata, dict) and metadata.get("version") == 2
        except ValueError:
            compatible = False
        if not compatible:
            raise CoreError("Scanner API protocol v2 is not ready")
        resp = await self._post(CLAIM_URL, retry=False)
        if resp.status_code == 204:
            return None
        if resp.status_code != 200:
            self._raise_for_status(resp, CLAIM_URL)
        try:
            return ScanJob.model_validate(resp.json())
        except Exception as e:
            raise CoreError("Malformed or incompatible claim payload") from e

    async def progress(
        self,
        job: ScanJob,
        stage: str,
        status: str,
        items: int = 0,
        duration_ms: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """Stage progress update — also refreshes the job lease (heartbeat)."""
        path = f"/api/v1/scanner/jobs/{job.scan_id}/progress"
        resp = await self._post(path, json={
            "stage": stage,
            "status": status,
            "items": items,
            "duration_ms": duration_ms,
            **({"error": error} if error else {}),
        }, job=job)
        self._raise_for_status(resp, path)

    async def observations(self, job: ScanJob, stage: str, data: Dict[str, Any]) -> None:
        """Submit raw observations for a stage (idempotent per stage)."""
        path = f"/api/v1/scanner/jobs/{job.scan_id}/observations"
        resp = await self._post(path, json={"stage": stage, "data": data}, job=job)
        self._raise_for_status(resp, path)

    async def complete(self, job: ScanJob, stats: Dict[str, Any]) -> None:
        """Recon finished — Core runs finalize (security checks → score → AI)."""
        path = f"/api/v1/scanner/jobs/{job.scan_id}/complete"
        resp = await self._post(path, json={"stats": stats}, job=job)
        self._raise_for_status(resp, path)

    async def fail(self, job: ScanJob, stage: Optional[str], error: str) -> None:
        """Terminal failure. JobLost here means the job was already revoked."""
        path = f"/api/v1/scanner/jobs/{job.scan_id}/fail"
        resp = await self._post(path, json={
            "stage": stage,
            "error": (error or "unknown error")[:2000],
        }, job=job)
        self._raise_for_status(resp, path)
