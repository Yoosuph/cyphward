"""
Cyphward Security Reports & Email Dispatch API Router
Allows exporting and emailing executive board reports via Brevo.
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
import httpx
import logging

from backend.app.core.database import execute_query, execute_one
from backend.app.core.auth import get_current_org, require_admin, log_audit
from backend.app.risk.engine import compute_risk_score, latest_assessment
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
        "assets_count": assets_count,
        "critical_count": sum(1 for f in findings if f.get("severity") == "critical"),
        "high_count": sum(1 for f in findings if f.get("severity") == "high"),
        "medium_count": sum(1 for f in findings if f.get("severity") == "medium"),
        "low_count": sum(1 for f in findings if f.get("severity") == "low"),
        "resolved_recent": resolved_recent.get("count", 0),
        "findings": findings,
    }


@router.get("")
def list_reports(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    rows = execute_query(
        """
        SELECT r.id, r.title, r.status, r.summary, r.domain_id, r.scan_id, r.created_at, r.updated_at,
               d.domain
        FROM reports r
        LEFT JOIN domains d ON d.id = r.domain_id AND d.org_id = r.org_id
        WHERE r.org_id = %s
        ORDER BY r.created_at DESC
        LIMIT 100
        """,
        (org["id"],),
    ) or []
    return {"reports": rows, "total": len(rows)}


@router.post("", status_code=201)
def create_report(
    req: CreateReportRequest,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Generate and persist an assessment report from live data (spec §32)."""
    # A supplied domain must belong to the caller's org — reject before the
    # report is assembled or stored (the composite (org_id, domain_id) FK
    # enforces the same rule at insert time).
    if req.domain_id:
        domain = execute_one(
            "SELECT id FROM domains WHERE id = %s AND org_id = %s",
            (req.domain_id, org["id"]),
        )
        if not domain:
            raise HTTPException(status_code=404, detail="Domain not found.")
    data = _build_report(org, req.domain_id)
    title = req.title or f"Security Assessment — {data['domain'] or org['name']}"

    html_content = generate_executive_report_html(
        org_name=data["org_name"],
        domain=data["domain"],
        score=data["score"],
        grade=data["grade"],
        posture_label=data["posture_label"],
        assets_count=data["assets_count"],
        critical_count=data["critical_count"],
        high_count=data["high_count"],
        medium_count=data["medium_count"],
    )

    summary = {
        "score": data["score"],
        "grade": data["grade"],
        "assessed": data["assessed"],
        "assessed_at": (data.get("assessment") or {}).get("completed_at"),
        "assets": data["assets_count"],
        "critical": data["critical_count"],
        "high": data["high_count"],
        "medium": data["medium_count"],
        "low": data["low_count"],
        "resolved_last_30d": data["resolved_recent"],
    }

    report = execute_one(
        """
        INSERT INTO reports (org_id, domain_id, title, status, html, summary, created_by)
        VALUES (%s, %s, %s, 'ready', %s, %s::jsonb, %s)
        RETURNING id, org_id, domain_id, title, status, summary, created_at, updated_at
        """,
        (org["id"], req.domain_id, title, html_content, __import__("json").dumps(summary),
         org.get("current_user_id")),
    )
    log_audit(org["id"], org.get("current_user_id"), "report.generated", "report", str(report["id"]))
    return {"report": report}


@router.get("/{report_id}")
def get_report(report_id: str, org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    report = execute_one(
        "SELECT * FROM reports WHERE id = %s AND org_id = %s",
        (report_id, org["id"]),
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    return {"report": report}


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
        subject = f"Your security report for {org_name} — not assessed yet"

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
        summary_text=req.custom_note,
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
