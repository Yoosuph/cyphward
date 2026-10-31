"""Assessment snapshot API (Packet 04).

Any member of the organization can list and read its snapshots; owners and admins create them.
Every query is scoped by the caller's organization, so another organization's id is a 404.
Starter reads the readiness counts and the security group only (decision D1).
"""
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from backend.app.compliance import status
from backend.app.core.auth import get_current_org, require_admin, require_owner
from backend.app.core.suspension import require_active_admin, require_active_owner
from backend.app.snapshots import store

router = APIRouter(prefix="/api/v1/snapshots", tags=["Assessment snapshots"])


def retention_note(months: int) -> str:
    return (f"Kept for {months} months from the day it is issued (the default is 36 months, 3 years), and removed with "
            "your organisation. A snapshot is never edited, and the app never deletes one: after the period it becomes "
            "eligible for removal by an operator. Deleting a domain does not remove snapshots that mention it. "
            "Names of answer owners recorded at the time stay in issued snapshots and packs.")


class SnapshotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: Optional[str] = None


class RetentionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    months: int


@router.get("")
def list_snapshots(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    months = store.retention_months(org)
    rows = [store.summary(r, months) for r in store.listing(org["id"])]
    return {"snapshots": rows, "total": store.count(org["id"]), "retention_months": months, "retention": retention_note(months)}


@router.get("/retention")
def get_retention(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    months = store.retention_months(org)
    return {"retention_months": months, "retention": retention_note(months)}


@router.put("/retention")
def set_retention(req: RetentionIn, org: Dict[str, Any] = Depends(require_active_owner)) -> Dict[str, Any]:
    try:
        months = store.set_retention(org, org.get("current_user_id"), req.months)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"retention_months": months, "retention": retention_note(months)}


@router.post("", status_code=201)
def create_snapshot(req: SnapshotIn, org: Dict[str, Any] = Depends(require_active_admin)) -> Dict[str, Any]:
    if not store.valid_request_key(req.request_key):
        raise HTTPException(status_code=422, detail="request_key must be 8-80 letters, digits or . _ : -")
    try:
        made = store.create(org, org.get("current_user_id"), request_key=req.request_key)
    except store.StateChanging:
        raise HTTPException(status_code=409, detail="Your data changed while the snapshot was being read. Try again.")
    except store.Busy:
        raise HTTPException(status_code=503, detail="Snapshots are being prepared right now. Try again in a few seconds.",
                            headers={"Retry-After": "5"})
    return {"snapshot": store.summary(made["snapshot"], store.retention_months(org)), "created": made["created"]}


@router.get("/{snapshot_id}")
def get_snapshot(snapshot_id: str, org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    try:
        UUID(snapshot_id)
    except ValueError:  # a malformed id is the same 404 as another organization's id
        raise HTTPException(status_code=404, detail="Snapshot not found.")
    row = store.get(org["id"], snapshot_id)
    if not row:
        raise HTTPException(status_code=404, detail="Snapshot not found.")
    starter = status.is_starter(org)
    months = store.retention_months(org)
    return {"snapshot": {**store.summary(row, months), "intact": store.verify(row),
                         "content": store.for_plan(row["content"], starter)},
            "retention_months": months, "retention": retention_note(months)}
