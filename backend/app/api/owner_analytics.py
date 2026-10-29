"""Owner console analytics (phase 1): platform-wide counts, read-only.

Aggregates only. No response carries a customer address (email, domain, hostname), a finding title or any other
customer content, and no row-level identifier: just counts by day, status, plan or severity. The sample-data demo
organization is left out of every count (core/demo_org.py), as on the overview.

* GET /api/v1/owner/analytics/summary?range=7|30|90     organizations, billing states, subscriptions, scans, users
* GET /api/v1/owner/analytics/timeseries?range=7|30|90  scans per day (by outcome) and new findings per day by severity

Every read needs an owner session and writes its owner audit row first (no row, no data). An unknown range is
refused with 422. Queries run under a 5 s statement timeout in one short read-only transaction
(core/owner_reads.py), and each result is capped at ROW_CAP rows. Billing states are defined in core/owner_lists.py.

Newsletter subscriber counts stay on their own endpoint (GET /api/v1/newsletter/stats), which the console calls.
"""
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, Query, Request

from backend.app.core import owner as owner_mod
from backend.app.core import owner_reads as reads
from backend.app.core.demo_org import DEMO_ORG_ID, DEMO_USER_ID

router = APIRouter(prefix="/api/v1/owner/analytics", tags=["Owner console analytics"])

Range = Literal["7", "30", "90"]
ROW_CAP = 1000
SEVERITIES = ("critical", "high", "medium", "low", "info")
# Every scan status the code writes. Listing them lets the day counts use idx_scans_status_created
# (status, created_at); a status outside this list is not counted.
SCAN_STATUSES = ("queued", "running", "completed", "failed", "cancelled")


def _audit(request: Request, owner: Dict[str, Any], section: str, days: int) -> None:
    owner_mod.audit(request, f"owner.view.analytics_{section}", "success", user_id=owner["user_id"],
                    email=owner["email"], session_id=owner["session_id"], metadata={"range_days": days})


def _since(days: int) -> datetime:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=days - 1)


def _int(row: Dict[str, Any], key: str) -> int:
    return int((row or {}).get(key) or 0)


@router.get("/summary")
def summary(request: Request, window: Range = Query("30", alias="range"),
            owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    days = int(window)
    _audit(request, owner, "summary", days)
    params = {"since": _since(days), "demo": DEMO_ORG_ID, "statuses": list(SCAN_STATUSES)}
    orgs, billing, subs, scans, users = reads.bounded_read([
        ("""
         SELECT count(*) AS total, count(*) FILTER (WHERE created_at >= %(since)s) AS new_in_range,
                (SELECT count(*) FROM organization_suspensions os
                  WHERE os.status = 'suspended' AND os.org_id <> %(demo)s) AS suspended
         FROM organizations WHERE id <> %(demo)s
         """, params),
        ("""
         SELECT CASE WHEN s.status = 'active' AND s.current_period_end > now() THEN 'paid'
                     WHEN s.status = 'trialing' AND s.current_period_end > now() THEN 'trialing'
                     ELSE 'free' END AS billing, count(*) AS n
         FROM organizations o LEFT JOIN subscriptions s ON s.org_id = o.id
         WHERE o.id <> %(demo)s GROUP BY 1 LIMIT 10
         """, params),
        ("""
         SELECT CASE WHEN status IN ('trialing', 'active') AND current_period_end <= now() THEN 'lapsed'
                     ELSE status END AS status, count(*) AS n
         FROM subscriptions WHERE org_id <> %(demo)s GROUP BY 1 ORDER BY 1 LIMIT 20
         """, params),
        ("""
         SELECT status, count(*) AS n FROM scans
         WHERE status = ANY(%(statuses)s) AND created_at >= %(since)s AND org_id <> %(demo)s
         GROUP BY 1 LIMIT 20
         """, params),
        ("""
         SELECT count(*) AS total, count(*) FILTER (WHERE created_at >= %(since)s) AS new_in_range
         FROM profiles WHERE id <> %(demo_user)s
         """, {**params, "demo_user": DEMO_USER_ID}),
    ])
    by_billing = {r["billing"]: int(r["n"]) for r in billing}
    by_scan = {r["status"]: int(r["n"]) for r in scans}
    finished = by_scan.get("completed", 0) + by_scan.get("failed", 0)
    org = orgs[0] if orgs else {}
    user = users[0] if users else {}
    return {
        "as_of": time.time(),
        "range_days": days,
        "since": params["since"].isoformat(),
        "organizations": {"total": _int(org, "total"), "new_in_range": _int(org, "new_in_range"),
                          "suspended": _int(org, "suspended")},
        "billing": {k: by_billing.get(k, 0) for k in ("paid", "trialing", "free")},
        "subscription_status": [{"status": r["status"], "count": int(r["n"])} for r in subs],
        "scans": {
            "total": sum(by_scan.values()),
            **{k: by_scan.get(k, 0) for k in SCAN_STATUSES},
            # Share of finished scans (completed or failed) that completed; null when none finished.
            "success_rate": round(by_scan.get("completed", 0) / finished, 4) if finished else None,
            "failure_rate": round(by_scan.get("failed", 0) / finished, 4) if finished else None,
        },
        "users": {"total": _int(user, "total"), "new_in_range": _int(user, "new_in_range")},
        "definitions": {
            "paid": "Subscription active and its current period has not ended.",
            "trialing": "Subscription in trial and its current period has not ended.",
            "free": "No subscription, or one that is past due, canceled or past its period end.",
            "lapsed": "Subscription marked active or trialing whose current period has ended.",
            "success_rate": "Completed scans divided by completed plus failed scans in the range.",
        },
    }


@router.get("/timeseries")
def timeseries(request: Request, window: Range = Query("30", alias="range"),
               owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    days = int(window)
    _audit(request, owner, "timeseries", days)
    since = _since(days)
    params = {"since": since, "demo": DEMO_ORG_ID, "statuses": list(SCAN_STATUSES),
              "severities": list(SEVERITIES), "cap": ROW_CAP}
    scan_rows, finding_rows = reads.bounded_read([
        ("""
         SELECT to_char(date_trunc('day', created_at AT TIME ZONE 'UTC'), 'YYYY-MM-DD') AS day, status,
                count(*) AS n
         FROM scans
         WHERE status = ANY(%(statuses)s) AND created_at >= %(since)s AND org_id <> %(demo)s
         GROUP BY 1, 2 ORDER BY 1 LIMIT %(cap)s
         """, params),
        ("""
         SELECT to_char(date_trunc('day', created_at AT TIME ZONE 'UTC'), 'YYYY-MM-DD') AS day, severity,
                count(*) AS n
         FROM findings
         WHERE created_at >= %(since)s AND org_id <> %(demo)s AND severity = ANY(%(severities)s)
         GROUP BY 1, 2 ORDER BY 1 LIMIT %(cap)s
         """, params),
    ])
    # Every day in the range is present (zeros included), oldest first.
    day_keys = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    scans = {d: {"day": d, "total": 0, **{s: 0 for s in SCAN_STATUSES}} for d in day_keys}
    for r in scan_rows:
        if r["day"] in scans:
            scans[r["day"]][r["status"]] += int(r["n"])
            scans[r["day"]]["total"] += int(r["n"])
    findings = {d: {"day": d, **{s: 0 for s in SEVERITIES}} for d in day_keys}
    for r in finding_rows:
        if r["day"] in findings:
            findings[r["day"]][r["severity"]] += int(r["n"])
    return {"as_of": time.time(), "range_days": days, "since": since.isoformat(),
            "scans_per_day": list(scans.values()), "findings_per_day": list(findings.values()),
            "truncated": len(scan_rows) >= ROW_CAP or len(finding_rows) >= ROW_CAP}

