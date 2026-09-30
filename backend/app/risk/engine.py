"""
Cyphward Risk Scoring Engine (0-100)
Computes a simple, explainable security score across 4 pillars.
"""
from typing import List, Dict, Any


def compute_risk_score(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate security score between 0 and 100 based on active findings.
    Breaks the score into 4 simple pillars:
    - Network & DNS (0 - 25)
    - Web & Apps (0 - 35)
    - Encryption (0 - 25)
    - Exposure (0 - 15)
    """
    pillar_net_max = 25
    pillar_web_max = 35
    pillar_tls_max = 25
    pillar_exp_max = 15

    net_score = pillar_net_max
    web_score = pillar_web_max
    tls_score = pillar_tls_max
    exp_score = pillar_exp_max

    counts = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0
    }

    factors = []

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
        counts[sev] = counts.get(sev, 0) + 1
        cat = f.get("category", "")
        title = f.get("title", "Security issue")
        pen = weights.get(sev, 3)

        # Which pillar loses points
        if "DNS" in cat or "Email" in cat or "Network" in cat:
            deduct = min(net_score, pen)
            net_score -= deduct
            if sev in ["critical", "high"]:
                factors.append({"impact": f"-{deduct}", "type": "negative", "label": title})
        elif "HTTP" in cat or "Application" in cat or "Header" in cat:
            deduct = min(web_score, pen)
            web_score -= deduct
            if sev in ["critical", "high", "medium"]:
                factors.append({"impact": f"-{deduct}", "type": "negative", "label": title})
        elif "SSL" in cat or "TLS" in cat or "Encryption" in cat:
            deduct = min(tls_score, pen)
            tls_score -= deduct
            if sev in ["critical", "high"]:
                factors.append({"impact": f"-{deduct}", "type": "negative", "label": title})
        else:
            deduct = min(exp_score, pen)
            exp_score -= deduct
            if sev in ["critical", "high", "medium"]:
                factors.append({"impact": f"-{deduct}", "type": "negative", "label": title})

    net_score = max(0, min(pillar_net_max, net_score))
    web_score = max(0, min(pillar_web_max, web_score))
    tls_score = max(0, min(pillar_tls_max, tls_score))
    exp_score = max(0, min(pillar_exp_max, exp_score))

    total_score = net_score + web_score + tls_score + exp_score

    # Simple bonus notes when a pillar is healthy
    if tls_score >= 20:
        factors.append({"impact": "+5", "type": "positive", "label": "Strong encryption (TLS 1.3) is active"})
    if net_score >= 20:
        factors.append({"impact": "+4", "type": "positive", "label": "DNS and email records look solid"})
    if web_score >= 28:
        factors.append({"impact": "+5", "type": "positive", "label": "Web apps have good security headers"})
    if exp_score >= 12:
        factors.append({"impact": "+3", "type": "positive", "label": "Very little sensitive data exposed publicly"})

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
        "score": total_score,
        "max_score": 100,
        "grade": grade,
        "posture_label": posture_label,
        "status_color": status_color,
        "counts": counts,
        "subscores": subscores,
        "factors": factors[:6]
    }
