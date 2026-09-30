"""
Cyphward Finding Normalization Worker
Standardizes disparate observations into consistent, actionable security findings.
"""
from typing import List, Dict, Any


def normalize_findings(
    raw_findings: List[Dict[str, Any]],
    asset_id: str,
    org_id: str,
    scan_id: str
) -> List[Dict[str, Any]]:
    """
    Normalize and deduplicate raw finding candidates.
    Ensures valid severity levels, categories, structured evidence, and remediation guidelines.
    """
    valid_severities = {"critical", "high", "medium", "low", "info"}
    seen_signatures = set()
    normalized = []

    for rf in raw_findings:
        title = rf.get("title", "Unclassified Security Finding").strip()
        sev = rf.get("severity", "medium").lower().strip()
        if sev not in valid_severities:
            sev = "medium"

        category = rf.get("category", "Security Configuration").strip()
        desc = rf.get("description", "").strip()
        remediation = rf.get("remediation", "").strip()
        evidence = rf.get("evidence") or {}

        # Signature for deduplication across the same asset
        sig = f"{asset_id}:{title}"
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)

        normalized.append({
            "scan_id": scan_id,
            "asset_id": asset_id,
            "org_id": org_id,
            "title": title,
            "description": desc,
            "severity": sev,
            "category": category,
            "evidence": evidence,
            "remediation": remediation,
            "status": "open",
        })

    return normalized
