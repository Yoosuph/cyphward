"""Reviewed notification wording, in one place (notifications phase 1).

Every in-app notification and every notification email is rendered from a template here. A template takes only
values the page that the link opens already shows (a domain or host name, a date, a count, a member's email to the
people who manage members) and never raw scanner, worker or error text. A failed scan's sentence comes from the
reviewed failure categories (core/scan_failures.py).

Each kind names:
  category    the mute bucket a person can turn off in Settings (CATEGORIES)
  severity    info, warning or critical. Only critical events are emailed, and they are never dropped by the
              daily cap.
  recipients  "all" members, "admins" (owners and admins) or "owners" of the organisation, unless the trigger passes
              its own list.
  owner       True when the event also goes to the owner console. Every critical kind is owner-relevant, so a
              customer's mute never hides a critical event from the owner console (test_notifications.py).
  link        the path the notification opens.

Plain English, no claim wording (test_notifications.py runs the extended banned-phrase list over every template).
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from backend.app.core.scan_failures import failure_for

SEVERITIES = ("info", "warning", "critical")

# Category -> label shown in Settings. Keep the keys stable: they are stored in notification_preferences.
CATEGORIES: Dict[str, str] = {
    "scans": "Scans",
    "findings": "Findings",
    "billing": "Plan and trial",
    "members": "Team members",
    "organisation": "Organisation status",
    "compliance": "Compliance reminders",
}
CATEGORY_HINTS: Dict[str, str] = {
    "scans": "A scan finished, did not finish, or found a new host.",
    "findings": "A finding was rated critical or high, came back, or was resolved.",
    "billing": "Your trial or plan period ends in 7 days, and again the day before.",
    "members": "Someone was invited, joined or was removed.",
    "organisation": "Cyphward suspended this organisation or lifted the suspension.",
    "compliance": "A recorded answer expires within 30 days, or a report is due.",
}

Render = Callable[[Dict[str, Any], int], Tuple[str, str]]


@dataclass(frozen=True)
class Kind:
    category: str
    severity: str
    recipients: str
    owner: bool
    link: str
    render: Render


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many.format(n=count)


def _scan_completed(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    title = f"Scan finished for {p.get('domain') or 'your domain'}" if n == 1 else f"{n} scans finished"
    score = p.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        shown = int(score) if float(score).is_integer() else round(float(score), 1)
        first = (f"Score {shown}/100, grade {p['grade']}, within the declared scope. " if p.get("grade")
                 else f"Known-risk score {shown}/100. ")
    else:
        # posture_label is one of the risk engine's fixed labels (risk/engine.py), never scanner text.
        first = f"No score: {p['posture_label']}. " if p.get("posture_label") else "No score for this scan. "
    unchecked = int(p.get("not_evaluated") or 0)
    later = f" {unchecked} could not be checked this time (not evaluated)." if unchecked else ""
    body = (f"{first}{int(p.get('new') or 0)} new and {int(p.get('resolved') or 0)} resolved findings.{later} "
            "The results are on the Scans page.") if n == 1 else "The results are on the Scans page."
    return title, body


def _scan_failed(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    title = (f"Scan did not finish for {p.get('domain') or 'your domain'}" if n == 1
             else f"{n} scans did not finish")
    return title, failure_for(p.get("code"))["message"]


def _asset(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    title = f"New host found: {p.get('hostname') or 'a new host'}" if n == 1 else f"{n} new hosts found"
    return title, (f"It was found on {p.get('domain') or 'your domain'} during the latest scan. "
                   "Review it on the Assets page.")


def _finding(level: str) -> Render:
    def render(p: Dict[str, Any], n: int) -> Tuple[str, str]:
        where = p.get("hostname") or "your domain"
        title = (f"{level.capitalize()} finding on {where}" if n == 1
                 else f"{n} {level} findings recorded")
        again = " It was marked resolved before and was seen again." if p.get("reopened") else ""
        body = (_plural(n, f"A finding rated {level} was recorded.", f"{{n}} findings rated {level} were recorded.")
                + again + " Open Findings to see what each one is and how to fix it.")
        return title, body
    return render


def _finding_reopened(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    title = f"Finding seen again on {p.get('hostname') or 'your domain'}" if n == 1 else f"{n} findings seen again"
    return title, "A finding that was marked resolved was seen again by the latest scan. Open Findings to review it."


def _finding_resolved(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    title = f"Finding resolved on {p.get('hostname') or 'your domain'}" if n == 1 else f"{n} findings resolved"
    how = "A recheck" if p.get("recheck") else "The latest scan"
    return title, f"{how} no longer sees the issue. It is listed as resolved on the Findings page."


def _finding_still_open(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    title = f"Issue still present on {p.get('hostname') or 'your domain'}" if n == 1 else f"{n} issues still present"
    return title, "A recheck shows the issue is still there. The finding stays open; the fix steps are on the Findings page."


def _ending(what: str, soon: bool) -> Render:
    def render(p: Dict[str, Any], n: int) -> Tuple[str, str]:
        date = p.get("date") or "soon"
        org = p.get("org_name") or "this organisation"
        if what == "trial":
            title = f"Trial ends on {date}" if soon else "Trial ends within a day"
            body = (f"The trial for {org} ends on {date}. Contact Cyphward through the Contact page to arrange a "
                    "plan. Paid access starts after payment is confirmed.")
        else:
            title = f"Plan period ends on {date}" if soon else "Plan period ends within a day"
            body = (f"The current plan period for {org} ends on {date}. Contact Cyphward through the Contact page "
                    "to renew. After it ends, the workspace stays readable but new scans and reports pause.")
        return title, body
    return render


def _member_invited(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    title = f"{p.get('email') or 'Someone'} was invited" if n == 1 else f"{n} people were invited"
    return title, "Pending invitations are listed on the Team tab in Settings until they are accepted."


def _member_joined(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    title = f"{p.get('name') or 'Someone'} joined the workspace" if n == 1 else f"{n} people joined the workspace"
    return title, "Members and their roles are listed on the Team tab in Settings."


def _member_removed(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    title = f"{p.get('email') or 'A member'} was removed" if n == 1 else f"{n} members were removed"
    return title, "Cyphward removed this person's access to the workspace. Members are listed on the Team tab in Settings."


def _suspended(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    return ("This organisation is suspended",
            "Cyphward suspended this organisation. Changes and scheduled scans are paused; you can still sign in "
            "and read your pages. Contact Cyphward through the Contact page with any questions.")


def _unsuspended(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    return ("The suspension was lifted",
            "Cyphward lifted the suspension. Changes and scheduled scans work again.")


def _attestation(threshold: int) -> Render:
    def render(p: Dict[str, Any], n: int) -> Tuple[str, str]:
        if n > 1:
            return (f"{n} answers need renewing within {threshold} days",
                    "The answers that back these items expire soon. Review them and record fresh answers to keep "
                    "your records current.")
        return (f"Renewal due in {threshold} days: {p.get('item') or 'a recorded answer'}"[:200],
                f"The answer that backs this item expires on {p.get('date') or 'its expiry date'}. "
                "Review it and record a fresh answer to keep your records current.")
    return render


def _report_due(p: Dict[str, Any], n: int) -> Tuple[str, str]:
    return ("Six-monthly data-security report is due",
            "A DPO's six-monthly report covers data security for the last six months. Issue a data-security section "
            "from the Packs area; it is supporting evidence, not a Compliance Audit Return.")


KINDS: Dict[str, Kind] = {
    "scan_completed": Kind("scans", "info", "all", False, "/scans", _scan_completed),
    "scan_failed": Kind("scans", "warning", "all", True, "/scans", _scan_failed),
    "asset_discovered": Kind("scans", "info", "all", False, "/assets", _asset),
    "finding_critical": Kind("findings", "critical", "all", True, "/findings", _finding("critical")),
    "finding_high": Kind("findings", "warning", "all", False, "/findings", _finding("high")),
    "finding_reopened": Kind("findings", "info", "all", False, "/findings", _finding_reopened),
    "finding_resolved": Kind("findings", "info", "all", False, "/findings", _finding_resolved),
    "finding_still_open": Kind("findings", "info", "all", False, "/findings", _finding_still_open),
    "trial_ending_soon": Kind("billing", "info", "owners", True, "/settings", _ending("trial", True)),
    "trial_ending_tomorrow": Kind("billing", "warning", "owners", True, "/settings", _ending("trial", False)),
    "subscription_ending_soon": Kind("billing", "info", "owners", True, "/settings", _ending("plan", True)),
    "subscription_ending_tomorrow": Kind("billing", "warning", "owners", True, "/settings", _ending("plan", False)),
    "member_invited": Kind("members", "info", "admins", False, "/settings?tab=team", _member_invited),
    "member_joined": Kind("members", "info", "admins", False, "/settings?tab=team", _member_joined),
    "member_removed": Kind("members", "info", "admins", False, "/settings?tab=team", _member_removed),
    "org_suspended": Kind("organisation", "critical", "all", True, "/overview", _suspended),
    "org_unsuspended": Kind("organisation", "info", "all", True, "/overview", _unsuspended),
    "attestation_expiring_30": Kind("compliance", "info", "admins", False, "/comply", _attestation(30)),
    "attestation_expiring_7": Kind("compliance", "warning", "admins", False, "/comply", _attestation(7)),
    "compliance_report_due": Kind("compliance", "info", "admins", False, "/comply", _report_due),
}

# The finding kind for a severity; anything below high gets no "became critical or high" notification.
FINDING_KIND_BY_SEVERITY = {"critical": "finding_critical", "high": "finding_high"}


def render(kind: str, params: Optional[Dict[str, Any]], count: int = 1, audience: str = "customer",
           ) -> Tuple[str, str]:
    """(title, body) for a kind. The owner console's title names the organisation, since it lists every one."""
    params = params or {}
    title, body = KINDS[kind].render(params, max(int(count or 1), 1))
    if audience == "owner" and params.get("org_name"):
        title = f"{params['org_name']}: {title}"
    return title[:200], body[:600]


# ── Rows written before phase 1 ────────────────────────────────────────────
# Old rows have no category and some carry scanner text in the body. They are kept and shown with their title; the
# kinds that could carry raw text are shown with a reviewed body instead of the stored one.
LEGACY_CATEGORY = {
    "scan_completed": "scans", "new_asset": "scans", "critical_finding": "findings", "high_risk_exposure": "findings",
    "finding_reopened": "findings", "finding_resolved": "findings", "compliance_renewal": "compliance",
    "compliance_report_due": "compliance",
}
LEGACY_REVIEWED_BODY = {
    "critical_finding": "A finding rated critical was recorded. Open Findings to see what it is and how to fix it.",
    "high_risk_exposure": "A finding rated high was recorded. Open Findings to see what it is and how to fix it.",
    "finding_reopened": "A finding that was marked resolved was seen again. Open Findings to review it.",
    "new_asset": "A new host was found during a scan. Review it on the Assets page.",
}
LEGACY_SEVERITY = {"low": "info", "medium": "warning", "high": "warning"}


def legacy_category(type_: Optional[str]) -> str:
    return LEGACY_CATEGORY.get(type_ or "", "scans")


def display_severity(severity: Optional[str]) -> str:
    sev = (severity or "info").lower()
    return sev if sev in SEVERITIES else LEGACY_SEVERITY.get(sev, "info")


# ── Email ──────────────────────────────────────────────────────────────────
def email_subject(title: str) -> str:
    return f"Cyphward: {title}"[:200]


EMAIL_FOOTER = ("You get this email because critical {label} alerts are on for your account. "
                "To stop these emails, change your notification settings.")
