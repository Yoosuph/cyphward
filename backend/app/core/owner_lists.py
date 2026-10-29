"""Owner console list queries: organizations, users and subscriptions (docs/admin-2026-10-29).

One builder per list, shared by the paged view and its CSV export, so an export always matches the filter on
screen. Filters and sort keys are closed sets (FastAPI refuses anything else with 422); each sort key maps to a
fixed SQL expression here, never to text from the request. Every ordering ends with the row id, so pages are stable.

Billing states (organizations):
  paid      the subscription is `active` and its current period has not ended
  trialing  the subscription is `trialing` and its current period has not ended
  free      everything else: no subscription row, past due, canceled, or a period that has ended
Subscription `lapsed` is the billing code's effective past due (core billing/subscriptions.effective_status): an
`active` or `trialing` row whose current period has ended.
"""
from typing import Any, Dict, Literal, Tuple

Dir = Literal["asc", "desc"]
PlanFilter = Literal["", "starter", "growth", "other"]
YesNo = Literal["", "yes", "no"]

OrgBilling = Literal["", "paid", "trialing", "free"]
OrgSort = Literal["created", "name", "plan", "members", "domains", "last_scan"]
UserMfa = Literal["", "authenticator", "email_code", "none"]
UserSort = Literal["created", "email", "name", "last_sign_in"]
SubStatus = Literal["", "trialing", "active", "past_due", "canceled", "lapsed"]
SubSort = Literal["period_end", "created", "organization", "plan", "status"]

Query = Tuple[str, Dict[str, Any]]


def like(q: str) -> str:
    q = q.strip()[:100].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{q}%"


def _order(expr: str, direction: str) -> str:
    d = "DESC" if direction == "desc" else "ASC"
    return f"ORDER BY {expr} {d} NULLS LAST, x.id {d}"


_PLAN_FILTER = ("(%(plan)s = '' OR (%(plan)s = 'other' AND x.plan NOT IN ('starter', 'growth')) "
                "OR x.plan = %(plan)s)")

# ── Organizations ──────────────────────────────────────────────────────────
_ORG_SORT = {
    "created": "x.created_at", "name": "lower(x.name)", "plan": "x.plan", "members": "x.members",
    "domains": "x.domains", "last_scan": "x.last_scan_at",
}

_ORG_BASE = """
    SELECT o.id, o.name, o.slug, o.created_at,
      COALESCE(sub.plan, o.plan) AS plan,
      sub.status AS subscription_status, sub.current_period_end,
      CASE WHEN sub.status = 'active' AND sub.current_period_end > now() THEN 'paid'
           WHEN sub.status = 'trialing' AND sub.current_period_end > now() THEN 'trialing'
           ELSE 'free' END AS billing,
      COALESCE(os.status = 'suspended', false) AS suspended,
      (SELECT count(*) FROM organization_members m WHERE m.org_id = o.id) AS members,
      (SELECT p.email FROM organization_members m JOIN profiles p ON p.id = m.user_id
         WHERE m.org_id = o.id AND m.role = 'owner' ORDER BY m.created_at LIMIT 1) AS owner_email,
      (SELECT count(*) FROM domains d WHERE d.org_id = o.id AND d.revoked_at IS NULL) AS domains,
      (SELECT count(*) FROM domains d WHERE d.org_id = o.id AND d.revoked_at IS NULL
         AND d.verification_status = 'verified') AS domains_verified,
      ls.created_at AS last_scan_at, ls.status AS last_scan_status
    FROM organizations o
    LEFT JOIN subscriptions sub ON sub.org_id = o.id
    LEFT JOIN organization_suspensions os ON os.org_id = o.id
    LEFT JOIN LATERAL (SELECT sc.created_at, sc.status FROM scans sc WHERE sc.org_id = o.id
                       ORDER BY sc.created_at DESC LIMIT 1) ls ON true
    WHERE (%(q)s = '' OR o.name ILIKE %(like)s OR o.slug ILIKE %(like)s
           OR EXISTS (SELECT 1 FROM domains d WHERE d.org_id = o.id AND d.domain ILIKE %(like)s)
           OR EXISTS (SELECT 1 FROM organization_members m JOIN profiles p ON p.id = m.user_id
                      WHERE m.org_id = o.id AND p.email ILIKE %(like)s))
"""

_ORG_WHERE = (f"(%(billing)s = '' OR x.billing = %(billing)s) AND {_PLAN_FILTER} "
              "AND (%(suspended)s = '' OR x.suspended = (%(suspended)s = 'yes'))")


def organizations(q: str, billing: str, plan: str, suspended: str, sort: str, direction: str,
                  limit: int, offset: int) -> Tuple[Query, Query]:
    params = {"q": q.strip()[:100], "like": like(q), "billing": billing, "plan": plan, "suspended": suspended,
              "limit": limit, "offset": offset}
    rows = (f"SELECT * FROM ({_ORG_BASE}) x WHERE {_ORG_WHERE} {_order(_ORG_SORT[sort], direction)} "
            "LIMIT %(limit)s OFFSET %(offset)s", params)
    total = (f"SELECT count(*) AS n FROM ({_ORG_BASE}) x WHERE {_ORG_WHERE}", params)
    return rows, total


ORG_CSV = (("id", "id"), ("name", "name"), ("slug", "slug"), ("plan", "plan"), ("billing", "billing"),
           ("subscription_status", "subscription_status"), ("suspended", "suspended"), ("members", "members"),
           ("domains", "domains"), ("domains_verified", "domains_verified"), ("owner_email", "owner_email"),
           ("last_scan_at", "last_scan_at"), ("created_at", "created_at"))

# ── Users ──────────────────────────────────────────────────────────────────
_USER_SORT = {"created": "x.created_at", "email": "lower(x.email)", "name": "lower(x.full_name)",
              "last_sign_in": "x.last_sign_in_at"}

_USER_BASE = """
    SELECT p.id, p.email, p.full_name, p.provider, p.created_at,
      p.email_verified_at IS NOT NULL AS email_verified,
      CASE WHEN p.totp_enrolled_at IS NOT NULL THEN 'authenticator'
           WHEN p.mfa_enrolled_at IS NOT NULL THEN 'email_code' ELSE 'none' END AS mfa,
      EXISTS (SELECT 1 FROM platform_owners po WHERE po.user_id = p.id) AS platform_owner,
      COALESCE((SELECT json_agg(json_build_object('org_id', o.id, 'name', o.name, 'role', m.role) ORDER BY o.name)
                  FROM organization_members m JOIN organizations o ON o.id = m.org_id
                  WHERE m.user_id = p.id), '[]'::json) AS memberships,
      (SELECT max(s.created_at) FROM auth_sessions s WHERE s.user_id = p.id) AS last_sign_in_at,
      (SELECT count(*) FROM auth_sessions s WHERE s.user_id = p.id
         AND s.revoked_at IS NULL AND s.expires_at > now()) AS active_sessions
    FROM profiles p
    WHERE (%(q)s = '' OR p.email ILIKE %(like)s OR p.full_name ILIKE %(like)s)
"""

_USER_WHERE = ("(%(mfa)s = '' OR x.mfa = %(mfa)s) "
               "AND (%(verified)s = '' OR x.email_verified = (%(verified)s = 'yes'))")


def users(q: str, mfa: str, verified: str, sort: str, direction: str, limit: int, offset: int) -> Tuple[Query, Query]:
    params = {"q": q.strip()[:100], "like": like(q), "mfa": mfa, "verified": verified, "limit": limit,
              "offset": offset}
    rows = (f"SELECT * FROM ({_USER_BASE}) x WHERE {_USER_WHERE} {_order(_USER_SORT[sort], direction)} "
            "LIMIT %(limit)s OFFSET %(offset)s", params)
    total = (f"SELECT count(*) AS n FROM ({_USER_BASE}) x WHERE {_USER_WHERE}", params)
    return rows, total


def user_roles(row: Dict[str, Any]) -> str:
    return "; ".join(f"{m.get('name')} ({m.get('role')})" for m in (row.get("memberships") or []))


USER_CSV = (("id", "id"), ("email", "email"), ("full_name", "name"), ("provider", "sign_in_method"),
            ("email_verified", "email_verified"), ("mfa", "second_step"), ("roles", "organizations_and_roles"),
            ("last_sign_in_at", "last_sign_in_at"), ("created_at", "created_at"))

# ── Subscriptions ─────────────────────────────────────────────────────────
_SUB_SORT = {"period_end": "x.current_period_end", "created": "x.created_at", "organization": "lower(x.org_name)",
             "plan": "x.plan", "status": "x.effective_status"}

_SUB_BASE = """
    SELECT s.id, o.id AS org_id, o.name AS org_name, s.plan, s.status, s.provider,
      CASE WHEN s.status IN ('trialing', 'active') AND s.current_period_end <= now() THEN 'lapsed'
           ELSE s.status END AS effective_status,
      s.current_period_start, s.current_period_end, s.trial_ends_at, s.cancel_at_period_end, s.created_at
    FROM subscriptions s JOIN organizations o ON o.id = s.org_id
    WHERE (%(q)s = '' OR o.name ILIKE %(like)s)
"""

_SUB_WHERE = f"(%(status)s = '' OR x.effective_status = %(status)s) AND {_PLAN_FILTER}"


def subscriptions(q: str, status: str, plan: str, sort: str, direction: str,
                  limit: int, offset: int) -> Tuple[Query, Query]:
    params = {"q": q.strip()[:100], "like": like(q), "status": status, "plan": plan, "limit": limit,
              "offset": offset}
    rows = (f"SELECT * FROM ({_SUB_BASE}) x WHERE {_SUB_WHERE} {_order(_SUB_SORT[sort], direction)} "
            "LIMIT %(limit)s OFFSET %(offset)s", params)
    total = (f"SELECT count(*) AS n FROM ({_SUB_BASE}) x WHERE {_SUB_WHERE}", params)
    return rows, total


SUB_CSV = (("id", "id"), ("org_id", "organization_id"), ("org_name", "organization"), ("plan", "plan"),
           ("status", "status"), ("effective_status", "effective_status"), ("provider", "provider"),
           ("current_period_start", "current_period_start"), ("current_period_end", "current_period_end"),
           ("trial_ends_at", "trial_ends_at"), ("cancel_at_period_end", "cancel_at_period_end"),
           ("created_at", "created_at"))
