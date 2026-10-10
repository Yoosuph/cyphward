"""
Cyphward Risk Scoring Engine (0-100)
Computes organization risk and independent health scores for 4 categories.

Scoring is assessment-gated: a numeric score is only produced when the
caller passes `assessment` metadata from a completed scan. Without that,
the engine returns an explicit "Not assessed" payload — an empty findings
list must never be presented as a 100/100 score.
"""
from typing import List, Dict, Any, Optional

SCORE_MODEL = "cyphward-risk-v2"
SCORE_SCOPE = "organization"
# Relative risk burden, not direct deductions from the 0–100 score.
RISK_WEIGHTS = {"critical": 60, "high": 20, "medium": 5, "low": 1, "info": 0}
PILLARS = ("Network & DNS", "Web & Apps", "Encryption", "Exposure")


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
        "scope": SCORE_SCOPE,
        "risk_points": None,
        "assessment": None,
        "counts": counts,
        "subscores": [],
        "factors": [],
    }


def finding_pillar(finding: Dict[str, Any]) -> str:
    """Classify risk without changing the detector identity used for rechecks.

    Existing Nuclei rows remain valid: interpret their evidence here instead
    of renaming the stored category (which would affect baseline matching).
    """
    category = (finding.get("category") or "").lower()
    evidence = finding.get("evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    if "nuclei" in category or evidence.get("template_id"):
        tags = evidence.get("tags") or []
        if isinstance(tags, str):
            tags = tags.split(",")
        tags = {str(tag).strip().lower() for tag in tags}
        kind = str(evidence.get("type") or "").lower()
        if kind in {"ssl", "tls"} or tags & {"ssl", "tls", "certificate", "encryption"}:
            return "Encryption"
        if kind == "dns" or tags & {"dns", "email", "spf", "dmarc", "dkim"}:
            return "Network & DNS"
        if tags & {"exposure", "exposures", "disclosure", "token", "secrets", "backup"}:
            return "Exposure"
        if kind in {"tcp", "network"}:
            return "Network & DNS"
        # HTTP templates and legacy Nuclei rows belong to application risk.
        return "Web & Apps"
    if any(word in category for word in ("dns", "email", "network")):
        return "Network & DNS"
    if any(word in category for word in ("ssl", "tls", "encryption")):
        return "Encryption"
    if any(word in category for word in ("http", "application", "header")):
        return "Web & Apps"
    return "Exposure"


def _health(risk_points: int) -> float:
    # Strictly decreasing before presentation rounding; no category caps.
    return round(10000 / (100 + risk_points), 1)


def seven_day_baseline(org_id: str) -> Optional[Dict[str, Any]]:
    """Compare only organization snapshots computed under this model.

    The latest snapshot at/before the window boundary represents the known
    posture seven days ago. Legacy/domain scores are never comparable.
    """
    from backend.app.core.database import execute_one

    return execute_one(
        """
        SELECT score, created_at FROM score_snapshots
        WHERE org_id = %s AND model = %s AND scope = %s
          AND created_at <= now() - interval '7 days'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (org_id, SCORE_MODEL, SCORE_SCOPE),
    )


def compute_risk_score(
    findings: List[Dict[str, Any]],
    assessment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Organization risk v2: 100 / (1 + total risk points / 100).

    Every unresolved finding contributes its severity weight to the overall
    risk burden, regardless of category. Category health uses the same
    formula independently; these diagnostic scores are not additive.
    Decimal display can still round very small changes; risk_points and
    finding counts expose the exact burden. A score is not a coverage claim.
    """
    counts = _severity_counts(findings)
    if not assessment:
        return _not_assessed(counts)

    active = [f for f in findings if f.get("status") != "resolved"]
    burdens = {name: 0 for name in PILLARS}
    weighted = []
    for finding in active:
        weight = RISK_WEIGHTS.get((finding.get("severity") or "medium").lower(), 5)
        burdens[finding_pillar(finding)] += weight
        weighted.append((weight, finding))
    total_risk = sum(burdens.values())
    total_score = _health(total_risk)
    factors = []
    # Largest risks first, with deterministic ordering independent of SQL order.
    for weight, finding in sorted(weighted, key=lambda item: (-item[0], item[1].get("title", ""))):
        if not weight:
            continue
        factor = {
            "impact": f"{weight} risk pts",
            "type": "negative",
            "label": finding.get("title", "Security issue"),
        }
        # Do not attribute an older finding to the latest scan of another domain.
        if finding.get("scan_id"):
            factor["scan_id"] = str(finding["scan_id"])
        if finding.get("last_seen_at"):
            factor["assessed_at"] = str(finding["last_seen_at"])
        factors.append(factor)
    if not total_risk:
        factors.append({
            "impact": "0 risk pts", "type": "positive",
            "label": "No scored open findings. Scan coverage still determines what was checked.",
            "scan_id": assessment.get("scan_id"),
            "assessed_at": assessment.get("completed_at"),
        })

    if total_score >= 85:
        grade, posture_label, status_color = "A", "Excellent", "ok"
    elif total_score >= 70:
        grade, posture_label, status_color = "B", "Good", "ok"
    elif total_score >= 55:
        grade, posture_label, status_color = "C", "Fair", "warn"
    elif total_score >= 40:
        grade, posture_label, status_color = "D", "Poor", "accent"
    else:
        grade, posture_label, status_color = "F", "Critical", "accent"

    subscores = []
    for name, burden in burdens.items():
        health = _health(burden)
        subscores.append({
            "name": name, "score": health, "max": 100, "pct": health,
            "status": "Good" if health >= 80 else "OK" if health >= 55 else "Needs work",
            "risk_points": burden,
        })
    return {
        "assessed": True, "score": total_score, "max_score": 100,
        "grade": grade, "posture_label": posture_label, "status_color": status_color,
        "model": SCORE_MODEL, "scope": SCORE_SCOPE,
        "assessment": {**assessment, "model": SCORE_MODEL},
        "risk_points": total_risk, "counts": counts,
        "subscores": subscores, "factors": factors[:6],
    }
