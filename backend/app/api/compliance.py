"""Compliance readiness API (packets C1, C3a, C3b and C5).

Reads are open to any member of the organization. Recording a customer answer
is owner/admin only, and so is the breach incident log. Evidence only, never a legal verdict: every response
carries the register disclaimer, statuses are present / gap / not assessed /
awaiting input with their source, and missing evidence is never reported as
present.
"""
import asyncio
import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
import psycopg
from psycopg_pool import PoolTimeout
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from backend.app import storage as file_storage
from backend.app.compliance import (attestation_store, document_store, documents, evidence_file_store,
                                    evidence_files, incidents, questionnaire, status)
from backend.app.compliance.attestations import AnswerError
from backend.app.core.auth import get_current_org, require_admin
from backend.app.core.rate_limit import check_rate_limit

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
    except document_store.Busy as exc:
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"})
    except document_store.DocumentError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/documents/{document_id}/approve", status_code=201)
def approve_document(document_id: UUID, org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    _require_growth(org)
    try:
        approved = document_store.approve(str(org["id"]), org["current_user_id"], str(document_id))
    except document_store.DocumentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except document_store.Busy as exc:
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"})
    if approved is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return approved


# ── Evidence files (packet C6) ────────────────────────────────────────────────
#
# Growth plan only. Owner/admin upload and remove; any member lists and downloads. Bytes go to a private bucket;
# a download is a 60-second signed link that forces a download, issued only after the database confirms the file
# belongs to the caller's organisation. There is no inline preview and no public URL.

logger = logging.getLogger("cyphward.evidence_files.api")
MAX_UPLOADS_PER_ORG = 2           # of the process's slots, one organisation may hold this many
ATTEMPTS_PER_HOUR = 60            # upload attempts per organisation per hour, refused ones included
DOWNLOADS_PER_MINUTE = 30         # download links per user per organisation per minute
MAX_CONCURRENT_UPLOADS = 4        # per process: at most this many request bodies (10 MB each) are held at once
UPLOAD_SLOT_WAIT_SECONDS = 10.0
UPLOAD_READ_SECONDS = 60.0         # a slow sender cannot hold an upload slot longer than this
RETRY_AFTER = {"Retry-After": "5"}
_slots: Dict[str, Any] = {}
_org_inflight: Dict[str, int] = {}
DB_UNAVAILABLE = (PoolTimeout, psycopg.OperationalError)


def _upload_slots() -> asyncio.Semaphore:
    """One semaphore per running event loop (a semaphore must not be shared between loops)."""
    loop = asyncio.get_running_loop()
    if _slots.get("loop") is not loop:
        _slots["loop"], _slots["sem"] = loop, asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)
    return _slots["sem"]


def _storage_or_503() -> file_storage.Storage:
    try:
        return file_storage.get_storage()
    except file_storage.StorageNotConfigured:
        raise HTTPException(status_code=503, detail="File uploads are not available right now.", headers=RETRY_AFTER)


def _file_id_or_404(file_id: str) -> str:
    try:
        return str(UUID(file_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="File not found.")


def _quota_http(exc: evidence_file_store.QuotaExceeded) -> HTTPException:
    if exc.reason == "rate":
        return HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after or 60)})
    return HTTPException(status_code=409, detail=str(exc))


async def _read_body(request: Request) -> bytes:
    """The request body, refused as soon as it passes the size limit (no unbounded buffering)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > evidence_files.MAX_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 10 MB.")
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > evidence_files.MAX_BYTES:
            raise HTTPException(status_code=413, detail="The file is larger than 10 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/evidence-files")
def list_evidence_files(question_key: Optional[str] = Query(default=None, max_length=80),
                        org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    _require_growth(org)
    result = evidence_file_store.listing(str(org["id"]), question_key)
    result["limits"] = {"max_bytes": evidence_files.MAX_BYTES, "max_files": evidence_files.MAX_FILES,
                        "max_total_bytes": evidence_files.MAX_TOTAL_BYTES,
                        "extensions": sorted(evidence_files.EXTENSIONS), "label": evidence_files.ALLOWED_TEXT}
    result["uploads_available"] = file_storage.uploads_enabled() and file_storage.is_configured()
    return result


@router.post("/evidence-files", status_code=201)
async def upload_evidence_file(request: Request, question_key: str = Query(min_length=1, max_length=80),
                               org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The request body is the file itself (no multipart); the name travels percent-encoded in X-File-Name.

    Nothing slow runs on the event loop: database reads, the content check and the hash run in the thread pool."""
    await run_in_threadpool(_require_growth, org)
    if not file_storage.uploads_enabled():
        raise HTTPException(status_code=503, detail="File uploads are not available right now.", headers=RETRY_AFTER)
    if questionnaire.question(question_key) is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    raw_name = request.headers.get("x-file-name") or ""
    if len(raw_name) > 1500:
        raise HTTPException(status_code=422, detail="The file name is too long.")
    try:
        name, kind = evidence_files.check_name(unquote(raw_name))
    except evidence_files.FileRejected as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    storage = _storage_or_503()
    org_id, actor = str(org["id"]), str(org["current_user_id"])
    # Every attempt counts, saved or refused, so refused files cannot be used to burn CPU without limit.
    await run_in_threadpool(check_rate_limit, f"evidence-upload:{org_id}", ATTEMPTS_PER_HOUR, evidence_files.RATE_WINDOW_SECONDS)
    if _org_inflight.get(org_id, 0) >= MAX_UPLOADS_PER_ORG:
        raise HTTPException(status_code=503, detail="Your organisation already has uploads running. Try again in a few seconds.",
                            headers=RETRY_AFTER)
    _org_inflight[org_id] = _org_inflight.get(org_id, 0) + 1
    try:
        try:
            await asyncio.wait_for(_upload_slots().acquire(), timeout=UPLOAD_SLOT_WAIT_SECONDS)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=503, detail="Many uploads are running. Try again in a few seconds.",
                                headers=RETRY_AFTER)
        try:
            return await _store_upload(request, storage, org_id, actor, question_key, name, kind)
        finally:
            _upload_slots().release()
    finally:
        _org_inflight[org_id] -= 1
        if _org_inflight[org_id] <= 0:
            _org_inflight.pop(org_id, None)


def _inspect(kind: str, data: bytes) -> str:
    """Content check and hash (CPU work): runs in the thread pool. Returns the sha256."""
    evidence_files.check_content(kind, data)
    return hashlib.sha256(data).hexdigest()


async def _store_upload(request: Request, storage, org_id: str, actor: str, question_key: str, name: str,
                        kind: str) -> Dict[str, Any]:
    try:
        data = await asyncio.wait_for(_read_body(request), timeout=UPLOAD_READ_SECONDS)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="The upload took too long. Try again on a faster connection.")
    try:
        sha256 = await run_in_threadpool(_inspect, kind, data)
    except evidence_files.FileRejected as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    checked = evidence_files.Checked(name, kind, evidence_files.ALLOWED_TYPES[kind])
    try:
        await run_in_threadpool(evidence_file_store.precheck, org_id, len(data))
    except evidence_file_store.QuotaExceeded as exc:
        raise _quota_http(exc)
    except DB_UNAVAILABLE:
        raise HTTPException(status_code=503, detail="Try again in a few seconds.", headers=RETRY_AFTER)
    file_id = str(uuid.uuid4())
    path = evidence_files.storage_path(org_id, file_id)
    try:
        await run_in_threadpool(storage.put, path, data, checked.content_type)
    except file_storage.StorageError:
        raise HTTPException(status_code=502, detail="The file could not be stored. Try again.")
    try:
        return await run_in_threadpool(
            evidence_file_store.register, org_id, actor, question_key=question_key, file_id=file_id,
            checked=checked, size=len(data), sha256=sha256)
    except BaseException as exc:
        # The row was not saved: do not leave the object behind (reconcile catches it if this fails too).
        if isinstance(exc, asyncio.CancelledError):
            asyncio.get_running_loop().run_in_executor(None, evidence_file_store.delete_object, storage, path)
        else:
            await run_in_threadpool(evidence_file_store.delete_object, storage, path)
        if isinstance(exc, evidence_file_store.QuotaExceeded):
            raise _quota_http(exc)
        if isinstance(exc, evidence_file_store.Busy) or isinstance(exc, DB_UNAVAILABLE):
            raise HTTPException(status_code=503, detail="Another upload is being saved. Try again in a few seconds."
                                if isinstance(exc, evidence_file_store.Busy) else "Try again in a few seconds.",
                                headers=RETRY_AFTER)
        raise


@router.get("/evidence-files/{file_id}/download")
def download_evidence_file(file_id: str, response: Response, org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    _require_growth(org)
    org_id, actor = str(org["id"]), str(org["current_user_id"])
    found = evidence_file_store.find_for_download(org_id, _file_id_or_404(file_id))
    if found is None:
        raise HTTPException(status_code=404, detail="File not found.")
    check_rate_limit(f"evidence-download:{org_id}:{actor}", DOWNLOADS_PER_MINUTE, 60)
    storage = _storage_or_503()
    try:
        url = storage.create_signed_url(found["storage_path"], evidence_files.SIGNED_URL_SECONDS, found["display_name"])
    except file_storage.StorageObjectNotFound:
        raise HTTPException(status_code=404, detail="This file is no longer available.")
    except file_storage.StorageError:
        raise HTTPException(status_code=502, detail="The download link could not be created. Try again.")
    evidence_file_store.audit_download_link(org_id, actor, found)  # after the link exists; if it fails no link is returned
    response.headers["Cache-Control"] = "no-store"
    return {"url": url, "expires_in": evidence_files.SIGNED_URL_SECONDS, "display_name": found["display_name"],
            "content_type": found["content_type"], "size_bytes": int(found["size_bytes"])}


@router.delete("/evidence-files/{file_id}")
def remove_evidence_file(file_id: str, org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    _require_growth(org)
    row = evidence_file_store.mark_removed(str(org["id"]), str(org["current_user_id"]), _file_id_or_404(file_id))
    if row is None:
        raise HTTPException(status_code=404, detail="File not found.")
    # The file no longer downloads. If the object cannot be deleted now, reconcile deletes it later.
    try:
        storage: Optional[file_storage.Storage] = file_storage.get_storage()
    except file_storage.StorageNotConfigured:
        storage = None
    cleaned = storage is not None and evidence_file_store.delete_object(storage, row["storage_path"])
    return {"id": str(row["id"]), "removed": True, "object_deleted": cleaned}
