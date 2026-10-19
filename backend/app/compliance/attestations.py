"""Attestation truth table (packet C3a, section 3). Pure: no database access.

A customer answer is evidence labelled `customer_attested`. It turns into status
only through the questionnaire's own mapping:

- yes / no / date answers become present / gap through `evidence_on`;
- not sure, an unanswered question and an expired answer are awaiting input;
- an applicability answer that excludes a requirement makes it not applicable,
  with the recorded answer as the reason;
- superseded answers never reach this module (the store passes only current rows).

Nothing here is a legal verdict: the statuses describe what the customer has
answered and whether that answer has expired.
"""
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.app.compliance import questionnaire as qn

PRESENT, GAP, NOT_APPLICABLE, AWAITING = "present", "gap", "not_applicable", "awaiting_input"
DEFAULT_EXPIRY = timedelta(days=365)  # 12 months
MAX_EXPIRY = timedelta(days=730)  # 24 months (plan section 5)
LONG_DIGITS = re.compile(r"\d{7,}")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ANSWER_KEYS = {"value", "date", "text"}


class AnswerError(ValueError):
    """A request the questionnaire cannot accept. The API maps it to 422."""


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def is_expired(row: Dict[str, Any], now: datetime) -> bool:
    return _as_utc(row["expires_at"]) <= now


def is_shown(question: Dict[str, Any], current: Dict[str, Dict[str, Any]]) -> bool:
    """A follow-up question is shown only when its prerequisite has the value it names.

    The prerequisite's expiry is ignored here: it decides what is asked, not what counts.
    """
    rule = question.get("show_if")
    if not rule:
        return True
    row = current.get(rule["question"])
    return row is not None and row["answer"].get("value") == rule["value"]


def question_outcome(question: Dict[str, Any], row: Optional[Dict[str, Any]], shown: bool,
                     now: datetime) -> Dict[str, str]:
    """Status and reason for one question's current answer."""
    if not shown or row is None:
        return {"status": AWAITING, "reason": "awaiting_answer"}
    if is_expired(row, now):
        return {"status": AWAITING, "reason": "answer_expired"}
    value = row["answer"].get("value")
    if value == qn.NOT_SURE:
        return {"status": AWAITING, "reason": "answer_not_sure"}
    status = question["evidence_on"].get(value)
    if status is None:
        return {"status": AWAITING, "reason": "awaiting_answer"}
    return {"status": status, "reason": REASONS[status]}


REASONS = {PRESENT: "answer_present", GAP: "answer_gap", NOT_APPLICABLE: "answered_not_applicable"}
REASON_TEXT = {
    "awaiting_answer": "No answer yet. An owner or admin can answer this on the questionnaire.",
    "answer_expired": "Renewal due: the answer has expired. Answer the question again.",
    "answer_not_sure": "You answered not sure, so this counts as awaiting input, not as a gap.",
    "answer_present": "You told us this is in place. This is your statement; Cyphward did not check it.",
    "answer_gap": "You told us this isn't in place yet.",
    "answered_not_applicable": "Your answer means this requirement doesn't apply to you, so it leaves the readiness count.",
}


def requirement_outcome(requirement_key: str, current: Dict[str, Dict[str, Any]],
                        now: datetime) -> Optional[Dict[str, Any]]:
    """Customer-answer status for one requirement, or None when no question asks about it.

    Precedence: an applicability answer that excludes the requirement wins; then
    any gap; then any awaiting question; otherwise present. A not-sure or
    unanswered applicability question leaves the requirement applicable (D13).
    """
    evidence = qn.questions_evidencing(requirement_key)
    rules = qn.applicability_for(requirement_key)
    if not evidence and not rules:
        return None
    for rule in rules:
        question = rule["question"]
        row = current.get(question["key"])
        if row is None or not is_shown(question, current):
            continue
        if is_expired(row, now):
            entry = {"question_key": question["key"], "row": row, "status": AWAITING, "reason": "answer_expired"}
            return _result(AWAITING, "answer_expired", [entry])
        if row["answer"].get("value") == rule["when"]:
            entry = {"question_key": question["key"], "row": row, "status": NOT_APPLICABLE,
                     "reason": "answered_not_applicable"}
            return _result(NOT_APPLICABLE, "answered_not_applicable", [entry])

    entries = []
    for question in evidence:
        shown = is_shown(question, current)
        outcome = question_outcome(question, current.get(question["key"]), shown, now)
        entries.append({"question_key": question["key"], "row": current.get(question["key"]) if shown else None,
                        **outcome})
    for wanted in (NOT_APPLICABLE, GAP, AWAITING):
        for entry in entries:
            if entry["status"] == wanted:
                return _result(wanted, entry["reason"], entries)
    expiries = [_as_utc(e["row"]["expires_at"]) for e in entries if e["row"] is not None]
    return _result(PRESENT, "answer_present", entries, expires_at=min(expiries) if expiries else None)


def _result(status: str, reason: str, entries: List[Dict[str, Any]],
            expires_at: Optional[datetime] = None) -> Dict[str, Any]:
    return {"status": status, "reason": reason, "answers": entries, "expires_at": expires_at}


class HeadlineMismatch(AssertionError):
    """A row's headline status and source do not describe one evidence item. A bug, never a data state."""


def check_headline(status: str, source: Optional[str], sources: List[Dict[str, Any]]) -> None:
    """The headline (status, source) pair must be one of the requirement's own source items.

    Raised, not repaired: presentation code must never rewrite a status to make a row agree (a frozen,
    hashed snapshot would then hold data that no source produced)."""
    if source is None:
        return
    item = next((s for s in sources if s["source"] == source), None)
    if item is None or item["status"] != status:
        raise HeadlineMismatch(f"headline {source}/{status} is not one of {[(s['source'], s['status']) for s in sources]}")


def merge(observed: Optional[Dict[str, Any]], attested: Optional[Dict[str, Any]],
          observed_sourced: bool) -> Dict[str, Any]:
    """Combine a requirement's observed result with its customer-answer result.

    Customer-only requirements take the answer result. Where a requirement has
    observed evidence too (DPO contact, `observed_sourced`), the two stay
    separate: present if either is present, otherwise a gap if either is a gap,
    and both are always returned in `sources` so no label is shared.
    """
    if attested is None:
        return observed
    if not observed_sourced:
        base = observed or {"domains": [], "unlinked_finding_ids": []}
        sources = [{"source": "customer_attested", "status": attested["status"], "reason": attested["reason"]}]
        check_headline(attested["status"], "customer_attested", sources)
        return {**attested, "domains": base["domains"], "unlinked_finding_ids": base["unlinked_finding_ids"],
                "headline_source": "customer_attested", "sources": sources}
    sources = [
        {"source": "externally_observed", "status": observed["status"], "reason": observed["reason"]},
        {"source": "customer_attested", "status": attested["status"], "reason": attested["reason"]},
    ]
    if observed["status"] == PRESENT:
        head, source = observed, "externally_observed"
    elif attested["status"] == PRESENT:
        head, source = attested, "customer_attested"
    elif observed["status"] == GAP:
        head, source = observed, "externally_observed"
    else:
        head, source = attested, "customer_attested"
    check_headline(head["status"], source, sources)
    return {**observed, "status": head["status"], "reason": head["reason"], "answers": attested["answers"],
            "expires_at": attested.get("expires_at"), "headline_source": source, "sources": sources}


# ── Answer validation (before anything is written) ─────────────────────────


def normalize_answer(question: Dict[str, Any], answer: Any, today: date) -> Dict[str, Any]:
    if not isinstance(answer, dict) or not set(answer) <= ANSWER_KEYS or "value" not in answer:
        raise AnswerError("Answer needs a value, and may only include date and text.")
    value = answer["value"]
    if value not in qn.values_for(question):
        raise AnswerError(f"{value!r} is not an answer to this question.")
    normalized: Dict[str, Any] = {"value": value}

    if "date" in answer and answer["date"] is not None:
        if not question.get("allows_date") and question["type"] != "date":
            raise AnswerError("This question does not take a date.")
        normalized["date"] = _parse_date(answer["date"], today)
    if question["type"] == "date":
        if value == "date" and "date" not in normalized:
            raise AnswerError("Give the date.")
        if value != "date" and "date" in normalized:
            raise AnswerError("A date goes with a date answer only.")
    elif "date" in normalized and value == qn.NOT_SURE:
        raise AnswerError("A date does not go with this answer.")

    if "text" in answer and answer["text"] is not None:
        if not question.get("allows_text"):
            raise AnswerError("This question does not take text.")
        text = answer["text"]
        if not isinstance(text, str) or len(text) > question["text_max"]:
            raise AnswerError(f"Text must be a string of at most {question['text_max']} characters.")
        if LONG_DIGITS.search(text):
            raise AnswerError("Do not enter personal ID numbers.")
        if text.strip():
            normalized["text"] = text.strip()
    return normalized


def _parse_date(value: Any, today: date) -> str:
    if not isinstance(value, str) or not ISO_DATE.match(value):
        raise AnswerError("Dates must be YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise AnswerError("Dates must be real calendar dates.") from exc
    if parsed > today:
        raise AnswerError("A date cannot be in the future.")
    return parsed.isoformat()


def expiry_for(question: Dict[str, Any], answer: Dict[str, Any], expires_at: Optional[datetime],
               now: datetime) -> datetime:
    """Expiry for a new answer (D12). Date questions expire a fixed number of days after the date."""
    if "expiry_days_from_date" in question and answer["value"] == "date":
        if expires_at is not None:
            raise AnswerError("This answer's expiry follows its date; do not set one.")
        anchor = datetime.combine(date.fromisoformat(answer["date"]), time.min, tzinfo=timezone.utc)
        return anchor + timedelta(days=question["expiry_days_from_date"])
    if expires_at is None:
        return now + DEFAULT_EXPIRY
    expires_at = _as_utc(expires_at)
    if expires_at <= now:
        raise AnswerError("Expiry must be in the future.")
    if expires_at > now + MAX_EXPIRY:
        raise AnswerError("Expiry can be at most 24 months away.")
    return expires_at
