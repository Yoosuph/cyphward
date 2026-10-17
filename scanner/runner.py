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
import os
import dataclasses
import logging
import random
import shutil
import time
from typing import Any, Dict, List, Optional

from scanner.client import CoreClient, CoreError, JobLost
from scanner.config import load_config
from scanner.scope import ScopeError, assert_job_in_scope

from backend.app.scanner.discovery import discover_subdomains_with_health
from backend.app.scanner.dns_resolver import resolve_host_dns
from backend.app.scanner.http_probe import probe_http_service
from backend.app.scanner.naabu_runner import run_naabu_batch
from backend.app.scanner.sslyze_runner import run_sslyze_batch
from backend.app.scanner.nuclei_runner import run_nuclei_batch
from backend.app.scanner.privacy_probe import run_privacy_batch
from backend.app.scanner.tool_results import ToolBatchResult
from backend.app.scanner.dns_coverage import collect_dns_results
from shared.contracts import PRIVACY_CAPABILITY, ScanJob
from shared.scan_scope import select_targets
from shared.scan_budget import ReconBudget, gather_with_deadline
from backend.app.scanner.recon_policy import stage_plan, evaluate_stage, collect_http_results

logger = logging.getLogger("cyphward.scanner")

PORTS_STAGE_CONCURRENCY = 4
TLS_STAGE_CONCURRENCY = 2

# Stage → scan_results payload key (must match Core's finalize loader).
OBSERVATION_KEY = {
    "discovery": "discovered_hosts",
    "dns": "dns_records",
    "http": "http_probes",
    "privacy": "privacy_observations",
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
    with contextlib.suppress(asyncio.CancelledError, asyncio.InvalidStateError, JobLost):
        await beat


async def _heartbeat(
    client: CoreClient,
    job: ScanJob,
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
            await client.progress(job, stage, "running")
        except JobLost:
            logger.warning("scan=%s lease lost during heartbeat (stage=%s)", job.scan_id, stage)
            raise
        except CoreError as e:
            logger.debug("scan=%s heartbeat failed (transient): %s", job.scan_id, e)


async def _leased_result(factory, beat: asyncio.Task):
    """Stop active recon as soon as the heartbeat reports a revoked lease."""
    work = asyncio.create_task(factory())
    try:
        done, _ = await asyncio.wait({work, beat}, return_when=asyncio.FIRST_COMPLETED)
        if beat in done:
            await beat
            raise JobLost("Lease heartbeat stopped before the stage finished")
        return await work
    finally:
        if not work.done():
            work.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await work
        elif not work.cancelled():
            # Retrieve any simultaneous work error when lease loss won the
            # race, preventing an unhandled-task warning during cleanup.
            work.exception()


async def run_stage(
    client: CoreClient,
    cfg,
    job: ScanJob,
    stage: str,
    coro_factory,
    *,
    optional: bool = False,
    plan=None,
    budget=None,
) -> Optional[List[Any]]:
    """
    Run one recon stage with progress + heartbeat. Returns the result list,
    or None for optional stages that were skipped/failed (scan continues).
    """
    t0 = time.time()
    await client.progress(job, stage, "running")

    stop = asyncio.Event()
    beat = asyncio.create_task(
        _heartbeat(client, job, stage, max(5.0, min(30.0, cfg.heartbeat_seconds)), stop)
    )
    try:
        work = (lambda: evaluate_stage(budget, plan, coro_factory)) if plan is not None else coro_factory
        result = await _leased_result(work, beat)
    except asyncio.CancelledError:
        await _stop_beat(stop, beat)
        raise
    except JobLost:
        await _stop_beat(stop, beat)
        raise
    except Exception as exc:
        await _stop_beat(stop, beat)
        if optional:
            logger.warning("scan=%s stage=%s failed (continuing): %s", job.scan_id, stage, exc)
            await client.observations(job, stage, {
                OBSERVATION_KEY[stage]: [], "attempted_hosts": plan["selected_hosts"] if plan else [],
                "successful_hosts": [], "failed_hosts": {host: str(exc)[:300] for host in plan["selected_hosts"]} if plan else {},
                **({"stage_plan": plan, "omitted_hosts": plan["omitted_hosts"],
                    "execution_budget": budget.payload()} if plan else {}),
            })
            await client.progress(job, stage, "failed",
                                  duration_ms=_ms(t0), error=str(exc)[:500])
            return None
        raise JobAborted(stage, str(exc)) from exc
    else:
        await _stop_beat(stop, beat)

    if not isinstance(result, list):
        if optional:
            await client.observations(job, stage, {
                OBSERVATION_KEY[stage]: [], "attempted_hosts": [],
                "successful_hosts": [], "failed_hosts": {},
            })
            await client.progress(job, stage, "failed", error="Tool returned an invalid result type")
            return None
        raise JobAborted(stage, "Tool returned an invalid result type")

    batch = result if isinstance(result, ToolBatchResult) else None
    if result or batch is not None:
        await client.observations(job, stage, {
            OBSERVATION_KEY[stage]: result,
            **(batch.coverage() if batch is not None else {}),
        })
    state = batch.progress() if batch is not None else {"status": "completed"}
    await client.progress(job, stage, state["status"],
                          items=len(result), duration_ms=_ms(t0), error=state.get("error"))
    return result


async def run_discovery_stage(client: CoreClient, cfg, job: ScanJob, budget=None) -> List[str]:
    """Stage 1 (fatal): passive discovery + health + seed union.

    Not via run_stage — it coerces stage results to lists, but discovery
    yields (hosts, sources_failed). Progress, heartbeat and the observation
    are handled explicitly here instead. Returns the selected host list;
    raises on total failure. Persists the pre-selection
    discovery inventory and explicit omission reasons separately.
    """
    _t0 = time.time()
    await client.progress(job, "discovery", "running")
    _stop = asyncio.Event()
    _beat = asyncio.create_task(
        _heartbeat(client, job, "discovery", max(5.0, min(30.0, cfg.heartbeat_seconds)), _stop))
    try:
        work = lambda: discover_subdomains_with_health(job.target)
        hosts_raw, sources_failed = await _leased_result((lambda: budget.run(work)) if budget else work, _beat)
    except BaseException:
        await _stop_beat(_stop, _beat)
        raise
    else:
        await _stop_beat(_stop, _beat)
    # Owner-registered hosts ride along (scope filter below still applies).
    if getattr(job, "seed_hosts", None):
        seeds = {h.strip().lower() for h in job.seed_hosts if h}
        new_seeds = seeds - set(hosts_raw)
        if new_seeds:
            hosts_raw = sorted(set(hosts_raw) | seeds)
            logger.info("scan=%s discovery: +%d registered seed hosts",
                        job.scan_id, len(new_seeds))
    if sources_failed:
        logger.warning("scan=%s discovery sources failed: %s", job.scan_id, sources_failed)
    selection = select_targets(job.target, job.scope, hosts_raw, job.seed_hosts,
                               max_hosts=job.limits.max_hosts,
                               dns_max_hosts=job.limits.dns_max_hosts)
    await client.observations(job, "discovery",
                              {"discovered_hosts": hosts_raw,
                               "sources_failed": sources_failed,
                               "target_selection": selection.payload(),
                               **({"execution_budget": budget.payload()} if budget else {})})
    await client.progress(job, "discovery", "completed",
                          items=len(hosts_raw), duration_ms=_ms(_t0))
    return selection.selected_hosts


async def execute_job(client: CoreClient, cfg, job: ScanJob) -> Dict[str, Any]:
    """Run all recon stages for one claimed job (sequential, §16)."""
    assert_job_in_scope(job)
    limits = job.limits

    stats: Dict[str, Any] = {}

    budget = ReconBudget(limits.recon_timeout_seconds, limits.stage_timeout_seconds)
    discovered = await run_discovery_stage(client, cfg, job, budget)
    stats["discovered"] = len(discovered)

    dns_plan = stage_plan("dns", discovered, job.scope)
    async def _dns():
        results = await gather_with_deadline([resolve_host_dns(host) for host in dns_plan["selected_hosts"]])
        return collect_dns_results(dns_plan["selected_hosts"], results)
    dns_records = await run_stage(client, cfg, job, "dns", _dns, plan=dns_plan, budget=budget)
    assert dns_records is not None
    stats["dns"] = len(dns_records)

    http_plan = stage_plan("http", discovered, job.scope, dns_records)
    async def _http():
        sem = asyncio.Semaphore(max(1, cfg.http_probe_concurrency))
        async def _one(host):
            async with sem:
                return await probe_http_service(host, scope=list(job.scope))
        results = await gather_with_deadline([_one(host) for host in http_plan["selected_hosts"]])
        return collect_http_results(http_plan["selected_hosts"], results)
    http_probes = await run_stage(client, cfg, job, "http", _http, plan=http_plan, budget=budget)
    assert http_probes is not None
    stats["http"] = len(http_probes)


    ports_plan = stage_plan("ports", discovered, job.scope, dns_records, available=_tool("naabu"))
    async def _ports():
        return await run_naabu_batch(ports_plan["selected_hosts"], top_ports=limits.max_ports,
                                     timeout=limits.stage_timeout_seconds, concurrency=PORTS_STAGE_CONCURRENCY)
    ports = await run_stage(client, cfg, job, "ports", _ports, optional=True, plan=ports_plan, budget=budget)
    stats["ports"] = len(ports or [])

    tls_plan = stage_plan("tls", discovered, job.scope, dns_records, http_probes,
                          cap=limits.tls_max_hosts, available=_tool("sslyze"))
    async def _tls():
        return await run_sslyze_batch(tls_plan["selected_hosts"], timeout=limits.stage_timeout_seconds,
                                      concurrency=TLS_STAGE_CONCURRENCY)
    tls = await run_stage(client, cfg, job, "tls", _tls, optional=True, plan=tls_plan, budget=budget)
    stats["tls"] = len(tls or [])

    nuclei_tier = os.getenv("SCANNER_NUCLEI_TIER", "daily")
    nuclei_plan = stage_plan("nuclei", discovered, job.scope, dns_records, http_probes,
                             cap=limits.nuclei_max_hosts, available=_tool("nuclei"))
    async def _nuclei():
        findings = await run_nuclei_batch(nuclei_plan["selected_hosts"], concurrency=limits.nuclei_concurrency,
                                         timeout=limits.stage_timeout_seconds, tier=nuclei_tier)
        for finding in findings:
            if not finding.get("_hostname"):
                finding["_hostname"] = finding.get("evidence", {}).get("host") or job.target
        return findings
    nuclei = await run_stage(client, cfg, job, "nuclei", _nuclei, optional=True, plan=nuclei_plan, budget=budget)
    stats["nuclei"] = len(nuclei or [])

    # Optional static privacy checks, last so they only use leftover budget, and
    # only when the API accepts the stage (an older API would reject it).
    supports = getattr(client, "supports", None)
    if callable(supports) and supports(PRIVACY_CAPABILITY):
        privacy_plan = stage_plan("privacy", discovered, job.scope, dns_records, http_probes,
                                  cap=limits.privacy_max_hosts)
        async def _privacy():
            return await run_privacy_batch(privacy_plan["selected_hosts"], list(job.scope),
                                           max_pages=limits.privacy_max_pages)
        privacy = await run_stage(client, cfg, job, "privacy", _privacy, optional=True,
                                  plan=privacy_plan, budget=budget)
        stats["privacy"] = len(privacy or [])

    return stats


async def _safe_fail(client: CoreClient, job: ScanJob, stage: Optional[str], error: str) -> None:
    try:
        await client.fail(job, stage, error)
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
                await client.complete(job, stats)
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
