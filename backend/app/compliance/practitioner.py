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
import unicodedata
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
# Beyond the phrases above, a conclusion can be worded many ways ("complies with", "meets s.25", "in line with the
# NDPA", "sufficient"), and disguised many more (accents, look-alike letters and digits, spaces or dots between
# letters). Text is reduced to a SKELETON first (accents stripped, compatibility forms and invisible characters
# folded, look-alike letters mapped, and l, I, 1 and | all read as the same letter), then checked three ways:
# whole-word phrases, whole-token forms and prefixes, and a space-and-punctuation-free run of the long stems.
# "certificate" and "approval" are ordinary words (a TLS certificate, board approval minutes) and are allowed;
# "certified", "certification" and "approved" are claims and are not.
WITHHELD = "Comment withheld: the wording was not accepted"
EXTRA_LOOKALIKES = str.maketrans({"м": "m", "т": "t", "к": "k", "в": "b", "н": "h", "ѵ": "v", "ӏ": "i", "ı": "i",
                                  "μ": "m", "β": "b", "η": "n", "χ": "x"})
CONFUSABLE_CHARS = str.maketrans({"l": "i", "1": "i", "|": "i", "!": "i", "0": "o", "3": "e", "4": "a", "5": "s",
                                  "$": "s", "@": "a", "7": "t"})


class TextError(ValueError):
    """Free text the review notes cannot accept. The API maps it to 422."""


def skeleton(text: str) -> str:
    from backend.app.compliance.documents import fold  # one folding for every text check in the product
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return fold(stripped).translate(EXTRA_LOOKALIKES).translate(CONFUSABLE_CHARS)


def _sk(word: str) -> str:
    return skeleton(word)


EXACT_TOKENS = {_sk(w) for w in ("meets", "sufficient", "sufficiency", "lawfully", "passes")}
TOKEN_FORMS = re.compile("^(?:" + "|".join(_sk(w) for w in (
    r"certif(?:y|ied|ies|ying|ication|ications)", r"approv(?:e|ed|es|ing)")) + ")$")
TOKEN_PREFIXES = tuple(_sk(w) for w in ("complian", "complie", "comply", "conform", "satisf", "adequa", "guarante", "fulfil",
                                        "sufficien"))
RUN_STEMS = tuple(_sk(w) for w in ("complian", "complie", "comply", "conform", "satisf", "adequa", "guarante", "fulfil",
                                   "sufficien", "certified", "certification", "certifies", "approved", "inlinewith"))
CORE_STEMS = tuple(_sk(w) for w in ("complian", "complie", "comply", "conform", "certified", "certification", "approved", "satisf"))
EXTRA_PHRASES = ("in line with", "no gaps", "all good", "aligned with", "in accordance with", "consistent with the ndpa",
                 "consistent with ndpa", "ndpa ready", "ok to go", "is lawful", "are lawful", "was lawful", "fully lawful")
PHRASES = tuple(sorted({" ".join(re.findall(r"[a-z0-9]+", _sk(w))) for w in BANNED_PHRASES + EXTRA_PHRASES}))
# "met" and "meet" are ordinary words ("We met the DPO on 3 October") and a claim only in a few shapes:
# "requirement met", "it is met", "meet s.25", "meet the standard", or as the last word of the text.
MET_AFTER = {_sk(w) for w in ("requirement", "requirements", "is", "are", "was", "were", "been", "be", "fully", "all", "criteria",
                              "obligation", "obligations", "condition", "conditions", "standard", "standards", "it", "they",
                              "this", "these", "that", "not", "never")}
MEET_NEXT = {_sk(w) for w in ("s", "section", "ndpa", "gaid", "all", "every", "each", "in", "fully", "its", "their", "our")}
MEET_NEXT_PHRASES = tuple(" ".join(re.findall(r"[a-z0-9]+", _sk(w))) for w in (
    "the requirement", "the requirements", "the standard", "the standards", "the obligation", "the obligations",
    "the ndpa", "the act", "the criteria"))


def _met_claim(tokens: List[str], i: int) -> bool:
    word = tokens[i]
    nxt = tokens[i + 1] if i + 1 < len(tokens) else None
    if word == _sk("met"):
        return nxt is None or (i > 0 and tokens[i - 1] in MET_AFTER) or nxt in MEET_NEXT
    if word == _sk("meet"):
        tail = " ".join(tokens[i + 1:i + 3])
        return nxt is None or nxt in MEET_NEXT or any(tail.startswith(ph) for ph in MEET_NEXT_PHRASES)
    return False


def violation(text: str) -> Optional[str]:
    """The banned wording found in this text, or None. Used when text is written and again when it is printed."""
    sk = skeleton(text)
    tokens = re.findall(r"[a-z0-9]+", sk)
    spaced = " ".join(tokens)
    for phrase in PHRASES:
        if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", spaced):
            return phrase
    for i, token in enumerate(tokens):
        if token in EXACT_TOKENS or TOKEN_FORMS.match(token) or token.startswith(TOKEN_PREFIXES) or _met_claim(tokens, i):
            return token
    # The core stems are claims wherever they sit inside ONE word ("noncompliant", "fullycompliant", "NDPAcompliant",
    # "uncertified", "precertified").
    for token in tokens:
        for stem in CORE_STEMS:
            if stem in token:
                return stem
    # "c o m p l i a n t", "compl iant", "com-pliant": letters split up by spaces or marks. A stem counts only where it
    # BEGINS at the start of a word, so words that merely contain one across a boundary ("Useful file references",
    # "silicon form") are left alone.
    run, starts = "", set()
    for token in tokens:
        starts.add(len(run))
        run += token
    for stem in RUN_STEMS:
        at = run.find(stem)
        while at != -1:
            if at in starts:
                return stem
            at = run.find(stem, at + 1)
    return None


def safe_text(text: Optional[str]) -> Optional[str]:
    """Text for display in a pack: stored text that fails the check today is replaced, never printed."""
    if text is None:
        return None
    return WITHHELD if violation(text) else text


def clean_text(value: Optional[str], field: str, limit: int = MAX_TEXT, required: bool = False) -> Optional[str]:
    text = _CONTROL.sub("", value or "").strip()
    if not text:
        if required:
            raise TextError(f"{field} is required.")
        return None
    if len(text) > limit:
        raise TextError(f"{field} must be at most {limit} characters.")
    word = violation(text)
    if word:
        raise TextError(GUIDANCE.format(word=word))
    return text


def _iso(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def _day(value: Optional[datetime]) -> str:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d")


def _domain(row: Dict[str, Any]) -> str:
    domain = row.get("reviewer_domain") or "email domain not recorded"
    return "email domain withheld" if violation(domain) else domain  # the domain is chosen by the account holder too


def _who(row: Dict[str, Any]) -> str:
    """The name as the account gave it, with the email domain, never implying a licence was checked."""
    name = "Reviewer (name withheld)" if violation(row["reviewer_name"]) else row["reviewer_name"]
    return f"{name} ({_domain(row)}), a reviewer named by this organisation,"


def review_view(row: Dict[str, Any]) -> Dict[str, Any]:
    name = row["reviewer_name"]
    return {"outcome": row["outcome"], "outcome_label": OUTCOMES[row["outcome"]], "reviewer_name": name,
            "reviewer_domain": _domain(row),
            "reviewed_at": _iso(row["reviewed_at"]), "comment": safe_text(row.get("comment")),
            "label": f"Practitioner review recorded by {_who(row)} on {_day(row['reviewed_at'])}"}


def clause_view(row: Dict[str, Any]) -> Dict[str, Any]:
    name = row["reviewer_name"]
    day = _day(row["verified_at"])
    who = _who(row)
    return {"verified": bool(row["verified"]), "reviewer_name": name, "reviewer_domain": _domain(row),
            "at": _iso(row["verified_at"]), "note": safe_text(row.get("note")),
            "label": (f"reference reviewed by {who} {day}" if row["verified"]
                      else f"reference marked as not confirmed by {who} {day}")}


def latest_reviews(org_id: str) -> Dict[str, Dict[str, Any]]:
    """Newest practitioner review per requirement key, as shown."""
    rows = execute_query(
        "SELECT DISTINCT ON (requirement_key) requirement_key, outcome, reviewer_name, reviewer_domain, reviewed_at, comment "
        "FROM compliance_practitioner_reviews WHERE org_id = %s "
        "ORDER BY requirement_key, reviewed_at DESC, id DESC", (str(org_id),)) or []
    return {r["requirement_key"]: review_view(r) for r in rows}


def latest_clauses(org_id: str) -> Dict[str, Dict[str, Any]]:
    """Newest clause verification per requirement key (the overlay: newest row wins)."""
    rows = execute_query(
        "SELECT DISTINCT ON (requirement_key) requirement_key, verified, reviewer_name, reviewer_domain, verified_at, note "
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
