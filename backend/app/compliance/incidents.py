"""Breach incident log (packet C3b): the 72-hour deadline maths and the storage path.

The deadline is derived on every read, in UTC: `became_aware_at + 72 h`. It is
never stored. Times are stored in UTC; the organisation's display time zone
(decision D11) only changes how they are shown, and how a time typed without an
offset is read. Every query is scoped by organisation. A write runs in one
transaction together with its `audit_log` row. Incident titles and notes can
hold personal data, so neither is copied into the audit trail.

Nothing here is a legal verdict: the deadline is a reminder date, the notified
state is what the organisation recorded, and the checklist is plain and
operational.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg.types.json import Jsonb

from backend.app.core import database
from backend.app.core.database import execute_query

DEADLINE_HOURS = 72
DEFAULT_TIMEZONE = "Africa/Lagos"
LIST_LIMIT = 200
FUTURE_TOLERANCE = timedelta(minutes=5)  # clock skew between a browser and the server
SEVERITIES = ("low", "medium", "high", "critical")
STATUSES = ("open", "contained", "closed")
UPDATABLE = ("status", "severity", "notified_commission_at", "notified_subjects_at", "notes")
TIME_FIELDS = ("detected_at", "became_aware_at", "notified_commission_at", "notified_subjects_at")

DISCLAIMER = ("A plain operational checklist, not legal advice. Whether a breach must be reported, and to whom, "
              "depends on your circumstances: ask your data protection officer or adviser.")
CHECKLIST = (
    {"key": "contain", "title": "Contain", "text": "Stop the exposure: revoke access, rotate credentials, isolate affected systems."},
    {"key": "assess", "title": "Assess", "text": "Work out what personal data was involved, whose it is, and how many people could be affected."},
    {"key": "record", "title": "Record", "text": "Write down when it was detected, when you became aware of it, and what you know so far."},
    {"key": "notify_commission", "title": "Notify the Commission", "text": "If notification is required, notify the Commission within 72 hours of becoming aware, and record when you did."},
    {"key": "notify_people", "title": "Notify affected people", "text": "Where notification of affected people is required, tell them plainly what happened and what they can do, and record when you did."},
    {"key": "review", "title": "Review", "text": "Once contained, record what changed so it is less likely to happen again."},
)


class IncidentError(ValueError):
    """The request cannot be recorded. The API maps it to 422."""


def zone_for(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def to_utc(value: datetime, tz_name: Optional[str], label: str = "time") -> datetime:
    """A moment, in UTC. A time with an offset is taken as given. A time without one is read as
    wall-clock time in the organisation's display zone; a wall-clock time that the zone skipped or
    repeats (a clock change) is refused rather than guessed."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    zone = zone_for(tz_name)
    first = value.replace(tzinfo=zone, fold=0)
    utc = first.astimezone(timezone.utc)
    if utc.astimezone(zone).replace(tzinfo=None) != value:
        raise IncidentError(f"The {label} does not exist in {zone.key} (the clock skipped it). "
                            "Enter it with its UTC offset.")
    if first.utcoffset() != value.replace(tzinfo=zone, fold=1).utcoffset():
        raise IncidentError(f"The {label} falls on a clock change in {zone.key} and could be read two ways. "
                            "Enter it with its UTC offset.")
    return utc


def deadline_for(became_aware_at: datetime) -> datetime:
    return became_aware_at.astimezone(timezone.utc) + timedelta(hours=DEADLINE_HOURS)


def deadline_state(row: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """The Commission-notification clock for one incident, from UTC values only.

    - Not notified: `pending` until `now` passes the deadline, then `overdue`. Exactly at the
      deadline it is still pending with no hours left.
    - Notified at or before the deadline: `notified_on_time`, never overdue, whenever it is read.
    - Notified after the deadline: `notified_late`, shown as such. It is not "overdue": the notice
      was given. The incident still records how late.
    """
    deadline = deadline_for(row["became_aware_at"])
    notified = row.get("notified_commission_at")
    if notified is not None:
        late = notified > deadline
        return {"deadline_at": deadline, "commission_state": "notified_late" if late else "notified_on_time",
                "overdue": False, "notified_late": late, "hours_remaining": None,
                "notified_after_hours": round((notified - row["became_aware_at"]).total_seconds() / 3600, 2)}
    remaining = (deadline - now).total_seconds() / 3600
    overdue = now > deadline
    return {"deadline_at": deadline, "commission_state": "overdue" if overdue else "pending",
            "overdue": overdue, "notified_late": False, "hours_remaining": max(round(remaining, 2), 0.0),
            "notified_after_hours": None}


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _local(value: Optional[datetime], zone: ZoneInfo) -> Optional[str]:
    return value.astimezone(zone).isoformat() if value else None


def public(row: Dict[str, Any], tz_name: Optional[str], now: datetime) -> Dict[str, Any]:
    zone = zone_for(tz_name)
    state = deadline_state(row, now)
    out: Dict[str, Any] = {
        "id": str(row["id"]), "title": row["title"], "severity": row["severity"], "status": row["status"],
        "notes": row.get("notes"), "created_by": str(row["created_by"]) if row.get("created_by") else None,
        "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"]),
        "deadline_hours": DEADLINE_HOURS, "display_timezone": zone.key,
        **{k: _iso(row.get(k)) for k in TIME_FIELDS},
        "deadline_at": _iso(state["deadline_at"]),
        "hours_remaining": state["hours_remaining"], "overdue": state["overdue"],
        "notified_late": state["notified_late"], "commission_state": state["commission_state"],
        "notified_after_hours": state["notified_after_hours"],
    }
    out["local"] = {**{k: _local(row.get(k), zone) for k in TIME_FIELDS},
                    "deadline_at": _local(state["deadline_at"], zone)}
    return out


COLUMNS = ("id, org_id, title, severity, status, detected_at, became_aware_at, notified_commission_at, "
           "notified_subjects_at, notes, created_by, created_at, updated_at")


def listing(org: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    tz_name = org.get("display_timezone") or DEFAULT_TIMEZONE
    rows = execute_query(
        f"SELECT {COLUMNS} FROM compliance_incidents WHERE org_id = %s "
        "ORDER BY became_aware_at DESC, created_at DESC LIMIT %s", (str(org["id"]), LIST_LIMIT)) or []
    return {"disclaimer": DISCLAIMER, "checklist": list(CHECKLIST), "deadline_hours": DEADLINE_HOURS,
            "display_timezone": zone_for(tz_name).key, "incidents": [public(r, tz_name, now) for r in rows]}


def _not_future(value: datetime, now: datetime, label: str) -> None:
    if value > now + FUTURE_TOLERANCE:
        raise IncidentError(f"The {label} cannot be in the future.")


def _text(value: Optional[str], limit: int, label: str) -> Optional[str]:
    if value is None or not value.strip():
        return None
    if len(value.strip()) > limit:
        raise IncidentError(f"The {label} must be at most {limit} characters.")
    return value.strip()


def _choice(value: Any, allowed: tuple, label: str) -> str:
    if value not in allowed:
        raise IncidentError(f"The {label} must be one of: {', '.join(allowed)}.")
    return value


def create(org: Dict[str, Any], actor_id: str, *, title: str, severity: str, detected_at: datetime,
           became_aware_at: datetime, status: str = "open", notified_commission_at: Optional[datetime] = None,
           notified_subjects_at: Optional[datetime] = None, notes: Optional[str] = None,
           now: Optional[datetime] = None) -> Dict[str, Any]:
    tz_name = org.get("display_timezone") or DEFAULT_TIMEZONE
    heading = _text(title, 200, "title")
    if heading is None:
        raise IncidentError("An incident needs a title.")
    _choice(severity, SEVERITIES, "severity")
    _choice(status, STATUSES, "status")
    detected = to_utc(detected_at, tz_name, "detection time")
    aware = to_utc(became_aware_at, tz_name, "time you became aware")
    commission = to_utc(notified_commission_at, tz_name, "Commission notification time") if notified_commission_at else None
    subjects = to_utc(notified_subjects_at, tz_name, "notification time for affected people") if notified_subjects_at else None
    memo = _text(notes, 4000, "notes")
    org_id, actor = str(org["id"]), str(actor_id)

    with database.get_db() as conn:
        with conn.transaction():
            at = now or conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
            _validate_times(detected, aware, commission, subjects, at)
            row = conn.execute(
                f"INSERT INTO compliance_incidents (org_id, title, severity, status, detected_at, became_aware_at, "
                f"notified_commission_at, notified_subjects_at, notes, created_by, created_at, updated_at) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {COLUMNS}",
                (org_id, heading, severity, status, detected, aware, commission, subjects, memo, actor, at, at)
            ).fetchone()
            conn.execute(
                "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (org_id, actor, "compliance.incident.created", "compliance_incident", str(row["id"]),
                 Jsonb({"severity": severity, "status": status, "detected_at": _iso(detected),
                        "became_aware_at": _iso(aware), "notified_commission_at": _iso(commission),
                        "notified_subjects_at": _iso(subjects), "notes_recorded": memo is not None})))
    return public(row, tz_name, at)


def _validate_times(detected, aware, commission, subjects, now) -> None:
    _not_future(detected, now, "detection time")
    _not_future(aware, now, "time you became aware")
    if aware < detected - timedelta(days=30):
        raise IncidentError("You cannot have become aware more than 30 days before detection. Check the dates.")
    for value, label in ((commission, "Commission notification"), (subjects, "notification of affected people")):
        if value is None:
            continue
        _not_future(value, now, f"{label} time")
        if value < aware:
            raise IncidentError(f"The {label} cannot be before you became aware of the incident.")


def update(org: Dict[str, Any], actor_id: str, incident_id: str, changes: Dict[str, Any],
           now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Apply the fields present in `changes`; None when the incident is not in this organisation.
    `changes` holds only fields the caller sent, and an explicit None clears a notified time or the notes."""
    unknown = set(changes) - set(UPDATABLE)
    if unknown:
        raise IncidentError("These fields cannot be changed: " + ", ".join(sorted(unknown)) + ".")
    if not changes:
        raise IncidentError("Nothing to change.")
    tz_name = org.get("display_timezone") or DEFAULT_TIMEZONE
    clean: Dict[str, Any] = {}
    if "status" in changes:
        clean["status"] = _choice(changes["status"], STATUSES, "status")
    if "severity" in changes:
        clean["severity"] = _choice(changes["severity"], SEVERITIES, "severity")
    if "notes" in changes:
        clean["notes"] = _text(changes["notes"], 4000, "notes")
    for key, label in (("notified_commission_at", "Commission notification time"),
                       ("notified_subjects_at", "notification time for affected people")):
        if key in changes:
            clean[key] = to_utc(changes[key], tz_name, label) if changes[key] is not None else None
    org_id, actor = str(org["id"]), str(actor_id)

    with database.get_db() as conn:
        with conn.transaction():
            at = now or conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
            current = conn.execute(
                f"SELECT {COLUMNS} FROM compliance_incidents WHERE id = %s AND org_id = %s FOR UPDATE",
                (incident_id, org_id)).fetchone()
            if current is None:
                return None
            for key in ("notified_commission_at", "notified_subjects_at"):
                value = clean.get(key)
                if value is not None and key in changes:
                    _not_future(value, at, "notification time")
                    if value < current["became_aware_at"]:
                        raise IncidentError("A notification cannot be recorded before you became aware of the incident.")
            names = list(clean)
            sets = ", ".join(f"{name} = %s" for name in names)
            row = conn.execute(
                f"UPDATE compliance_incidents SET {sets}, updated_at = %s WHERE id = %s AND org_id = %s "
                f"RETURNING {COLUMNS}", (*clean.values(), at, incident_id, org_id)).fetchone()
            meta: Dict[str, Any] = {"changed": names}
            for key in ("status", "severity"):
                if key in clean:
                    meta[key] = clean[key]
                    meta[f"previous_{key}"] = current[key]
            for key in ("notified_commission_at", "notified_subjects_at"):
                if key in clean:
                    meta[key] = _iso(clean[key])
                    meta[f"previous_{key}"] = _iso(current[key])
            if "notes" in clean:
                meta["notes_cleared"] = clean["notes"] is None
            conn.execute(
                "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (org_id, actor, "compliance.incident.updated", "compliance_incident", incident_id, Jsonb(meta)))
    return public(row, tz_name, at)
