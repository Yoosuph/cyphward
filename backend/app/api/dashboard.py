"""
Cyphward Dashboard API Router (spec §34, §47.1.M)
GET /dashboard/summary
GET /dashboard/security-score
GET /dashboard/activity
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends

from backend.app.core.auth import get_current_org
from backend.app.core.database import execute_one, execute_query
from backend.app.risk.engine import compute_risk_score

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


@router.get("/summary")
def dashboard_summary(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    """Answers: what is exposed, what is wrong, what should I do?"""
    org_id = org["id"]

    domains = execute_one(
        """
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE verification_status = 'verified') AS verified
        FROM domains WHERE org_id = %s
        """,
        (org_id,),
    ) or {"total": 0, "verified": 0}

    assets = execute_one(
        "SELECT COUNT(*) AS total FROM assets WHERE org_id = %s",
        (org_id,),
    ) or {"total": 0}

    findings = execute_query(
        """
        SELECT severity, COUNT(*) AS count
        FROM findings
        WHERE org_id = %s AND status != 'resolved'
        GROUP BY severity
        """,
        (org_id,),
    ) or []

    by_sev = {row["severity"]: row["count"] for row in findings}
    open_total = sum(by_sev.values())

    remediation = execute_query(
        """
        SELECT status, COUNT(*) AS count
        FROM remediation_tasks
        WHERE org_id = %s
        GROUP BY status
        """,
        (org_id,),
    ) or []
    rem_by_status = {row["status"]: row["count"] for row in remediation}

    scans = execute_one(
        """
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status = 'completed') AS completed,
               COUNT(*) FILTER (WHERE status IN ('queued','running')) AS active
        FROM scans WHERE org_id = %s
        """,
        (org_id,),
    ) or {"total": 0, "completed": 0, "active": 0}

    return {
        "organization": {"id": org["id"], "name": org["name"], "slug": org["slug"]},
        "attack_surface": {
            "domains": domains.get("total", 0),
            "verified_domains": domains.get("verified", 0),
            "assets": assets.get("total", 0),
        },
        "findings": {
            "open_total": open_total,
            "critical": by_sev.get("critical", 0),
            "high": by_sev.get("high", 0),
            "medium": by_sev.get("medium", 0),
            "low": by_sev.get("low", 0),
            "info": by_sev.get("info", 0),
        },
        "remediation": {
            "open": rem_by_status.get("open", 0),
            "in_progress": rem_by_status.get("in_progress", 0),
            "ready_for_verification": rem_by_status.get("ready_for_verification", 0),
            "verified": rem_by_status.get("verified", 0),
            "reopened": rem_by_status.get("reopened", 0),
        },
        "scans": scans,
    }


@router.get("/security-score")
def dashboard_security_score(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    """Deterministic, explainable score with change reasons (spec §26)."""
    org_id = org["id"]
    findings = execute_query(
        "SELECT * FROM findings WHERE org_id = %s AND status != 'resolved'",
        (org_id,),
    ) or []
    scoring = compute_risk_score(findings)

    snapshots = execute_query(
        """
        SELECT score, created_at FROM score_snapshots
        WHERE org_id = %s ORDER BY created_at DESC LIMIT 2
        """,
        (org_id,),
    ) or []

    previous = snapshots[1]["score"] if len(snapshots) >= 2 else None
    current = snapshots[0]["score"] if snapshots else scoring["score"]

    return {
        "score": scoring["score"],
        "max_score": 100,
        "grade": scoring["grade"],
        "posture_label": scoring["posture_label"],
        "subscores": scoring["subscores"],
        "factors": scoring["factors"],
        "previous_score": previous,
        "change": (scoring["score"] - previous) if previous is not None else None,
        "reasons": scoring["factors"],
    }


@router.get("/activity")
def dashboard_activity(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    """Recent security-relevant activity: audit trail + scan history (spec §39)."""
    org_id = org["id"]
    audit = execute_query(
        """
        SELECT a.id, a.action, a.resource_type, a.resource_id, a.metadata, a.created_at,
               p.email AS actor_email, p.full_name AS actor_name
        FROM audit_log a
        LEFT JOIN profiles p ON p.id = a.user_id
        WHERE a.org_id = %s
        ORDER BY a.created_at DESC
        LIMIT 25
        """,
        (org_id,),
    ) or []

    recent_scans = execute_query(
        """
        SELECT s.id, s.status, s.score, s.current_stage, s.created_at, s.completed_at, d.domain
        FROM scans s
        JOIN domains d ON d.id = s.domain_id
        WHERE s.org_id = %s
        ORDER BY s.created_at DESC
        LIMIT 10
        """,
        (org_id,),
    ) or []

    return {"audit": audit, "recent_scans": recent_scans}
