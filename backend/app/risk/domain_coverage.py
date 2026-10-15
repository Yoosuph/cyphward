"""Per-domain assessment state behind the organisation grade gate.

A grade requires every verified domain in the organisation to have a complete
latest assessment. Anything else (partial, legacy/unknown, never scanned)
leaves a known-risk index without a grade. Every query is scoped by org_id.
"""
from typing import Any, Dict, List, Optional

from backend.app.risk.coverage import coverage_state

DOMAIN_COVERAGE_SQL = """
    SELECT d.id AS domain_id, d.domain, s.id AS scan_id, s.completed_at, s.stage_progress
    FROM domains d
    LEFT JOIN LATERAL (
        SELECT sc.id, sc.completed_at, sc.stage_progress
        FROM scans sc
        WHERE sc.org_id = d.org_id AND sc.domain_id = d.id AND sc.status = 'completed'
        ORDER BY sc.completed_at DESC NULLS LAST, sc.id DESC
        LIMIT 1
    ) s ON true
    WHERE d.org_id = %s AND d.verification_status = 'verified'
    ORDER BY d.created_at ASC, d.domain ASC
"""


def _stored_coverage(stage_progress: Any) -> Any:
    scoring = stage_progress.get("scoring") if isinstance(stage_progress, dict) else None
    return scoring.get("coverage") if isinstance(scoring, dict) else None


def org_domain_coverage(org_id: str, *, current: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Latest completed assessment state for each verified domain of one org.

    `current` is an assessment being completed in this transaction (not yet a
    completed row): {"domain_id", "domain", "scan_id", "completed_at",
    "coverage"}. It replaces that domain's stored entry, or is appended when
    the domain is no longer listed as verified.
    """
    from backend.app.core.database import execute_query

    entries = []
    for row in execute_query(DOMAIN_COVERAGE_SQL, (org_id,)) or []:
        scanned = row.get("scan_id") is not None
        entries.append({
            "domain_id": str(row["domain_id"]),
            "domain": row["domain"],
            "scan_id": str(row["scan_id"]) if scanned else None,
            "completed_at": str(row["completed_at"]) if row.get("completed_at") else None,
            "state": coverage_state({"coverage": _stored_coverage(row.get("stage_progress"))})
                     if scanned else "not_scanned",
        })
    if current:
        entry = {
            "domain_id": str(current["domain_id"]),
            "domain": current["domain"],
            "scan_id": str(current["scan_id"]),
            "completed_at": current.get("completed_at"),
            "state": coverage_state({"coverage": current.get("coverage")}),
        }
        index = next((i for i, item in enumerate(entries) if item["domain_id"] == entry["domain_id"]), None)
        if index is None:
            entries.append(entry)
        else:
            entries[index] = entry
    return entries
