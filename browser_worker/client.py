"""Core API client for the browser worker. Outbound HTTPS only, own key, own endpoints."""
import logging
import time
from typing import Any, Dict, Optional

import httpx

from browser_worker.config import BrowserConfig
from shared.browser_contracts import BROWSER_PROTOCOL_VERSION, BrowserJob, CAPABILITIES_HEADER, PRIVACY_BROWSER_CAPABILITY
from shared.scanner_identity import SCANNER_INFO_URL

logger = logging.getLogger("cyphward.browser.client")
BASE = "/api/v1/browser-worker"


class CoreError(Exception):
    """Core answered with an error worth backing off for."""


class JobLost(Exception):
    """409: this worker no longer holds the job."""


class CoreClient:
    def __init__(self, cfg: BrowserConfig, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._cfg = cfg
        self._http = httpx.AsyncClient(base_url=cfg.core_url, timeout=cfg.http_timeout_seconds, transport=transport,
                                       headers={"User-Agent": f"cyphward-browser-worker/{cfg.worker_id} (+{SCANNER_INFO_URL})"})

    async def aclose(self) -> None:
        await self._http.aclose()

    def _headers(self, job: Optional[BrowserJob] = None) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {self._cfg.api_key}", "X-Scanner-Id": self._cfg.worker_id,
                   "X-Timestamp": str(int(time.time())), "X-Browser-Protocol": str(BROWSER_PROTOCOL_VERSION),
                   CAPABILITIES_HEADER: PRIVACY_BROWSER_CAPABILITY}
        if job is not None:
            headers["X-Claim-Generation"] = str(job.claim_generation)
            headers["X-Claim-Token"] = job.claim_token
        return headers

    async def _post(self, path: str, job: Optional[BrowserJob] = None, json_body: Optional[Dict[str, Any]] = None) -> httpx.Response:
        try:
            return await self._http.post(path, headers=self._headers(job), json=json_body)
        except httpx.TransportError as exc:
            raise CoreError(f"network error on {path}: {exc}") from exc

    @staticmethod
    def _check(resp: httpx.Response, path: str) -> None:
        if resp.status_code == 409:
            raise JobLost(f"{path}: 409")
        if resp.status_code >= 400:
            raise CoreError(f"{path}: HTTP {resp.status_code}")

    async def claim(self) -> Optional[BrowserJob]:
        # No retry: a lost claim response is recovered by lease expiry, never by double dispatch.
        resp = await self._post(f"{BASE}/claim")
        if resp.status_code == 204:
            return None
        self._check(resp, "claim")
        try:
            return BrowserJob.model_validate(resp.json())
        except ValueError as exc:
            raise CoreError("malformed or incompatible claim payload") from exc

    async def heartbeat(self, job: BrowserJob) -> None:
        self._check(await self._post(f"{BASE}/jobs/{job.job_id}/heartbeat", job), "heartbeat")

    async def result(self, job: BrowserJob, observation: Dict[str, Any]) -> None:
        self._check(await self._post(f"{BASE}/jobs/{job.job_id}/result", job, observation), "result")

    async def fail(self, job: BrowserJob, reason: str, error: str) -> None:
        self._check(await self._post(f"{BASE}/jobs/{job.job_id}/fail", job,
                                     {"reason": reason, "error": (error or "unknown")[:500].replace("\n", " ")}), "fail")
