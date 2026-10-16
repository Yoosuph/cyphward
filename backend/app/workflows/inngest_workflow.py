"""
Cyphward Scan Pipeline & Asynchronous Execution Engine

Two-phase pipeline (spec §14/§21):

  Phase 1 — recon:      discovery → dns → http → ports → tls → nuclei
                        Writes raw observations to scan_results (stage rows).
                        Runs either in-process (SCANNER_MODE=local) or on the
                        Azure scanner worker via the scanner_jobs API (remote).

  Phase 2 — finalize:   security_checks → inventory → normalization → scoring
                        → AI analysis. Always runs in Core: loads observations
                        from scan_results, normalizes/diffs/risk-scores them.
                        Invoked by execute_scan_pipeline (local mode) or by
                        the /scanner/jobs/{id}/complete handler (remote mode).

Also hosts the daily scheduled-scan cron for verified domains.
"""
import asyncio
import json
import logging
import shutil
import socket
import secrets
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List

import inngest

from backend.app.core.config import (
    SCANNER_MODE,
    CORE_AI_TIMEOUT_SECONDS,
    SCANNER_LEASE_SECONDS,
    SCANNER_NUCLEI_CONCURRENCY,
    SCANNER_NUCLEI_MAX_HOSTS,
    SCANNER_MAX_PORTS,
    SCANNER_MAX_HOSTS,
    SCANNER_DNS_MAX_HOSTS,
    SCANNER_STAGE_TIMEOUT_SECONDS,
    SCANNER_RECON_TIMEOUT_SECONDS,
    SCANNER_TLS_MAX_HOSTS,
)
from backend.app.core.database import execute_one, execute_query, execute_many
from backend.app.core.auth import log_audit
from backend.app.core import scan_execution as execution
from backend.app.core.execution_fence import ClaimLost, ExecutionClaim, require_execution
from backend.app.core.scan_admission import admit_scan
from backend.app.core.cron_claim import (
    DAILY_SCAN_CRON_NAME,
    claim_cron_run,
    complete_cron_run,
    release_cron_run,
)
from backend.app.scanner.discovery import discover_subdomains, discover_subdomains_with_health
from backend.app.scanner.dns_resolver import resolve_host_dns
from backend.app.scanner.http_probe import probe_http_service
from backend.app.scanner.naabu_runner import run_naabu_batch
from backend.app.scanner.sslyze_runner import run_sslyze_batch
from backend.app.scanner.security_checks import run_security_checks
from backend.app.scanner.nuclei_runner import run_nuclei_batch
from backend.app.scanner.privacy_probe import run_privacy_batch
from backend.app.scanner.normalizer import normalize_findings
from backend.app.scanner.detectors import classify_detector, detector_key
from backend.app.scanner.dns_coverage import dns_finding_evaluated, collect_dns_results
from backend.app.scanner.tool_results import ToolBatchResult
from backend.app.risk.engine import compute_risk_score, SCORE_MODEL, SCORE_SCOPE
from backend.app.risk.coverage import assessment_coverage
from backend.app.risk.domain_coverage import org_domain_coverage
from backend.app.compliance.scan_evidence import evidence_for_scan
from backend.app.ai.factory import get_ai_provider
from backend.app.services.notifications import notify
from backend.app.services.mailer import send_email_async
from shared.contracts import STAGE_SECURITY_CHECKS, empty_stage_progress, ScanJobLimits
from shared.scan_scope import select_targets
from shared.scan_budget import ReconBudget, gather_with_deadline
from backend.app.scanner.recon_policy import THIRD_PARTY_SERVICE, stage_plan, evaluate_stage, collect_http_results

import os

logger = logging.getLogger("cyphward.scan")


def checker_view_for_third_party(probe: Any) -> Dict[str, Any]:
    """What the security checker may read from a host handed off to a third party.

    Only the certificate observed on the customer's own hostname stays; the
    HTTP response (status, headers, banners) is the provider's, so the
    response-derived checks see no response and raise nothing.
    """
    probe = probe if isinstance(probe, dict) else {}
    return {"hostname": probe.get("hostname"), "http_status": None, "security_headers": {}, "raw_headers": {},
            "server_header": None, "powered_by_header": None, "tls_info": probe.get("tls_info") or {}}

is_prod = os.getenv("INNGEST_IS_PRODUCTION", "false").lower() in ("true", "1")
signing_key = os.getenv("INNGEST_SIGNING_KEY")
event_key = os.getenv("INNGEST_EVENT_KEY")
inngest_client = inngest.Inngest(
    app_id="cyphward",
    is_production=is_prod if signing_key else False,
    signing_key=signing_key or None,
    event_key=event_key or None,
)

# Port-scan concurrency within the ports stage (one stage at a time, §16).
PORTS_STAGE_CONCURRENCY = 4
TLS_STAGE_CONCURRENCY = 2


def _tool_available(binary: str) -> bool:
    return shutil.which(binary) is not None


def _scan_status(scan_id: str) -> str:
    """Current status of a scan row ('' when the row no longer exists)."""
    row = execute_one("SELECT status FROM scans WHERE id = %s", (scan_id,))
    return (row or {}).get("status") or ""


def _still_running(scan_id: str) -> bool:
    """Boundary check: pipeline work continues only while status='running'."""
    return _scan_status(scan_id) == "running"


def _store_observation(scan_id: str, stage: str, data: Any) -> None:
    execution.store_observation(require_execution(scan_id), stage, data)


def _save_progress(scan_id: str, progress: Dict[str, Any], current_stage: str = None) -> None:
    """Fenced progress write — no-ops once the scan is cancelled/failed."""
    require_execution(scan_id)
    if current_stage:
        execute_query(
            "UPDATE scans SET stage_progress = %s::jsonb, current_stage = %s WHERE id = %s AND status = 'running'",
            (json.dumps(progress), current_stage, scan_id),
        )
    else:
        execute_query(
            "UPDATE scans SET stage_progress = %s::jsonb WHERE id = %s AND status = 'running'",
            (json.dumps(progress), scan_id),
        )


def _load_observations(scan_id: str) -> Dict[str, Any]:
    """Stage → raw_data map (later rows win; worker replaces per stage)."""
    claim = require_execution(scan_id)
    rows = execute_query(
        "SELECT stage, raw_data FROM scan_results WHERE scan_id = %s AND attempt_generation = %s ORDER BY created_at ASC",
        (scan_id, claim.observation_generation),
    ) or []
    observations: Dict[str, Any] = {}
    for row in rows:
        observations[row["stage"]] = row["raw_data"]
    return observations


async def _email_org_members(org_id: str, subject: str, html: str, text: str) -> None:
    """Best-effort email fanout to all org members (critical / reopened only)."""
    try:
        recipients = execute_query(
            """
            SELECT DISTINCT p.email, p.full_name
            FROM organization_members m
            JOIN profiles p ON p.id = m.user_id
            WHERE m.org_id = %s AND p.email IS NOT NULL AND p.email <> ''
            """,
            (org_id,),
        ) or []
    except Exception:
        return

    for rec in recipients:
        try:
            await send_email_async(
                rec["email"],
                subject,
                html,
                text,
                rec.get("full_name"),
                kind="alerts",
            )
        except Exception:
            continue


def _finding_email_html(
    org_name: str,
    title: str,
    severity: str,
    description: str,
    remediation: str,
    hostname: str,
    is_reopen: bool = False,
) -> str:
    verb = "Reopened" if is_reopen else "New"
    color = "#E5532B" if severity == "critical" else "#F97316"
    return f"""<!DOCTYPE html>
<html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#0A0907; color:#F5F2EB; padding:24px;">
  <div style="max-width:560px;margin:0 auto;background:#12100C;border:1px solid #2D271F;border-radius:8px;padding:24px;">
    <div style="font-family:monospace;font-size:12px;letter-spacing:2px;color:#E5532B;">CYPHWARD · {verb.upper()} {severity.upper()} FINDING</div>
    <h1 style="font-size:18px;margin:16px 0 8px;">{title}</h1>
    <p style="font-size:13px;color:#A8A095;margin:0 0 12px;">{org_name} · {hostname}</p>
    <p style="font-size:14px;line-height:1.6;color:#DDD7CD;">{description}</p>
    <p style="font-size:13px;color:#E5532B;"><strong>Remediation:</strong> {remediation}</p>
    <p style="font-size:12px;color:#8C8477;margin-top:20px;">Sign in to Cyphward to triage this finding in the findings workspace.</p>
  </div>
</body></html>"""


# ===========================================================================
# PHASE 1 — RECON (local fallback; the remote worker performs the same stages
# via its own runner and submits observations to Core over HTTPS).
# ===========================================================================
def _registered_hosts(org_id: str, domain_id: str) -> List[str]:
    """Owner-registered hostnames for a domain (scan-scope registration).

    Probed every scan even when passive discovery misses them. Returns
    normalized hostnames; callers union them into discovery results.
    """
    rows = execute_query(
        "SELECT hostname FROM monitored_hosts WHERE org_id = %s AND domain_id = %s",
        (org_id, domain_id),
    )
    return sorted({str(r["hostname"]).strip().lower() for r in (rows or []) if r.get("hostname")})


async def _execute_recon_local_owned(scan_id: str) -> Dict[str, Any]:
    """
    Run recon stages in-process: discovery → dns → http → ports → tls → nuclei.
    Writes one observation row per stage. Foundational stages (discovery/dns/
    http) fail the scan on error; ports/tls/nuclei degrade gracefully (§23).
    """
    require_execution(scan_id)
    scan = execute_one("""
        SELECT s.*, d.domain, d.org_id
        FROM scans s
        JOIN domains d ON s.domain_id = d.id
        WHERE s.id = %s
    """, (scan_id,))

    if not scan:
        raise ValueError(f"Scan {scan_id} not found.")

    domain = scan["domain"]

    progress = empty_stage_progress()
    progress["discovery"]["status"] = "running"
    claimed = execute_one("""
        UPDATE scans
        SET status = 'running', current_stage = 'discovery', started_at = now(), stage_progress = %s::jsonb
        WHERE id = %s AND status IN ('queued', 'running')
        RETURNING id
    """, (json.dumps(progress), scan_id))
    if not claimed:
        # Cancelled (or otherwise terminal) between dispatch and execution —
        # never resurrect the scan; run no stages.
        logger.info("scan=%s recon skipped: status no longer dispatchable", scan_id)
        return {"scan_id": scan_id, "cancelled": True}

    try:
        # ---------------------------------------------------------------------
        # STAGE 1: Passive Subdomain Discovery
        # ---------------------------------------------------------------------
        t0 = time.time()
        limits = ScanJobLimits(max_hosts=SCANNER_MAX_HOSTS, dns_max_hosts=SCANNER_DNS_MAX_HOSTS,
                               max_ports=SCANNER_MAX_PORTS, stage_timeout_seconds=SCANNER_STAGE_TIMEOUT_SECONDS,
                               recon_timeout_seconds=SCANNER_RECON_TIMEOUT_SECONDS, tls_max_hosts=SCANNER_TLS_MAX_HOSTS,
                               nuclei_max_hosts=SCANNER_NUCLEI_MAX_HOSTS, nuclei_concurrency=SCANNER_NUCLEI_CONCURRENCY)
        budget = ReconBudget(limits.recon_timeout_seconds, limits.stage_timeout_seconds)
        discovered_hosts, sources_failed = await budget.run(lambda: discover_subdomains_with_health(domain))
        d_dur = int((time.time() - t0) * 1000)
        if sources_failed:
            logger.warning("scan=%s discovery sources failed: %s", scan_id, sources_failed)

        # Owner-registered hosts ride along (scope-enforced at registration).
        registered = _registered_hosts(str(scan["org_id"]), str(scan["domain_id"]))
        if registered:
            discovered_hosts = sorted(set(discovered_hosts) | set(registered))

        selection = select_targets(domain, [domain], discovered_hosts, registered,
                                   max_hosts=limits.max_hosts,
                                   dns_max_hosts=limits.dns_max_hosts)

        progress["discovery"] = {"status": "completed", "items": len(discovered_hosts), "duration_ms": d_dur}
        if not _still_running(scan_id):
            return {"scan_id": scan_id, "cancelled": True}
        progress["dns"]["status"] = "running"
        _save_progress(scan_id, progress, "dns")
        _store_observation(scan_id, "discovery", {"discovered_hosts": discovered_hosts,
                                                  "sources_failed": sources_failed,
                                                  "target_selection": selection.payload(),
                                                  "execution_budget": budget.payload()})

        async def local_stage(stage, plan, factory, *, optional=False):
            started = time.monotonic()
            progress[stage] = {"status": "running", "items": 0, "duration_ms": 0}
            _save_progress(scan_id, progress, stage)
            try:
                batch = await evaluate_stage(budget, plan, factory)
            except ClaimLost:
                raise
            except Exception as error:
                if not optional:
                    raise
                batch = ToolBatchResult([], plan["selected_hosts"], [],
                                        {host: str(error)[:300] for host in plan["selected_hosts"]})
                batch.stage_plan, batch.omitted_hosts = plan, plan["omitted_hosts"]
                batch.execution_budget = budget.payload()
            progress[stage] = {**batch.progress(), "items": len(batch),
                               "duration_ms": int((time.monotonic() - started) * 1000)}
            keys = {"dns": "dns_records", "http": "http_probes", "privacy": "privacy_observations",
                    "ports": "open_ports", "tls": "tls_profiles", "nuclei": "nuclei_findings"}
            _store_observation(scan_id, stage, {keys[stage]: batch, **batch.coverage()})
            _save_progress(scan_id, progress, stage)
            return batch

        hosts = selection.selected_hosts
        dns_plan = stage_plan("dns", hosts, [domain])
        async def dns_work():
            results = await gather_with_deadline([resolve_host_dns(host) for host in dns_plan["selected_hosts"]])
            return collect_dns_results(dns_plan["selected_hosts"], results)
        valid_dns = await local_stage("dns", dns_plan, dns_work)

        http_plan = stage_plan("http", hosts, [domain], valid_dns)
        async def http_work():
            semaphore = asyncio.Semaphore(25)
            async def one(host):
                async with semaphore:
                    return await probe_http_service(host, scope=[domain])
            results = await gather_with_deadline([one(host) for host in http_plan["selected_hosts"]])
            return collect_http_results(http_plan["selected_hosts"], results)
        valid_http = await local_stage("http", http_plan, http_work)

        ports_plan = stage_plan("ports", hosts, [domain], valid_dns, available=_tool_available("naabu"))
        async def ports_work():
            return await run_naabu_batch(ports_plan["selected_hosts"], top_ports=limits.max_ports,
                                         timeout=limits.stage_timeout_seconds, concurrency=PORTS_STAGE_CONCURRENCY)
        await local_stage("ports", ports_plan, ports_work, optional=True)

        tls_plan = stage_plan("tls", hosts, [domain], valid_dns, valid_http,
                              cap=limits.tls_max_hosts, available=_tool_available("sslyze"))
        async def tls_work():
            return await run_sslyze_batch(tls_plan["selected_hosts"], timeout=limits.stage_timeout_seconds,
                                          concurrency=TLS_STAGE_CONCURRENCY)
        await local_stage("tls", tls_plan, tls_work, optional=True)

        nuclei_plan = stage_plan("nuclei", hosts, [domain], valid_dns, valid_http,
                                 cap=limits.nuclei_max_hosts, available=_tool_available("nuclei"))
        async def nuclei_work():
            findings = await run_nuclei_batch(nuclei_plan["selected_hosts"], concurrency=limits.nuclei_concurrency,
                                             timeout=limits.stage_timeout_seconds)
            for finding in findings:
                if not finding.get("_hostname"):
                    finding["_hostname"] = finding.get("evidence", {}).get("host") or domain
            return findings
        await local_stage("nuclei", nuclei_plan, nuclei_work, optional=True)

        # Optional static privacy checks, last so they only use leftover budget.
        privacy_plan = stage_plan("privacy", hosts, [domain], valid_dns, valid_http, cap=limits.privacy_max_hosts)
        async def privacy_work():
            return await run_privacy_batch(privacy_plan["selected_hosts"], [domain],
                                           max_pages=limits.privacy_max_pages)
        await local_stage("privacy", privacy_plan, privacy_work, optional=True)
        return {"scan_id": scan_id, "discovered": len(hosts), "dns": len(valid_dns), "http": len(valid_http),
                **{stage: progress[stage].get("items", 0) for stage in ("ports", "tls", "nuclei")}}

    except ClaimLost:
        raise
    except Exception as exc:
        progress["error"] = str(exc)
        execution.fail_claim(require_execution(scan_id), str(exc), progress)
        raise


# ===========================================================================
# PHASE 2 — FINALIZE (always Core). Reads observations produced by Phase 1 —
# in-process (local mode) or by the scanner worker (remote mode).
# ===========================================================================
async def _finalize_scan_owned(scan_id: str) -> Dict[str, Any]:
    """
    Core-side finalize: security checks → asset inventory → normalization/
    baseline diff → 0-100 risk scoring → AI analysis. Loads recon observations
    from scan_results, so it is independent of where Phase 1 ran.
    """
    require_execution(scan_id)
    scan = execute_one("""
        SELECT s.*, d.domain, d.org_id
        FROM scans s
        JOIN domains d ON s.domain_id = d.id
        WHERE s.id = %s
    """, (scan_id,))

    if not scan:
        raise ValueError(f"Scan {scan_id} not found.")

    org_id = scan["org_id"]
    domain_id = scan["domain_id"]
    domain = scan["domain"]

    org_row = execute_one("SELECT name FROM organizations WHERE id = %s", (org_id,))
    org_name = org_row["name"] if org_row else "Your organization"

    # Continue the worker's stage_progress (recon rows already completed).
    progress: Dict[str, Any] = scan.get("stage_progress") or {}
    if not isinstance(progress, dict):
        progress = {}
    for key, val in empty_stage_progress().items():
        progress.setdefault(key, val)

    observations = _load_observations(scan_id)
    discovered_hosts = (observations.get("discovery") or {}).get("discovered_hosts") or []
    # Belt-and-braces: owner-registered hosts apply even when the recon
    # side (older worker, pre-union scans) never saw them.
    registered_hosts = _registered_hosts(str(org_id), str(domain_id))
    for h in registered_hosts:
        if h not in discovered_hosts:
            discovered_hosts.append(h)
    discovered_hosts = sorted(set(discovered_hosts))
    valid_dns = (observations.get("dns") or {}).get("dns_records") or []
    valid_http = (observations.get("http") or {}).get("http_probes") or []
    nuclei_findings = (observations.get("nuclei") or {}).get("nuclei_findings") or []

    progress[STAGE_SECURITY_CHECKS]["status"] = "running"
    claimed = execute_one("""
        UPDATE scans
        SET status = 'running', current_stage = %s, stage_progress = %s::jsonb
        WHERE id = %s AND status IN ('queued', 'running')
        RETURNING id
    """, (STAGE_SECURITY_CHECKS, json.dumps(progress), scan_id))
    if not claimed:
        # Cancelled before finalize started — never resurrect or finalize it.
        status = _scan_status(scan_id)
        logger.info("scan=%s finalize skipped: status=%s", scan_id, status or "missing")
        return {"scan_id": scan_id, "status": status}

    email_jobs: List[Dict[str, Any]] = []

    try:
        if not _still_running(scan_id):
            return {"scan_id": scan_id, "status": _scan_status(scan_id)}

        # ---------------------------------------------------------------------
        # Asset inventory (per-scan targets + org asset upsert)
        # ---------------------------------------------------------------------
        dns_by_host = {d["hostname"]: d for d in valid_dns}
        http_by_host = {h["hostname"]: h for h in valid_http}
        # Hosts the HTTP stage handed off to a third party (e.g. a mail
        # provider's click-tracking host redirecting to its own domain). Their
        # response belongs to the provider, so response-derived checks
        # (headers, banners, robots.txt) are not the customer's findings.
        third_party_hosts = {
            host for host, reason in ((observations.get("http") or {}).get("omitted_hosts") or {}).items()
            if reason == THIRD_PARTY_SERVICE
        }

        target_rows = []
        for hname in discovered_hosts:
            dns_item = dns_by_host.get(hname)
            http_item = http_by_host.get(hname)
            if dns_item:
                t_status = "active" if (http_item and http_item.get("http_status")) or dns_item.get("primary_ip") else "discovered"
                t_ip = dns_item.get("primary_ip")
            else:
                t_status = "discovered"
                t_ip = None
            target_rows.append((
                scan_id, org_id, hname, t_ip, t_status,
                json.dumps({
                    "has_dns": bool(dns_item),
                    "http_status": (http_item or {}).get("http_status"),
                }),
            ))
        if target_rows:
            execute_many("""
                INSERT INTO scan_targets (scan_id, org_id, hostname, ip_address, status, last_seen, meta)
                VALUES (%s, %s, %s, %s, %s, now(), %s::jsonb)
                ON CONFLICT (scan_id, hostname) DO UPDATE SET
                    ip_address = COALESCE(EXCLUDED.ip_address, scan_targets.ip_address),
                    status = EXCLUDED.status,
                    last_seen = now(),
                    meta = EXCLUDED.meta
            """, target_rows)

        asset_id_map = {}
        for dns_item in valid_dns:
            hname = dns_item["hostname"]
            ip = dns_item.get("primary_ip")
            matched_http = http_by_host.get(hname, {})
            http_status = matched_http.get("http_status")
            techs = matched_http.get("technologies", [])
            tls = matched_http.get("tls_info", {})
            records = dns_item.get("records", {})

            atype = "Web Endpoint"
            if "mail" in hname or records.get("MX"):
                atype = "Mail Server"
            elif "api" in hname:
                atype = "API Gateway"
            elif "vpn" in hname:
                atype = "VPN Gateway"

            prior_asset = execute_one(
                "SELECT id FROM assets WHERE org_id = %s AND hostname = %s",
                (org_id, hname),
            )

            # 'active' only when we observed it responding or at least
            # resolved it; a name with neither is inventory, not a live host.
            asset_status = "active" if (http_status or ip) else "discovered"
            res = execute_one("""
                INSERT INTO assets (org_id, domain_id, hostname, ip_address, asset_type, status, http_status, technologies, tls_info, dns_records, last_seen)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, now())
                ON CONFLICT (org_id, hostname)
                DO UPDATE SET
                    ip_address = EXCLUDED.ip_address,
                    http_status = EXCLUDED.http_status,
                    technologies = EXCLUDED.technologies,
                    tls_info = EXCLUDED.tls_info,
                    dns_records = EXCLUDED.dns_records,
                    last_seen = now()
                RETURNING id;
            """, (org_id, domain_id, hname, ip, atype, asset_status, http_status, json.dumps(techs), json.dumps(tls), json.dumps(records)))

            if res:
                asset_id_map[hname] = res["id"]
                if not prior_asset:
                    notify(
                        org_id,
                        "new_asset",
                        f"New asset discovered: {hname}",
                        f"{atype} on {domain} was observed during scan #{str(scan_id)[:8]}.",
                        "info",
                        "/assets",
                    )

        # Registered-but-unresolved hosts: visible inventory (never clobber
        # an existing assessed row — DO NOTHING on conflict).
        for hname in _registered_hosts(str(org_id), str(domain_id)):
            if hname in asset_id_map:
                continue
            res = execute_one(
                """
                INSERT INTO assets (org_id, domain_id, hostname, status, last_seen)
                VALUES (%s, %s, %s, 'discovered', now())
                ON CONFLICT (org_id, hostname) DO NOTHING
                RETURNING id
                """,
                (org_id, domain_id, hname),
            )
            if res:
                asset_id_map[hname] = res["id"]

        # ---------------------------------------------------------------------
        # STAGE: Security Checks (pure-Python checks + worker nuclei findings)
        # ---------------------------------------------------------------------
        t0 = time.time()
        check_tasks = []
        dns_list = list(valid_dns)
        for dns_item in dns_list:
            hname = dns_item["hostname"]
            matched_http = http_by_host.get(hname, {})
            if hname in third_party_hosts:
                matched_http = checker_view_for_third_party(matched_http)
            is_apex = (hname == domain)
            check_tasks.append(run_security_checks(hname, dns_item, matched_http, is_apex=is_apex))

        check_results_list = await asyncio.gather(*check_tasks, return_exceptions=True)

        # Cancelled while security checks ran: stop before any findings writes.
        if not _still_running(scan_id):
            return {"scan_id": scan_id, "status": _scan_status(scan_id)}

        raw_check_findings = []
        # Hosts where the shared security-check detector completed (a host's
        # task raising is recorded by gather as the exception → not covered).
        check_success_hosts: set = set()
        for idx, chk_results in enumerate(check_results_list):
            if isinstance(chk_results, list):
                hname = dns_list[idx]["hostname"]
                check_success_hosts.add(hname)
                for cr in chk_results:
                    cr["_hostname"] = hname
                raw_check_findings.extend(chk_results)

        for nf in nuclei_findings:
            if not nf.get("_hostname"):
                nf["_hostname"] = nf.get("evidence", {}).get("host") or domain
        raw_check_findings.extend(nuclei_findings)

        sec_dur = int((time.time() - t0) * 1000)
        failed_checks = len(dns_list) - len(check_success_hosts)
        progress["security_checks"] = {"status": "failed" if failed_checks else "completed", "items": len(raw_check_findings),
                                       "duration_ms": sec_dur,
                                       **({"error": f"Security checks failed on {failed_checks} of {len(dns_list)} hosts."} if failed_checks else {})}
        progress["normalization"]["status"] = "running"
        _save_progress(scan_id, progress, "normalization")

        _store_observation(scan_id, 'security_checks', {"findings_count": len(raw_check_findings)})

        # ---------------------------------------------------------------------
        # STAGE: Finding Normalization, Upsert, Baseline Diff, Evidence
        # ---------------------------------------------------------------------
        t0 = time.time()
        normalized_all = []
        hostname_by_asset = {aid: h for h, aid in asset_id_map.items()}
        for dns_item in valid_dns:
            hname = dns_item["hostname"]
            asset_id = asset_id_map.get(hname)
            asset_raw = [f for f in raw_check_findings if f.get("_hostname") == hname]
            norm = normalize_findings(asset_raw, asset_id=asset_id, org_id=org_id, scan_id=scan_id)
            for nf in norm:
                nf["hostname"] = hname
            normalized_all.extend(norm)

        scanned_asset_ids = [aid for aid in asset_id_map.values() if aid]
        baseline = {"new": [], "reopened": [], "resolved": [], "not_evaluated": []}

        # -----------------------------------------------------------------
        # Detector coverage — "not evaluated" must never look like "clear".
        # A finding may only auto-resolve when its detector completed for
        # that specific host this scan; anything else stays open and is
        # recorded as not evaluated.
        # -----------------------------------------------------------------
        def _detector_covered(asset_id: Any, category: Any, evidence: Any, title: Any) -> bool:
            """Did this finding's detector complete for this host this scan?"""
            hostname = hostname_by_asset.get(asset_id) or hostname_by_asset.get(str(asset_id))
            name = classify_detector(category, evidence)["name"]
            if name == "nuclei":
                # Current CLI output proves matches/process completion only,
                # not exact-template negative coverage. Keep absence unknown.
                return False
            if name == "security_checks":
                if hostname not in check_success_hosts:
                    return False
                if category == "DNS & Email Security":
                    # Email checks only run on the domain apex.
                    return hostname == domain and dns_finding_evaluated(dns_by_host.get(hostname) or {}, title)
                if category == "SSL/TLS":
                    tls = (http_by_host.get(hostname) or {}).get("tls_info") or {}
                    return bool(tls.get("valid_to") or tls.get("issuer"))
                # A third-party host's response-derived checks do not apply:
                # an old finding there was read from the provider's response.
                if hostname in third_party_hosts:
                    return True
                # A function returning [] when HTTP is unreachable does not
                # mean headers, certificate or disclosure checks were clean.
                http = http_by_host.get(hostname) or {}
                return http.get("http_status") is not None and not http.get("error")
            return False

        if scanned_asset_ids:
            existing_findings = execute_query(
                """
                SELECT id, asset_id, title, status, severity, description, category, evidence, remediation
                FROM findings
                WHERE org_id = %s AND asset_id = ANY(%s)
                """,
                (org_id, scanned_asset_ids),
            ) or []
            # Keyed by detector identity (detector + rule/template), not the
            # display title — titles are mutable, a nuclei rule id is not.
            existing_map = {
                (f["asset_id"], detector_key(f.get("category"), f.get("evidence"), f["title"])): f
                for f in existing_findings
            }
            observed_by_asset: Dict[str, set] = {aid: set() for aid in scanned_asset_ids}

            for nf in normalized_all:
                asset_id = nf.get("asset_id")
                if not asset_id:
                    continue
                nf_key = detector_key(nf.get("category"), nf.get("evidence"), nf["title"])
                observed_by_asset.setdefault(asset_id, set()).add(nf_key)
                prior = existing_map.get((asset_id, nf_key))

                if prior is None:
                    row = execute_one(
                        """
                        INSERT INTO findings (
                            scan_id, asset_id, org_id, title, description, severity, category,
                            evidence, remediation, status, first_seen_at, last_seen_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'open', now(), now(), now())
                        RETURNING id
                        """,
                        (
                            nf["scan_id"], asset_id, org_id, nf["title"], nf["description"],
                            nf["severity"], nf["category"], json.dumps(nf["evidence"]),
                            nf["remediation"],
                        ),
                    )
                    if row:
                        nf["id"] = str(row["id"])
                        nf["_is_new"] = True
                        baseline["new"].append(nf)
                        execute_one(
                            """
                            INSERT INTO finding_evidence (finding_id, org_id, type, data)
                            VALUES (%s, %s, 'scanner_output', %s::jsonb)
                            RETURNING id
                            """,
                            (
                                row["id"], org_id,
                                json.dumps({
                                    "scan_id": scan_id,
                                    "hostname": nf.get("hostname") or hostname_by_asset.get(asset_id),
                                    "evidence": nf["evidence"],
                                    "source": "pipeline",
                                }),
                            ),
                        )
                    continue

                reopened = prior["status"] == "resolved"
                execute_query(
                    """
                    UPDATE findings
                    SET scan_id = %s,
                        description = %s,
                        severity = %s,
                        category = %s,
                        evidence = %s::jsonb,
                        remediation = %s,
                        last_seen_at = now(),
                        updated_at = now(),
                        status = CASE WHEN %s THEN 'open' ELSE findings.status END,
                        resolved_at = CASE WHEN %s THEN NULL ELSE findings.resolved_at END
                    WHERE id = %s AND org_id = %s
                    """,
                    (
                        nf["scan_id"], nf["description"], nf["severity"], nf["category"],
                        json.dumps(nf["evidence"]), nf["remediation"],
                        reopened, reopened, prior["id"], org_id,
                    ),
                )
                nf["id"] = str(prior["id"])
                if reopened:
                    nf["_is_reopened"] = True
                    baseline["reopened"].append(nf)

            # Auto-resolve findings on scanned assets that were not re-observed
            # — but only when their detector actually completed for that host.
            # A detector that didn't run is "not evaluated", never "clear".
            for aid, observed in observed_by_asset.items():
                for f in existing_findings:
                    if f["asset_id"] != aid or f["status"] == "resolved":
                        continue
                    f_key = detector_key(f.get("category"), f.get("evidence"), f["title"])
                    if f_key in observed:
                        continue
                    f_host = hostname_by_asset.get(str(f["asset_id"])) or hostname_by_asset.get(f["asset_id"])
                    if not _detector_covered(aid, f.get("category"), f.get("evidence"), f.get("title")):
                        baseline["not_evaluated"].append({
                            "id": str(f["id"]),
                            "title": f["title"],
                            "severity": f["severity"],
                            "asset_id": str(f["asset_id"]),
                            "hostname": f_host,
                            "detector": classify_detector(f.get("category"), f.get("evidence"))["name"],
                        })
                        continue
                    execute_query(
                        """
                        UPDATE findings
                        SET status = 'resolved', resolved_at = now(), updated_at = now()
                        WHERE id = %s AND org_id = %s
                        """,
                        (f["id"], org_id),
                    )
                    baseline["resolved"].append({
                        "id": str(f["id"]),
                        "title": f["title"],
                        "severity": f["severity"],
                        "asset_id": str(f["asset_id"]),
                        "hostname": f_host,
                    })
        else:
            # No assets in scope (empty discovery): still insert free-standing findings
            for nf in normalized_all:
                row = execute_one(
                    """
                    INSERT INTO findings (
                        scan_id, asset_id, org_id, title, description, severity, category,
                        evidence, remediation, status, first_seen_at, last_seen_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'open', now(), now(), now())
                    RETURNING id
                    """,
                    (
                        nf["scan_id"], nf.get("asset_id"), org_id, nf["title"], nf["description"],
                        nf["severity"], nf["category"], json.dumps(nf["evidence"]),
                        nf["remediation"],
                    ),
                )
                if row:
                    nf["id"] = str(row["id"])
                    nf["_is_new"] = True
                    baseline["new"].append(nf)
                    execute_one(
                        """
                        INSERT INTO finding_evidence (finding_id, org_id, type, data)
                        VALUES (%s, %s, 'scanner_output', %s::jsonb)
                        RETURNING id
                        """,
                        (row["id"], org_id, json.dumps({"scan_id": scan_id, "evidence": nf["evidence"], "source": "pipeline"})),
                    )

        # Baseline change notifications (in-app for all; email for critical / reopened)
        for nf in baseline["new"]:
            if nf["severity"] == "critical":
                notify(
                    org_id, "critical_finding",
                    f"Critical finding: {nf['title']}",
                    (nf.get("description") or "")[:480],
                    "critical", "/findings",
                )
                email_jobs.append({
                    "subject": f"[Cyphward] Critical finding: {nf['title']}",
                    "html": _finding_email_html(org_name, nf["title"], "critical", nf.get("description") or "", nf.get("remediation") or "", nf.get("hostname") or domain, False),
                    "text": f"Critical finding on {nf.get('hostname') or domain}: {nf['title']}. {nf.get('remediation') or ''}",
                })
            elif nf["severity"] == "high":
                notify(
                    org_id, "high_risk_exposure",
                    f"High risk exposure: {nf['title']}",
                    (nf.get("description") or "")[:480],
                    "high", "/findings",
                )

        for nf in baseline["reopened"]:
            notify(
                org_id, "finding_reopened",
                f"Finding reopened: {nf['title']}",
                (nf.get("description") or "")[:480],
                nf.get("severity") or "high", "/findings",
            )
            sev = nf.get("severity") or "high"
            email_jobs.append({
                "subject": f"[Cyphward] Finding reopened: {nf['title']}",
                "html": _finding_email_html(org_name, nf["title"], sev, nf.get("description") or "", nf.get("remediation") or "", nf.get("hostname") or domain, True),
                "text": f"Finding reopened on {nf.get('hostname') or domain}: {nf['title']}. {nf.get('remediation') or ''}",
            })

        for rf in baseline["resolved"]:
            notify(
                org_id, "finding_resolved",
                f"Finding resolved: {rf['title']}",
                f"Auto-resolved after scan — no longer observed on {rf.get('hostname') or domain}.",
                "info", "/findings",
            )

        norm_dur = int((time.time() - t0) * 1000)
        progress["normalization"] = {"status": "completed", "items": len(normalized_all), "duration_ms": norm_dur}
        progress["scoring"]["status"] = "running"
        _save_progress(scan_id, progress, "scoring")

        # ---------------------------------------------------------------------
        # STAGE: Deterministic Risk Scoring
        # ---------------------------------------------------------------------
        t0 = time.time()
        # This scan is the assessment being completed right now — score it
        # against its own evidence instead of the "no scan" gate.
        scan_completed_at = datetime.now(timezone.utc).isoformat()
        # Reconciliation may retain findings from failed/unattempted detectors
        # and other domains. Score the same open organization risk as Overview.
        open_findings = execute_query(
            "SELECT * FROM findings WHERE org_id = %s AND status != 'resolved'",
            (org_id,),
        ) or []
        coverage = assessment_coverage(domain, observations, check_success_hosts,
                                       registered_hosts=registered_hosts)
        # A grade needs every verified domain complete; this scan's domain
        # is judged on the coverage being committed now.
        domain_states = org_domain_coverage(str(org_id), current={
            "domain_id": str(domain_id), "domain": domain, "scan_id": str(scan_id),
            "completed_at": scan_completed_at, "coverage": coverage,
        })
        score_result = compute_risk_score(
            open_findings,
            assessment={
                "scan_id": str(scan_id),
                "status": "completed",
                "completed_at": scan_completed_at,
                "model": SCORE_MODEL,
                "coverage": coverage,
                "domains": domain_states,
            },
        )
        final_score = score_result["score"]
        score_dur = int((time.time() - t0) * 1000)

        # Compliance readiness evidence for this domain. Optional: a failure
        # here is recorded in the completion audit and never fails the scan.
        try:
            compliance_rows = evidence_for_scan(
                org_id=str(org_id), domain_id=str(domain_id), scan_id=str(scan_id), coverage=coverage,
                observations=observations, completed_at=scan_completed_at)
        except ClaimLost:
            raise
        except Exception:
            logger.warning("scan=%s compliance evidence could not be computed", scan_id, exc_info=True)
            compliance_rows = "error"

        progress["scoring"] = {
            "status": "completed", "score": final_score, "duration_ms": score_dur,
            "model": SCORE_MODEL, "scope": SCORE_SCOPE,
            "risk_points": score_result.get("risk_points"),
            "coverage": (score_result.get("assessment") or {}).get("coverage"),
            "grade": score_result.get("grade"),
            "domain_coverage": score_result.get("domain_coverage"),
        }

        # ---------------------------------------------------------------------
        # STAGE: AI Security Analysis
        # ---------------------------------------------------------------------
        t0 = time.time()
        progress["ai_analysis"]["status"] = "running"
        _save_progress(scan_id, progress, "ai_analysis")

        ai_explanations: List[Dict[str, Any]] = []
        try:
            async with asyncio.timeout(CORE_AI_TIMEOUT_SECONDS):
                ai = get_ai_provider()

                critical_high_findings = [f for f in normalized_all if f.get("severity") in ("critical", "high")]
                explain_tasks = [ai.explain_finding(finding) for finding in critical_high_findings]
                explain_results = await asyncio.gather(*explain_tasks, return_exceptions=True)
                for idx, result in enumerate(explain_results):
                    if isinstance(result, dict):
                        result["finding_id"] = critical_high_findings[idx].get("id")
                        ai_explanations.append(result)

                executive_summary = await ai.generate_executive_summary(org_name, score_result, open_findings)

                ai_data = {
                    "explanations_count": len(ai_explanations),
                    "critical_high_count": len(critical_high_findings),
                    "executive_summary": executive_summary,
                }
                _store_observation(scan_id, 'ai_analysis', ai_data)

                if ai_explanations:
                    _store_observation(scan_id, 'ai_explanations', ai_explanations)
            ai_dur = int((time.time() - t0) * 1000)
            progress["ai_analysis"] = {"status": "completed", "items": len(ai_explanations), "duration_ms": ai_dur}

        except ClaimLost:
            raise
        except TimeoutError:
            ai_dur = int((time.time() - t0) * 1000)
            progress["ai_analysis"] = {"status": "failed", "error": "AI analysis exceeded its deadline.", "duration_ms": ai_dur}
        except Exception as ai_err:
            ai_dur = int((time.time() - t0) * 1000)
            progress["ai_analysis"] = {"status": "failed", "error": str(ai_err), "duration_ms": ai_dur}

        not_evaluated_msg = (
            f" · {len(baseline['not_evaluated'])} not evaluated" if baseline['not_evaluated'] else ''
        )
        if final_score is not None and score_result.get("grade"):
            score_msg = f"Score {final_score}/100 · grade {score_result['grade']} · within declared scope"
        elif final_score is not None:
            score_msg = f"Known-risk score {final_score}/100 · {score_result['posture_label'].lower()}"
        else:
            score_msg = f"No score · {score_result['posture_label']}"
        execution.finish_assessment(require_execution(scan_id), str(org_id), score_result, progress, {
            'domain': domain, 'score': final_score, 'findings': len(normalized_all),
            'new': len(baseline['new']), 'reopened': len(baseline['reopened']),
            'resolved': len(baseline['resolved']), 'not_evaluated': len(baseline['not_evaluated']),
        }, {
            'model': SCORE_MODEL, 'scope': SCORE_SCOPE,
            'title': f'Scan completed for {domain}',
            'body': f"{score_msg} · {len(normalized_all)} findings observed · {len(baseline['new'])} new · {len(baseline['resolved'])} resolved{not_evaluated_msg}.",
            'severity': 'medium' if final_score is not None and final_score < 70 else 'info',
        }, compliance_evidence=compliance_rows)

        return {
            "scan_id": scan_id,
            "status": "completed",
            "score": final_score,
            "stage_progress": progress,
            "assets_discovered": len(valid_dns),
            "findings_count": len(normalized_all),
            "new_findings": len(baseline["new"]),
            "reopened_findings": len(baseline["reopened"]),
            "resolved_findings": len(baseline["resolved"]),
            "not_evaluated_findings": len(baseline["not_evaluated"]),
            "ai_analyzed": len(ai_explanations),
            "_email_jobs": email_jobs,
            "_email_org_id": org_id,
        }

    except ClaimLost:
        raise
    except Exception as exc:
        progress['error'] = str(exc)
        execution.fail_claim(require_execution(scan_id), str(exc), progress)
        raise


async def execute_recon_local(scan_id: str, claim: ExecutionClaim) -> Dict[str, Any]:
    if claim.scan_id != str(scan_id) or claim.phase != 'local':
        raise ClaimLost('Invalid local recon authority')
    return await execution.run_owned(claim, lambda: _execute_recon_local_owned(scan_id), execution.LOCAL_LEASE_SECONDS)


async def finalize_scan(scan_id: str, claim: ExecutionClaim) -> Dict[str, Any]:
    if claim.scan_id != str(scan_id) or claim.phase != 'core':
        raise ClaimLost('Invalid Core finalisation authority')
    result = await execution.run_owned(claim, lambda: _finalize_scan_owned(scan_id), execution.CORE_LEASE_SECONDS)
    jobs = result.pop('_email_jobs', [])
    org_id = result.pop('_email_org_id', None)
    # Email is best-effort after the authoritative completion transaction. A
    # restart after commit can lose delivery; this is not exactly-once mail.
    if result.get('status') == 'completed' and org_id and jobs:
        await asyncio.gather(*[_email_org_members(org_id,j['subject'],j['html'],j['text']) for j in jobs],return_exceptions=True)
    return result


async def execute_scan_pipeline(scan_id: str) -> Dict[str, Any]:
    if SCANNER_MODE != 'local':
        return {'scan_id':scan_id,'status':'remote_queue'}
    row = await asyncio.to_thread(execution.claim_recon, 'local:'+secrets.token_hex(12), 'local', execution.LOCAL_LEASE_SECONDS, scan_id)
    if row is None:
        status = await asyncio.to_thread(execution.inspect_status, scan_id)
        return {'scan_id':scan_id,'status':status,'cancelled':status=='cancelled','claimed':False}
    claim = execution.claim_from_row(row)
    recon = await execute_recon_local(scan_id,claim)
    if recon.get('cancelled') or recon.get('claim_lost'):
        return recon
    try:
        core_claim = await asyncio.to_thread(execution.handoff_to_core,claim)
    except ClaimLost:
        return {'scan_id':scan_id,'status':await asyncio.to_thread(execution.inspect_status,scan_id),'claim_lost':True}
    return await finalize_scan(scan_id,core_claim)


# ===========================================================================
# Inngest function definitions (event bus + cron; no compute in remote mode)
# ===========================================================================
@inngest_client.create_function(
    fn_id="cyphward-scan-pipeline",
    trigger=inngest.TriggerEvent(event="scan.requested")
)
async def inngest_scan_pipeline_fn(ctx: inngest.Context) -> Dict[str, Any]:
    """Inngest event handler. Remote mode: the scans row IS the queue — the
    worker claims it over outbound HTTPS; this function only acknowledges."""
    scan_id = ctx.event.data.get("scan_id")
    if not scan_id:
        raise ValueError("Missing scan_id in event data.")
    if SCANNER_MODE == "remote":
        return {"scan_id": scan_id, "dispatch": "remote_scanner"}
    return await execute_scan_pipeline(scan_id)


async def run_daily_scan_schedule() -> Dict[str, Any]:
    """
    Daily scheduled scans: one scan per verified domain for orgs that do not
    already have a queued/running scan (baseline drift detection).

    Shared implementation: triggered by the Inngest cron function below when
    the Inngest platform is wired, and by the in-process scheduler loop
    (backend.app.scheduler) otherwise.

    Durable-jobs claim (review P1): the whole sweep runs under one atomic
    cron_runs claim, so multiple API replicas (or the Inngest cron racing the
    in-process loop) cannot double-sweep a day. The `cron.ran` audit marker
    is still written for observability and for pre-claim legacy rows; the
    in-process loop treats either signal as "today already ran".

    Returns {"claimed": False, ...} without touching any rows when another
    owner holds today's claim; on failure the claim is released so the next
    retry can take over (a crashed owner's claim is taken over by the same
    statement after the stale window).
    """
    run_day = datetime.now(timezone.utc).date()
    claim = claim_cron_run(DAILY_SCAN_CRON_NAME, run_day, _claimant_id())
    if not claim:
        return {"claimed": False, "due_domains": 0, "scheduled": 0}

    try:
        result = await _daily_scan_sweep(run_day, claim)
        if not complete_cron_run(DAILY_SCAN_CRON_NAME, run_day, claim):
            raise ClaimLost("Scheduler ownership expired before completion")
    except BaseException:
        release_cron_run(DAILY_SCAN_CRON_NAME, run_day, claim)
        raise
    result["claimed"] = True
    log_audit(None, None, "cron.ran", "scheduler", None, {**result, "trigger":"cron"})
    return result


def _claimant_id() -> str:
    """Identify which process holds the cron claim (debugging aid)."""
    return f"{socket.gethostname()}:{os.getpid()}"


async def _daily_scan_sweep(run_day: date | None = None, cron_authority: dict | None = None) -> Dict[str, Any]:
    due_domains = execute_query(
        """
        SELECT d.id AS domain_id, d.org_id, d.domain
        FROM domains d
        WHERE d.verification_status = 'verified'
        ORDER BY d.created_at ASC
        """
    ) or []

    scheduled = 0
    skipped_quota = 0
    skipped_active = 0
    replayed = 0
    run_day = run_day or datetime.now(timezone.utc).date()

    for row in due_domains:
        admission = admit_scan(
            str(row["org_id"]), str(row["domain_id"]),
            request_scope=f"scheduled:{run_day.isoformat()}",
            request_key=f"domain:{row['domain_id']}",
            cron_authority=cron_authority,
        )
        if admission.outcome == "quota":
            skipped_quota += 1
            continue
        if admission.outcome == "active":
            skipped_active += 1
            continue
        if admission.outcome == "replayed":
            replayed += 1
            continue

        scan_id = str(admission.scan["id"])
        try:
            await inngest_client.send(inngest.Event(name="scan.requested", data={
                "version": 1,
                "scan_id": scan_id,
                "organization_id": str(row["org_id"]),
                "domain_id": str(row["domain_id"]),
                "trigger": "cron",
            }))
        except Exception as e:
            if SCANNER_MODE == "remote":
                # The queued row is the dispatch — the worker claims it.
                logger.warning("Inngest dispatch failed for cron scan %s (remote mode, worker polls): %s", scan_id, e)
            else:
                # Event gateway unavailable — run inline so the schedule still fires
                try:
                    await execute_scan_pipeline(scan_id)
                except Exception as inline_err:
                    logger.warning("local scan %s dispatch failed; durable recovery will retry: %s", scan_id, inline_err)
                    continue

        scheduled += 1
        log_audit(row["org_id"], None, "scan.scheduled", "scan", scan_id, {
            "domain": admission.domain,
            "trigger": "cron",
        })

    return {"due_domains": len(due_domains), "scheduled": scheduled,
            "skipped_quota": skipped_quota, "skipped_active": skipped_active,
            "replayed": replayed}


@inngest_client.create_function(
    fn_id="cyphward-daily-scan-scheduler",
    trigger=inngest.TriggerCron(cron="0 6 * * *"),
)
async def inngest_daily_scan_cron(ctx: inngest.Context) -> Dict[str, Any]:
    """Inngest platform cron entry point (06:00 UTC). Delegates to the shared
    daily scan schedule; only fires when the Inngest app is registered."""
    return await run_daily_scan_schedule()
