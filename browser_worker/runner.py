"""Browser worker main loop: claim one job, observe, report, repeat. One job at a time.

It claims only through the browser endpoints and the privacy_browser capability, and re-checks
every claim before opening a browser: the same fields the scanner worker re-checks (version,
verified authorization context, token shape, target inside scope), plus an https start URL on
the verified host itself.
"""
import argparse
import asyncio
import contextlib
import logging
import os
import random
from typing import Optional
from urllib.parse import urlsplit

from browser_worker.client import CoreClient, CoreError, JobLost
from browser_worker.config import BrowserConfig, load_config
from browser_worker.netguard import EgressPolicy, Refused, host_in_scope, numeric_host
from browser_worker.observer import Limits, ObservationFailed, observe
from shared.browser_contracts import ConsentObservation, JOB_TYPE_CONSENT, BrowserJob
from shared.scan_scope import canonical_host

logger = logging.getLogger("cyphward.browser.runner")


class InvalidJob(Exception):
    pass


def validate_job(job: BrowserJob) -> None:
    """Defence in depth on top of Core's own authorization at claim time."""
    if job.job_type != JOB_TYPE_CONSENT:
        raise InvalidJob("unsupported job type")
    ctx = job.authorization_context or {}
    if ctx.get("verification_status") != "verified" or ctx.get("verified_at_claim_time") is not True:
        raise InvalidJob("claim is not marked as verified at claim time")
    target = canonical_host(job.target)
    scope = [canonical_host(s) for s in job.scope]
    if target is None or any(s is None for s in scope) or not host_in_scope(target, scope):
        raise InvalidJob("target is outside the authorized scope")
    if numeric_host(target):
        raise InvalidJob("target must be a domain name, not an address")
    parts = urlsplit(job.url)
    if parts.scheme != "https" or (parts.hostname or "").lower().rstrip(".") != target or parts.port not in (None, 443) \
            or parts.username or parts.password:
        raise InvalidJob("start url must be https on the verified host")


def limits_for(job: BrowserJob) -> Limits:
    return Limits(job.limits.page_timeout_seconds, job.limits.job_timeout_seconds, job.limits.max_requests,
                  job.limits.max_total_bytes).clamped()


async def run_job(client: CoreClient, job: BrowserJob, cfg: BrowserConfig, policy: Optional[EgressPolicy] = None) -> str:
    """Process one claimed job; returns "completed", "failed" or "lost"."""
    policy = policy or EgressPolicy()
    lost = asyncio.Event()

    async def beat() -> None:
        while True:
            await asyncio.sleep(cfg.heartbeat_seconds)
            try:
                await client.heartbeat(job)
            except JobLost:
                lost.set()
                return
            except CoreError:
                logger.warning("job=%s heartbeat failed; will retry", job.job_id)

    heartbeat = asyncio.create_task(beat())
    try:
        try:
            validate_job(job)
        except InvalidJob as exc:
            return await _report_failure(client, job, "invalid_job", str(exc))
        work = asyncio.create_task(observe(
            job.url, [canonical_host(s) for s in job.scope], policy, limits=limits_for(job),
            chromium_path=cfg.chromium_path or None, sandbox=cfg.chromium_sandbox))
        done, _ = await asyncio.wait({work, asyncio.create_task(lost.wait())}, return_when=asyncio.FIRST_COMPLETED)
        if work not in done:
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            return "lost"
        try:
            raw = work.result()
            ConsentObservation.model_validate(raw)  # never send what Core would refuse
        except asyncio.CancelledError:
            raise
        except ObservationFailed as exc:
            return await _report_failure(client, job, exc.reason, str(exc))
        except Refused as exc:
            return await _report_failure(client, job, exc.reason if exc.reason in ("refused_address", "off_scope_redirect") else "invalid_job", str(exc))
        except ValueError as exc:
            return await _report_failure(client, job, "browser_error", f"result failed local validation: {str(exc)[:200]}")
        except Exception as exc:  # noqa: BLE001 - one job's browser fault must never end the worker or burn the job's attempts
            logger.exception("job=%s unexpected browser fault", job.job_id)
            return await _report_failure(client, job, "browser_error", f"unexpected {type(exc).__name__}")
        try:
            await client.result(job, raw)
        except JobLost:
            return "lost"
        return "completed"
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat


async def _report_failure(client: CoreClient, job: BrowserJob, reason: str, message: str) -> str:
    logger.info("job=%s failed: %s", job.job_id, reason)
    try:
        await client.fail(job, reason, message)
    except JobLost:
        return "lost"
    return "failed"


async def main_loop(cfg: BrowserConfig, once: bool = False) -> None:
    client = CoreClient(cfg)
    try:
        while True:
            try:
                job = await client.claim()
            except CoreError as exc:
                logger.warning("claim failed: %s", exc)
                job = None
            except Exception:  # noqa: BLE001 - nothing a claim can raise may end the worker; back off and retry
                logger.exception("claim crashed")
                job = None
            if job is not None:
                try:
                    outcome = await run_job(client, job, cfg)
                except CoreError as exc:
                    outcome = "error"
                    logger.warning("job=%s could not report: %s", job.job_id, exc)
                except Exception:  # noqa: BLE001 - keep serving; the lease expires and Core retries or fails the job
                    outcome = "error"
                    logger.exception("job=%s crashed", job.job_id)
                logger.info("job=%s outcome=%s", job.job_id, outcome)
                if once:
                    return
                continue
            if once:
                return
            await asyncio.sleep(cfg.poll_interval_seconds + random.uniform(0, 3))
    finally:
        await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Cyphward browser worker")
    parser.add_argument("--once", action="store_true", help="claim at most one job, then exit")
    args = parser.parse_args()
    cfg = load_config()
    os.environ.pop("BROWSER_API_KEY", None)  # belt and braces: read_api_key already removed it
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main_loop(cfg, once=args.once))
