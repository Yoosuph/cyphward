"""Compliance readiness API (packet C1). Read-only; any member of the organization.

Evidence only, never a legal verdict: every response carries the register
disclaimer, statuses are present / gap / not assessed with their source, and
missing evidence is never reported as present.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from backend.app.compliance import status
from backend.app.core.auth import get_current_org

router = APIRouter(prefix="/api/v1/compliance", tags=["Compliance readiness"])


@router.get("/overview")
def compliance_overview(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    return status.overview(org)


@router.get("/requirements/{key}")
def compliance_requirement(key: str, org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    detail = status.requirement_detail(org, key[:120])
    if detail is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")
    if detail.get("locked"):
        raise HTTPException(status_code=403, detail="This requirement group is part of the Growth plan.")
    return detail
