"""Compliance readiness API (packets C1 and C3a).

Reads are open to any member of the organization. Recording a customer answer
is owner/admin only. Evidence only, never a legal verdict: every response
carries the register disclaimer, statuses are present / gap / not assessed /
awaiting input with their source, and missing evidence is never reported as
present.
"""
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.app.compliance import attestation_store, questionnaire, status
from backend.app.compliance.attestations import AnswerError
from backend.app.core.auth import get_current_org, require_admin

router = APIRouter(prefix="/api/v1/compliance", tags=["Compliance readiness"])
GROWTH_DETAIL = "This part of the compliance pages is part of the Growth plan."


class AttestationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_key: str = Field(min_length=1, max_length=80)
    answer: Dict[str, Any]
    owner_user_id: UUID
    expires_at: Optional[datetime] = None
    evidence_link: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=1000)


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


@router.get("/questionnaire")
def compliance_questionnaire(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    if status.is_starter(org):
        raise HTTPException(status_code=403, detail=GROWTH_DETAIL)
    return attestation_store.questionnaire(org)


@router.post("/attestations", status_code=201)
def record_attestation(body: AttestationIn, org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    # Same plan gate as the reads: a Starter organisation cannot store answers it could not read back.
    if status.is_starter(org):
        raise HTTPException(status_code=403, detail=GROWTH_DETAIL)
    try:
        return attestation_store.record(
            org, org["current_user_id"], question_key=body.question_key, answer=body.answer,
            owner_user_id=str(body.owner_user_id), expires_at=body.expires_at,
            evidence_link=body.evidence_link, notes=body.notes)
    except AnswerError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except attestation_store.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/attestations/{question_key}")
def compliance_attestation_history(question_key: str,
                                   org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    if status.is_starter(org):
        raise HTTPException(status_code=403, detail=GROWTH_DETAIL)
    if questionnaire.question(question_key[:80]) is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    return {"question_key": question_key[:80],
            "history": attestation_store.history(str(org["id"]), question_key[:80])}
