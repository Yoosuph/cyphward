"""
Cyphward Overview API Router
Aggregates deterministic risk score, asset telemetry, severity distribution, and recent scans.
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any
from backend.app.core.database import get_db
from backend.app.risk.engine import compute_risk_score, latest_assessment
from backend.app.core.auth import get_current_org

router = APIRouter(prefix="/api/v1/overview", tags=["Overview"])


@router.get("")
def get_overview(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    """Retrieve full executive command overview metrics."""
    org_id = org["id"]

    with get_db() as conn:
        with conn.cursor() as cur:
            # 1. Domains
            cur.execute("SELECT * FROM domains WHERE org_id = %s ORDER BY created_at ASC", (org_id,))
            domain_rows = cur.fetchall() or []
            primary_domain = domain_rows[0]["domain"] if domain_rows else "No Domain"
            verified_domains_count = len([d for d in domain_rows if d["verification_status"] == "verified"])

            # 2. Assets count
            cur.execute("SELECT count(*) as cnt FROM assets WHERE org_id = %s", (org_id,))
            assets_count_row = cur.fetchone()
            total_assets = assets_count_row["cnt"] if assets_count_row else 0

            # 3. Findings (anything not resolved still represents risk)
            cur.execute("""
                SELECT id, title, severity, category, status, evidence, remediation
                FROM findings
                WHERE org_id = %s AND status != 'resolved'
            """, (org_id,))
            findings = cur.fetchall() or []

            # 4. Recent scans
            cur.execute("""
                SELECT s.id, s.status, s.score, s.current_stage, s.stage_progress, s.started_at, s.completed_at, s.created_at,
                       d.domain
                FROM scans s
                JOIN domains d ON s.domain_id = d.id
                WHERE s.org_id = %s
                ORDER BY s.created_at DESC
                LIMIT 5
            """, (org_id,))
            recent_scans = cur.fetchall() or []

            # 5. Trend snapshots
            cur.execute("""
                SELECT score, created_at
                FROM score_snapshots
                WHERE org_id = %s
                ORDER BY created_at DESC
                LIMIT 2
            """, (org_id,))
            snapshots = cur.fetchall() or []

    # Compute deterministic score — only when a completed scan exists;
    # otherwise the payload reports "Not assessed" instead of an empty 100.
    scoring = compute_risk_score(findings, assessment=latest_assessment(org_id))

    trend = 0
    if len(snapshots) >= 2:
        trend = snapshots[0]["score"] - snapshots[1]["score"]

    return {
        "organization": {
            "id": org["id"],
            "name": org["name"],
            "slug": org["slug"],
            "cac_rc": org.get("cac_rc"),
            "sector": org.get("sector"),
            "plan": org.get("plan"),
            "primary_domain": primary_domain,
            "domains_count": len(domain_rows),
            "verified_domains_count": verified_domains_count,
        },
        "score": scoring["score"],
        "max_score": 100,
        "grade": scoring["grade"],
        "posture_label": scoring["posture_label"],
        "status_color": scoring["status_color"],
        "assessed": scoring["assessed"],
        "assessment": scoring["assessment"],
        "model": scoring["model"],
        "trend": trend,
        "counts": {
            "total_assets": total_assets,
            "total_findings": len(findings),
            "critical": scoring["counts"]["critical"],
            "high": scoring["counts"]["high"],
            "medium": scoring["counts"]["medium"],
            "low": scoring["counts"]["low"],
            "info": scoring["counts"]["info"],
        },
        "subscores": scoring["subscores"],
        "factors": scoring["factors"],
        "recent_scans": recent_scans,
    }
