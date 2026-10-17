"""Attestation storage (packet C3a): current answers, history and the one write path.

Every query is scoped by organization. A write runs in one transaction that
takes a per-question advisory lock, checks the owner is a member of this
organization (row lock), supersedes the current answer, inserts the new one
and writes `audit_log` in the same transaction. A failure at any step leaves
the previous answer current and nothing audited.
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from psycopg.types.json import Jsonb

from backend.app.compliance import attestations as truth
from backend.app.compliance import questionnaire as qn
from backend.app.compliance import register
from backend.app.core import database
from backend.app.core.database import execute_query

DEFAULT_TIMEZONE = "Africa/Lagos"
HISTORY_LIMIT = 100
HTTPS_LINK = re.compile(r"^https://\S+$")


class ConflictError(RuntimeError):
    """The current answer changed while this one was being recorded. The API maps it to 409."""


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _public(row: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    answer = row["answer"]
    return {
        "id": str(row["id"]),
        "value": answer.get("value"),
        "date": answer.get("date"),
        "text": answer.get("text"),
        "owner_user_id": str(row["owner_user_id"]) if row.get("owner_user_id") else None,
        "owner_name": row.get("owner_name"),
        "attested_at": _iso(row["attested_at"]),
        "expires_at": _iso(row["expires_at"]),
        "expired": truth.is_expired(row, now),
        "evidence_link": row.get("evidence_link"),
        "notes": row.get("notes"),
    }


CURRENT_SQL = (
    "SELECT a.id, a.question_key, a.answer, a.owner_user_id, p.full_name AS owner_name, a.attested_at, "
    "a.expires_at, a.evidence_link, a.notes FROM compliance_attestations a "
    "LEFT JOIN profiles p ON p.id = a.owner_user_id "
    "WHERE a.org_id = %s AND a.superseded_by IS NULL"
)


def current_rows(org_id: str) -> Dict[str, Dict[str, Any]]:
    """Current answer per question for an organization, keyed by question key."""
    return {row["question_key"]: row for row in execute_query(CURRENT_SQL, (org_id,)) or []}


def _answer_state(row: Optional[Dict[str, Any]], shown: bool, now: datetime) -> str:
    if not shown or row is None:
        return "unanswered"
    if truth.is_expired(row, now):
        return "expired"
    if row["answer"].get("value") == qn.NOT_SURE:
        return "not_sure"
    return "answered"


def questionnaire(org: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Every question with its current answer, shown state and effect on the register."""
    # Imported here: status reads this module's rows, so a top-level import would be circular.
    from backend.app.compliance.status import REASON_TEXT, STATUS_LABELS

    now = now or datetime.now(timezone.utc)
    current = current_rows(str(org["id"]))
    titles = {g["key"]: g["title"] for g in register.REGISTER["groups"]}
    questions = []
    for question in qn.QUESTIONS:
        shown = truth.is_shown(question, current)
        row = current.get(question["key"])
        entry: Dict[str, Any] = {
            "key": question["key"], "group": question["group"], "group_title": titles[question["group"]],
            "prompt": question["prompt"], "type": question["type"], "shown": shown,
            "options": question.get("options", []),
            "allow_not_applicable": bool(question.get("allow_not_applicable")),
            "allows_date": bool(question.get("allows_date")) or question["type"] == "date",
            "date_label": question.get("date_label"),
            "allows_text": bool(question.get("allows_text")), "text_label": question.get("text_label"),
            "text_max": question.get("text_max"),
            "expiry_days_from_date": question.get("expiry_days_from_date"),
            "show_if": question.get("show_if"),
            "evidences": [{"key": k, "title": register.requirement(k)["title"]} for k in question["evidences"]],
            "applicability": [{"requirement_key": r["target"], "when": r["when"]}
                              for r in question.get("applicability", [])],
            "answer_state": _answer_state(row, shown, now),
            "current": _public(row, now) if row else None,
            "status": None, "status_label": None, "reason": None, "reason_text": None,
        }
        if question["evidences"]:
            outcome = truth.question_outcome(question, row, shown, now)
            entry.update(status=outcome["status"], status_label=STATUS_LABELS[outcome["status"]],
                         reason=outcome["reason"], reason_text=REASON_TEXT.get(outcome["reason"], ""))
        questions.append(entry)
    return {
        "disclaimer": register.DISCLAIMER,
        "version": qn.QUESTIONNAIRE["version"],
        "register_version": qn.QUESTIONNAIRE["register_version"],
        "display_timezone": org.get("display_timezone") or DEFAULT_TIMEZONE,
        "answered": sum(1 for q in questions if q["answer_state"] != "unanswered"),
        "questions": questions,
    }


def history(org_id: str, question_key: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    rows = execute_query(
        "SELECT a.id, a.answer, a.owner_user_id, p.full_name AS owner_name, a.attested_at, a.expires_at, "
        "a.evidence_link, a.notes, a.superseded_by IS NOT NULL AS superseded "
        "FROM compliance_attestations a LEFT JOIN profiles p ON p.id = a.owner_user_id "
        "WHERE a.org_id = %s AND a.question_key = %s ORDER BY a.attested_at DESC, a.created_at DESC LIMIT %s",
        (org_id, question_key, HISTORY_LIMIT)) or []
    return [{**_public(row, now), "superseded": bool(row["superseded"])} for row in rows]


def _evidence_link(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if len(value) > 500 or not HTTPS_LINK.match(value):
        raise truth.AnswerError("The evidence link must be an https:// address of at most 500 characters.")
    return value


def _notes(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    if len(value) > 1000:
        raise truth.AnswerError("Notes must be at most 1000 characters.")
    return value.strip()


def _current_in(conn, org_id: str) -> Dict[str, Dict[str, Any]]:
    return {row["question_key"]: row for row in conn.execute(CURRENT_SQL, (org_id,)).fetchall()}


def record(org: Dict[str, Any], actor_id: str, *, question_key: str, answer: Any, owner_user_id: str,
           expires_at: Optional[datetime] = None, evidence_link: Optional[str] = None,
           notes: Optional[str] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Record an answer, superseding the current one in the same transaction, and audit it."""
    now = now or datetime.now(timezone.utc)
    question = qn.question(question_key)
    if question is None:
        raise truth.AnswerError("That question is not in the questionnaire.")
    normalized = truth.normalize_answer(question, answer, today=now.date())
    expiry = truth.expiry_for(question, normalized, expires_at, now)
    link, memo = _evidence_link(evidence_link), _notes(notes)
    org_id, actor, owner = str(org["id"]), str(actor_id), str(owner_user_id)
    new_id = str(uuid.uuid4())

    with database.get_db() as conn:
        with conn.transaction():
            # One writer per (organization, question): the supersede below depends on it.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"compliance:{org_id}:{question_key}",))
            # FOR SHARE blocks a concurrent membership removal until this write commits.
            member = conn.execute(
                "SELECT 1 FROM organization_members WHERE org_id = %s AND user_id = %s FOR SHARE",
                (org_id, owner)).fetchone()
            if member is None:
                raise truth.AnswerError("The owner must be a member of this organization.")
            current = _current_in(conn, org_id)
            if not truth.is_shown(question, current):
                raise truth.AnswerError("This question is not shown for your current answers.")
            prior = current.get(question_key)
            if prior is not None:
                # The FK to the new row is deferred to commit, so it may point at the row inserted below.
                moved = conn.execute(
                    "UPDATE compliance_attestations SET superseded_by = %s "
                    "WHERE id = %s AND org_id = %s AND superseded_by IS NULL",
                    (new_id, prior["id"], org_id)).rowcount
                if moved != 1:
                    raise ConflictError("The current answer changed. Reload the questionnaire and try again.")
            conn.execute(
                "INSERT INTO compliance_attestations (id, org_id, question_key, questionnaire_version, answer, "
                "owner_user_id, attested_by, attested_at, expires_at, evidence_link, notes) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (new_id, org_id, question_key, qn.QUESTIONNAIRE["version"], Jsonb(normalized), owner, actor,
                 now, expiry, link, memo))
            # Answer text and notes stay out of the audit trail: they can be personal data.
            conn.execute(
                "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (org_id, actor, "compliance.attestation.recorded", "compliance_attestation", new_id,
                 Jsonb({"question_key": question_key, "value": normalized["value"],
                        "date": normalized.get("date"),
                        "superseded_id": str(prior["id"]) if prior else None,
                        "owner_user_id": owner, "expires_at": expiry.isoformat(),
                        "evidence_link_recorded": link is not None,
                        "questionnaire_version": qn.QUESTIONNAIRE["version"]})))
    return {"id": new_id, "question_key": question_key, "value": normalized["value"],
            "superseded_id": str(prior["id"]) if prior else None, "expires_at": _iso(expiry)}
