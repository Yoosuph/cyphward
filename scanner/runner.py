"""
Cyphward scanner worker runner (spec §15–§19).

Executes a claimed job sequentially — one stage at a time (§16), never
concurrent jobs (SCANNER_MAX_CONCURRENT_SCANS=1). Foundational stages
(discovery/dns/http) abort the job on failure; ports/tls/nuclei degrade
gracefully (§23). Raw observations only — Core owns normalization and risk
decisions (§19).

Usage:
    python -m scanner.runner            # daemon loop (systemd)
    python -m scanner.runner --once     # at most one job, then exit
"""
import argparse
import asyncio
import contextlib
import dataclasses
import logging
import random
import shutil
import time
from typing import Any, Dict, List, Optional

from scanner.client import CoreClient, CoreError, JobLost
from scanner.config import load_config
from scanner.scope import ScopeError, assert_job_in_scope, filter_hosts, host_in_scope

from backend.app.scanner.discovery import discover_subdomains
from backend.app.scanner.dns_resolver import resolve_host_dns
from backend.app.scanner.http_probe import probe_http_service
from backend.app.scanner.naabu_runner import run_naabu_batch
from backend.app.scanner.sslyze_runner import run_sslyze_batch
from backend.app.scanner.nuclei_runner import run_nuclei_batch
from shared.contracts import ScanJob

logger = logging.getLogger("cyphward.scanner")

TLS_HOST_CAP = 25
PORTS_STAGE_CONCURRENCY = 4
TLS_STAGE_CONCURRENCY = 2

# Stage → scan_results payload key (must match Core's finalize loader).
OBSERVATION_KEY = {
    "discovery": "discovered_hosts",
    "dns": "dns_records",
    "http": "http_probes",
    "ports": "open_ports",
    "tls": "tls_profiles",
    "nuclei": "nuclei_findings",
}


class JobAborted(Exception):
    """Fatal stage failure — report to Core via the fail endpoint."""

    def __init__(self, stage: str, error: str):
        super().__init__(error)
        self.stage = stage
        self.error = error


def _ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def _tool(binary: str) -> bool:
    return shutil.which(binary) is not None


async def _stop_beat(stop: asyncio.Event, beat: asyncio.Task) -> None:
    stop.set()
    beat.cancel()
    with contextlib.suppress(asyncio.CancelledError, asyncio.InvalidStateError):
        await beat


async def _heartbeat(
    client: CoreClient,
    scan_id: str,
    stage: str,
    interval: float,
    stop: asyncio.Event,
) -> None:
    """Refresh the job lease while a long stage runs. 409 = lease revoked."""
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await client.progress(scan_id, stage, "running")
        except JobLost:
            logger.warning("scan=%s lease lost during heartbeat (stage=%s)", scan_id, stage)
            return
        except CoreError as e:
            logger.debug("scan=%s heartbeat failed (transient): %s", scan_id, e)


async def run_stage(
    client: CoreClient,
    cfg,
    job: ScanJob,
    stage: str,
    coro_factory,
    *,
    optional: bool = False,
) -> Optional[List[Any]]:
    """
    Run one recon stage with progress + heartbeat. Returns the result list,
    or None for optional stages that were skipped/failed (scan continues).
    """
    t0 = time.time()
    await client.progress(job.scan_id, stage, "running")

    stop = asyncio.Event()
    beat = asyncio.create_task(
        _heartbeat(client, job.scan_id, stage, max(30.0, cfg.heartbeat_seconds), stop)
    )
    try:
        result = await coro_factory()
    except JobLost:
        await _stop_beat(stop, beat)
        raise
    except Exception as exc:
        await _stop_beat(stop, beat)
        if optional:
            logger.warning("scan=%s stage=%s failed (continuing): %s", job.scan_id, stage, exc)
            await client.progress(job.scan_id, stage, "failed",
                                  duration_ms=_ms(t0), error=str(exc)[:500])
            return None
        raise JobAborted(stage, str(exc)) from exc
    else:
        await _stop_beat(stop, beat)

    if not isinstance(result, list):
        result = []

    if result:
        await client.observations(job.scan_id, stage, {OBSERVATION_KEY[stage]: result})
    await client.progress(job.scan_id, stage, "completed",
                          items=len(result), duration_ms=_ms(t0))
    return result


async def _gather_dicts(awaitables) -> List[Dict[str, Any]]:
    results = await asyncio.gather(*awaitables, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


async def execute_job(client: CoreClient, cfg, job: ScanJob) -> Dict[str, Any]:
    """Run all recon stages for one claimed job (sequential, §16)."""
    assert_job_in_scope(job)
    limits = job.limits
    max_hosts = limits.max_hosts

    stats: Dict[str, Any] = {}

    # --- STAGE 1: discovery (fatal) --------------------------------------
    hosts_raw = await run_stage(client, cfg, job, "discovery", lambda: discover_subdomains(job.target))
    assert hosts_raw is not None
    # Owner-registered hosts ride along (scope filter below still applies).
    if getattr(job, "seed_hosts", None):
        hosts_raw = sorted(set(hosts_raw) | {h.strip().lower() for h in job.seed_hosts if h})
    # Per-host suffix validation (§40) + de-dup + cap (first scope check).
    discovered = filter_hosts(hosts_raw, job.scope, max_hosts)
    if len(hosts_raw) > len(discovered):
        logger.info("scan=%s discovery: %d/%d hosts in scope",
                    job.scan_id, len(discovered), len(hosts_raw))
    stats["discovered"] = len(discovered)
    if not discovered:
        logger.warning("scan=%s discovery returned no in-scope hosts", job.scan_id)

    # --- STAGE 2: dns (fatal) --------------------------------------------
    async def _dns():
        return await _gather_dicts([resolve_host_dns(h) for h in discovered])

    dns_records = await run_stage(client, cfg, job, "dns", _dns)
    assert dns_records is not None
    stats["dns"] = len(dns_records)

    # --- STAGE 3: http (fatal, second scope check before probing) --------
    http_targets = [d["hostname"] for d in dns_records
                    if d.get("hostname") and host_in_scope(d["hostname"], job.scope)]

    async def _http():
        sem = asyncio.Semaphore(max(1, cfg.http_probe_concurrency))

        async def _one(host: str):
            async with sem:
                return await probe_http_service(host, scope=list(job.scope))

        return await _gather_dicts([_one(h) for h in http_targets])

    http_probes = await run_stage(client, cfg, job, "http", _http)
    assert http_probes is not None
    stats["http"] = len(http_probes)

    # --- STAGE 4: ports (optional) ---------------------------------------
    if not _tool("naabu"):
        await client.progress(job.scan_id, "ports", "skipped", error="naabu not installed")
    else:
        port_targets = [d["hostname"] for d in dns_records if d.get("hostname")]

        async def _ports():
            return await run_naabu_batch(
                port_targets,
                top_ports=limits.max_ports,
                timeout=limits.stage_timeout_seconds,
                concurrency=PORTS_STAGE_CONCURRENCY,
            )

        open_ports = await run_stage(client, cfg, job, "ports", _ports, optional=True)
        stats["ports"] = len(open_ports or [])

    # --- STAGE 5: tls (optional) -----------------------------------------
    if not _tool("sslyze"):
        await client.progress(job.scan_id, "tls", "skipped", error="sslyze not installed")
    else:
        tls_targets = [
            h["hostname"] for h in http_probes
            if h.get("http_status") and str(h.get("url", "")).startswith("https")
            and host_in_scope(h["hostname"], job.scope)
        ][:TLS_HOST_CAP]

        async def _tls():
            return await run_sslyze_batch(
                tls_targets,
                timeout=limits.stage_timeout_seconds,
                concurrency=TLS_STAGE_CONCURRENCY,
            )

        tls_profiles = await run_stage(client, cfg, job, "tls", _tls, optional=True)
        stats["tls"] = len(tls_profiles or [])

    # --- STAGE 6: nuclei (optional, §23 + OOM guardrails) ----------------
    if not _tool("nuclei"):
        await client.progress(job.scan_id, "nuclei", "skipped", error="nuclei not installed")
    else:
        active_hosts = [
            h["hostname"] for h in http_probes
            if h.get("http_status") and h.get("hostname")
            and host_in_scope(h["hostname"], job.scope)
        ][:limits.nuclei_max_hosts]

        async def _nuclei():
            findings = await run_nuclei_batch(
                active_hosts,
                concurrency=limits.nuclei_concurrency,
                timeout=limits.stage_timeout_seconds,
            )
            for nf in findings:
                if not nf.get("_hostname"):
                    nf["_hostname"] = nf.get("evidence", {}).get("host") or job.target
            return findings

        nuclei_findings = await run_stage(client, cfg, job, "nuclei", _nuclei, optional=True)
        stats["nuclei"] = len(nuclei_findings or [])

        if nuclei_findings is not None:
            # Re-submit the nuclei observation with the attempted host list:
            # finalize gates baseline resolution on real coverage, so
            # "not evaluated" is distinguishable from "no findings".
            try:
                await client.observations(job.scan_id, "nuclei", {
                    "nuclei_findings": nuclei_findings,
                    "attempted_hosts": active_hosts,
                })
            except JobLost:
                raise
            except CoreError as e:
                logger.debug("scan=%s nuclei observation resubmit failed (transient): %s", job.scan_id, e)

    return stats


async def _safe_fail(client: CoreClient, job: ScanJob, stage: Optional[str], error: str) -> None:
    try:
        await client.fail(job.scan_id, stage, error)
    except JobLost:
        logger.warning("scan=%s already revoked; fail report dropped", job.scan_id)
    except CoreError as e:
        logger.warning("scan=%s fail report not delivered: %s", job.scan_id, e)


async def run_daemon(cfg, once: bool = False) -> int:
    """Poll → claim → execute → complete/fail. --once: one claim max."""
    client = CoreClient(cfg)
    logger.info("scanner id=%s polling %s (once=%s, interval=%ss)",
                cfg.scanner_id, cfg.core_url, once, cfg.poll_interval_seconds)
    exit_code = 0
    try:
        while True:
            try:
                job = await client.claim()
            except CoreError as e:
                logger.warning("claim failed: %s", e)
                if once:
                    return 1
                await asyncio.sleep(cfg.poll_interval_seconds + random.uniform(0, 3))
                continue

            if job is None:
                if once:
                    logger.info("queue empty")
                    return 0
                await asyncio.sleep(cfg.poll_interval_seconds + random.uniform(0, 3))
                continue

            logger.info("scan=%s claimed target=%s scope=%s lease=%s",
                        job.scan_id, job.target, job.scope, job.lease_expires_at)
            try:
                stats = await execute_job(client, cfg, job)
                await client.complete(job.scan_id, stats)
                logger.info("scan=%s recon complete: %s", job.scan_id, stats)
            except JobLost:
                logger.warning("scan=%s lease lost — aborting attempt", job.scan_id)
            except ScopeError as e:
                logger.error("scan=%s scope violation: %s", job.scan_id, e)
                await _safe_fail(client, job, "scope", str(e))
            except JobAborted as e:
                logger.error("scan=%s aborted at stage=%s: %s", job.scan_id, e.stage, e.error)
                await _safe_fail(client, job, e.stage, e.error)
            except Exception as e:
                logger.exception("scan=%s crashed", job.scan_id)
                await _safe_fail(client, job, None, str(e))

            if once:
                return exit_code
            await asyncio.sleep(1)
    finally:
        await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Cyphward scanner worker")
    parser.add_argument("--once", action="store_true",
                        help="claim at most one job, then exit")
    parser.add_argument("--poll-interval", type=int, default=None,
                        help="override SCANNER_POLL_INTERVAL_SECONDS")
    args = parser.parse_args()

    cfg = load_config()
    if args.poll_interval:
        cfg = dataclasses.replace(cfg, poll_interval_seconds=args.poll_interval)

    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(asyncio.run(run_daemon(cfg, once=args.once)))


if __name__ == "__main__":
    main()
