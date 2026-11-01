"""Expiry reminders for customer answers (packet C3b).

A daily job, run under the same atomic `cron_runs` claim as the scan sweep (from
the in-process scheduler and from the Inngest cron). For each current answer that
expires within 30 or 7 days it records a `compliance_reminders` row FIRST, in the
same transaction as the in-app notification, and only then sends the email. A
retry therefore cannot send twice: the second pass finds the row and skips. The
cost is that a crash between the commit and the email loses that email; the
in-app notification is already there.

An answer in the 7-day window gets the 7-day reminder only, never both at once.
A stale claim cannot write or send: the claim is checked, under FOR SHARE, in
every transaction that writes, and again just before each email.

The email names the requirement, the expiry date and a link. It carries no
answer content, no notes and no evidence link.
"""
import asyncio
import html
import logging
import os
import socket
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.app.compliance import questionnaire as qn
from backend.app.compliance import register
from backend.app.compliance.incidents import DEFAULT_TIMEZONE, zone_for
from backend.app.core import database
from backend.app.core.config import FRONTEND_URL
from backend.app.core.cron_claim import (
    COMPLIANCE_REMINDERS_CRON_NAME,
    claim_cron_run,
    complete_cron_run,
    lock_cron_claim,
    release_cron_run,
)
from backend.app.core.execution_fence import ClaimLost
from backend.app.services import mailer, notification_messages, notifications

logger = logging.getLogger("cyphward.compliance.reminders")

THRESHOLDS = (30, 7)  # days before expiry, largest first
LINK_PATH = "/comply"
DUE_SQL = """
SELECT a.id, a.org_id, a.question_key, a.owner_user_id, a.expires_at, o.name AS org_name,
       o.display_timezone, t.threshold_days
FROM compliance_attestations a
JOIN organizations o ON o.id = a.org_id
-- The smallest threshold the answer is inside: 5 days left is a 7-day reminder, not also a 30-day one.
CROSS JOIN LATERAL (SELECT min(x) AS threshold_days FROM unnest(%s::int[]) AS x
                    WHERE a.expires_at <= %s + make_interval(days => x)) t
WHERE a.superseded_by IS NULL
  AND NOT EXISTS (SELECT 1 FROM organization_suspensions os WHERE os.org_id = a.org_id AND os.status = 'deleted')
  AND a.expires_at > %s
  AND a.answer ->> 'value' IS DISTINCT FROM 'not_sure'
  AND t.threshold_days IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM compliance_reminders r
                  WHERE r.attestation_id = a.id AND r.threshold_days = t.threshold_days)
ORDER BY a.expires_at, a.id
"""
RECIPIENTS_SQL = """
SELECT DISTINCT ON (lower(p.email)) p.id, p.email, p.full_name
FROM profiles p
WHERE p.email IS NOT NULL AND p.email <> '' AND p.id IN (
  -- Current members only: the answer's owner, if they are still a member, plus the organisation's owners and admins.
  SELECT user_id FROM organization_members WHERE org_id = %s AND (user_id = %s OR role IN ('owner', 'admin')))
ORDER BY lower(p.email)
"""


DPO_DUE_SQL = """
SELECT o.id, o.name, o.plan, o.display_timezone FROM organizations o
WHERE NOT EXISTS (SELECT 1 FROM dpo_reminders r WHERE r.org_id = o.id AND r.period_key = %s)
  AND NOT EXISTS (SELECT 1 FROM evidence_packs p WHERE p.org_id = o.id AND p.issued_at >= %s AND p.dpo IS NOT NULL)
  AND EXISTS (SELECT 1 FROM domains d WHERE d.org_id = o.id AND d.verification_status = 'verified')
  AND EXISTS (SELECT 1 FROM organization_members m WHERE m.org_id = o.id AND m.role IN ('owner', 'admin'))
  AND NOT EXISTS (SELECT 1 FROM organization_suspensions os WHERE os.org_id = o.id AND os.status = 'deleted')
ORDER BY o.id
"""


def dpo_period(now: datetime) -> Dict[str, Any]:
    """The calendar half-year the reminder belongs to: ('2026-H2', start of that half)."""
    now = now.astimezone(timezone.utc)
    first = 1 if now.month <= 6 else 7
    return {"key": f"{now.year}-H{1 if first == 1 else 2}",
            "start": datetime(now.year, first, 1, tzinfo=timezone.utc)}


def dpo_notification_copy() -> Dict[str, str]:
    """The in-app wording, from the reviewed templates (services/notification_messages.py)."""
    title, body = notification_messages.render("compliance_report_due", {})
    return {"title": title, "body": body}


def dpo_email_copy(org_name: str, url: str) -> Dict[str, str]:
    subject = f"Six-monthly data-security report due: {org_name}"[:200]
    text = (f"The six-monthly data-security report for {org_name} is due this half-year.\n\n"
            "Open the Packs area to issue a data-security section for your DPO. It lists scans run, coverage, findings "
            "opened and resolved, and incident counts, and it is supporting evidence for a DPCO. It is not a "
            f"Compliance Audit Return.\n\nOpen Cyphward: {url}\n\nThis reminder is sent once each half-year. — Cyphward")
    page = (f'<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;'
            f'color:#3A352D;line-height:1.65;max-width:520px"><p>The six-monthly data-security report for '
            f'<strong>{html.escape(org_name)}</strong> is due this half-year.</p><p>Open the Packs area to issue a '
            f'data-security section for your DPO. It is supporting evidence for a DPCO, not a Compliance Audit Return.</p>'
            f'<p><a href="{html.escape(url)}" style="display:inline-block;background:#E5532B;color:#fff;'
            f'text-decoration:none;border-radius:8px;padding:12px 22px;font-weight:700">Open Cyphward</a></p>'
            f'<p style="font-size:12px;color:#8A8377">This reminder is sent once each half-year.</p></div>')
    return {"subject": subject, "text": text, "html": page}


def _record_dpo_reminder(claim: Dict[str, Any], item: Dict[str, Any], period: str) -> Optional[List[Dict[str, Any]]]:
    with database.get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                lock_cron_claim(cur, claim)
                cur.execute("INSERT INTO dpo_reminders (org_id, period_key) VALUES (%s, %s) ON CONFLICT DO NOTHING "
                            "RETURNING org_id", (item["id"], period))
                if cur.fetchone() is None:
                    return None
                cur.execute(RECIPIENTS_SQL, (item["id"], None))
                people = cur.fetchall()
                notifications.emit("compliance_report_due", item["id"], key=f"dpo_report:{item['id']}:{period}",
                                   recipients=[p["id"] for p in people], cur=cur)
                return people


async def _dpo_sweep(claim: Dict[str, Any], now: datetime, result: Dict[str, Any]) -> None:
    """Growth organisations that have not issued a pack this half-year get one reminder per half-year."""
    from backend.app.compliance.status import is_starter

    period = dpo_period(now)
    due = await asyncio.to_thread(lambda: database.execute_query(DPO_DUE_SQL, (period["key"], period["start"])) or [])
    for item in due:
        if await asyncio.to_thread(is_starter, {"id": item["id"], "plan": item["plan"]}):
            result["dpo_skipped"] += 1
            continue
        recipients = await asyncio.to_thread(_record_dpo_reminder, claim, item, period["key"])
        if recipients is None:
            result["dpo_skipped"] += 1
            continue
        result["dpo_reminded"] += 1
        email = dpo_email_copy(item["name"], link())
        for person in recipients:
            if not await asyncio.to_thread(_claim_is_current, claim):
                raise ClaimLost("Scheduler claim is no longer current")
            if await asyncio.to_thread(notifications.email_muted, person["id"], "compliance"):
                result["email_muted"] += 1
                continue
            try:
                await mailer.send_email_async(person["email"], email["subject"], email["html"], email["text"],
                                              person.get("full_name"), kind="alerts")
                result["emails_sent"] += 1
            except Exception:
                result["email_failures"] += 1
                logger.warning("DPO reminder email failed for an organisation member", exc_info=True)


# Trials and plan periods that end within 7 days (notifications phase 1). Each subscription period gets the 7-day
# notice once and the 1-day notice once; a period first seen inside the last day gets the 1-day notice only.
BILLING_DUE_SQL = """
SELECT s.id, s.org_id, s.status, s.current_period_end, o.display_timezone
FROM subscriptions s JOIN organizations o ON o.id = s.org_id
WHERE s.status IN ('trialing', 'active') AND s.current_period_end > %s
  AND s.current_period_end <= %s + interval '7 days'
  AND NOT EXISTS (SELECT 1 FROM organization_suspensions os WHERE os.org_id = s.org_id AND os.status = 'deleted')
ORDER BY s.current_period_end, s.id
"""


def billing_kind(status: str, ends_at: datetime, now: datetime) -> str:
    what = "trial" if status == "trialing" else "subscription"
    return f"{what}_ending_tomorrow" if ends_at - now <= timedelta(days=1) else f"{what}_ending_soon"


def _billing_sweep(claim: Dict[str, Any], now: datetime, result: Dict[str, Any]) -> None:
    for sub in database.execute_query(BILLING_DUE_SQL, (now, now)) or []:
        kind = billing_kind(sub["status"], sub["current_period_end"], now)
        with database.get_db() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    lock_cron_claim(cur, claim)
                    result["billing_notified"] += notifications.emit(
                        kind, sub["org_id"], key=f"{kind}:{sub['id']}:{sub['current_period_end'].isoformat()}",
                        params={"date": expiry_date_text(sub["current_period_end"], sub["display_timezone"])},
                        cur=cur)


def _claimant_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def what_expires(question_key: str) -> Optional[str]:
    """The register requirement(s) the answer evidences, else the question itself. Never the answer."""
    question = qn.question(question_key)
    if question is None:
        return None
    titles = [register.requirement(k)["title"] for k in question["evidences"]]
    return "; ".join(titles) if titles else question["prompt"]


def expiry_date_text(expires_at: datetime, tz_name: Optional[str]) -> str:
    local = expires_at.astimezone(zone_for(tz_name or DEFAULT_TIMEZONE))
    return f"{local.day} {local.strftime('%B %Y')}"


def link() -> str:
    return f"{FRONTEND_URL}{LINK_PATH}"


def notification_copy(subject_text: str, expiry_text: str, threshold: int) -> Dict[str, str]:
    """The in-app wording, from the reviewed templates (services/notification_messages.py)."""
    kind = "attestation_expiring_7" if threshold <= 7 else "attestation_expiring_30"
    title, body = notification_messages.render(kind, {"item": subject_text, "date": expiry_text})
    return {"title": title, "body": body}


def email_copy(org_name: str, subject_text: str, expiry_text: str, threshold: int, url: str) -> Dict[str, str]:
    subject = f"Renewal due by {expiry_text}: {subject_text}"[:200]
    text = (f"An answer recorded for {org_name} on Cyphward expires on {expiry_text} "
            f"({threshold} days or fewer from now).\n\n"
            f"Item: {subject_text}\n\n"
            "Review it and record a fresh answer to keep your records current. "
            "After it expires, this item shows as awaiting your input until a fresh answer is recorded.\n\n"
            f"Open the questionnaire: {url}\n\n"
            "This reminder is sent once for each threshold. It does not include your answer.\n\n"
            "— Cyphward")
    safe = {k: html.escape(v) for k, v in (("org", org_name), ("item", subject_text), ("date", expiry_text))}
    page = (f'<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;'
            f'color:#3A352D;line-height:1.65;max-width:520px">'
            f'<p>An answer recorded for <strong>{safe["org"]}</strong> on Cyphward expires on '
            f'<strong>{safe["date"]}</strong> ({threshold} days or fewer from now).</p>'
            f'<p>Item: <strong>{safe["item"]}</strong></p>'
            f'<p>Review it and record a fresh answer to keep your records current. '
            f'After it expires, this item shows as awaiting your input until a fresh answer is recorded.</p>'
            f'<p><a href="{html.escape(url)}" style="display:inline-block;background:#E5532B;color:#fff;'
            f'text-decoration:none;border-radius:8px;padding:12px 22px;font-weight:700">Open the questionnaire</a></p>'
            f'<p style="font-size:12px;color:#8A8377">This reminder is sent once for each threshold. '
            f'It does not include your answer.</p></div>')
    return {"subject": subject, "text": text, "html": page}


def _due(now: datetime) -> List[Dict[str, Any]]:
    return database.execute_query(DUE_SQL, (list(THRESHOLDS), now, now)) or []


def _record_reminder(claim: Dict[str, Any], item: Dict[str, Any], subject_text: str, expiry_text: str,
                     ) -> Optional[List[Dict[str, Any]]]:
    """Under the held claim: the reminder row, then the in-app notification, in one transaction.
    Returns the email recipients, or None when another run already recorded this reminder."""
    with database.get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                lock_cron_claim(cur, claim)
                cur.execute(
                    "INSERT INTO compliance_reminders (attestation_id, threshold_days) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING RETURNING attestation_id", (item["id"], item["threshold_days"]))
                if cur.fetchone() is None:
                    return None
                cur.execute(RECIPIENTS_SQL, (item["org_id"], item["owner_user_id"]))
                people = cur.fetchall()
                notifications.emit(f"attestation_expiring_{item['threshold_days']}", item["org_id"],
                                   key=f"attestation:{item['id']}:{item['threshold_days']}",
                                   params={"item": subject_text, "date": expiry_text},
                                   recipients=[p["id"] for p in people], cur=cur)
                return people


def _claim_is_current(claim: Dict[str, Any]) -> bool:
    try:
        with database.get_db() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    lock_cron_claim(cur, claim)
        return True
    except ClaimLost:
        return False


async def _sweep(claim: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    result = {"due": 0, "reminded": 0, "emails_sent": 0, "email_failures": 0, "skipped": 0,
              "dpo_reminded": 0, "dpo_skipped": 0, "email_muted": 0, "billing_notified": 0}
    due = await asyncio.to_thread(_due, now)
    result["due"] = len(due)
    for item in due:
        subject_text = what_expires(item["question_key"])
        if subject_text is None:  # a question retired from the questionnaire
            result["skipped"] += 1
            continue
        expiry_text = expiry_date_text(item["expires_at"], item["display_timezone"])
        recipients = await asyncio.to_thread(_record_reminder, claim, item, subject_text, expiry_text)
        if recipients is None:
            result["skipped"] += 1
            continue
        result["reminded"] += 1
        email = email_copy(item["org_name"], subject_text, expiry_text, item["threshold_days"], link())
        for person in recipients:
            if not await asyncio.to_thread(_claim_is_current, claim):
                raise ClaimLost("Scheduler claim is no longer current")
            if await asyncio.to_thread(notifications.email_muted, person["id"], "compliance"):
                result["email_muted"] += 1
                continue
            try:
                await mailer.send_email_async(person["email"], email["subject"], email["html"], email["text"],
                                              person.get("full_name"), kind="alerts")
                result["emails_sent"] += 1
            except Exception:
                result["email_failures"] += 1
                logger.warning("compliance reminder email failed for an organisation member", exc_info=True)
    await _dpo_sweep(claim, now, result)
    await asyncio.to_thread(_billing_sweep, claim, now, result)
    # Catch-up for critical notification emails a restart left pending (services/notifications.py).
    result["notification_emails"] = await notifications.deliver_pending_emails()
    return result


async def run_compliance_reminders(now: Optional[datetime] = None, run_day: Optional[date] = None) -> Dict[str, Any]:
    """The daily job. Returns {"claimed": False} without touching anything when another owner holds today's claim."""
    now = now or datetime.now(timezone.utc)
    run_day = run_day or now.astimezone(timezone.utc).date()
    claim = await asyncio.to_thread(claim_cron_run, COMPLIANCE_REMINDERS_CRON_NAME, run_day, _claimant_id())
    if not claim:
        return {"claimed": False, "due": 0, "reminded": 0}
    try:
        result = await _sweep(claim, now)
        if not await asyncio.to_thread(complete_cron_run, COMPLIANCE_REMINDERS_CRON_NAME, run_day, claim):
            raise ClaimLost("Scheduler ownership expired before completion")
    except BaseException:
        await asyncio.to_thread(release_cron_run, COMPLIANCE_REMINDERS_CRON_NAME, run_day, claim)
        raise
    result["claimed"] = True
    logger.info("compliance reminders complete: %s", result)
    return result
