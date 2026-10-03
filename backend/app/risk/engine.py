"""
Cyphward Risk Scoring Engine (0-100)
Computes a simple, explainable security score across 4 pillars.

Scoring is assessment-gated: a numeric score is only produced when the
caller passes `assessment` metadata from a completed scan. Without that,
the engine returns an explicit "Not assessed" payload — an empty findings
list must never be presented as a 100/100 score.
"""
from typing import List, Dict, Any, Optional

SCORE_MODEL = "cyphward-risk-v1"


def latest_assessment(org_id: str) -> Optional[Dict[str, Any]]:
    """
    Assessment metadata for the most recent completed scan of an org.
    Returns None when no completed scan exists — callers must then treat
    the score as "not assessed".
    """
    from backend.app.core.database import execute_one

    row = execute_one(
        """
        SELECT id, status, completed_at, stage_progress
        FROM scans
        WHERE org_id = %s AND status = 'completed'
        ORDER BY completed_at DESC NULLS LAST
        LIMIT 1
        """,
        (org_id,),
    )
    if not row:
        return None
    assessment: Dict[str, Any] = {
        "scan_id": str(row["id"]),
        "status": row["status"],
        "completed_at": str(row["completed_at"]) if row.get("completed_at") else None,
        "model": SCORE_MODEL,
    }
    stages = row.get("stage_progress")
    if isinstance(stages, dict):
        assessment["stages"] = stages
    return assessment


def _severity_counts(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        if f.get("status") == "resolved":
            continue
        sev = f.get("severity", "medium").lower()
        counts[sev] = counts.get(sev, 0) + 1
    return counts


def _not_assessed(counts: Dict[str, int]) -> Dict[str, Any]:
    """Explicit unassessed payload — no score, no grade, no claims."""
    return {
        "assessed": False,
        "score": None,
        "max_score": 100,
        "grade": None,
        "posture_label": "Not assessed",
        "status_color": "muted",
        "model": SCORE_MODEL,
        "assessment": None,
        "counts": counts,
        "subscores": [],
        "factors": [],
    }


def compute_risk_score(
    findings: List[Dict[str, Any]],
    assessment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Calculate security score between 0 and 100 based on active findings.
    Breaks the score into 4 simple pillars:
    - Network & DNS (0 - 25)
    - Web & Apps (0 - 35)
    - Encryption (0 - 25)
    - Exposure (0 - 15)

    `assessment` must describe the completed scan this score is based on
    (see latest_assessment). Without it the result is "not assessed".
    Every factor carries the scan id and assessment date it derives from.
    """
    counts = _severity_counts(findings)

    if not assessment:
        return _not_assessed(counts)

    pillar_net_max = 25
    pillar_web_max = 35
    pillar_tls_max = 25
    pillar_exp_max = 15

    net_score = pillar_net_max
    web_score = pillar_web_max
    tls_score = pillar_tls_max
    exp_score = pillar_exp_max

    factors = []

    def _factor(impact: str, factor_type: str, label: str) -> Dict[str, Any]:
        item: Dict[str, Any] = {"impact": impact, "type": factor_type, "label": label}
        if assessment.get("scan_id"):
            item["scan_id"] = assessment["scan_id"]
        if assessment.get("completed_at"):
            item["assessed_at"] = assessment["completed_at"]
        return item

    # How many points each severity removes
    weights = {
        "critical": 15,
        "high": 8,
        "medium": 3,
        "low": 1,
        "info": 0
    }

    for f in findings:
        if f.get("status") == "resolved":
            continue

        sev = f.get("severity", "medium").lower()
        cat = f.get("category", "")
        title = f.get("title", "Security issue")
        pen = weights.get(sev, 3)

        # Which pillar loses points
        if "DNS" in cat or "Email" in cat or "Network" in cat:
            deduct = min(net_score, pen)
            net_score -= deduct
            if sev in ["critical", "high"]:
                factors.append(_factor(f"-{deduct}", "negative", title))
        elif "HTTP" in cat or "Application" in cat or "Header" in cat:
            deduct = min(web_score, pen)
            web_score -= deduct
            if sev in ["critical", "high", "medium"]:
                factors.append(_factor(f"-{deduct}", "negative", title))
        elif "SSL" in cat or "TLS" in cat or "Encryption" in cat:
            deduct = min(tls_score, pen)
            tls_score -= deduct
            if sev in ["critical", "high"]:
                factors.append(_factor(f"-{deduct}", "negative", title))
        else:
            deduct = min(exp_score, pen)
            exp_score -= deduct
            if sev in ["critical", "high", "medium"]:
                factors.append(_factor(f"-{deduct}", "negative", title))

    net_score = max(0, min(pillar_net_max, net_score))
    web_score = max(0, min(pillar_web_max, web_score))
    tls_score = max(0, min(pillar_tls_max, tls_score))
    exp_score = max(0, min(pillar_exp_max, exp_score))

    total_score = net_score + web_score + tls_score + exp_score

    # Bonus notes only appear on an assessed score: a healthy pillar means
    # the completed scan's detectors observed that pillar and raised nothing.
    if tls_score >= 20:
        factors.append(_factor("+5", "positive", "Strong encryption (TLS 1.3) is active"))
    if net_score >= 20:
        factors.append(_factor("+4", "positive", "DNS and email records look solid"))
    if web_score >= 28:
        factors.append(_factor("+5", "positive", "Web apps have good security headers"))
    if exp_score >= 12:
        factors.append(_factor("+3", "positive", "Very little sensitive data exposed publicly"))

    # Simple grade and plain-English status
    if total_score >= 85:
        grade = "A"
        posture_label = "Excellent"
        status_color = "ok"
    elif total_score >= 70:
        grade = "B"
        posture_label = "Good"
        status_color = "ok"
    elif total_score >= 55:
        grade = "C"
        posture_label = "Fair"
        status_color = "warn"
    elif total_score >= 40:
        grade = "D"
        posture_label = "Poor"
        status_color = "accent"
    else:
        grade = "F"
        posture_label = "Critical"
        status_color = "accent"

    def _status(score: int, maximum: int) -> str:
        pct = (score / maximum) * 100 if maximum else 0
        if pct >= 80:
            return "Good"
        if pct >= 55:
            return "OK"
        return "Needs work"

    subscores = [
        {
            "name": "Network & DNS",
            "score": net_score,
            "max": pillar_net_max,
            "pct": round((net_score / pillar_net_max) * 100),
            "status": _status(net_score, pillar_net_max)
        },
        {
            "name": "Web & Apps",
            "score": web_score,
            "max": pillar_web_max,
            "pct": round((web_score / pillar_web_max) * 100),
            "status": _status(web_score, pillar_web_max)
        },
        {
            "name": "Encryption",
            "score": tls_score,
            "max": pillar_tls_max,
            "pct": round((tls_score / pillar_tls_max) * 100),
            "status": _status(tls_score, pillar_tls_max)
        },
        {
            "name": "Exposure",
            "score": exp_score,
            "max": pillar_exp_max,
            "pct": round((exp_score / pillar_exp_max) * 100),
            "status": _status(exp_score, pillar_exp_max)
        }
    ]

    return {
        "assessed": True,
        "score": total_score,
        "max_score": 100,
        "grade": grade,
        "posture_label": posture_label,
        "status_color": status_color,
        "model": SCORE_MODEL,
        "assessment": assessment,
        "counts": counts,
        "subscores": subscores,
        "factors": factors[:6]
    }
