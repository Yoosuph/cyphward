"""Server-side plan model and entitlement enforcement (review P1 — plan
enforcement, line 33).

The UI plan selector used to be sent as `sector` while the backend left
`organizations.plan` at its database default — advertised plans had no
server meaning. Plans are now canonical here: creation validates against
the allowlist, and scan/domain/report/invite paths enforce per-plan
quotas with HTTP 402. Billing-provider subscription state (renewal,
invoices) is the follow-up; quotas are the server entitlement until then.

Quotas are per calendar month (UTC) for scans/reports, totals for
domains/members. `None` means unlimited.
"""
from typing import Any, Dict, Optional

from fastapi import HTTPException

from backend.app.core.database import execute_one

PLANS: Dict[str, Dict[str, Any]] = {
    "starter": {
        "label": "Starter",
        "monthly_scans": 30,
        "max_domains": 1,
        "monthly_reports": 30,
        "max_members": 1,
    },
    "growth": {
        "label": "Growth",
        "monthly_scans": 300,
        "max_domains": 10,
        "monthly_reports": 300,
        "max_members": 25,
    },
}

DEFAULT_PLAN = "growth"
# Pre-catalog rows (growth/scale/sovereign/Enterprise Defense) resolve here
# so existing tenants keep working after the catalog cutover.
LEGACY_PLAN_FALLBACK = "growth"

# Retired tiers: selectable nowhere new, but recognized for old rows.
RETIRED_PLANS = {"scale": "growth", "sovereign": "growth", "enterprise defense": "growth"}

# quota key -> (usage key, unit noun)
QUOTA_DEFS = {
    "scans": ("monthly_scans", "scans"),
    "domains": ("max_domains", "domains"),
    "reports": ("monthly_reports", "reports"),
    "members": ("max_members", "members"),
}


def parse_plan(raw: Any) -> str:
    """Strict plan parsing for writes — unknown values are rejected."""
    slug = (raw or "").strip().lower() if isinstance(raw, str) else ""
    if slug not in PLANS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown plan '{raw}'. Must be one of {sorted(PLANS)}.",
        )
    return slug


def entitlements_for(org: Dict[str, Any]) -> Dict[str, Any]:
    """Tolerant entitlement resolution for reads — legacy plan text maps
    through the retired-tier table instead of breaking existing tenants."""
    slug = (org.get("plan") or "").strip().lower() if isinstance(org.get("plan"), str) else ""
    if slug not in PLANS:
        slug = RETIRED_PLANS.get(slug, LEGACY_PLAN_FALLBACK)
    return {"plan": slug, **PLANS[slug]}


def usage_for_org(org_id: str, exclude_snapshot_id: Optional[str] = None) -> Dict[str, int]:
    """Current quota usage for an organization.

    `exclude_snapshot_id` leaves one snapshot out of the count: a pack about to be issued from it turns that
    snapshot's unit into the pack's unit, so issuing must not count the snapshot as well."""
    scans = execute_one(
        """
        SELECT count(*) AS n FROM scans
        WHERE org_id = %s AND created_at >= (date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
        """,
        (org_id,),
    )
    reports = execute_one(
        """
        SELECT count(*) AS n FROM reports
        WHERE org_id = %s AND created_at >= date_trunc('month', now())
        """,
        (org_id,),
    )
    # Issued records are report-sized units: a report, an evidence pack, and a snapshot that neither a report
    # nor a pack belongs to (those are already counted through the report or pack).
    snapshots = execute_one(
        """
        SELECT count(*) AS n FROM assessment_snapshots s
        WHERE s.org_id = %s AND s.created_at >= date_trunc('month', now())
          AND (%s::uuid IS NULL OR s.id <> %s::uuid)
          AND NOT EXISTS (SELECT 1 FROM reports r WHERE r.org_id = s.org_id AND r.snapshot_id = s.id)
          AND NOT EXISTS (SELECT 1 FROM evidence_packs p WHERE p.org_id = s.org_id AND p.snapshot_id = s.id)
        """,
        (org_id, exclude_snapshot_id, exclude_snapshot_id),
    )
    packs = execute_one(
        "SELECT count(*) AS n FROM evidence_packs WHERE org_id = %s AND created_at >= date_trunc('month', now())",
        (org_id,),
    )
    domains = execute_one(
        "SELECT count(*) AS n FROM domains WHERE org_id = %s", (org_id,)
    )
    members = execute_one(
        "SELECT count(*) AS n FROM organization_members WHERE org_id = %s",
        (org_id,),
    )
    return {
        "monthly_scans": (scans or {}).get("n", 0),
        "monthly_reports": (reports or {}).get("n", 0) + (snapshots or {}).get("n", 0) + (packs or {}).get("n", 0),
        "domains": (domains or {}).get("n", 0),
        "members": (members or {}).get("n", 0),
    }


def monthly_scan_count(org_id: str) -> int:
    row = execute_one(
        """
        SELECT count(*) AS n FROM scans
        WHERE org_id = %s AND created_at >= (date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
        """,
        (org_id,),
    )
    return (row or {}).get("n", 0)


def require_quota(org: Dict[str, Any], kind: str, *, exclude_snapshot_id: Optional[str] = None) -> Dict[str, Any]:
    """Enforce one quota; raises 402 with the plan limit when exhausted.

    `kind` is one of scans/domains/reports/members. Returns the resolved
    entitlements (plan + limits) for audit/metadata use. A live
    subscription governs when present, else the org plan text.
    """
    from backend.app.billing.subscriptions import resolve_plan

    sub = execute_one("SELECT * FROM subscriptions WHERE org_id = %s", (str(org["id"]),))
    ent = resolve_plan(org, sub)
    quota_key, noun = QUOTA_DEFS[kind]
    limit: Optional[int] = ent[quota_key]
    if limit is None:
        return ent
    usage = usage_for_org(str(org["id"]), exclude_snapshot_id)
    used = usage[{"scans": "monthly_scans", "reports": "monthly_reports"}.get(kind, kind)]
    if used >= limit:
        label = ent["label"]
        raise HTTPException(
            status_code=402,
            detail=(
                f"{noun.capitalize()} quota reached for the {label} plan "
                f"({used}/{limit} this month). Upgrade or contact support."
                if kind in ("scans", "reports")
                else f"{noun.capitalize()} limit reached for the {label} plan "
                f"({used}/{limit}). Upgrade or contact support."
            ),
        )
    return ent
