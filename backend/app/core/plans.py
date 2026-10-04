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
    "growth": {
        "label": "Growth",
        "monthly_scans": 100,
        "max_domains": 3,
        "monthly_reports": 100,
        "max_members": 5,
    },
    "scale": {
        "label": "Scale",
        "monthly_scans": 1000,
        "max_domains": None,
        "monthly_reports": 1000,
        "max_members": 50,
    },
    "sovereign": {
        "label": "Sovereign",
        "monthly_scans": None,
        "max_domains": None,
        "monthly_reports": None,
        "max_members": None,
    },
}

DEFAULT_PLAN = "scale"
# Pre-entitlement rows (e.g. the old 'Enterprise Defense' database default)
# resolve to this plan so legacy organizations keep working.
LEGACY_PLAN_FALLBACK = "scale"

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
    """Tolerant entitlement resolution for reads — legacy plan text falls
    back to the continuity tier instead of breaking existing tenants."""
    slug = (org.get("plan") or "").strip().lower() if isinstance(org.get("plan"), str) else ""
    if slug not in PLANS:
        slug = LEGACY_PLAN_FALLBACK
    return {"plan": slug, **PLANS[slug]}


def usage_for_org(org_id: str) -> Dict[str, int]:
    """Current quota usage for an organization."""
    scans = execute_one(
        """
        SELECT count(*) AS n FROM scans
        WHERE org_id = %s AND created_at >= date_trunc('month', now())
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
    domains = execute_one(
        "SELECT count(*) AS n FROM domains WHERE org_id = %s", (org_id,)
    )
    members = execute_one(
        "SELECT count(*) AS n FROM organization_members WHERE org_id = %s",
        (org_id,),
    )
    return {
        "monthly_scans": (scans or {}).get("n", 0),
        "monthly_reports": (reports or {}).get("n", 0),
        "domains": (domains or {}).get("n", 0),
        "members": (members or {}).get("n", 0),
    }


def monthly_scan_count(org_id: str) -> int:
    row = execute_one(
        """
        SELECT count(*) AS n FROM scans
        WHERE org_id = %s AND created_at >= date_trunc('month', now())
        """,
        (org_id,),
    )
    return (row or {}).get("n", 0)


def require_quota(org: Dict[str, Any], kind: str) -> Dict[str, Any]:
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
    usage = usage_for_org(str(org["id"]))
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
