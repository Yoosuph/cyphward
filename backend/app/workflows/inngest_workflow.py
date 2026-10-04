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
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import inngest

from backend.app.core.config import (
    SCANNER_MODE,
    SCANNER_NUCLEI_CONCURRENCY,
    SCANNER_NUCLEI_MAX_HOSTS,
    SCANNER_MAX_PORTS,
    SCANNER_STAGE_TIMEOUT_SECONDS,
)
from backend.app.core.database import execute_one, execute_query, execute_many
from backend.app.core.auth import log_audit
from backend.app.core.plans import PLANS, LEGACY_PLAN_FALLBACK
from backend.app.core.cron_claim import (
    DAILY_SCAN_CRON_NAME,
    claim_cron_run,
    complete_cron_run,
    release_cron_run,
)
from backend.app.scanner.discovery import discover_subdomains
from backend.app.scanner.dns_resolver import resolve_host_dns
from backend.app.scanner.http_probe import probe_http_service
from backend.app.scanner.naabu_runner import run_naabu_batch
from backend.app.scanner.sslyze_runner import run_sslyze_batch
from backend.app.scanner.security_checks import run_security_checks
from backend.app.scanner.nuclei_runner import run_nuclei_batch
from backend.app.scanner.normalizer import normalize_findings
from backend.app.scanner.detectors import classify_detector, detector_key
from backend.app.risk.engine import compute_risk_score, SCORE_MODEL
from backend.app.ai.factory import get_ai_provider
from backend.app.services.notifications import notify
from backend.app.services.mailer import send_email_async
from shared.contracts import STAGE_SECURITY_CHECKS, empty_stage_progress

import os

logger = logging.getLogger("cyphward.scan")

is_prod = os.getenv("INNGEST_IS_PRODUCTION", "false").lower() in ("true", "1")
signing_key = os.getenv("INNGEST_SIGNING_KEY")
event_key = os.getenv("INNGEST_EVENT_KEY")
inngest_client = inngest.Inngest(
    app_id="cyphward",
    is_production=is_prod if signing_key else False,
    signing_key=signing_key or None,
    event_key=event_key or None,
)

DNS_HOST_CAP = 40
# TLS analysis is expensive — hard cap independent of discovery breadth.
TLS_HOST_CAP = 25
# Port-scan concurrency within the ports stage (one stage at a time, §16).
PORTS_STAGE_CONCURRENCY = 4
TLS_STAGE_CONCURRENCY = 2


def _queued_stage_progress() -> Dict[str, Any]:
    """Initial stage_progress for a newly queued scan row (all stages queued)."""
    return empty_stage_progress()


def _tool_available(binary: str) -> bool:
    return shutil.which(binary) is not None


# A scan row only accepts pipeline writes while it is running — or completed,
# for the post-completion AI-progress flush. Cancelled/failed/terminal scans
# reject every stage write so a cancelled scan can never be resurrected
# (review item "P1 — trustworthy scan history").
_WRITABLE_SCAN_STATUSES = ("running", "completed")


def _scan_status(scan_id: str) -> str:
    """Current status of a scan row ('' when the row no longer exists)."""
    row = execute_one("SELECT status FROM scans WHERE id = %s", (scan_id,))
    return (row or {}).get("status") or ""


def _still_running(scan_id: str) -> bool:
    """Boundary check: pipeline work continues only while status='running'."""
    return _scan_status(scan_id) == "running"


def _stage_write_allowed(scan_id: str) -> bool:
    return _scan_status(scan_id) in _WRITABLE_SCAN_STATUSES


def _store_observation(scan_id: str, stage: str, data: Dict[str, Any]) -> None:
    """Idempotent observation write (replaces a previous row for the stage).
    Fenced: cancelled/terminal scans accept no further stage writes."""
    if not _stage_write_allowed(scan_id):
        return
    execute_query("DELETE FROM scan_results WHERE scan_id = %s AND stage = %s", (scan_id, stage))
    execute_query(
        "INSERT INTO scan_results (scan_id, stage, raw_data) VALUES (%s, %s, %s::jsonb)",
        (scan_id, stage, json.dumps(data)),
    )


def _save_progress(scan_id: str, progress: Dict[str, Any], current_stage: str = None) -> None:
    """Fenced progress write — no-ops once the scan is cancelled/failed."""
    if not _stage_write_allowed(scan_id):
        return
    if current_stage:
        execute_query(
            "UPDATE scans SET stage_progress = %s::jsonb, current_stage = %s WHERE id = %s AND status IN ('running', 'completed')",
            (json.dumps(progress), current_stage, scan_id),
        )
    else:
        execute_query(
            "UPDATE scans SET stage_progress = %s::jsonb WHERE id = %s AND status IN ('running', 'completed')",
            (json.dumps(progress), scan_id),
        )


def _load_observations(scan_id: str) -> Dict[str, Any]:
    """Stage → raw_data map (later rows win; worker replaces per stage)."""
    rows = execute_query(
        "SELECT stage, raw_data FROM scan_results WHERE scan_id = %s ORDER BY created_at ASC",
        (scan_id,),
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
async def execute_recon_local(scan_id: str) -> Dict[str, Any]:
    """
    Run recon stages in-process: discovery → dns → http → ports → tls → nuclei.
    Writes one observation row per stage. Foundational stages (discovery/dns/
    http) fail the scan on error; ports/tls/nuclei degrade gracefully (§23).
    """
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
        discovered_hosts = await discover_subdomains(domain)
        d_dur = int((time.time() - t0) * 1000)

        progress["discovery"] = {"status": "completed", "items": len(discovered_hosts), "duration_ms": d_dur}
        if not _still_running(scan_id):
            return {"scan_id": scan_id, "cancelled": True}
        progress["dns"]["status"] = "running"
        _save_progress(scan_id, progress, "dns")
        _store_observation(scan_id, "discovery", {"discovered_hosts": discovered_hosts})

        # ---------------------------------------------------------------------
        # STAGE 2: DNS Resolution
        # ---------------------------------------------------------------------
        t0 = time.time()
        dns_tasks = [resolve_host_dns(h) for h in discovered_hosts[:DNS_HOST_CAP]]
        dns_results = await asyncio.gather(*dns_tasks, return_exceptions=True)
        valid_dns = [r for r in dns_results if isinstance(r, dict)]
        dns_dur = int((time.time() - t0) * 1000)

        progress["dns"] = {"status": "completed", "items": len(valid_dns), "duration_ms": dns_dur}
        if not _still_running(scan_id):
            return {"scan_id": scan_id, "cancelled": True}
        progress["http"]["status"] = "running"
        _save_progress(scan_id, progress, "http")
        _store_observation(scan_id, "dns", {"dns_records": valid_dns})

        # ---------------------------------------------------------------------
        # STAGE 3: HTTP/HTTPS Probing — resolved hosts only; probing an
        # unresolved name only manufactures null/error observations.
        # ---------------------------------------------------------------------
        t0 = time.time()
        # scope=[domain]: redirect hops must stay under the scanned domain.
        http_tasks = [
            probe_http_service(h["hostname"], scope=[domain])
            for h in valid_dns if h.get("primary_ip")
        ]
        http_results = await asyncio.gather(*http_tasks, return_exceptions=True)
        valid_http = [r for r in http_results if isinstance(r, dict)]
        http_dur = int((time.time() - t0) * 1000)

        progress["http"] = {"status": "completed", "items": len(valid_http), "duration_ms": http_dur}
        if not _still_running(scan_id):
            return {"scan_id": scan_id, "cancelled": True}
        progress["ports"]["status"] = "running"
        _save_progress(scan_id, progress, "ports")
        _store_observation(scan_id, "http", {"http_probes": valid_http})

        # ---------------------------------------------------------------------
        # STAGE 4: TCP Port Discovery (naabu) — optional, degrades gracefully
        # ---------------------------------------------------------------------
        t0 = time.time()
        if not _tool_available("naabu"):
            progress["ports"] = {"status": "skipped", "items": 0, "duration_ms": 0,
                                 "error": "naabu not installed"}
        else:
            try:
                port_targets = [h["hostname"] for h in valid_dns if h.get("primary_ip")]
                open_ports = await run_naabu_batch(
                    port_targets,
                    top_ports=SCANNER_MAX_PORTS,
                    timeout=SCANNER_STAGE_TIMEOUT_SECONDS,
                    concurrency=PORTS_STAGE_CONCURRENCY,
                )
                ports_dur = int((time.time() - t0) * 1000)
                progress["ports"] = {"status": "completed", "items": len(open_ports),
                                     "duration_ms": ports_dur}
                _store_observation(scan_id, "ports", {"open_ports": open_ports})
            except Exception as ports_err:
                ports_dur = int((time.time() - t0) * 1000)
                progress["ports"] = {"status": "failed", "items": 0, "duration_ms": ports_dur,
                                     "error": str(ports_err)[:500]}

        if not _still_running(scan_id):
            return {"scan_id": scan_id, "cancelled": True}
        progress["tls"]["status"] = "running"
        _save_progress(scan_id, progress, "tls")

        # ---------------------------------------------------------------------
        # STAGE 5: TLS Analysis (sslyze) — optional, degrades gracefully
        # ---------------------------------------------------------------------
        t0 = time.time()
        if not _tool_available("sslyze"):
            progress["tls"] = {"status": "skipped", "items": 0, "duration_ms": 0,
                               "error": "sslyze not installed"}
        else:
            try:
                tls_targets = [
                    h["hostname"] for h in valid_http
                    if h.get("http_status") and str(h.get("url", "")).startswith("https")
                ][:TLS_HOST_CAP]
                tls_profiles = await run_sslyze_batch(
                    tls_targets,
                    timeout=SCANNER_STAGE_TIMEOUT_SECONDS,
                    concurrency=TLS_STAGE_CONCURRENCY,
                )
                tls_dur = int((time.time() - t0) * 1000)
                progress["tls"] = {"status": "completed", "items": len(tls_profiles),
                                   "duration_ms": tls_dur}
                _store_observation(scan_id, "tls", {"tls_profiles": tls_profiles})
            except Exception as tls_err:
                tls_dur = int((time.time() - t0) * 1000)
                progress["tls"] = {"status": "failed", "items": 0, "duration_ms": tls_dur,
                                   "error": str(tls_err)[:500]}

        if not _still_running(scan_id):
            return {"scan_id": scan_id, "cancelled": True}
        progress["nuclei"]["status"] = "running"
        _save_progress(scan_id, progress, "nuclei")

        # ---------------------------------------------------------------------
        # STAGE 6: Nuclei Deep Vulnerability Scanning — optional (§23)
        # ---------------------------------------------------------------------
        t0 = time.time()
        if not _tool_available("nuclei"):
            progress["nuclei"] = {"status": "skipped", "items": 0, "duration_ms": 0,
                                  "error": "nuclei not installed"}
        else:
            try:
                active_hosts = [h["hostname"] for h in valid_dns if any(
                    hp.get("hostname") == h["hostname"] and hp.get("http_status")
                    for hp in valid_http
                )][:SCANNER_NUCLEI_MAX_HOSTS]
                nuclei_findings = await run_nuclei_batch(
                    active_hosts,
                    concurrency=SCANNER_NUCLEI_CONCURRENCY,
                    timeout=SCANNER_STAGE_TIMEOUT_SECONDS,
                )
                for nf in nuclei_findings:
                    if not nf.get("_hostname"):
                        nf["_hostname"] = nf.get("evidence", {}).get("host") or domain
                nuclei_dur = int((time.time() - t0) * 1000)
                progress["nuclei"] = {"status": "completed", "items": len(nuclei_findings),
                                      "duration_ms": nuclei_dur}
                _store_observation(scan_id, "nuclei", {
                    "nuclei_findings": nuclei_findings,
                    "attempted_hosts": active_hosts,
                })
            except Exception as nuclei_err:
                nuclei_dur = int((time.time() - t0) * 1000)
                progress["nuclei"] = {"status": "failed", "items": 0, "duration_ms": nuclei_dur,
                                      "error": str(nuclei_err)[:500]}

        _save_progress(scan_id, progress)

        if not _still_running(scan_id):
            return {"scan_id": scan_id, "cancelled": True}

        return {
            "scan_id": scan_id,
            "discovered": len(discovered_hosts),
            "dns": len(valid_dns),
            "http": len(valid_http),
            "ports": progress["ports"].get("items", 0),
            "tls": progress["tls"].get("items", 0),
            "nuclei": progress["nuclei"].get("items", 0),
        }

    except Exception as exc:
        progress["error"] = str(exc)
        execute_query("""
            UPDATE scans
            SET status = 'failed', error_message = %s, stage_progress = %s::jsonb, completed_at = now()
            WHERE id = %s AND status IN ('queued', 'running')
        """, (str(exc), json.dumps(progress), scan_id))
        raise


# ===========================================================================
# PHASE 2 — FINALIZE (always Core). Reads observations produced by Phase 1 —
# in-process (local mode) or by the scanner worker (remote mode).
# ===========================================================================
async def finalize_scan(scan_id: str) -> Dict[str, Any]:
    """
    Core-side finalize: security checks → asset inventory → normalization/
    baseline diff → 0-100 risk scoring → AI analysis. Loads recon observations
    from scan_results, so it is independent of where Phase 1 ran.
    """
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

        # ---------------------------------------------------------------------
        # STAGE: Security Checks (pure-Python checks + worker nuclei findings)
        # ---------------------------------------------------------------------
        t0 = time.time()
        check_tasks = []
        dns_list = list(valid_dns)
        for dns_item in dns_list:
            hname = dns_item["hostname"]
            matched_http = http_by_host.get(hname, {})
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
        progress["security_checks"] = {"status": "completed", "items": len(raw_check_findings),
                                       "duration_ms": sec_dur}
        progress["normalization"]["status"] = "running"
        _save_progress(scan_id, progress, "normalization")

        execute_query("""
            INSERT INTO scan_results (scan_id, stage, raw_data)
            VALUES (%s, 'security_checks', %s::jsonb)
        """, (scan_id, json.dumps({"findings_count": len(raw_check_findings)})))

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
        nuclei_obs = observations.get("nuclei") or {}
        if isinstance(nuclei_obs.get("attempted_hosts"), list):
            nuclei_attempted = [h for h in nuclei_obs["attempted_hosts"] if isinstance(h, str)]
        else:
            # Legacy observations (pre-attempted_hosts): recompute the rule
            # recon used — HTTP-responsive hosts, discovery order, capped.
            nuclei_attempted = []
            for h in valid_dns:
                hn = h.get("hostname")
                if not hn or hn in nuclei_attempted:
                    continue
                if any(hp.get("hostname") == hn and hp.get("http_status") for hp in valid_http):
                    nuclei_attempted.append(hn)
                if len(nuclei_attempted) >= SCANNER_NUCLEI_MAX_HOSTS:
                    break
        nuclei_stage_ok = (progress.get("nuclei") or {}).get("status") == "completed"
        nuclei_covered_hosts = set(nuclei_attempted) if nuclei_stage_ok else set()

        def _detector_covered(asset_id: Any, category: Any, evidence: Any) -> bool:
            """Did this finding's detector complete for this host this scan?"""
            hostname = hostname_by_asset.get(asset_id) or hostname_by_asset.get(str(asset_id))
            name = classify_detector(category, evidence)["name"]
            if name == "nuclei":
                return hostname in nuclei_covered_hosts
            if name == "security_checks":
                return hostname in check_success_hosts
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
                    if not _detector_covered(aid, f.get("category"), f.get("evidence")):
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

        if email_jobs:
            await asyncio.gather(
                *[_email_org_members(org_id, j["subject"], j["html"], j["text"]) for j in email_jobs],
                return_exceptions=True,
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
        score_result = compute_risk_score(
            normalized_all,
            assessment={
                "scan_id": str(scan_id),
                "status": "completed",
                "completed_at": scan_completed_at,
                "model": SCORE_MODEL,
            },
        )
        final_score = score_result["score"]
        score_dur = int((time.time() - t0) * 1000)

        progress["scoring"] = {"status": "completed", "score": final_score, "duration_ms": score_dur}

        completed = execute_one("""
            UPDATE scans
            SET status = 'completed', current_stage = 'completed', score = %s,
                stage_progress = %s::jsonb, completed_at = now(),
                claimed_by = NULL, lease_expires_at = NULL
            WHERE id = %s AND status = 'running'
            RETURNING id
        """, (final_score, json.dumps(progress), scan_id))
        if not completed:
            # Cancelled mid-finalize: refuse to complete, score, snapshot,
            # notify or run AI analysis on a scan the user cancelled.
            status = _scan_status(scan_id)
            logger.info("scan=%s finalize completion refused: status=%s", scan_id, status or "missing")
            return {"scan_id": scan_id, "status": status}

        # Record Score Snapshot
        execute_query("""
            INSERT INTO score_snapshots (org_id, domain_id, score, subscores, factors)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
        """, (org_id, domain_id, final_score, json.dumps(score_result["subscores"]), json.dumps(score_result["factors"])))

        not_evaluated_msg = (
            f" · {len(baseline['not_evaluated'])} not evaluated"
            if baseline["not_evaluated"] else ""
        )
        notify(
            org_id, "scan_completed",
            f"Scan completed for {domain}",
            f"Score {final_score}/100 · {len(normalized_all)} findings observed · {len(baseline['new'])} new · {len(baseline['resolved'])} resolved{not_evaluated_msg}.",
            "info" if final_score >= 70 else "medium",
            "/scans",
        )

        # ---------------------------------------------------------------------
        # STAGE: AI Security Analysis
        # ---------------------------------------------------------------------
        t0 = time.time()
        progress["ai_analysis"]["status"] = "running"
        _save_progress(scan_id, progress, "ai_analysis")

        ai_explanations: List[Dict[str, Any]] = []
        try:
            ai = get_ai_provider()

            critical_high_findings = [f for f in normalized_all if f.get("severity") in ("critical", "high")]
            explain_tasks = [ai.explain_finding(finding) for finding in critical_high_findings]
            explain_results = await asyncio.gather(*explain_tasks, return_exceptions=True)
            for idx, result in enumerate(explain_results):
                if isinstance(result, dict):
                    result["finding_id"] = critical_high_findings[idx].get("id")
                    ai_explanations.append(result)

            executive_summary = await ai.generate_executive_summary(org_name, score_result, normalized_all)

            ai_data = {
                "explanations_count": len(ai_explanations),
                "critical_high_count": len(critical_high_findings),
                "executive_summary": executive_summary,
            }
            execute_query("""
                INSERT INTO scan_results (scan_id, stage, raw_data)
                VALUES (%s, 'ai_analysis', %s::jsonb)
            """, (scan_id, json.dumps(ai_data)))

            if ai_explanations:
                execute_query("""
                    INSERT INTO scan_results (scan_id, stage, raw_data)
                    VALUES (%s, 'ai_explanations', %s::jsonb)
                """, (scan_id, json.dumps(ai_explanations)))

            ai_dur = int((time.time() - t0) * 1000)
            progress["ai_analysis"] = {"status": "completed", "items": len(ai_explanations), "duration_ms": ai_dur}

        except Exception as ai_err:
            ai_dur = int((time.time() - t0) * 1000)
            progress["ai_analysis"] = {"status": "failed", "error": str(ai_err), "duration_ms": ai_dur}

        execute_query("""
            UPDATE scans
            SET stage_progress = %s::jsonb
            WHERE id = %s AND status IN ('running', 'completed')
        """, (json.dumps(progress), scan_id))

        log_audit(org_id, None, "scan.completed", "scan", scan_id, {
            "domain": domain,
            "score": final_score,
            "findings": len(normalized_all),
            "new": len(baseline["new"]),
            "reopened": len(baseline["reopened"]),
            "resolved": len(baseline["resolved"]),
            "not_evaluated": len(baseline["not_evaluated"]),
        })

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
        }

    except Exception as exc:
        progress["error"] = str(exc)
        execute_query("""
            UPDATE scans
            SET status = 'failed', error_message = %s, stage_progress = %s::jsonb,
                completed_at = now(), claimed_by = NULL, lease_expires_at = NULL
            WHERE id = %s AND status IN ('queued', 'running')
        """, (str(exc), json.dumps(progress), scan_id))
        raise


async def execute_scan_pipeline(scan_id: str) -> Dict[str, Any]:
    """
    Local-mode end-to-end pipeline: recon in-process, then Core finalize.
    In remote mode the worker replaces Phase 1; Core only runs finalize_scan.
    """
    recon = await execute_recon_local(scan_id)
    if recon.get("cancelled"):
        return recon
    return await finalize_scan(scan_id)


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
        result = await _daily_scan_sweep()
        complete_cron_run(DAILY_SCAN_CRON_NAME, run_day)
    except BaseException:
        release_cron_run(DAILY_SCAN_CRON_NAME, run_day)
        raise
    result["claimed"] = True
    return result


def _claimant_id() -> str:
    """Identify which process holds the cron claim (debugging aid)."""
    return f"{socket.gethostname()}:{os.getpid()}"


async def _daily_scan_sweep() -> Dict[str, Any]:
    due_domains = execute_query(
        """
        SELECT d.id AS domain_id, d.org_id, d.domain
        FROM domains d
        WHERE d.verification_status = 'verified'
          AND NOT EXISTS (
            SELECT 1 FROM scans s
            WHERE s.org_id = d.org_id
              AND s.status IN ('queued', 'running')
          )
        ORDER BY d.created_at ASC
        """
    ) or []

    scheduled = 0
    skipped_quota = 0
    stage_progress = _queued_stage_progress()

    # Plan quotas apply to automation too (review P1 line 33) — an org at
    # its monthly scan limit is skipped instead of burning quota.
    plan_rows = execute_query("SELECT id, plan FROM organizations") or []
    plan_of = {
        str(r["id"]): ((r.get("plan") or "").strip().lower() or LEGACY_PLAN_FALLBACK)
        for r in plan_rows
    }

    for row in due_domains:
        slug = plan_of.get(str(row["org_id"]), LEGACY_PLAN_FALLBACK)
        quota = PLANS.get(slug, PLANS[LEGACY_PLAN_FALLBACK])["monthly_scans"]
        if quota is not None:
            # Module-level execute_one so tests can fake it; None row = 0.
            used_row = execute_one(
                """
                SELECT count(*) AS n FROM scans
                WHERE org_id = %s AND created_at >= date_trunc('month', now())
                """,
                (str(row["org_id"]),),
            )
            if (used_row or {}).get("n", 0) >= quota:
                skipped_quota += 1
                continue
        new_scan = execute_one(
            """
            INSERT INTO scans (org_id, domain_id, scan_type, status, current_stage, stage_progress)
            VALUES (%s, %s, 'EXTERNAL_ASSESSMENT', 'queued', 'queued', %s::jsonb)
            RETURNING id
            """,
            (row["org_id"], row["domain_id"], json.dumps(stage_progress)),
        )
        if not new_scan:
            continue

        scan_id = str(new_scan["id"])
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
                    execute_query(
                        "UPDATE scans SET status = 'failed', error_message = %s, completed_at = now() WHERE id = %s AND status IN ('queued', 'running')",
                        (str(inline_err), scan_id),
                    )
                    continue

        scheduled += 1
        log_audit(row["org_id"], None, "scan.scheduled", "scan", scan_id, {
            "domain": row["domain"],
            "trigger": "cron",
        })

    log_audit(None, None, "cron.ran", "scheduler", None, {
        "due_domains": len(due_domains),
        "scheduled": scheduled,
        "skipped_quota": skipped_quota,
        "trigger": "cron",
    })

    return {"due_domains": len(due_domains), "scheduled": scheduled,
            "skipped_quota": skipped_quota}


@inngest_client.create_function(
    fn_id="cyphward-daily-scan-scheduler",
    trigger=inngest.TriggerCron(cron="0 6 * * *"),
)
async def inngest_daily_scan_cron(ctx: inngest.Context) -> Dict[str, Any]:
    """Inngest platform cron entry point (06:00 UTC). Delegates to the shared
    daily scan schedule; only fires when the Inngest app is registered."""
    return await run_daily_scan_schedule()
