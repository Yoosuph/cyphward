"""Owner console actions (stage 3): a few safe changes, each one recorded.

Every action:

* needs an owner console session *and* the exact console Origin
  (`require_owner_mutation`), so a bearer token or a cross-site form can't
  trigger it;
* takes a written reason (kept in the owner audit log only, never shown to
  the customer);
* runs in one transaction with its `owner_audit` row (who, why, before and
  after), so a change can't commit without its record and a failed change
  never leaves a "success" row. Refusals (unknown target, wrong state) are
  audited separately as `rejected`;
* also writes the customer's own activity log entry, attributed to
  "cyphward" rather than to the owner's account.

Organization actions (change plan, extend trial, suspend, unsuspend, remove or
restore a member) also need the organization's exact name typed in the request body
(`confirm_name`). It is compared with the name read under the row lock, so a
mistyped or stale name is refused (409) and audited as rejected.

Actions: change an organization's plan, extend a trial, suspend or unsuspend
an organization, remove a member, restore a removed member, cancel a queued or
running scan, sign a user out everywhere. Nothing here deletes customer data:
removing a member deletes only the membership link (the person's account and
everything the organization holds stay), and the owner audit row keeps the
email, role and join date, which restore_member reads back.

Suspension (phase 2 rule, core/suspension.py): while an organization is
suspended its members can sign in and read everything, but every customer
write is refused with 403 `organization_suspended`, new and scheduled scans
pause, and queued scans wait. Owner actions here are never blocked by a
suspension (restoring a member is refused, so a suspended organization does
not gain members). It is not written to the customer's activity log.

Deleting an organization (docs/admin-delete-org/README.md) has three actions:
`delete` (a soft delete: status 'deleted', hidden from customers and from the
owner lists, queued scans cancelled), `restore` (within 30 days) and `purge`
(only after those 30 days, with the name and the word DELETE typed, and only
when no compliance record is still inside its retention period; it deletes the
organization row, its tenant data cascades, and its stored evidence files are
queued for the reconcile script). Guardrails are in core/org_guard.py. Every
other organization action refuses a deleted organization until it is restored.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints

from backend.app.core import database
from backend.app.core import org_guard
from backend.app.core import owner as owner_mod
from backend.app.core.plans import PLANS, parse_plan
from backend.app.core.scan_cancel import CANCEL_ACTIVE_SCAN_SQL
from backend.app.compliance.evidence_file_store import QUEUE_PURGE_SQL

router = APIRouter(prefix="/api/v1/owner", tags=["Owner console actions"])

MAX_TRIAL_DAYS = 60          # per extension
MAX_TRIAL_HORIZON_DAYS = 90  # a trial never ends more than this far ahead

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]


class ReasonBody(BaseModel):
    reason: Reason


class OrgActionBody(ReasonBody):
    # The organization's name exactly as stored (no trimming, case-sensitive), typed by the owner.
    confirm_name: str = Field(min_length=1, max_length=200)


class PlanBody(OrgActionBody):
    plan: str = Field(min_length=1, max_length=32)


class TrialBody(OrgActionBody):
    days: int = Field(ge=1, le=MAX_TRIAL_DAYS)


NAME_MISMATCH = "The name you typed does not match this organization. Nothing was changed."
# Reviewed wording for the delete, restore and purge actions (frontend/src/owner/ownerApi.ts REVIEWED_DETAILS).
DELETED_REFUSED = ("This organization has been deleted. Restore it before making any other change. "
                   "Nothing was changed.")
ALREADY_DELETED = "This organization is already deleted."
NOT_DELETED = "This organization is not deleted. Nothing was changed."
PROTECTED_REFUSED = ("This organization is protected and cannot be deleted or purged from the console. "
                     "Nothing was changed.")
PAID_REFUSED = ("This organization has an active paid subscription. It must be cancelled before the organization "
                "can be deleted. Nothing was changed.")
RESTORE_WINDOW_PASSED = ("The 30-day restore window for this organization has passed, so it can no longer be "
                         "restored. Nothing was changed.")
PURGE_TOO_EARLY = ("The 30-day restore window has not passed yet, so this organization cannot be purged. "
                   "Nothing was changed.")
PURGE_WORD_MISMATCH = "Type the word DELETE in capitals to confirm the purge. Nothing was changed."
RETENTION_HOLD_CODE = "retention_hold"
# Counts only follow in the refusal; "compliance" is left out of the sentence for the console's claim-wording filter.
RETENTION_HOLD = ("Some records of this organization are still inside their retention period, so it cannot be "
                  "purged yet. Nothing was changed.")
DELETE_ORG_MESSAGES = (DELETED_REFUSED, ALREADY_DELETED, NOT_DELETED, PROTECTED_REFUSED, PAID_REFUSED,
                       RESTORE_WINDOW_PASSED, PURGE_TOO_EARLY, PURGE_WORD_MISMATCH, RETENTION_HOLD)


def _check_name(org: Dict[str, Any], typed: str) -> None:
    if typed != org.get("name"):
        raise HTTPException(status_code=409, detail=NAME_MISMATCH)


def _uuid(value: str) -> str:
    import uuid
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Not found.")


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _run(request: Request, owner: Dict[str, Any], action: str, target_type: str, target_id: str,
         reason: str, work: Callable[[Any], Dict[str, Any]]) -> Dict[str, Any]:
    """Run `work(cur)` and its owner audit row in one transaction.

    `work` returns {"result": ..., "audit": {...before/after...}} or raises
    HTTPException to refuse; a refusal rolls back and is audited as rejected.
    """
    try:
        with database.get_db() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    done = work(cur)
                    cur.execute(
                        "INSERT INTO owner_audit (actor_user_id, actor_email, session_id, action, outcome, "
                        "target_type, target_id, ip, user_agent, metadata) "
                        "VALUES (%s, %s, %s, %s, 'success', %s, %s, %s, %s, %s::jsonb) RETURNING id",
                        (owner["user_id"], owner["email"], owner["session_id"], action, target_type, target_id,
                         owner_mod.client_ip(request), (request.headers.get("user-agent") or "")[:200] or None,
                         json.dumps({"reason": reason, **done["audit"]}, default=_iso)),
                    )
                    if cur.fetchone() is None:
                        raise RuntimeError("owner audit insert returned no row")
    except HTTPException as refused:
        if refused.status_code < 500:
            owner_mod.audit(request, action, "rejected", user_id=owner["user_id"], email=owner["email"],
                            session_id=owner["session_id"], target_type=target_type, target_id=target_id,
                            metadata={"reason": reason, "detail": refused.detail})
        raise
    except Exception:
        owner_mod.logger.exception("owner action %s failed", action)
        raise HTTPException(status_code=503, detail="The change could not be saved. Nothing was changed.")
    return done["result"]


def _customer_log(cur, org_id: Optional[str], user_id: Optional[str], action: str,
                  resource_type: str, resource_id: str, metadata: Dict[str, Any]) -> None:
    cur.execute(
        "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
        (org_id, user_id, action, resource_type, resource_id, json.dumps({"by": "cyphward", **metadata})),
    )


def _lock_org(cur, org_id: str, allow_deleted: bool = False) -> Dict[str, Any]:
    """Same lock order as customer billing: organization row first, then its subscription and lifecycle rows.

    A deleted organization is refused (409) unless the action is one of delete, restore or purge."""
    cur.execute("SELECT id, name, plan FROM organizations WHERE id = %s FOR UPDATE", (org_id,))
    org = cur.fetchone()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    cur.execute("SELECT id, plan, status, current_period_end, trial_ends_at, cancel_at_period_end FROM subscriptions "
                "WHERE org_id = %s FOR UPDATE", (org_id,))
    sub = cur.fetchone()
    cur.execute("SELECT status FROM organization_suspensions WHERE org_id = %s FOR UPDATE", (org_id,))
    lifecycle = (cur.fetchone() or {}).get("status") or "active"
    if lifecycle == "deleted" and not allow_deleted:
        raise HTTPException(status_code=409, detail=DELETED_REFUSED)
    return {"org": org, "sub": sub, "status": lifecycle}


# ── Plan ───────────────────────────────────────────────────────────────────
@router.post("/organizations/{org_id}/plan")
def change_plan(org_id: str, body: PlanBody, request: Request,
                owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Set the plan that governs the organization. Status, period and invoices are untouched."""
    org_id = _uuid(org_id)
    plan = parse_plan(body.plan)

    def work(cur):
        locked = _lock_org(cur, org_id)
        org, sub = locked["org"], locked["sub"]
        _check_name(org, body.confirm_name)
        before = (sub or {}).get("plan") or org.get("plan")
        if before == plan:
            raise HTTPException(status_code=409, detail=f"Already on the {PLANS[plan]['label']} plan.")
        cur.execute("UPDATE organizations SET plan = %s WHERE id = %s RETURNING id", (plan, org_id))
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="The organization changed; reload and try again.")
        if sub:
            cur.execute("UPDATE subscriptions SET plan = %s, updated_at = now() WHERE id = %s RETURNING id",
                        (plan, sub["id"]))
            if cur.fetchone() is None:
                raise HTTPException(status_code=409, detail="The subscription changed; reload and try again.")
        _customer_log(cur, org_id, None, "billing.plan_changed", "organization", org_id,
                      {"from": before, "plan": plan})
        return {"result": {"plan": plan, "previous_plan": before},
                "audit": {"from": before, "to": plan, "subscription": bool(sub)}}

    return _run(request, owner, "owner.action.change_plan", "organization", org_id, body.reason, work)


# ── Trial ──────────────────────────────────────────────────────────────────
@router.post("/organizations/{org_id}/trial")
def extend_trial(org_id: str, body: TrialBody, request: Request,
                 owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Push a trialing subscription's end out by `days` (from now if it has already lapsed)."""
    org_id = _uuid(org_id)

    def work(cur):
        locked = _lock_org(cur, org_id)
        _check_name(locked["org"], body.confirm_name)
        sub = locked["sub"]
        if not sub or (sub.get("status") or "").lower() != "trialing":
            raise HTTPException(status_code=409, detail="This organization isn't on a trial.")
        now = datetime.now(timezone.utc)
        current = sub.get("trial_ends_at") or sub.get("current_period_end") or now
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        new_end = max(current, now) + timedelta(days=body.days)
        if new_end > now + timedelta(days=MAX_TRIAL_HORIZON_DAYS):
            raise HTTPException(status_code=409,
                                detail=f"A trial can't end more than {MAX_TRIAL_HORIZON_DAYS} days from today.")
        # effective_status() expires a trial at current_period_end, so both move together.
        cur.execute(
            "UPDATE subscriptions SET trial_ends_at = %s, current_period_end = %s, updated_at = now() "
            "WHERE id = %s AND status = 'trialing' RETURNING trial_ends_at",
            (new_end, new_end, sub["id"]))
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="The subscription changed; reload and try again.")
        _customer_log(cur, org_id, None, "billing.trial_extended", "subscription", str(sub["id"]),
                      {"days": body.days, "trial_ends_at": new_end.isoformat()})
        return {"result": {"trial_ends_at": new_end.isoformat(), "previous_trial_ends_at": _iso(current)},
                "audit": {"days": body.days, "from": current, "to": new_end}}

    return _run(request, owner, "owner.action.extend_trial", "organization", org_id, body.reason, work)


# ── Suspension ─────────────────────────────────────────────────────────────
@router.post("/organizations/{org_id}/suspend")
def suspend_organization(org_id: str, body: OrgActionBody, request: Request,
                         owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Mark the organization suspended (reversible with /unsuspend). Customer writes and scans pause (module doc)."""
    org_id = _uuid(org_id)

    def work(cur):
        locked = _lock_org(cur, org_id)
        _check_name(locked["org"], body.confirm_name)
        if locked["status"] == "suspended":
            raise HTTPException(status_code=409, detail="This organization is already suspended.")
        cur.execute(
            "INSERT INTO organization_suspensions (org_id, status, changed_at, changed_by) "
            "VALUES (%s, 'suspended', now(), %s) "
            "ON CONFLICT (org_id) DO UPDATE SET status = 'suspended', changed_at = now(), "
            "changed_by = EXCLUDED.changed_by RETURNING status, changed_at",
            (org_id, owner["user_id"]))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="The organization changed; reload and try again.")
        return {"result": {"organization_id": org_id, "suspended": True, "changed_at": _iso(row["changed_at"])},
                "audit": {"from": "active", "to": "suspended"}}

    return _run(request, owner, "owner.action.suspend", "organization", org_id, body.reason, work)


@router.post("/organizations/{org_id}/unsuspend")
def unsuspend_organization(org_id: str, body: OrgActionBody, request: Request,
                           owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Lift a suspension. The row stays (status 'active'), so nothing is deleted."""
    org_id = _uuid(org_id)

    def work(cur):
        org = _lock_org(cur, org_id)["org"]
        _check_name(org, body.confirm_name)
        cur.execute(
            "UPDATE organization_suspensions SET status = 'active', changed_at = now(), changed_by = %s "
            "WHERE org_id = %s AND status = 'suspended' RETURNING status, changed_at",
            (owner["user_id"], org_id))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="This organization is not suspended.")
        return {"result": {"organization_id": org_id, "suspended": False, "changed_at": _iso(row["changed_at"])},
                "audit": {"from": "suspended", "to": "active"}}

    return _run(request, owner, "owner.action.unsuspend", "organization", org_id, body.reason, work)


# ── Members ────────────────────────────────────────────────────────────────
@router.post("/organizations/{org_id}/members/{user_id}/remove")
def remove_member(org_id: str, user_id: str, body: OrgActionBody, request: Request,
                  owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Remove one person from one organization. Only the membership link is deleted; the last owner stays."""
    org_id = _uuid(org_id)
    user_id = _uuid(user_id)

    def work(cur):
        org = _lock_org(cur, org_id)["org"]
        _check_name(org, body.confirm_name)
        cur.execute(
            "SELECT m.role, m.created_at, p.email FROM organization_members m JOIN profiles p ON p.id = m.user_id "
            "WHERE m.org_id = %s AND m.user_id = %s FOR UPDATE OF m",
            (org_id, user_id))
        member = cur.fetchone()
        if member is None:
            raise HTTPException(status_code=404, detail="Member not found in this organization.")
        # Same guard as the customer's own role change (api/members.py): the owner rows are locked in a fixed
        # order and the last owner is never removed.
        cur.execute(
            """
            WITH locked AS (
                SELECT user_id FROM organization_members
                WHERE org_id = %s AND role = 'owner'
                ORDER BY user_id
                FOR UPDATE
            )
            DELETE FROM organization_members m
             WHERE m.org_id = %s AND m.user_id = %s
               AND (m.role <> 'owner' OR (SELECT count(*) FROM locked) > 1)
            RETURNING m.role
            """,
            (org_id, org_id, user_id))
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="An organization must keep at least one owner.")
        cur.execute("SELECT count(*) AS n FROM organization_members WHERE org_id = %s", (org_id,))
        remaining = int(cur.fetchone()["n"])
        _customer_log(cur, org_id, None, "member.removed", "profile", user_id, {"role": member["role"]})
        return {"result": {"organization_id": org_id, "removed_user_id": user_id, "role": member["role"],
                           "members": remaining},
                "audit": {"user_id": user_id, "email": member["email"], "role": member["role"],
                          "joined_at": member["created_at"], "members_after": remaining}}

    return _run(request, owner, "owner.action.remove_member", "organization", org_id, body.reason, work)


class RestoreBody(OrgActionBody):
    # The owner_audit row that recorded the removal (shown on the organization page).
    audit_id: str = Field(min_length=1, max_length=64)


RESTORABLE_ROLES = ("owner", "admin", "member")


@router.post("/organizations/{org_id}/members/restore")
def restore_member(org_id: str, body: RestoreBody, request: Request,
                   owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Put back a membership that an earlier owner action removed, from that action's audit row.

    The person, role and join date come only from the stored audit row (never from the request). Refused when the
    organization is suspended, when the person is already a member, when that removal was already restored, or
    when the account is gone or its email no longer matches the record. Each audit row restores at most once.
    """
    org_id = _uuid(org_id)
    audit_id = _uuid(body.audit_id)

    def work(cur):
        locked = _lock_org(cur, org_id)
        org = locked["org"]
        _check_name(org, body.confirm_name)
        if locked["status"] == "suspended":
            raise HTTPException(status_code=409, detail="This organization is suspended. Lift the suspension "
                                                        "before restoring a member. Nothing was changed.")
        cur.execute(
            "SELECT id, metadata FROM owner_audit WHERE id = %s AND action = 'owner.action.remove_member' "
            "AND outcome = 'success' AND target_type = 'organization' AND target_id = %s",
            (audit_id, org_id))
        removal = cur.fetchone()
        if removal is None:
            raise HTTPException(status_code=404, detail="No member removal with that record was found for this "
                                                        "organization.")
        meta = removal["metadata"] or {}
        user_id, email, role = meta.get("user_id"), (meta.get("email") or ""), meta.get("role")
        if not user_id or role not in RESTORABLE_ROLES:
            raise HTTPException(status_code=409, detail="That record does not hold enough detail to restore the "
                                                        "member. Nothing was changed.")
        user_id = _uuid(user_id)
        cur.execute(
            "SELECT id FROM owner_audit WHERE target_type = 'organization' AND target_id = %s "
            "AND action = 'owner.action.restore_member' AND outcome = 'success' "
            "AND metadata->>'restored_from' = %s LIMIT 1",
            (org_id, audit_id))
        if cur.fetchone() is not None:
            raise HTTPException(status_code=409, detail="This removal has already been restored. Nothing was "
                                                        "changed.")
        cur.execute("SELECT id, email FROM profiles WHERE id = %s", (user_id,))
        profile = cur.fetchone()
        if profile is None:
            raise HTTPException(status_code=409, detail="That person's account no longer exists, so the membership "
                                                        "cannot be restored.")
        if (profile.get("email") or "").strip().lower() != email.strip().lower():
            raise HTTPException(status_code=409, detail="That account's email has changed since the removal. "
                                                        "Nothing was changed.")
        cur.execute(
            "INSERT INTO organization_members (user_id, org_id, role, created_at) "
            "VALUES (%s, %s, %s, COALESCE(%s::timestamptz, now())) "
            "ON CONFLICT (user_id, org_id) DO NOTHING RETURNING id",
            (user_id, org_id, role, meta.get("joined_at")))
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="This person is already a member of this organization.")
        cur.execute("SELECT count(*) AS n FROM organization_members WHERE org_id = %s", (org_id,))
        members = int(cur.fetchone()["n"])
        _customer_log(cur, org_id, None, "member.restored", "profile", user_id, {"role": role})
        return {"result": {"organization_id": org_id, "restored_user_id": user_id, "role": role,
                           "members": members},
                "audit": {"restored_from": audit_id, "user_id": user_id, "email": email, "role": role,
                          "joined_at": meta.get("joined_at"), "members_after": members}}

    return _run(request, owner, "owner.action.restore_member", "organization", org_id, body.reason, work)


# ── Delete, restore, purge ─────────────────────────────────────────────────
class PurgeBody(OrgActionBody):
    # The word DELETE, typed by the owner as a second confirmation (exact, capitals).
    confirm_word: str = Field(min_length=1, max_length=20)


def _guard_protected(org: Dict[str, Any]) -> bool:
    """Refuse a protected organization unless the override flag is on. True when the override was used."""
    if not org_guard.is_protected(org):
        return False
    if not org_guard.override_enabled():
        raise HTTPException(status_code=409, detail=PROTECTED_REFUSED)
    return True


# The queued-scan half of the shared cancel transition (core/scan_cancel.py): fences any claim and records the
# cancellation; running scans are left to finish.
CANCEL_QUEUED_SCANS_SQL = """
    UPDATE scans
    SET status = 'cancelled', completed_at = now(),
        claimed_by = NULL, lease_expires_at = NULL, claim_token = NULL,
        execution_phase = NULL, claim_generation = claim_generation + 1
    WHERE org_id = %s AND status = 'queued'
    RETURNING id
"""


@router.post("/organizations/{org_id}/delete")
def delete_organization(org_id: str, body: OrgActionBody, request: Request,
                        owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Soft delete: mark the organization deleted (reversible with /restore for 30 days). Nothing is removed.

    Customers lose sight of it at once (it leaves their memberships; its routes answer 404), it leaves the owner
    lists by default, its queued scans are cancelled, a running scan finishes and scheduled scans skip it. Refused
    while it has an active paid subscription, and for a protected organization (core/org_guard.py)."""
    org_id = _uuid(org_id)

    def work(cur):
        locked = _lock_org(cur, org_id, allow_deleted=True)
        org, sub, before = locked["org"], locked["sub"], locked["status"]
        _check_name(org, body.confirm_name)
        if before == "deleted":
            raise HTTPException(status_code=409, detail=ALREADY_DELETED)
        override = _guard_protected(org)
        if org_guard.paid_subscription_active(sub):
            raise HTTPException(status_code=409, detail=PAID_REFUSED)
        cur.execute(
            "INSERT INTO organization_suspensions (org_id, status, changed_at, changed_by, deleted_at, deleted_by) "
            "VALUES (%s, 'deleted', now(), %s, now(), %s) "
            "ON CONFLICT (org_id) DO UPDATE SET status = 'deleted', changed_at = now(), "
            "changed_by = EXCLUDED.changed_by, deleted_at = now(), deleted_by = EXCLUDED.deleted_by "
            "RETURNING deleted_at, deleted_at + make_interval(days => %s) AS restore_until",
            (org_id, owner["user_id"], owner["user_id"], org_guard.RESTORE_WINDOW_DAYS))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="The organization changed; reload and try again.")
        cur.execute(CANCEL_QUEUED_SCANS_SQL, (org_id,))
        cancelled = [str(r["id"]) for r in cur.fetchall()]
        return {"result": {"organization_id": org_id, "deleted": True, "deleted_at": _iso(row["deleted_at"]),
                           "restore_until": _iso(row["restore_until"]), "queued_scans_cancelled": len(cancelled)},
                "audit": {"from": before, "to": "deleted", "deleted_at": row["deleted_at"],
                          "restore_until": row["restore_until"], "queued_scans_cancelled": cancelled,
                          "subscription_status": (sub or {}).get("status"),
                          "cancel_at_period_end": (sub or {}).get("cancel_at_period_end"),
                          "protected_override": override}}

    return _run(request, owner, "owner.action.delete_org", "organization", org_id, body.reason, work)


@router.post("/organizations/{org_id}/restore")
def restore_organization(org_id: str, body: OrgActionBody, request: Request,
                         owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Undo a soft delete inside the 30-day window. The organization returns to the status it had before (a
    suspended one comes back suspended). Scans cancelled by the delete stay cancelled."""
    org_id = _uuid(org_id)

    def work(cur):
        locked = _lock_org(cur, org_id, allow_deleted=True)
        _check_name(locked["org"], body.confirm_name)
        if locked["status"] != "deleted":
            raise HTTPException(status_code=409, detail=NOT_DELETED)
        cur.execute("SELECT deleted_at, deleted_at + make_interval(days => %s) > now() AS restorable "
                    "FROM organization_suspensions WHERE org_id = %s", (org_guard.RESTORE_WINDOW_DAYS, org_id))
        window = cur.fetchone() or {}
        if not window.get("restorable"):
            raise HTTPException(status_code=409, detail=RESTORE_WINDOW_PASSED)
        # The status before the delete, from the delete's own audit row. If it cannot be read, come back suspended,
        # never more open than before: the owner can then lift the suspension deliberately.
        cur.execute(
            "SELECT metadata->>'from' AS prior FROM owner_audit WHERE target_type = 'organization' AND target_id = %s "
            "AND action = 'owner.action.delete_org' AND outcome = 'success' ORDER BY created_at DESC LIMIT 1",
            (org_id,))
        prior = (cur.fetchone() or {}).get("prior")
        status = prior if prior in ("active", "suspended") else "suspended"
        cur.execute(
            "UPDATE organization_suspensions SET status = %s, changed_at = now(), changed_by = %s, "
            "deleted_at = NULL, deleted_by = NULL WHERE org_id = %s AND status = 'deleted' RETURNING changed_at",
            (status, owner["user_id"], org_id))
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="The organization changed; reload and try again.")
        return {"result": {"organization_id": org_id, "deleted": False, "status": status},
                "audit": {"from": "deleted", "to": status, "deleted_at": window.get("deleted_at"),
                          "prior_status_recorded": prior is not None}}

    return _run(request, owner, "owner.action.restore_org", "organization", org_id, body.reason, work)


PURGE_LOCK_TIMEOUT = "5s"
PURGE_STATEMENT_TIMEOUT = "60s"


@router.post("/organizations/{org_id}/purge")
def purge_organization(org_id: str, body: PurgeBody, request: Request,
                       owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Permanently remove a deleted organization's data, after the restore window, in one transaction.

    Needs the exact name and the word DELETE. Refused (with counts only) while any reviewer grant, pack, snapshot,
    compliance document or evidence file is still inside its retention period (core/org_guard.py). The organization
    row is deleted and its tenant data cascades, as the customer's own closing does; the owner audit keeps the
    record. Stored evidence files are queued in compliance_evidence_purge_queue in the same transaction and deleted
    later by backend/scripts/reconcile_evidence_files.py, never inline."""
    org_id = _uuid(org_id)

    def work(cur):
        cur.execute(f"SET LOCAL lock_timeout = '{PURGE_LOCK_TIMEOUT}'")
        cur.execute(f"SET LOCAL statement_timeout = '{PURGE_STATEMENT_TIMEOUT}'")
        cur.execute("SET LOCAL TimeZone = 'UTC'")
        locked = _lock_org(cur, org_id, allow_deleted=True)
        org = locked["org"]
        _check_name(org, body.confirm_name)
        if body.confirm_word != org_guard.PURGE_WORD:
            raise HTTPException(status_code=409, detail=PURGE_WORD_MISMATCH)
        if locked["status"] != "deleted":
            raise HTTPException(status_code=409, detail=NOT_DELETED)
        override = _guard_protected(org)
        cur.execute("SELECT deleted_at, deleted_at + make_interval(days => %s) <= now() AS due "
                    "FROM organization_suspensions WHERE org_id = %s", (org_guard.RESTORE_WINDOW_DAYS, org_id))
        window = cur.fetchone() or {}
        if not window.get("due"):
            raise HTTPException(status_code=409, detail=PURGE_TOO_EARLY)
        counts = org_guard.retention_counts(cur, org_id)
        held = {k: counts[k] for k in org_guard.RETAINED_KINDS}
        if any(held.values()):
            raise HTTPException(status_code=409, detail={"code": RETENTION_HOLD_CODE, "message": RETENTION_HOLD,
                                                         "counts": held,
                                                         "retention_months": counts["retention_months"]})
        cur.execute(
            "SELECT (SELECT count(*) FROM organization_members WHERE org_id = %(o)s) AS members, "
            "(SELECT count(*) FROM domains WHERE org_id = %(o)s) AS domains, "
            "(SELECT count(*) FROM scans WHERE org_id = %(o)s) AS scans, "
            "(SELECT count(*) FROM findings WHERE org_id = %(o)s) AS findings, "
            "(SELECT count(*) FROM compliance_evidence_files WHERE org_id = %(o)s) AS evidence_files",
            {"o": org_id})
        removed = {k: int(v) for k, v in (cur.fetchone() or {}).items()}
        cur.execute(QUEUE_PURGE_SQL, (org_id, org_id))
        queued = cur.fetchone() is not None
        cur.execute("DELETE FROM organizations WHERE id = %s RETURNING id", (org_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="The organization changed; reload and try again.")
        return {"result": {"organization_id": org_id, "purged": True, "evidence_files_queued": queued},
                "audit": {"from": "deleted", "to": "purged", "name": org.get("name"),
                          "deleted_at": window.get("deleted_at"), "removed": removed,
                          "evidence_files_queued": queued, "retention_months": counts["retention_months"],
                          "protected_override": override}}

    return _run(request, owner, "owner.action.purge_org", "organization", org_id, body.reason, work)


# ── Scan ───────────────────────────────────────────────────────────────────
@router.post("/scans/{scan_id}/cancel")
def cancel_scan(scan_id: str, body: ReasonBody, request: Request,
                owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Cancel a queued or running scan (e.g. one whose worker stopped), fencing its worker."""
    scan_id = _uuid(scan_id)

    def work(cur):
        cur.execute("SELECT id, org_id, status, claimed_by, lease_expires_at FROM scans WHERE id = %s FOR UPDATE",
                    (scan_id,))
        scan = cur.fetchone()
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found.")
        if scan["status"] not in ("queued", "running"):
            raise HTTPException(status_code=409, detail=f"Scan is already {scan['status']}.")
        cur.execute(CANCEL_ACTIVE_SCAN_SQL, (scan_id, scan["org_id"]))
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="The scan changed state; reload and try again.")
        _customer_log(cur, str(scan["org_id"]), None, "scan.cancelled", "scan", scan_id, {})
        return {"result": {"status": "cancelled", "previous_status": scan["status"]},
                "audit": {"from": scan["status"], "to": "cancelled", "org_id": str(scan["org_id"]),
                          "claimed_by": scan.get("claimed_by"), "lease_expires_at": scan.get("lease_expires_at")}}

    return _run(request, owner, "owner.action.cancel_scan", "scan", scan_id, body.reason, work)


# ── User ───────────────────────────────────────────────────────────────────
@router.post("/users/{user_id}/sign-out")
def sign_out_everywhere(user_id: str, body: ReasonBody, request: Request,
                        owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """End every customer-app session and forget every remembered browser for a user.

    Access tokens stop working at once (each request checks its session). The
    user's owner-console sessions, if any, are not touched here.
    """
    user_id = _uuid(user_id)

    def work(cur):
        if user_id == owner["user_id"]:
            raise HTTPException(status_code=409, detail="That's your own account — use Sign out instead.")
        cur.execute("SELECT id FROM profiles WHERE id = %s", (user_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="User not found.")
        cur.execute("UPDATE auth_sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL "
                    "RETURNING id", (user_id,))
        sessions = len(cur.fetchall())
        cur.execute("DELETE FROM trusted_browsers WHERE user_id = %s RETURNING id", (user_id,))
        browsers = len(cur.fetchall())
        _customer_log(cur, None, user_id, "auth.signed_out_everywhere", "user", user_id,
                      {"sessions": sessions, "remembered_browsers": browsers})
        return {"result": {"sessions_revoked": sessions, "remembered_browsers_cleared": browsers},
                "audit": {"sessions_revoked": sessions, "remembered_browsers_cleared": browsers}}

    return _run(request, owner, "owner.action.sign_out_everywhere", "user", user_id, body.reason, work)
