"""Practitioner review notes and the per-organisation clause-verification overlay (packet C6), read side.

A practitioner review is one named practitioner's note that they reviewed a requirement. It is shown next
to the requirement and never changes its status, its source or the readiness counts, and it says nothing
about the organisation's obligations. A clause verification is the practitioner's note that the clause
REFERENCE (the citation) was checked; it replaces the words "reference pending review" for this
organisation only. The register file is code and is not touched.

Both tables are append-only; the newest row per (organisation, requirement) is the one shown. This module
only reads and words things; writes are in reviewer.py. Kept free of imports from status.py (which imports
this) so there is no cycle.
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.app.core.database import execute_query

OUTCOMES = {"reviewed": "Reviewed", "reviewed_with_comments": "Reviewed, with comments"}
MAX_TEXT = 500
# The same words the readiness copy never uses. A comment or note appears in packs under Cyphward's name, so
# text that states a conclusion about the organisation is refused with guidance rather than stored.
BANNED_PHRASES = (
    "compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit",
    "compliance score", "fully meets", "meets the requirement", "is met", "partial compliance", "fully compliant",
    "is compliant", "satisfy ndpa", "adequate", "adequacy", "guarantee",
)
GUIDANCE = ("Describe what you reviewed (the clause reference, the documents seen), not whether the organisation "
            "complies. Words that state a conclusion, such as '{word}', are not accepted.")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class TextError(ValueError):
    """Free text the review notes cannot accept. The API maps it to 422."""


def clean_text(value: Optional[str], field: str, limit: int = MAX_TEXT, required: bool = False) -> Optional[str]:
    text = _CONTROL.sub("", value or "").strip()
    if not text:
        if required:
            raise TextError(f"{field} is required.")
        return None
    if len(text) > limit:
        raise TextError(f"{field} must be at most {limit} characters.")
    lowered = text.lower()
    for word in BANNED_PHRASES:
        # Whole words only: "this method" must not trip "is met".
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", lowered):
            raise TextError(GUIDANCE.format(word=word))
    return text


def _iso(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def _day(value: Optional[datetime]) -> str:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d")


def review_view(row: Dict[str, Any]) -> Dict[str, Any]:
    name = row["reviewer_name"]
    return {"outcome": row["outcome"], "outcome_label": OUTCOMES[row["outcome"]], "reviewer_name": name,
            "reviewed_at": _iso(row["reviewed_at"]), "comment": row.get("comment"),
            "label": f"Practitioner review recorded by {name} on {_day(row['reviewed_at'])}"}


def clause_view(row: Dict[str, Any]) -> Dict[str, Any]:
    name = row["reviewer_name"]
    day = _day(row["verified_at"])
    return {"verified": bool(row["verified"]), "reviewer_name": name, "at": _iso(row["verified_at"]),
            "note": row.get("note"),
            "label": (f"reference reviewed by {name}, {day}" if row["verified"]
                      else f"reference marked as not confirmed by {name}, {day}")}


def latest_reviews(org_id: str) -> Dict[str, Dict[str, Any]]:
    """Newest practitioner review per requirement key, as shown."""
    rows = execute_query(
        "SELECT DISTINCT ON (requirement_key) requirement_key, outcome, reviewer_name, reviewed_at, comment "
        "FROM compliance_practitioner_reviews WHERE org_id = %s "
        "ORDER BY requirement_key, reviewed_at DESC, id DESC", (str(org_id),)) or []
    return {r["requirement_key"]: review_view(r) for r in rows}


def latest_clauses(org_id: str) -> Dict[str, Dict[str, Any]]:
    """Newest clause verification per requirement key (the overlay: newest row wins)."""
    rows = execute_query(
        "SELECT DISTINCT ON (requirement_key) requirement_key, verified, reviewer_name, verified_at, note "
        "FROM compliance_clause_verifications WHERE org_id = %s "
        "ORDER BY requirement_key, verified_at DESC, id DESC", (str(org_id),)) or []
    return {r["requirement_key"]: clause_view(r) for r in rows}


def clause_label(clause: str, register_verified: bool, overlay: Optional[Dict[str, Any]]) -> str:
    """The clause as shown. The register's own verification wins; otherwise this organisation's overlay."""
    if register_verified:
        return clause
    if overlay and overlay.get("verified"):
        return f"{clause} · {overlay['label']}"
    return f"{clause} · reference pending review"


def reference_pending(register_verified: bool, overlay: Optional[Dict[str, Any]]) -> bool:
    return not register_verified and not (overlay and overlay.get("verified"))


def pending_count(requirements: List[Dict[str, Any]], overlays: Dict[str, Dict[str, Any]]) -> int:
    return sum(1 for r in requirements if reference_pending(r["clause_verified"], overlays.get(r["key"])))
