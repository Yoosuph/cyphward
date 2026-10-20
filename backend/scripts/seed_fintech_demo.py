#!/usr/bin/env python3
"""Sample-data demo organisation "Fintech Org" for investor walkthroughs.

    python -m backend.scripts.seed_fintech_demo seed   --database-url URL            # dry run (default)
    python -m backend.scripts.seed_fintech_demo seed   --database-url URL --apply
    python -m backend.scripts.seed_fintech_demo unseed --database-url URL --apply

Rules this file enforces:
    - Dry run unless --apply is given. A dry run writes nothing.
    - Writes only to the URL given explicitly (or CYPHWARD_DEMO_DATABASE_URL). No .env, no DATABASE_URL fallback.
    - Default --target local: loopback host and database cyphward_test or cyphward_demo only.
    - --target production needs --confirm-production with the exact phrase below.
    - Every row belongs to the fixed demo organisation id, and the demo owner has the fixed user id. Unseed
      deletes the organisation (the database cascades to its rows) and the demo owner, and only after it has
      checked that the organisation, its members, its domain and the owner look exactly as the seed wrote them.
    - The domain scanme.nmap.org stays `pending` with a sample token that was never issued. Nothing here verifies
      it, so scanning and organisation-level grading stay closed exactly as they are for an unverified domain.
    - Per-scan grades come from the existing risk engine (backend/app/risk/engine.py). The seed supplies its own
      assessment with the same shape as a completed scan, because a pending domain cannot produce an organisation
      assessment through the live path.
    - Nothing is sent: no mail, no notification rows, no subscription with a provider, no invoices.
    - Attestations, incidents, the readiness pack and the drafts go through the app's own functions, which run
      their own transactions. If that second phase fails, the organisation is deleted again.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from backend.app.core import demo_org

# ── Fixed identities (never reused by real data) ─────────────────────────────
DEMO_ORG_ID = demo_org.DEMO_ORG_ID  # the app excludes these ids from production metrics (core/demo_org.py)
DEMO_USER_ID = demo_org.DEMO_USER_ID
DEMO_ORG_NAME = "Fintech Org (SAMPLE DATA)"
DEMO_SLUG = "fintech-org-sample-data"
DEMO_EMAIL = "demo.owner@fintech-org.test"  # .test is reserved; nothing is delivered to it
DEMO_NAME = "Sample Owner (SAMPLE DATA)"
DEMO_DOMAIN = "scanme.nmap.org"
DEMO_TOKEN = "sample-data-not-issued"
SAMPLE_LABEL = "SAMPLE DATA"
SAMPLE_NOTE = "Synthetic sample evidence for the demo organisation. Not observed on scanme.nmap.org."

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
LOCAL_DATABASES = {"cyphward_test", "cyphward_demo"}
PRODUCTION_CONFIRMATION = "SEED-FINTECH-DEMO-IN-PRODUCTION"
DEMO_PASSWORD_ENV = "CYPHWARD_DEMO_PASSWORD"
MIN_PASSWORD_LENGTH = 8  # the app's own policy (auth._check_password_policy)

# Owned by the demo organisation; the cascade removes everything else keyed to it.
ORG_SCOPED_TABLES = (
    "organization_members", "domains", "assets", "scans", "findings", "score_snapshots",
    "subscriptions", "audit_log", "compliance_attestations", "compliance_incidents", "compliance_evidence",
    "evidence_packs", "assessment_snapshots", "compliance_documents", "compliance_document_quota",
    "compliance_document_approvals", "remediation_tasks", "notifications", "reports",
)

# ── Scans: three completed sample assessments, oldest first ──────────────────
SCANS = (
    {"key": "scan-1", "days_ago": 62},
    {"key": "scan-2", "days_ago": 31},
    {"key": "scan-3", "days_ago": 3},
)

# Scoring coverage in the same shape the scanner writes (backend/app/risk/coverage.py); the label says sample.
COVERAGE = {
    "version": 2, "check_set": "cyphward-checks-v1", "state": "complete", "evaluated_checks": 5,
    "requested_checks": 5, "missing": [], "omitted_checks": [],
    "label": f"{SAMPLE_LABEL}: synthetic coverage for {DEMO_DOMAIN}",
    "targets": {"selected": 1, "in_scope": 1, "assessed": 1}, "nuclei": {"state": "not_run"},
}

# ── Findings: `first` and `resolved` are scan numbers (1-based). `resolved` is the scan that no longer saw it.
FINDINGS: Tuple[Dict[str, Any], ...] = (
    {"key": "tls-legacy", "title": "SAMPLE: TLS 1.0 still accepted", "severity": "critical",
     "category": "TLS Configuration", "first": 1, "resolved": 3, "status": "resolved",
     "description": "Sample finding: the sample host is described as accepting TLS 1.0 handshakes.",
     "remediation": "Disable TLS 1.0 and 1.1 on every listener and retest with a current TLS client."},
    {"key": "hsts", "title": "SAMPLE: HSTS header not set", "severity": "high",
     "category": "HTTP Headers", "first": 1, "resolved": 3, "status": "resolved",
     "description": "Sample finding: the sample response is described as lacking Strict-Transport-Security.",
     "remediation": "Send Strict-Transport-Security with max-age of at least six months on HTTPS responses."},
    {"key": "spf-all", "title": "SAMPLE: SPF policy ends in +all", "severity": "high",
     "category": "Email Authentication", "first": 1, "resolved": None, "status": "in_progress",
     "description": "Sample finding: the sample domain's SPF record is described as allowing any sender.",
     "remediation": "End the SPF record with -all or ~all and list only the real sending services."},
    {"key": "dmarc-none", "title": "SAMPLE: DMARC policy set to none", "severity": "high",
     "category": "Email Authentication", "first": 2, "resolved": None, "status": "open",
     "description": "Sample finding: the sample DMARC record is described as monitoring only (p=none).",
     "remediation": "Publish reports, then move the DMARC policy to quarantine and finally reject."},
    {"key": "csp", "title": "SAMPLE: Content-Security-Policy header not set", "severity": "medium",
     "category": "HTTP Headers", "first": 1, "resolved": 2, "status": "resolved",
     "description": "Sample finding: the sample response is described as lacking a Content-Security-Policy.",
     "remediation": "Add a Content-Security-Policy that starts from default-src 'self' and tighten it over time."},
    {"key": "xfo", "title": "SAMPLE: X-Frame-Options header not set", "severity": "medium",
     "category": "HTTP Headers", "first": 1, "resolved": None, "status": "open",
     "description": "Sample finding: the sample response is described as lacking clickjacking protection.",
     "remediation": "Send frame-ancestors in the CSP, or X-Frame-Options: DENY on pages that must not be framed."},
    {"key": "cert-expiry", "title": "SAMPLE: TLS certificate expires within 30 days", "severity": "medium",
     "category": "TLS Configuration", "first": 2, "resolved": 3, "status": "resolved",
     "description": "Sample finding: the sample certificate is described as expiring within thirty days.",
     "remediation": "Renew the certificate and automate renewal so expiry is not a manual task."},
    {"key": "version-leak", "title": "SAMPLE: Server software version disclosed", "severity": "medium",
     "category": "Information Disclosure", "first": 1, "resolved": None, "status": "acknowledged",
     "description": "Sample finding: the sample response is described as naming its server software and version.",
     "remediation": "Remove version strings from the Server and X-Powered-By headers."},
    {"key": "security-txt", "title": "SAMPLE: security.txt contact file not published", "severity": "low",
     "category": "Information Disclosure", "first": 1, "resolved": None, "status": "open",
     "description": "Sample finding: the sample host is described as having no published security contact file.",
     "remediation": "Publish /.well-known/security.txt with a monitored contact address and an expiry date."},
    {"key": "samesite", "title": "SAMPLE: Cookies without SameSite attribute", "severity": "low",
     "category": "HTTP Headers", "first": 3, "resolved": None, "status": "open",
     "description": "Sample finding: a sample cookie is described as missing the SameSite attribute.",
     "remediation": "Set SameSite=Lax or Strict on session cookies that do not need cross-site use."},
    {"key": "referrer", "title": "SAMPLE: Referrer-Policy header not set", "severity": "low",
     "category": "HTTP Headers", "first": 2, "resolved": None, "status": "open",
     "description": "Sample finding: the sample response is described as lacking a Referrer-Policy.",
     "remediation": "Send Referrer-Policy: strict-origin-when-cross-origin."},
)

# ── Questionnaire answers: (question key, answer, expiry in days or None to use the question's rule)
ATTESTATIONS: Tuple[Tuple[str, Any], ...] = (
    ("registration.major_importance", {"value": "no"}),
    ("registration.registered", {"value": "yes"}),
    ("registration.car_filed", {"value": "no"}),
    ("dpo.designated", {"value": "yes"}),
    ("dpo.contact_published", {"value": "yes"}),
    ("dpo.reports_to_management", {"value": "no"}),
    ("dpo.six_monthly_report", {"value": "date", "date": "2026-06-30"}),
    ("breach.response_plan", {"value": "yes"}),
    ("breach.notification_process", {"value": "yes"}),
    ("breach.incident_log", {"value": "yes"}),
    ("dpia.high_risk_processing", {"value": "yes"}),
    ("dpia.done", {"value": "no"}),
    ("lawful_basis.documented", {"value": "yes"}),
    ("consent.records_kept", {"value": "no"}),
    ("rights.process", {"value": "yes"}),
    ("transfers.outside_nigeria", {"value": "yes"}),
    ("transfers.identified", {"value": "yes"}),
    ("training.in_place", {"value": "yes"}),
    ("training.last_session", {"value": "date", "date": "2026-03-15"}),
)

# ── Incidents (days relative to the seed time) ───────────────────────────────
INCIDENTS = (
    {"title": "SAMPLE: Statement sent to a wrong customer address", "severity": "medium", "status": "contained",
     "detected_days_ago": 20, "aware_hours_after_detection": 2, "commission_hours_after_aware": 20,
     "notes": "Sample incident. Two statements were mailed to the same wrong address; the mailbox owner confirmed deletion."},
    {"title": "SAMPLE: Repeated sign-in failures on customer login", "severity": "high", "status": "open",
     "detected_days_ago": 2, "aware_hours_after_detection": 1, "commission_hours_after_aware": None,
     "notes": "Sample incident. Login throttling triggered; no account takeover is recorded in this sample."},
)

# ── Requirement evidence records (register keys from compliance/registers/ndpa_gaid_v1.json) ─
# status is one of present / gap / not_assessed. Tool-observed rows link to findings where relevant.
EVIDENCE: Tuple[Tuple[str, str, str, Optional[str]], ...] = (
    ("ndpa.s39.encryption_in_transit", "tool_observed", "present", "tls-legacy"),
    ("ndpa.s39.web_security_headers", "tool_observed", "gap", "xfo"),
    ("ndpa.s39.email_anti_spoofing", "tool_observed", "gap", "spf-all"),
    ("ndpa.s39.exposed_services_inventoried", "tool_observed", "not_assessed", None),
    ("ndpa.s39.known_vulnerability_testing", "tool_observed", "not_assessed", None),
    ("gaid.notice.privacy_policy", "externally_observed", "not_assessed", None),
    ("gaid.dpo.designated", "customer_attested", "present", None),
    ("gaid.registration.annual_car", "customer_attested", "gap", None),
)

REMEDIATION_TASKS = (
    {"finding": "spf-all", "title": "SAMPLE: Tighten the SPF record", "priority": "high", "status": "in_progress",
     "days_until_due": 14},
    {"finding": "dmarc-none", "title": "SAMPLE: Move DMARC to quarantine after report review", "priority": "high",
     "status": "open", "days_until_due": 30},
)


# ── Target guard ─────────────────────────────────────────────────────────────
class RefusedTarget(Exception):
    """The URL or target flags do not allow a write."""


class Refused(Exception):
    """The database does not look like the demo organisation (or is missing it)."""


def check_target(url: str, target: str, confirm: Optional[str]) -> Dict[str, Any]:
    """Return the parsed connection info, or raise RefusedTarget. Never connects."""
    if not url:
        raise RefusedTarget("No database URL given. Pass --database-url or set CYPHWARD_DEMO_DATABASE_URL.")
    info = conninfo_to_dict(url)
    host = str(info.get("host") or "")
    name = str(info.get("dbname") or "")
    if target == "local":
        if host not in LOOPBACK_HOSTS or name not in LOCAL_DATABASES:
            raise RefusedTarget(
                f"--target local only writes to a loopback database named one of {sorted(LOCAL_DATABASES)}; "
                f"got host {host!r}, database {name!r}. For production use --target production."
            )
    elif target == "production":
        if confirm != PRODUCTION_CONFIRMATION:
            raise RefusedTarget(
                f"--target production writes to a live database. Pass --confirm-production {PRODUCTION_CONFIRMATION}"
            )
    else:
        raise RefusedTarget(f"Unknown target {target!r}.")
    return info


def _configure_app(url: str) -> None:
    """Point the app's own modules at the explicit URL before they are imported.

    `config` loads .env files without overriding existing variables, so setting these first means no other
    database can be reached. Document drafts stay on the deterministic template: the model path is off.
    """
    os.environ["DATABASE_URL"] = url
    os.environ["COMPLIANCE_DOCS_MODEL"] = "off"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days(now: datetime, days: float) -> datetime:
    return now - timedelta(days=days)


# ── Scoring replay (pure; uses the risk engine) ──────────────────────────────
def observed_in(scan_number: int) -> List[Dict[str, Any]]:
    """Findings the scan with this number saw: first seen by it and not yet resolved before it."""
    seen = []
    for finding in FINDINGS:
        resolved = finding["resolved"]
        if finding["first"] <= scan_number and (resolved is None or resolved > scan_number):
            seen.append(finding)
    return seen


def score_scan(scan_number: int, scan_id: str, domain_id: str, completed_at: datetime) -> Dict[str, Any]:
    from backend.app.risk.engine import SCORE_MODEL, compute_risk_score

    rows = [
        {"title": f["title"], "severity": f["severity"], "category": f["category"], "evidence": {}, "status": "open"}
        for f in observed_in(scan_number)
    ]
    assessment = {
        "scan_id": scan_id, "status": "completed", "completed_at": completed_at.isoformat(),
        "model": SCORE_MODEL, "coverage": COVERAGE,
        "domains": [{"domain_id": domain_id, "domain": DEMO_DOMAIN, "scan_id": scan_id,
                     "completed_at": completed_at.isoformat(), "state": "complete"}],
    }
    return compute_risk_score(rows, assessment=assessment)


# ── Plan (dry run) ───────────────────────────────────────────────────────────
def plan_counts() -> Dict[str, int]:
    open_now = observed_in(len(SCANS))
    return {
        "organisation": 1, "owner profile": 1, "owner membership": 1, "subscription (trialing, manual)": 1,
        "domain (pending, sample token)": 1, "asset (scanme.nmap.org)": 1,
        "scans (completed)": len(SCANS), "findings (across scans)": len(FINDINGS),
        "findings open in latest scan": len(open_now), "score snapshots": len(SCANS),
        "attestation answers": len(ATTESTATIONS), "incidents": len(INCIDENTS),
        "evidence records": len(EVIDENCE), "remediation tasks": len(REMEDIATION_TASKS),
        "audit rows (seed actions)": 2 + len(SCANS),
        "readiness pack": 1, "draft documents": 4,
    }


def _fingerprint_row(conn) -> Optional[Dict[str, Any]]:
    return conn.execute("SELECT * FROM organizations WHERE id = %s", (DEMO_ORG_ID,)).fetchone()


def _looks_like_demo(conn) -> bool:
    org = _fingerprint_row(conn)
    if not org or org["name"] != DEMO_ORG_NAME or org["slug"] != DEMO_SLUG:
        return False
    members = [str(r["user_id"]) for r in conn.execute(
        "SELECT user_id FROM organization_members WHERE org_id = %s", (DEMO_ORG_ID,)).fetchall()]
    if members != [DEMO_USER_ID]:
        return False
    profile = conn.execute("SELECT email FROM profiles WHERE id = %s", (DEMO_USER_ID,)).fetchone()
    return bool(profile) and profile["email"] == DEMO_EMAIL


def status(url: str) -> str:
    """Describe what is in the target right now, without writing."""
    with psycopg.connect(url, row_factory=dict_row) as conn:
        if _fingerprint_row(conn) is None:
            return "absent"
        return "seeded" if _looks_like_demo(conn) else "conflict"


# ── Seed ─────────────────────────────────────────────────────────────────────
def _insert_identity(cur, password_hash: str) -> None:
    # The same INSERT the app's /register path uses, with the fixed demo id.
    cur.execute(
        "INSERT INTO profiles (id, email, full_name, role, password_hash, provider) "
        "VALUES (%s, %s, %s, 'Member', %s, 'email')",
        (DEMO_USER_ID, DEMO_EMAIL, DEMO_NAME, password_hash),
    )


def _insert_organisation(cur, now: datetime) -> None:
    # Member role: password sign-in needs no emailed step-up code (owners and admins always get one).
    # Mirrors api/organizations.py for the trial: a manual trialing subscription. The trial is extended to
    # 90 days so a walkthrough a few weeks later still has full quotas.
    cur.execute(
        "INSERT INTO organizations (id, name, slug, sector, plan, created_at, updated_at) "
        "VALUES (%s, %s, %s, 'Fintech & Digital Commerce', 'growth', %s, %s)",
        (DEMO_ORG_ID, DEMO_ORG_NAME, DEMO_SLUG, _days(now, 62), now),
    )
    cur.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s, %s, 'member')",
                (DEMO_USER_ID, DEMO_ORG_ID))
    cur.execute(
        "INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, current_period_end, "
        "trial_ends_at) VALUES (%s, 'growth', 'trialing', 'manual', %s, %s, %s)",
        (DEMO_ORG_ID, now, now + timedelta(days=90), now + timedelta(days=90)),
    )
    cur.execute(
        "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata, created_at) "
        "VALUES (%s, %s, 'org.created', 'organization', %s, %s::jsonb, %s)",
        (DEMO_ORG_ID, DEMO_USER_ID, DEMO_ORG_ID, json.dumps({"slug": DEMO_SLUG, "plan": "growth",
                                                            "sample": True}), _days(now, 62)),
    )


def _insert_domain_and_assets(cur, now: datetime) -> str:
    domain_id = cur.execute(
        "INSERT INTO domains (org_id, domain, verification_status, verification_token, verified_at, created_at, "
        "updated_at) VALUES (%s, %s, 'pending', %s, NULL, %s, %s) RETURNING id",
        (DEMO_ORG_ID, DEMO_DOMAIN, DEMO_TOKEN, _days(now, 62), now),
    ).fetchone()["id"]
    cur.execute(
        "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata, created_at) "
        "VALUES (%s, %s, 'domain.added', 'domain', %s, %s::jsonb, %s)",
        (DEMO_ORG_ID, DEMO_USER_ID, str(domain_id), json.dumps({"domain": DEMO_DOMAIN, "sample": True,
                                                               "verification_status": "pending"}),
         _days(now, 62)),
    )
    return str(domain_id)


def _insert_scans_and_findings(cur, now: datetime, domain_id: str) -> Tuple[str, Dict[str, str]]:
    asset_id = cur.execute(
        "INSERT INTO assets (org_id, domain_id, hostname, asset_type, status, first_seen, last_seen) "
        "VALUES (%s, %s, %s, 'Web Endpoint', 'active', %s, %s) RETURNING id",
        (DEMO_ORG_ID, domain_id, DEMO_DOMAIN, _days(now, 62), _days(now, 3)),
    ).fetchone()["id"]
    scan_ids: Dict[str, str] = {}
    scan_times: Dict[int, datetime] = {}
    scan_scores: Dict[int, Dict[str, Any]] = {}
    for number, spec in enumerate(SCANS, start=1):
        completed = _days(now, spec["days_ago"])
        scan_id = str(uuid.uuid4())
        scan_ids[spec["key"]] = scan_id
        scan_times[number] = completed
        score = score_scan(number, scan_id, domain_id, completed)
        scan_scores[number] = score
        progress = {
            "dns": {"items": 1, "status": "completed", "duration_ms": 0},
            "http": {"items": 1, "status": "completed", "duration_ms": 0},
            "discovery": {"items": 1, "status": "completed", "duration_ms": 0},
            "normalization": {"items": 1, "status": "completed", "duration_ms": 0},
            "security_checks": {"items": len(observed_in(number)), "status": "completed", "duration_ms": 0},
            "scoring": {"status": "completed", "score": score["score"], "coverage": COVERAGE,
                        "label": SAMPLE_LABEL},
        }
        cur.execute(
            "INSERT INTO scans (id, org_id, domain_id, status, score, stage_progress, current_stage, started_at, "
            "completed_at, created_at) VALUES (%s, %s, %s, 'completed', %s, %s::jsonb, 'completed', %s, %s, %s)",
            (scan_id, DEMO_ORG_ID, domain_id, score["score"], json.dumps(progress), completed - timedelta(minutes=12),
             completed, completed - timedelta(minutes=13)),
        )
        cur.execute(
            "INSERT INTO score_snapshots (org_id, domain_id, score, subscores, factors, model, scope, risk_points, "
            "scan_id, assessment_coverage, created_at) VALUES (%s, NULL, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, "
            "%s::jsonb, %s)",
            (DEMO_ORG_ID, score["score"], json.dumps(score["subscores"], default=str),
             json.dumps(score["factors"], default=str), score["model"], score["scope"], score["risk_points"],
             scan_id, json.dumps(COVERAGE), completed),
        )
        cur.execute(
            "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata, created_at) "
            "VALUES (%s, NULL, 'scan.completed', 'scan', %s, %s::jsonb, %s)",
            (DEMO_ORG_ID, scan_id, json.dumps({"sample": True, "score": score["score"], "grade": score["grade"],
                                               "findings": len(observed_in(number))}), completed),
        )

    finding_ids: Dict[str, str] = {}
    for finding in FINDINGS:
        first_scan_id = scan_ids[SCANS[finding["first"] - 1]["key"]]
        first_seen = scan_times[finding["first"]]
        last_number = (finding["resolved"] - 1) if finding["resolved"] else len(SCANS)
        last_seen = scan_times[last_number]
        resolved_at = scan_times[finding["resolved"]] if finding["resolved"] else None
        row = cur.execute(
            "INSERT INTO findings (org_id, scan_id, asset_id, title, description, severity, category, evidence, "
            "remediation, status, confidence, impact, source, first_seen_at, last_seen_at, resolved_at, updated_at, "
            "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, 'medium', %s, 'sample', %s, %s, %s, "
            "%s, %s) RETURNING id",
            (DEMO_ORG_ID, first_scan_id, asset_id, finding["title"], f"{finding['description']} {SAMPLE_NOTE}",
             finding["severity"], finding["category"],
             json.dumps({"sample": True, "label": SAMPLE_LABEL, "note": SAMPLE_NOTE}),
             finding["remediation"], finding["status"], "Sample impact text for the demo only.",
             first_seen, last_seen, resolved_at, last_seen, first_seen),
        ).fetchone()
        finding_ids[finding["key"]] = str(row["id"])
    return str(asset_id), {"scans": scan_ids, "findings": finding_ids, "scores": {
        str(k): v["score"] for k, v in scan_scores.items()}}


def _insert_evidence_and_tasks(cur, now: datetime, ids: Dict[str, Any], register_version: str) -> None:
    for requirement, source, state, finding_key in EVIDENCE:
        finding_ids = [ids["findings"][finding_key]] if finding_key else []
        cur.execute(
            "INSERT INTO compliance_evidence (org_id, requirement_key, register_version, source, status, observed_at, "
            "expires_at, scan_id, finding_ids, details, created_by, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
            (DEMO_ORG_ID, requirement, register_version, source, state, now,
             now + timedelta(days=180) if source == "tool_observed" else None,
             ids["scans"]["scan-3"] if source == "tool_observed" else None,
             finding_ids, json.dumps({"sample": True, "label": SAMPLE_LABEL}), DEMO_USER_ID, now),
        )
    for task in REMEDIATION_TASKS:
        cur.execute(
            "INSERT INTO remediation_tasks (org_id, finding_id, title, instructions, assignee_id, priority, status, "
            "due_date, created_by, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (DEMO_ORG_ID, ids["findings"][task["finding"]], task["title"], SAMPLE_NOTE, DEMO_USER_ID,
             task["priority"], task["status"], (now + timedelta(days=task["days_until_due"])).date(),
             DEMO_USER_ID, now, now),
        )


def _register_version() -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "compliance", "registers",
                        "ndpa_gaid_v1.json")
    with open(path, encoding="utf-8") as handle:
        return str(json.load(handle)["version"])


def _app_phase(url: str, now: datetime) -> Dict[str, Any]:
    """Attestations, incidents, the readiness pack and two drafts, through the app's own functions."""
    from backend.app.compliance import attestation_store, document_store, incidents
    from backend.app.compliance import documents as docs
    from backend.app.packs import store as packs

    if docs.MODEL_ENABLED:
        raise RuntimeError("Document drafts must use the template path for the demo seed.")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        org = conn.execute("SELECT * FROM organizations WHERE id = %s", (DEMO_ORG_ID,)).fetchone()
    done: Dict[str, int] = {}
    for key, answer in ATTESTATIONS:
        attestation_store.record(org, DEMO_USER_ID, question_key=key, answer=answer, owner_user_id=DEMO_USER_ID,
                                 now=now)
    done["attestations"] = len(ATTESTATIONS)
    for item in INCIDENTS:
        detected = _days(now, item["detected_days_ago"])
        aware = detected + timedelta(hours=item["aware_hours_after_detection"])
        commission = (aware + timedelta(hours=item["commission_hours_after_aware"])
                      if item["commission_hours_after_aware"] else None)
        incidents.create(org, DEMO_USER_ID, title=item["title"], severity=item["severity"], detected_at=detected,
                         became_aware_at=aware, status=item["status"], notified_commission_at=commission,
                         notes=item["notes"], now=now)
    done["incidents"] = len(INCIDENTS)
    packs.issue_with_new_snapshot(org, DEMO_USER_ID, "readiness_pack", include_dpo=True)
    done["packs"] = 1
    for kind in docs.KINDS:
        asyncio.run(document_store.generate(org, DEMO_USER_ID, kind))
    done["documents"] = len(docs.KINDS)
    return done


def seed(url: str, password: str, *, apply: bool, now: Optional[datetime] = None) -> Dict[str, Any]:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RefusedTarget(f"The demo password must be at least {MIN_PASSWORD_LENGTH} characters.")
    now = now or _now()
    current = status(url)
    if current == "seeded":
        return {"action": "noop", "state": current, "counts": {}}
    if current == "conflict":
        raise Refused("The demo organisation id or user id is already used by something that is not the demo. "
                      "Refusing to write.")
    if not apply:
        return {"action": "dry-run", "state": current, "counts": plan_counts()}

    _configure_app(url)
    from backend.app.core.security import hash_password

    password_hash = hash_password(password)
    register_version = _register_version()
    with psycopg.connect(url, row_factory=dict_row) as conn:
        with conn.transaction():
            _insert_identity(conn, password_hash)
            _insert_organisation(conn, now)
            domain_id = _insert_domain_and_assets(conn, now)
            _, ids = _insert_scans_and_findings(conn, now, domain_id)
            _insert_evidence_and_tasks(conn, now, ids, register_version)
    try:
        _app_phase(url, now)
    except Exception:
        _remove(url, verify=False)
        raise
    # Counts are read back from the rows that now exist, so what is reported is what was written.
    return {"action": "seeded", "state": "seeded", "counts": _row_counts(url)}


def _row_counts(url: str) -> Dict[str, int]:
    with psycopg.connect(url, row_factory=dict_row) as conn:
        counts = {table: conn.execute(sql.SQL("SELECT count(*) AS n FROM {} WHERE org_id = %s").format(
            sql.Identifier(table)), (DEMO_ORG_ID,)).fetchone()["n"] for table in ORG_SCOPED_TABLES}
        counts["profiles (demo owner)"] = conn.execute(
            "SELECT count(*) AS n FROM profiles WHERE id = %s", (DEMO_USER_ID,)).fetchone()["n"]
    return {table: n for table, n in counts.items() if n}


# ── Unseed ───────────────────────────────────────────────────────────────────
def count_all(url: str) -> Dict[str, int]:
    """Exact row counts for every ordinary table in the public schema."""
    with psycopg.connect(url, row_factory=dict_row) as conn:
        names = [r["relname"] for r in conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') ORDER BY c.relname").fetchall()]
        return {name: conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(
            sql.Identifier(name))).fetchone()["n"] for name in names}


# Exact bucket keys the auth code uses for the demo owner. Never a pattern: a real account's key must survive.
THROTTLE_KEYS = (
    f"login:{DEMO_EMAIL}", f"reset:{DEMO_EMAIL}",
    f"welcome:{DEMO_USER_ID}", f"mfa:{DEMO_USER_ID}", f"mfa-send:{DEMO_USER_ID}", f"mfa-verify:{DEMO_USER_ID}",
    f"mfa-disable:{DEMO_USER_ID}", f"totp-enroll:{DEMO_USER_ID}", f"totp-disable:{DEMO_USER_ID}",
)


def clear_throttles(url: str) -> int:
    """Forget the throttle buckets for the demo owner, by exact key only."""
    with psycopg.connect(url) as conn:
        cur = conn.execute("DELETE FROM rate_limits WHERE bucket_key = ANY(%s)", (list(THROTTLE_KEYS),))
        conn.commit()
        return cur.rowcount


def _remove(url: str, *, verify: bool) -> Dict[str, int]:
    """Delete the demo organisation (cascade), the demo owner's profile and the demo's throttle buckets.

    audit_log is append-only for the application role, so sign-in rows that have no organisation stay (they are
    keyed to the demo owner's id, which no longer exists). Rows that belong to the organisation go with it.
    """
    with psycopg.connect(url, row_factory=dict_row) as conn:
        if verify and not _looks_like_demo(conn):
            raise Refused("The demo organisation is missing or does not look like the sample. Nothing was removed.")
        removed: Dict[str, int] = {}
        with conn.transaction():
            for table in ORG_SCOPED_TABLES:
                removed[table] = conn.execute(sql.SQL(
                    "SELECT count(*) AS n FROM {} WHERE org_id = %s").format(sql.Identifier(table)),
                    (DEMO_ORG_ID,)).fetchone()["n"]
            removed["rate_limits (demo owner)"] = conn.execute(
                "DELETE FROM rate_limits WHERE bucket_key = ANY(%s)", (list(THROTTLE_KEYS),)).rowcount
            conn.execute("DELETE FROM organizations WHERE id = %s AND name = %s AND slug = %s",
                         (DEMO_ORG_ID, DEMO_ORG_NAME, DEMO_SLUG))
            conn.execute("DELETE FROM profiles WHERE id = %s AND email = %s AND NOT EXISTS "
                         "(SELECT 1 FROM organization_members WHERE user_id = %s)",
                         (DEMO_USER_ID, DEMO_EMAIL, DEMO_USER_ID))
        return removed


def unseed(url: str, *, apply: bool) -> Dict[str, Any]:
    current = status(url)
    if current == "absent":
        raise Refused("The demo organisation is not in this database. Nothing to remove.")
    if current == "conflict":
        raise Refused("The demo organisation looks different from the sample. Refusing to delete it.")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        counts = {table: conn.execute(sql.SQL("SELECT count(*) AS n FROM {} WHERE org_id = %s").format(
            sql.Identifier(table)), (DEMO_ORG_ID,)).fetchone()["n"] for table in ORG_SCOPED_TABLES}
    if not apply:
        return {"action": "dry-run", "state": current, "counts": counts}
    removed = _remove(url, verify=True)
    return {"action": "unseeded", "state": "absent", "counts": removed}


# ── CLI ──────────────────────────────────────────────────────────────────────
def _password() -> str:
    value = os.environ.get(DEMO_PASSWORD_ENV, "")
    if value:
        return value
    if sys.stdin.isatty():
        return getpass.getpass("Demo owner password (not stored): ")
    raise RefusedTarget(f"Set {DEMO_PASSWORD_ENV} or run in a terminal to type the demo password.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("seed", "unseed", "status"))
    parser.add_argument("--database-url", default=os.environ.get("CYPHWARD_DEMO_DATABASE_URL", ""))
    parser.add_argument("--target", choices=("local", "production"), default="local")
    parser.add_argument("--confirm-production", default=None)
    parser.add_argument("--apply", action="store_true", help="Write. Without this the command is a dry run.")
    args = parser.parse_args(argv)
    try:
        check_target(args.database_url, args.target, args.confirm_production)
        if args.command == "status":
            print(status(args.database_url))
            return 0
        if args.command == "seed":
            result = seed(args.database_url, _password() if args.apply else "dry-run-password", apply=args.apply)
        else:
            result = unseed(args.database_url, apply=args.apply)
    except (RefusedTarget, Refused) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str))
    if not args.apply and result["action"] == "dry-run":
        print("Dry run: nothing was written. Add --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
