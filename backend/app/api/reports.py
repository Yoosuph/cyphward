"""
Cyphward Security Reports & Email Dispatch API Router
Allows exporting and emailing executive board reports via Brevo.
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
import httpx
import json
import logging
from datetime import datetime

from backend.app.core.database import execute_query, execute_one
from backend.app.core.auth import get_current_org, require_admin, log_audit
from backend.app.core.plans import require_quota
from backend.app.risk.check_set import COVERAGE_VERSION, NUCLEI_LINE, domain_coverage_line
from backend.app.risk.engine import compute_risk_score, latest_assessment
from backend.app.snapshots import store as snapshots
from backend.app.services.mailer import (
    generate_executive_report_html,
    send_email_async,
)


logger = logging.getLogger("cyphward.reports")

router = APIRouter(prefix="/api/v1/reports", tags=["Reports & Notifications"])


class SendReportEmailRequest(BaseModel):
    to_email: EmailStr
    recipient_name: Optional[str] = None
    subject: Optional[str] = None
    custom_note: Optional[str] = None


class CreateReportRequest(BaseModel):
    domain_id: Optional[str] = None
    title: Optional[str] = None
    request_key: Optional[str] = None


def _report_scope(scoring: Dict[str, Any]) -> Dict[str, Any]:
    """Declared-scope copy read from the scoring result. Display only; never changes scoring."""
    coverage = (scoring.get("assessment") or {}).get("coverage") or {}
    domain_coverage = list(scoring.get("domain_coverage") or [])
    return {
        "scope_label": scoring.get("scope_label"),
        "coverage_label": coverage.get("label") or None,
        "domain_coverage": domain_coverage,
        "domain_coverage_line": scoring.get("domain_coverage_line") or domain_coverage_line(domain_coverage),
        "nuclei_line": NUCLEI_LINE if coverage.get("version") == COVERAGE_VERSION else None,
    }


def _build_report(org: Dict[str, Any], domain_id: Optional[str] = None) -> Dict[str, Any]:
    """Assemble live assessment data for report generation (spec §32)."""
    org_id = org["id"]
    findings = execute_query(
        "SELECT * FROM findings WHERE org_id = %s AND status != 'resolved'", (org_id,)
    ) or []
    resolved_recent = execute_one(
        """
        SELECT COUNT(*) AS count FROM findings
        WHERE org_id = %s AND status = 'resolved' AND resolved_at > now() - interval '30 days'
        """,
        (org_id,),
    ) or {"count": 0}

    if domain_id:
        domain_row = execute_one(
            "SELECT domain FROM domains WHERE id = %s AND org_id = %s",
            (domain_id, org_id),
        ) or {}
    else:
        domain_row = execute_one(
            "SELECT domain FROM domains WHERE org_id = %s AND verification_status = 'verified' ORDER BY created_at ASC LIMIT 1",
            (org_id,),
        ) or {}

    assets_count = (execute_one(
        "SELECT COUNT(*) as count FROM assets WHERE org_id = %s", (org_id,)
    ) or {}).get("count", 0)

    scoring = compute_risk_score(findings, assessment=latest_assessment(org_id))
    return {
        "org_name": org.get("name", ""),
        "domain": domain_row.get("domain", ""),
        "score": scoring.get("score"),
        "grade": scoring.get("grade"),
        "posture_label": scoring.get("posture_label", ""),
        "assessed": scoring.get("assessed", False),
        "assessment": scoring.get("assessment"),
        "model": scoring.get("model"),
        "scope": scoring.get("scope"),
        **_report_scope(scoring),
        "assets_count": assets_count,
        "critical_count": sum(1 for f in findings if f.get("severity") == "critical"),
        "high_count": sum(1 for f in findings if f.get("severity") == "high"),
        "medium_count": sum(1 for f in findings if f.get("severity") == "medium"),
        "low_count": sum(1 for f in findings if f.get("severity") == "low"),
        "resolved_recent": resolved_recent.get("count", 0),
        "findings": findings,
    }


def _report_drivers(findings: list[Dict[str, Any]]) -> list[Dict[str, str]]:
    """Show actual open findings, highest severity first, without invented impacts."""
    priority = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return [
        {
            "impact": str(f.get("severity") or "finding").upper(),
            "title": str(f.get("title") or "Security finding"),
            "desc": str(f.get("description") or "See your dashboard for evidence."),
            "remedy": str(f.get("remediation") or "See your dashboard for recommended actions."),
        }
        for f in sorted(findings, key=lambda f: priority.get(str(f.get("severity")), 4))[:5]
    ]


LEGACY_LABEL = ("Legacy report: built from live data before assessment snapshots existed. Its figures may differ "
                "from today's and its evidence cannot be verified.")
SNAPSHOT_LABEL = "Issued from a frozen assessment snapshot. Later scans and changes do not alter it."


def _integrity(row: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy reports (no snapshot) are labelled, never backfilled."""
    if row.get("snapshot_id"):
        return {"integrity": "snapshot", "integrity_label": SNAPSHOT_LABEL}
    return {"integrity": "legacy", "integrity_label": LEGACY_LABEL}


def _drivers_from_snapshot(findings: list[Dict[str, Any]]) -> list[Dict[str, str]]:
    return _report_drivers([{"severity": f["severity"], "title": f["title"], "description": f["description"],
                             "remediation": f["remediation"]} for f in findings])


def render_from_snapshot(content: Dict[str, Any], snapshot: Dict[str, Any], focus_domain: Optional[str]) -> str:
    """The report page, built only from the frozen content: the same snapshot always renders the same page."""
    scoring, scope = content["scoring"], content["scope"]
    counts = scoring["counts"]
    integrity = [
        f"Issued from assessment snapshot {snapshot['seq']} (sha256 {snapshot['content_sha256'][:12]}…), "
        f"frozen {content['generated_at'][:16].replace('T', ' ')} UTC. Later scans do not change this report.",
        scope["note"],
    ]
    if focus_domain:
        integrity.append(f"Focus domain: {focus_domain}. The score above is organisation-wide, not a score for "
                         "this domain alone.")
    return generate_executive_report_html(
        org_name=scope["org_name"], domain=focus_domain or ", ".join(d["domain"] for d in scope["domains"]),
        score=scoring["score"], grade=scoring["grade"], posture_label=scoring["posture_label"],
        assets_count=scope["assets"], critical_count=counts.get("critical", 0), high_count=counts.get("high", 0),
        medium_count=counts.get("medium", 0), low_count=counts.get("low", 0),
        resolved_recent_count=content["findings"].get("resolved_last_30d", 0),
        drivers=_drivers_from_snapshot(content["findings"]["open"]),
        scope_label=scoring.get("scope_label"), coverage_label=scoring.get("coverage_label"),
        domain_line=scoring.get("domain_coverage_line") or scope.get("domain_line") or None, nuclei_line=scoring.get("nuclei_line"),
        generated_at=datetime.fromisoformat(content["generated_at"]),
        report_ref=f"S{snapshot['seq']}-{snapshot['content_sha256'][:8]}", integrity_lines=integrity,
    )


def _summary_from_snapshot(content: Dict[str, Any], snapshot: Dict[str, Any], focus: Optional[str]) -> Dict[str, Any]:
    scoring, counts = content["scoring"], content["scoring"]["counts"]
    return {
        "score": scoring["score"], "grade": scoring["grade"], "assessed": scoring["assessed"],
        "assessed_at": content["dates"]["assessment_completed_at"],
        "model": scoring["model"], "scope": scoring["scope"], "scope_label": scoring["scope_label"],
        "coverage_label": scoring["coverage_label"], "domain_coverage_line": scoring["domain_coverage_line"],
        "domain_coverage": scoring["domain_states"], "nuclei_line": scoring["nuclei_line"],
        "assets": content["scope"]["assets"], "critical": counts.get("critical", 0), "high": counts.get("high", 0),
        "medium": counts.get("medium", 0), "low": counts.get("low", 0),
        "resolved_last_30d": content["findings"]["resolved_last_30d"],
        "snapshot": {"id": str(snapshot["id"]), "seq": snapshot["seq"], "sha256": snapshot["content_sha256"],
                     "generated_at": content["generated_at"]},
        "focus_domain": focus,
    }


@router.get("")
def list_reports(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    rows = execute_query(
        """
        SELECT r.id, r.title, r.status, r.summary, r.domain_id, r.scan_id, r.snapshot_id, r.report_version,
               r.created_at, r.updated_at, d.domain
        FROM reports r
        LEFT JOIN domains d ON d.id = r.domain_id AND d.org_id = r.org_id
        WHERE r.org_id = %s
        ORDER BY r.created_at DESC
        LIMIT 100
        """,
        (org["id"],),
    ) or []
    rows = [{**r, **_integrity(r)} for r in rows]
    return {"reports": rows, "total": len(rows)}


@router.post("", status_code=201)
def create_report(
    req: CreateReportRequest,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Freeze an assessment snapshot and generate the report from it (Packet 04).

    The snapshot is organisation-scoped; `domain_id` only names a focus domain, which must belong to
    this organisation and be in the snapshot's scope (a verified domain). One request makes one
    snapshot and one report in a single transaction; a retried `request_key` returns the first.
    """
    if not snapshots.valid_request_key(req.request_key):
        raise HTTPException(status_code=422, detail="request_key must be 8-80 letters, digits or . _ : -")
    focus = None
    if req.domain_id:
        domain = execute_one("SELECT id, domain, verification_status FROM domains WHERE id = %s AND org_id = %s",
                             (req.domain_id, org["id"]))
        if not domain:
            raise HTTPException(status_code=404, detail="Domain not found.")
        if domain["verification_status"] != "verified":
            raise HTTPException(status_code=422, detail="That domain is not verified, so it is not in the assessment scope.")
        focus = domain["domain"]
    if req.request_key:
        again = execute_one(
            "SELECT r.id FROM reports r JOIN assessment_snapshots s ON s.org_id = r.org_id AND s.id = r.snapshot_id "
            "WHERE r.org_id = %s AND s.request_key = %s", (org["id"], req.request_key))
        if again:
            return {"report": _report_row(org["id"], again["id"]), "created": False}
    require_quota(org, "reports")

    def insert_report(conn, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        content = snapshot["content"]
        if focus and focus not in [d["domain"] for d in content["scope"]["domains"]]:
            raise HTTPException(status_code=422, detail="That domain is not in the assessment scope.")
        title = req.title or f"Security Assessment — {focus or content['scope']['org_name']}"
        html_content = render_from_snapshot(content, snapshot, focus)
        return conn.execute(
            "INSERT INTO reports (org_id, domain_id, title, status, html, summary, created_by, snapshot_id, report_version) "
            "VALUES (%s, %s, %s, 'ready', %s, %s::jsonb, %s, %s, %s) RETURNING id",
            (org["id"], req.domain_id, title, html_content,
             json.dumps(_summary_from_snapshot(content, snapshot, focus)), org.get("current_user_id"),
             snapshot["id"], content["report_version"])).fetchone()

    try:
        made = snapshots.create(org, org.get("current_user_id"), request_key=req.request_key, on_insert=insert_report)
    except snapshots.StateChanging:
        raise HTTPException(status_code=409, detail="Your data changed while the report was being prepared. Try again.")
    except snapshots.Busy:
        raise HTTPException(status_code=503, detail="Reports are being prepared right now. Try again in a few seconds.",
                            headers={"Retry-After": "5"})
    if made["created"]:
        log_audit(org["id"], org.get("current_user_id"), "report.generated", "report", str(made["extra"]["id"]))
        return {"report": _report_row(org["id"], made["extra"]["id"]), "created": True}
    again = execute_one("SELECT id FROM reports WHERE org_id = %s AND snapshot_id = %s ORDER BY created_at LIMIT 1",
                        (org["id"], made["snapshot"]["id"]))
    if not again:
        raise HTTPException(status_code=409, detail="That request key was already used for a snapshot without a report.")
    return {"report": _report_row(org["id"], again["id"]), "created": False}


def _report_row(org_id: Any, report_id: Any) -> Dict[str, Any]:
    row = execute_one(
        "SELECT id, org_id, domain_id, title, status, summary, snapshot_id, report_version, created_at, updated_at "
        "FROM reports WHERE id = %s AND org_id = %s", (str(report_id), str(org_id)))
    return {**row, **_integrity(row)}


@router.get("/{report_id}")
def get_report(report_id: str, org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    report = execute_one(
        "SELECT * FROM reports WHERE id = %s AND org_id = %s",
        (report_id, org["id"]),
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    return {"report": {**report, **_integrity(report)}}


@router.post("/send-email")
async def send_executive_report_email(
    req: SendReportEmailRequest,
    background_tasks: BackgroundTasks,
    org: Dict[str, Any] = Depends(require_admin),
):
    """
    Generates and dispatches a high-fidelity Executive Security Briefing email
    to the designated recipient using the configured Brevo service.
    """
    to_email = str(req.to_email).strip()

    org_id = org["id"]
    org_name = org.get("name", "")

    data = _build_report(org)
    findings = data["findings"]
    domain_name = data["domain"]
    assets_count = data["assets_count"]
    score_val = data["score"]
    grade = data["grade"]
    posture_label = data["posture_label"]
    critical_count = data["critical_count"]
    high_count = data["high_count"]
    medium_count = data["medium_count"]

    if req.subject:
        subject = req.subject
    elif score_val is not None:
        subject = f"Your security report for {org_name} — score {score_val}/100"
    else:
        subject = f"Your security report for {org_name} — no score available"

    html_content = generate_executive_report_html(
        org_name=org_name,
        domain=domain_name,
        score=score_val,
        grade=grade,
        posture_label=posture_label,
        assets_count=assets_count,
        critical_count=critical_count,
        high_count=high_count,
        medium_count=medium_count,
        low_count=data["low_count"],
        resolved_recent_count=data["resolved_recent"],
        summary_text=req.custom_note,
        drivers=_report_drivers(findings),
        scope_label=data["scope_label"],
        coverage_label=data["coverage_label"],
        domain_line=data["domain_coverage_line"] or None,
        nuclei_line=data["nuclei_line"],
    )

    try:
        result = await send_email_async(
            to_email=to_email,
            subject=subject,
            html_content=html_content,
            recipient_name=req.recipient_name,
            kind="reports",
        )
        log_audit(org_id, org.get("current_user_id"), "report.emailed", "report", None,
                  {"to": to_email})
        return {
            "success": True,
            "message": f"Executive Security Assessment successfully dispatched to {to_email}",
            "result": result,
            "org": org_name,
            "domain": domain_name,
            "score": score_val,
        }
    except Exception as e:
        logger.error(f"Failed to dispatch report to {to_email}: {e}")
        detail = "Email dispatch failed. Please try again later."
        msg = str(e)
        if "Unauthorized IP" in msg or "unrecognised IP" in msg or "unauthorized" in msg.lower():
            detail = (
                "Brevo rejected this server's IP. "
                "Whitelist it at https://app.brevo.com/security/authorised_ips, then retry."
            )
        raise HTTPException(status_code=502, detail=detail)
