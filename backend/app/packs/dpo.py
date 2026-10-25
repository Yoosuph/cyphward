"""DPO six-monthly data-security section (packet C4, GAID 2025 Art. 13).

Counts only: scans run, coverage, findings opened and resolved, incidents logged (by status and
severity, never a title or a note), and the notices and consent observations held in the snapshot.
The window is the six calendar months ending at the snapshot's own time, so the same snapshot always
gives the same window. Every query is scoped by org_id and bounded above by that end time.
This is supporting evidence. It is not a Compliance Audit Return.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from backend.app.core.database import execute_one, execute_query
from backend.app.risk.coverage import coverage_state

WINDOW_DAYS = 183  # six months, fixed so the window is the same arithmetic everywhere
OBSERVATION_GROUPS = ("notices", "consent")
STATES = ("complete", "partial", "unassessed", "unknown")
SEVERITIES = ("critical", "high", "medium", "low")
INCIDENT_STATUSES = ("open", "contained", "closed")


def window_for(end: datetime) -> Dict[str, datetime]:
    end = end.astimezone(timezone.utc)
    return {"start": end - timedelta(days=WINDOW_DAYS), "end": end}


def _counts(rows: List[Dict[str, Any]], key: str, allowed: tuple) -> Dict[str, int]:
    counted = {k: 0 for k in allowed}
    for row in rows:
        counted[row[key]] = counted.get(row[key], 0) + int(row["n"])
    return counted


def build(org_id: str, end: datetime, snapshot_content: Dict[str, Any]) -> Dict[str, Any]:
    win = window_for(end)
    org, start, stop = str(org_id), win["start"], win["end"]
    scans = execute_query(
        "SELECT status, count(*) AS n FROM scans WHERE org_id = %s AND created_at > %s AND created_at <= %s "
        "GROUP BY status", (org, start, stop)) or []
    cov_rows = execute_query(
        "SELECT stage_progress -> 'scoring' -> 'coverage' AS coverage FROM scans WHERE org_id = %s "
        "AND status = 'completed' AND completed_at > %s AND completed_at <= %s", (org, start, stop)) or []
    states = {k: 0 for k in STATES}
    for row in cov_rows:
        state = coverage_state({"coverage": row["coverage"]})
        states[state if state in states else "unknown"] += 1
    opened = execute_query(
        "SELECT severity, count(*) AS n FROM findings WHERE org_id = %s AND first_seen_at > %s AND first_seen_at <= %s "
        "GROUP BY severity", (org, start, stop)) or []
    resolved = execute_query(
        "SELECT severity, count(*) AS n FROM findings WHERE org_id = %s AND status = 'resolved' "
        "AND resolved_at > %s AND resolved_at <= %s GROUP BY severity", (org, start, stop)) or []
    incidents = execute_query(
        "SELECT status, severity, count(*) AS n, count(*) FILTER (WHERE notified_commission_at IS NOT NULL) AS notified "
        "FROM compliance_incidents WHERE org_id = %s AND became_aware_at > %s AND became_aware_at <= %s "
        "GROUP BY status, severity", (org, start, stop)) or []
    domains = execute_one(
        "SELECT count(*) AS n FROM domains WHERE org_id = %s AND verification_status = 'verified'", (org,)) or {"n": 0}
    observations = [{
        "key": r["key"], "title": r["title"], "group": r["group"], "status": r["status"],
        "status_label": r["status_label"], "source_label": r["source_label"],
        "observed_at": max([d["observed_at"] for d in r["domains"] if d.get("observed_at")] or [None], default=None),
    } for r in snapshot_content["compliance"]["requirements"] if r["group"] in OBSERVATION_GROUPS]
    return {
        "window": {"start": start.isoformat(), "end": stop.isoformat(), "days": WINDOW_DAYS},
        "scans": {"run": sum(int(r["n"]) for r in scans), "by_status": {r["status"]: int(r["n"]) for r in scans},
                  "coverage": states, "verified_domains": int(domains["n"])},
        "findings": {"opened": _counts(opened, "severity", SEVERITIES), "resolved": _counts(resolved, "severity", SEVERITIES),
                     "open_at_snapshot": snapshot_content["scoring"]["counts"]},
        "incidents": {"logged": sum(int(r["n"]) for r in incidents),
                      "by_status": _counts(incidents, "status", INCIDENT_STATUSES),
                      "by_severity": _counts(incidents, "severity", SEVERITIES),
                      "commission_notified": sum(int(r["notified"]) for r in incidents)},
        "observations": observations,
    }
