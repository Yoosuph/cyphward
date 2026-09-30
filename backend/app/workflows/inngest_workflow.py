"""
Cyphward Inngest Scan Pipeline & Asynchronous Execution Engine
Implements the multi-stage scanning pipeline:
Discovery -> DNS -> HTTP -> Security Checks -> Nuclei -> Normalization -> Risk Scoring -> AI Analysis
Also hosts the daily scheduled-scan cron for verified domains.
"""
import time
import json
import asyncio
from typing import Dict, Any, List, Optional
import inngest

from backend.app.core.database import execute_one, execute_query, execute_many, get_db
from backend.app.core.auth import log_audit
from backend.app.scanner.discovery import discover_subdomains
from backend.app.scanner.dns_resolver import resolve_host_dns
from backend.app.scanner.http_probe import probe_http_service
from backend.app.scanner.security_checks import run_security_checks
from backend.app.scanner.nuclei_runner import run_nuclei_batch
from backend.app.scanner.normalizer import normalize_findings
from backend.app.risk.engine import compute_risk_score
from backend.app.ai.factory import get_ai_provider
from backend.app.services.notifications import notify
from backend.app.services.mailer import send_email_async

import os

is_prod = os.getenv("INNGEST_IS_PRODUCTION", "false").lower() in ("true", "1")
signing_key = os.getenv("INNGEST_SIGNING_KEY")
inngest_client = inngest.Inngest(
    app_id="cyphward",
    is_production=is_prod if signing_key else False,
    signing_key=signing_key
)

DNS_HOST_CAP = 40


def _queued_stage_progress() -> Dict[str, Any]:
    return {
        "discovery": {"status": "queued", "items": 0, "duration_ms": 0},
        "dns": {"status": "queued", "items": 0, "duration_ms": 0},
        "http": {"status": "queued", "items": 0, "duration_ms": 0},
        "security_checks": {"status": "queued", "items": 0, "duration_ms": 0},
        "nuclei": {"status": "queued", "items": 0, "duration_ms": 0},
        "normalization": {"status": "queued", "items": 0, "duration_ms": 0},
        "scoring": {"status": "queued", "score": None, "duration_ms": 0},
        "ai_analysis": {"status": "queued", "items": 0, "duration_ms": 0},
    }


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


async def execute_scan_pipeline(scan_id: str) -> Dict[str, Any]:
    """
    Execute the end-to-end 6-stage security scanning pipeline for a scan record.
    Tracks live stage progress, records raw scan results, populates assets,
    normalizes findings (upsert by org/asset/title), and updates the 0-100 score.
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

    progress = {
        "discovery": {"status": "running", "items": 0, "duration_ms": 0},
        "dns": {"status": "pending", "items": 0, "duration_ms": 0},
        "http": {"status": "pending", "items": 0, "duration_ms": 0},
        "security_checks": {"status": "pending", "items": 0, "duration_ms": 0},
        "nuclei": {"status": "pending", "items": 0, "duration_ms": 0},
        "normalization": {"status": "pending", "items": 0, "duration_ms": 0},
        "scoring": {"status": "pending", "score": None, "duration_ms": 0},
        "ai_analysis": {"status": "pending", "items": 0, "duration_ms": 0}
    }

    execute_query("""
        UPDATE scans
        SET status = 'running', current_stage = 'discovery', started_at = now(), stage_progress = %s::jsonb
        WHERE id = %s
    """, (json.dumps(progress), scan_id))

    email_jobs: List[Dict[str, Any]] = []

    try:
        # ---------------------------------------------------------------------
        # STAGE 1: Passive Subdomain Discovery
        # ---------------------------------------------------------------------
        t0 = time.time()
        discovered_hosts = await discover_subdomains(domain)
        d_dur = int((time.time() - t0) * 1000)

        progress["discovery"] = {"status": "completed", "items": len(discovered_hosts), "duration_ms": d_dur}
        progress["dns"]["status"] = "running"

        execute_query("""
            UPDATE scans
            SET current_stage = 'dns', stage_progress = %s::jsonb
            WHERE id = %s
        """, (json.dumps(progress), scan_id))

        execute_query("""
            INSERT INTO scan_results (scan_id, stage, raw_data)
            VALUES (%s, 'discovery', %s::jsonb)
        """, (scan_id, json.dumps({"discovered_hosts": discovered_hosts})))

        # ---------------------------------------------------------------------
        # STAGE 2: DNS Resolution
        # ---------------------------------------------------------------------
        t0 = time.time()
        dns_tasks = [resolve_host_dns(h) for h in discovered_hosts[:DNS_HOST_CAP]]
        dns_results = await asyncio.gather(*dns_tasks, return_exceptions=True)
        valid_dns = [r for r in dns_results if isinstance(r, dict)]
        dns_dur = int((time.time() - t0) * 1000)

        progress["dns"] = {"status": "completed", "items": len(valid_dns), "duration_ms": dns_dur}
        progress["http"]["status"] = "running"

        execute_query("""
            UPDATE scans
            SET current_stage = 'http', stage_progress = %s::jsonb
            WHERE id = %s
        """, (json.dumps(progress), scan_id))

        execute_query("""
            INSERT INTO scan_results (scan_id, stage, raw_data)
            VALUES (%s, 'dns', %s::jsonb)
        """, (scan_id, json.dumps({"dns_records": valid_dns})))

        # ---------------------------------------------------------------------
        # STAGE 3: HTTP/HTTPS Probing
        # ---------------------------------------------------------------------
        t0 = time.time()
        http_tasks = [probe_http_service(h["hostname"]) for h in valid_dns]
        http_results = await asyncio.gather(*http_tasks, return_exceptions=True)
        valid_http = [r for r in http_results if isinstance(r, dict)]
        http_dur = int((time.time() - t0) * 1000)

        progress["http"] = {"status": "completed", "items": len(valid_http), "duration_ms": http_dur}
        progress["security_checks"]["status"] = "running"

        execute_query("""
            UPDATE scans
            SET current_stage = 'security_checks', stage_progress = %s::jsonb
            WHERE id = %s
        """, (json.dumps(progress), scan_id))

        execute_query("""
            INSERT INTO scan_results (scan_id, stage, raw_data)
            VALUES (%s, 'http', %s::jsonb)
        """, (scan_id, json.dumps({"http_probes": valid_http})))

        # Populate per-scan target inventory
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

        # Upsert discovered assets into the inventory
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

            res = execute_one("""
                INSERT INTO assets (org_id, domain_id, hostname, ip_address, asset_type, status, http_status, technologies, tls_info, dns_records, last_seen)
                VALUES (%s, %s, %s, %s, %s, 'active', %s, %s::jsonb, %s::jsonb, %s::jsonb, now())
                ON CONFLICT (org_id, hostname)
                DO UPDATE SET
                    ip_address = EXCLUDED.ip_address,
                    http_status = EXCLUDED.http_status,
                    technologies = EXCLUDED.technologies,
                    tls_info = EXCLUDED.tls_info,
                    dns_records = EXCLUDED.dns_records,
                    last_seen = now()
                RETURNING id;
            """, (org_id, domain_id, hname, ip, atype, http_status, json.dumps(techs), json.dumps(tls), json.dumps(records)))

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
        # STAGE 4: Security Checks + Nuclei Vulnerability Scanning
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
        raw_check_findings = []
        for idx, chk_results in enumerate(check_results_list):
            if isinstance(chk_results, list):
                hname = dns_list[idx]["hostname"]
                for cr in chk_results:
                    cr["_hostname"] = hname
                raw_check_findings.extend(chk_results)

        sec_dur = int((time.time() - t0) * 1000)
        progress["security_checks"] = {"status": "completed", "items": len(raw_check_findings), "duration_ms": sec_dur}
        progress["nuclei"]["status"] = "running"

        execute_query("""
            UPDATE scans
            SET current_stage = 'nuclei', stage_progress = %s::jsonb
            WHERE id = %s
        """, (json.dumps(progress), scan_id))

        # ---------------------------------------------------------------------
        # STAGE 4b: Nuclei Deep Vulnerability Scanning
        # ---------------------------------------------------------------------
        t0 = time.time()
        active_hosts = [h["hostname"] for h in valid_dns if any(
            hp.get("hostname") == h["hostname"] and hp.get("http_status")
            for hp in valid_http
        )]
        nuclei_findings = await run_nuclei_batch(active_hosts, concurrency=10, timeout=300)
        for nf in nuclei_findings:
            if not nf.get("_hostname"):
                nf["_hostname"] = nf.get("evidence", {}).get("host") or domain
        raw_check_findings.extend(nuclei_findings)
        nuclei_dur = int((time.time() - t0) * 1000)

        progress["nuclei"] = {"status": "completed", "items": len(nuclei_findings), "duration_ms": nuclei_dur}
        progress["normalization"]["status"] = "running"

        execute_query("""
            UPDATE scans
            SET current_stage = 'normalization', stage_progress = %s::jsonb
            WHERE id = %s
        """, (json.dumps(progress), scan_id))

        execute_query("""
            INSERT INTO scan_results (scan_id, stage, raw_data)
            VALUES (%s, 'security_checks', %s::jsonb)
        """, (scan_id, json.dumps({"findings_count": len(raw_check_findings)})))

        # ---------------------------------------------------------------------
        # STAGE 5: Finding Normalization, Upsert, Baseline Diff, Evidence
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
        baseline = {"new": [], "reopened": [], "resolved": []}

        if scanned_asset_ids:
            existing_findings = execute_query(
                """
                SELECT id, asset_id, title, status, severity, description, category, evidence, remediation
                FROM findings
                WHERE org_id = %s AND asset_id = ANY(%s)
                """,
                (org_id, scanned_asset_ids),
            ) or []
            existing_map = {(f["asset_id"], f["title"]): f for f in existing_findings}
            observed_by_asset: Dict[str, set] = {aid: set() for aid in scanned_asset_ids}

            for nf in normalized_all:
                asset_id = nf.get("asset_id")
                if not asset_id:
                    continue
                observed_by_asset.setdefault(asset_id, set()).add(nf["title"])
                prior = existing_map.get((asset_id, nf["title"]))

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
            for aid, observed in observed_by_asset.items():
                for f in existing_findings:
                    if f["asset_id"] == aid and f["title"] not in observed and f["status"] != "resolved":
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
                            "hostname": hostname_by_asset.get(str(f["asset_id"])) or hostname_by_asset.get(f["asset_id"]),
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

        execute_query("""
            UPDATE scans
            SET current_stage = 'scoring', stage_progress = %s::jsonb
            WHERE id = %s
        """, (json.dumps(progress), scan_id))

        # ---------------------------------------------------------------------
        # STAGE 6: Deterministic Risk Scoring
        # ---------------------------------------------------------------------
        t0 = time.time()
        score_result = compute_risk_score(normalized_all)
        final_score = score_result["score"]
        score_dur = int((time.time() - t0) * 1000)

        progress["scoring"] = {"status": "completed", "score": final_score, "duration_ms": score_dur}

        execute_query("""
            UPDATE scans
            SET status = 'completed', current_stage = 'completed', score = %s, stage_progress = %s::jsonb, completed_at = now()
            WHERE id = %s
        """, (final_score, json.dumps(progress), scan_id))

        # Record Score Snapshot
        execute_query("""
            INSERT INTO score_snapshots (org_id, domain_id, score, subscores, factors)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
        """, (org_id, domain_id, final_score, json.dumps(score_result["subscores"]), json.dumps(score_result["factors"])))

        notify(
            org_id, "scan_completed",
            f"Scan completed for {domain}",
            f"Score {final_score}/100 · {len(normalized_all)} findings observed · {len(baseline['new'])} new · {len(baseline['resolved'])} resolved.",
            "info" if final_score >= 70 else "medium",
            "/scans",
        )

        # ---------------------------------------------------------------------
        # STAGE 7: AI Security Analysis
        # ---------------------------------------------------------------------
        t0 = time.time()
        progress["ai_analysis"]["status"] = "running"

        execute_query("""
            UPDATE scans
            SET current_stage = 'ai_analysis', stage_progress = %s::jsonb
            WHERE id = %s
        """, (json.dumps(progress), scan_id))

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
            WHERE id = %s
        """, (json.dumps(progress), scan_id))

        log_audit(org_id, None, "scan.completed", "scan", scan_id, {
            "domain": domain,
            "score": final_score,
            "findings": len(normalized_all),
            "new": len(baseline["new"]),
            "reopened": len(baseline["reopened"]),
            "resolved": len(baseline["resolved"]),
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
            "ai_analyzed": len(ai_explanations),
        }

    except Exception as exc:
        progress["error"] = str(exc)
        execute_query("""
            UPDATE scans
            SET status = 'failed', error_message = %s, stage_progress = %s::jsonb, completed_at = now()
            WHERE id = %s
        """, (str(exc), json.dumps(progress), scan_id))
        raise


# Define Inngest Function definition for Inngest dev server / cloud
@inngest_client.create_function(
    fn_id="cyphward-scan-pipeline",
    trigger=inngest.TriggerEvent(event="scan.requested")
)
async def inngest_scan_pipeline_fn(ctx: inngest.Context) -> Dict[str, Any]:
    """Inngest Multi-Step Workflow function."""
    scan_id = ctx.event.data.get("scan_id")
    if not scan_id:
        raise ValueError("Missing scan_id in event data.")
    return await execute_scan_pipeline(scan_id)


@inngest_client.create_function(
    fn_id="cyphward-daily-scan-scheduler",
    trigger=inngest.TriggerCron(cron="0 6 * * *"),
)
async def inngest_daily_scan_cron(ctx: inngest.Context) -> Dict[str, Any]:
    """
    Daily scheduled scans: one scan per verified domain for orgs that do not
    already have a queued/running scan (baseline drift detection).
    """
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
    stage_progress = _queued_stage_progress()

    for row in due_domains:
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
        except Exception:
            # Event gateway unavailable — run inline so the schedule still fires
            try:
                await execute_scan_pipeline(scan_id)
            except Exception as inline_err:
                execute_query(
                    "UPDATE scans SET status = 'failed', error_message = %s, completed_at = now() WHERE id = %s",
                    (str(inline_err), scan_id),
                )
                continue

        scheduled += 1
        log_audit(row["org_id"], None, "scan.scheduled", "scan", scan_id, {
            "domain": row["domain"],
            "trigger": "cron",
        })

    return {"due_domains": len(due_domains), "scheduled": scheduled}
