"""Compliance readiness API (packets C1, C3a, C3b and C5).

Reads are open to any member of the organization. Recording a customer answer
is owner/admin only, and so is the breach incident log. Evidence only, never a legal verdict: every response
carries the register disclaimer, statuses are present / gap / not assessed /
awaiting input with their source, and missing evidence is never reported as
present.
"""
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.app.compliance import attestation_store, document_store, documents, incidents, questionnaire, status
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


class IncidentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    severity: str
    status: str = "open"
    detected_at: datetime
    became_aware_at: datetime
    notified_commission_at: Optional[datetime] = None
    notified_subjects_at: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=4000)


class IncidentPatch(BaseModel):
    """Only fields that were sent are applied; an explicit null clears a notified time or the notes."""
    model_config = ConfigDict(extra="forbid")

    status: Optional[str] = None
    severity: Optional[str] = None
    notified_commission_at: Optional[datetime] = None
    notified_subjects_at: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=4000)


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


def _require_growth(org: Dict[str, Any]) -> None:
    if status.is_starter(org):
        raise HTTPException(status_code=403, detail=GROWTH_DETAIL)


@router.get("/incidents")
def list_incidents(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    _require_growth(org)
    return incidents.listing(org)


@router.post("/incidents", status_code=201)
def create_incident(body: IncidentIn, org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    _require_growth(org)
    try:
        return incidents.create(org, org["current_user_id"], **body.model_dump())
    except incidents.IncidentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/incidents/{incident_id}")
def update_incident(incident_id: UUID, body: IncidentPatch,
                    org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    _require_growth(org)
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    # A status or severity cannot be cleared: it is a required field.
    for required in ("status", "severity"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=422, detail=f"The {required} cannot be empty.")
    try:
        updated = incidents.update(org, org["current_user_id"], str(incident_id), changes)
    except incidents.IncidentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return updated


@router.get("/documents")
def list_documents(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    _require_growth(org)
    return document_store.listing(org)


@router.get("/documents/{document_id}")
def get_document(document_id: UUID, org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    _require_growth(org)
    found = document_store.get(str(org["id"]), str(document_id))
    if found is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return found


@router.post("/documents/{kind}/generate", status_code=201)
async def generate_document(kind: str, org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    _require_growth(org)
    if kind not in documents.KINDS:
        raise HTTPException(status_code=404, detail="Document not found.")
    try:
        return await document_store.generate(org, org["current_user_id"], kind)
    except document_store.QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except document_store.DocumentError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/documents/{document_id}/approve", status_code=201)
def approve_document(document_id: UUID, org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    _require_growth(org)
    try:
        approved = document_store.approve(str(org["id"]), org["current_user_id"], str(document_id))
    except document_store.DocumentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if approved is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return approved
