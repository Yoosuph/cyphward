"""DPCO reviewer access API (packet C6).

Owner endpoints (/api/v1/compliance/reviewer-grants): only an organisation OWNER grants, lists and revokes.
Granting is Growth plan only; listing and revoking work on any plan so an organisation that downgraded can
still see and end access. Reviewer endpoints (/api/v1/compliance/reviewer/...): the signed-in account's own
active grant for the organisation in X-Organization-Id, checked on every request (see compliance/reviewer.py).
A reviewer is not a member: none of the member endpoints accept them.
"""
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.app.compliance import reviewer, status
from backend.app.compliance.practitioner import TextError
from backend.app.core.auth import get_current_user, require_owner
from backend.app.core.database import execute_one
from backend.app.core.rate_limit import check_rate_limit

owner_router = APIRouter(prefix="/api/v1/compliance/reviewer-grants", tags=["Reviewer access (owner)"])
router = APIRouter(prefix="/api/v1/compliance/reviewer", tags=["Reviewer access (reviewer)"])
GROWTH_DETAIL = "Reviewer access is part of the Growth plan."
NOTE = ("A practitioner review is the practitioner's own note about a clause reference or a requirement. It does not "
        "change any status and is not a statement about the organisation's obligations.")


def _busy(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "3"})


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    days: int = Field(default=reviewer.DEFAULT_DAYS, ge=reviewer.MIN_DAYS, le=reviewer.MAX_DAYS)
    purpose: str = Field(min_length=1, max_length=reviewer.PURPOSE_MAX)


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["reviewed", "reviewed_with_comments"]
    comment: Optional[str] = Field(default=None, max_length=500)
    request_key: Optional[str] = Field(default=None, max_length=80)


class ClauseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    note: Optional[str] = Field(default=None, max_length=500)
    request_key: Optional[str] = Field(default=None, max_length=80)


# ── Owner ─────────────────────────────────────────────────────────────────


@owner_router.get("")
def list_grants(org: Dict[str, Any] = Depends(require_owner)) -> Dict[str, Any]:
    org_id = str(org["id"])
    return {"grants": reviewer.list_grants(org_id), "activity": reviewer.activity(org_id),
            "audit": reviewer.audit_trail(org_id), "note": NOTE,
            "limits": {"min_days": reviewer.MIN_DAYS, "default_days": reviewer.DEFAULT_DAYS,
                       "max_days": reviewer.MAX_DAYS, "purpose_max": reviewer.PURPOSE_MAX},
            "can_grant": not status.is_starter(org)}


@owner_router.post("", status_code=201)
def grant(body: GrantIn, org: Dict[str, Any] = Depends(require_owner)) -> Dict[str, Any]:
    if status.is_starter(org):
        raise HTTPException(status_code=403, detail=GROWTH_DETAIL)
    org_id = str(org["id"])
    check_rate_limit(f"reviewer-grant:{org_id}", 20, 3600)
    check_rate_limit(f"reviewer-grant-user:{org['current_user_id']}", 30, 3600)
    try:
        row = reviewer.grant_access(org, str(org["current_user_id"]), body.email, body.days, body.purpose)
    except reviewer.GrantError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except reviewer.Busy as exc:
        raise _busy(exc)
    # Whether the address already has an account is not revealed: a new grant always reads "pending".
    mine = next(g for g in reviewer.list_grants(org_id) if g["id"] == str(row["id"]))
    return {"grant": {**mine, "status": "pending"}}


@owner_router.post("/{grant_id}/revoke")
def revoke(grant_id: str, org: Dict[str, Any] = Depends(require_owner)) -> Dict[str, Any]:
    try:
        reviewer.revoke(str(org["id"]), grant_id, str(org["current_user_id"]))
    except reviewer.NotFound:
        raise HTTPException(status_code=404, detail="Grant not found.")
    except reviewer.AlreadyEnded:
        raise HTTPException(status_code=409, detail="That access has already ended.")
    except reviewer.Busy as exc:
        raise _busy(exc)
    return {"revoked": True}


# ── Reviewer ──────────────────────────────────────────────────────────────


@router.get("/grants")
def my_grants(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """The organisations this account may review right now (no organisation header: it picks one)."""
    out = []
    for g in reviewer.active_grants(str(user["id"])):
        full = execute_one("SELECT * FROM organizations WHERE id = %s", (g["org_id"],))
        if full and not status.is_starter(full):
            out.append({"org_id": str(g["org_id"]), "org_name": g["org_name"], "purpose": g["purpose"],
                        "expires_at": g["expires_at"].isoformat()})
    return {"grants": out, "note": NOTE}


@router.get("/overview")
def overview(ctx: Dict[str, Any] = Depends(reviewer.require_reviewer)) -> Dict[str, Any]:
    return {**reviewer.overview(ctx), "reviewer_note": NOTE}


@router.get("/requirements/{key}")
def requirement(key: str, ctx: Dict[str, Any] = Depends(reviewer.require_reviewer)) -> Dict[str, Any]:
    detail = reviewer.requirement_detail(ctx, key)
    if detail is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")
    return detail


def _write(ctx: Dict[str, Any], call) -> Dict[str, Any]:
    check_rate_limit(f"reviewer-write:{ctx['grant_id']}", 120, 3600)
    try:
        return call()
    except TextError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except reviewer.GrantError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except reviewer.NotFound:
        raise HTTPException(status_code=404, detail="Requirement not found.")
    except reviewer.NoAccess:
        raise reviewer.denied()
    except reviewer.Busy as exc:
        raise _busy(exc)


@router.post("/requirements/{key}/review", status_code=201)
def record_review(key: str, body: ReviewIn, ctx: Dict[str, Any] = Depends(reviewer.require_reviewer)) -> Dict[str, Any]:
    return {"practitioner_review": _write(ctx, lambda: reviewer.record_review(ctx, key[:120], body.outcome, body.comment, body.request_key))}


@router.post("/requirements/{key}/clause-reference", status_code=201)
def record_clause(key: str, body: ClauseIn, ctx: Dict[str, Any] = Depends(reviewer.require_reviewer)) -> Dict[str, Any]:
    return {"clause_review": _write(ctx, lambda: reviewer.record_clause(ctx, key[:120], body.verified, body.note, body.request_key))}
