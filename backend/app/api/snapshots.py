"""Assessment snapshot API (Packet 04).

Any member of the organization can list and read its snapshots; owners and admins create them.
Every query is scoped by the caller's organization, so another organization's id is a 404.
Starter reads the readiness counts and the security group only (decision D1).
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from backend.app.compliance import status
from backend.app.core.auth import get_current_org, require_admin
from backend.app.snapshots import store

router = APIRouter(prefix="/api/v1/snapshots", tags=["Assessment snapshots"])
RETENTION = ("Kept for the life of your organisation and removed with it. A snapshot is never edited; "
             "deleting a domain does not remove snapshots that mention it.")


class SnapshotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: Optional[str] = None


@router.get("")
def list_snapshots(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    rows = [store.summary(r) for r in store.listing(org["id"])]
    return {"snapshots": rows, "total": len(rows), "retention": RETENTION}


@router.post("", status_code=201)
def create_snapshot(req: SnapshotIn, org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    if not store.valid_request_key(req.request_key):
        raise HTTPException(status_code=422, detail="request_key must be 8-80 letters, digits or . _ : -")
    try:
        made = store.create(org, org.get("current_user_id"), request_key=req.request_key)
    except store.StateChanging:
        raise HTTPException(status_code=409, detail="Your data changed while the snapshot was being read. Try again.")
    return {"snapshot": store.summary(made["snapshot"]), "created": made["created"]}


@router.get("/{snapshot_id}")
def get_snapshot(snapshot_id: str, org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    try:
        row = store.get(org["id"], snapshot_id)
    except Exception:  # a malformed id is the same 404 as another organization's id
        row = None
    if not row:
        raise HTTPException(status_code=404, detail="Snapshot not found.")
    starter = status.is_starter(org)
    return {"snapshot": {**store.summary(row), "intact": store.verify(row),
                         "content": store.for_plan(row["content"], starter)},
            "retention": RETENTION}
