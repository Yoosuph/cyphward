"""NDPA readiness evidence pack API (packet C4). Growth plan only (decision D1: Starter gets 403 on reads and writes).

Members list and download; owners and admins issue. A pack is generated from an assessment snapshot of the
caller's organisation (a new one is frozen when no snapshot id is given), stored once, and served as stored.
Another organisation's snapshot or pack id is a 404.
"""
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from backend.app.compliance import status
from backend.app.core.auth import get_current_org, require_admin
from backend.app.packs import store
from backend.app.snapshots import store as snapshots

router = APIRouter(prefix="/api/v1/packs", tags=["Evidence packs"])
GROWTH_DETAIL = "Evidence packs are part of the Growth plan."
NOT_A_CAR = "Supporting evidence only. Not a Compliance Audit Return."


class PackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: Optional[str] = None
    kind: Literal["readiness_pack", "dpo_section"] = "readiness_pack"
    include_dpo: bool = True
    request_key: Optional[str] = None


def _growth(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    if status.is_starter(org):
        raise HTTPException(status_code=403, detail=GROWTH_DETAIL)
    return org


def _growth_admin(org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    if status.is_starter(org):
        raise HTTPException(status_code=403, detail=GROWTH_DETAIL)
    return org


@router.get("")
def list_packs(org: Dict[str, Any] = Depends(_growth)) -> Dict[str, Any]:
    rows = [store.summary(r) for r in store.listing(org["id"])]
    return {"packs": rows, "total": len(rows), "notice": NOT_A_CAR}


@router.post("", status_code=201)
def issue_pack(req: PackIn, org: Dict[str, Any] = Depends(_growth_admin)) -> Dict[str, Any]:
    if not snapshots.valid_request_key(req.request_key):
        raise HTTPException(status_code=422, detail="request_key must be 8-80 letters, digits or . _ : -")
    if req.request_key:
        again = store.by_request_key(org["id"], req.request_key)
        if again:
            return {"pack": store.summary(again), "created": False}
    user = org.get("current_user_id")
    snapshot_id = req.snapshot_id
    if snapshot_id is None:
        try:
            made = snapshots.create(org, user)
        except snapshots.StateChanging:
            raise HTTPException(status_code=409, detail="Your data changed while the snapshot was being read. Try again.")
        snapshot_id = str(made["snapshot"]["id"])
    try:
        issued = store.issue(org, user, snapshot_id, req.kind, include_dpo=req.include_dpo, request_key=req.request_key)
    except store.SnapshotMissing:
        raise HTTPException(status_code=404, detail="Snapshot not found.")
    except store.SnapshotAltered:
        raise HTTPException(status_code=409, detail="That snapshot no longer matches its recorded hash; no pack was issued.")
    return {"pack": store.summary(issued["pack"]), "created": issued["created"]}


@router.get("/{pack_id}")
def get_pack(pack_id: str, org: Dict[str, Any] = Depends(_growth)) -> Dict[str, Any]:
    row = store.get(org["id"], pack_id)
    if not row:
        raise HTTPException(status_code=404, detail="Pack not found.")
    return {"pack": store.summary(row), "notice": NOT_A_CAR}


def _download(pack_id: str, org: Dict[str, Any], body: str, media: str, extension: str) -> Response:
    row = store.get(org["id"], pack_id, body=body)
    if not row:
        raise HTTPException(status_code=404, detail="Pack not found.")
    data = row[body].encode("utf-8") if body == "html" else bytes(row[body])
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="cyphward-{row["kind"]}-{str(row["id"])[:8]}.{extension}"',
        "ETag": f'"{row[body + "_sha256"]}"', "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/{pack_id}/html")
def download_html(pack_id: str, org: Dict[str, Any] = Depends(_growth)) -> Response:
    return _download(pack_id, org, "html", "text/html; charset=utf-8", "html")


@router.get("/{pack_id}/pdf")
def download_pdf(pack_id: str, org: Dict[str, Any] = Depends(_growth)) -> Response:
    return _download(pack_id, org, "pdf", "application/pdf", "pdf")
