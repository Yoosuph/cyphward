"""Evidence files (packet C6): rows, quotas, audit, removal, organisation purge and reconcile.

The bytes live in a private Supabase Storage bucket (`backend/app/storage`); this module owns the rows that say
which organisation a file belongs to. Order of an upload, so no connection or lock is held while bytes move:
  1. validate (name, size, magic bytes) and cheaply pre-check the quotas;
  2. put the object in storage (no database connection held);
  3. ONE short transaction: advisory lock per organisation (bounded wait), quota and rate check, insert the row,
     write `audit_log`. If it fails for any reason the caller deletes the object again.

The app role may SELECT, INSERT and UPDATE (removed_at, removed_by) only. A removal marks the row first and then
deletes the object; if the delete fails the row stays marked and `reconcile` deletes the object later. The file does
not download once it is marked. Every query is scoped by organisation. Audit rows carry ids, size, type and question
key, never the file name or any content.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.types.json import Jsonb

from backend.app.compliance import evidence_files as ef
from backend.app.core import database
from backend.app.core.database import execute_query
from backend.app.storage import Storage, StorageError

logger = logging.getLogger("cyphward.evidence_files")

LOCK_WAIT_MS = 5000
RECONCILE_MIN_AGE_SECONDS = 900
RECONCILE_MAX_DELETE = 50


class QuotaExceeded(RuntimeError):
    """A cap was reached (`reason`: files | bytes | rate). The API maps files and bytes to 409, rate to 429."""

    def __init__(self, reason: str, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        self.reason, self.retry_after = reason, retry_after


class Busy(RuntimeError):
    """Another upload for this organisation is still being saved. The API maps it to 503."""


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _audit(conn, org_id: str, actor: str, action: str, file_id: str, meta: Dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (org_id, actor, action, "compliance_evidence_file", file_id, Jsonb(meta)))


# ── Usage and quotas ──────────────────────────────────────────────────────────

USAGE_SQL = (
    "SELECT count(*) FILTER (WHERE removed_at IS NULL) AS files, "
    "COALESCE(sum(size_bytes) FILTER (WHERE removed_at IS NULL), 0) AS bytes, "
    "count(*) FILTER (WHERE uploaded_at > clock_timestamp() - make_interval(secs => %s)) AS recent, "
    "COALESCE(CEIL(EXTRACT(EPOCH FROM (min(uploaded_at) FILTER (WHERE uploaded_at > clock_timestamp() "
    "- make_interval(secs => %s)) + make_interval(secs => %s) - clock_timestamp()))), 0) AS retry_after "
    "FROM compliance_evidence_files WHERE org_id = %s"
)


def _check_quota(usage: Dict[str, Any], size: int) -> None:
    if int(usage["files"]) >= ef.MAX_FILES:
        raise QuotaExceeded("files", f"Your organisation already has {ef.MAX_FILES} evidence files attached. "
                                     "Remove one before adding another.")
    if int(usage["bytes"]) + size > ef.MAX_TOTAL_BYTES:
        raise QuotaExceeded("bytes", f"Your organisation's evidence files are limited to {ef.MAX_TOTAL_BYTES // (1024 * 1024)} MB "
                                     "in total. Remove a file to make room.")
    if int(usage["recent"]) >= ef.UPLOADS_PER_HOUR:
        raise QuotaExceeded("rate", f"Up to {ef.UPLOADS_PER_HOUR} files can be uploaded per hour. Try again shortly.",
                            retry_after=max(1, min(int(usage["retry_after"] or 0), ef.RATE_WINDOW_SECONDS)))


def _usage(conn_or_none, org_id: str) -> Dict[str, Any]:
    params = (float(ef.RATE_WINDOW_SECONDS),) * 3 + (org_id,)
    if conn_or_none is not None:
        return conn_or_none.execute(USAGE_SQL, params).fetchone()
    return execute_query(USAGE_SQL, params)[0]


def usage(org_id: str) -> Dict[str, Any]:
    row = _usage(None, org_id)
    return {"files": int(row["files"]), "bytes": int(row["bytes"])}


def precheck(org_id: str, size: int) -> None:
    """Unlocked early refusal so a full organisation does not upload bytes first. The locked check decides."""
    _check_quota(_usage(None, org_id), size)


# ── Upload ────────────────────────────────────────────────────────────────────


def register(org_id: str, actor: str, *, question_key: str, file_id: str, checked: ef.Checked, size: int,
             sha256: str) -> Dict[str, Any]:
    """Insert the row for an object that is already in storage, under the organisation lock. The caller deletes
    the object when this raises."""
    try:
        return _register(str(org_id), str(actor), question_key, file_id, checked, size, sha256)
    except psycopg.errors.LockNotAvailable as exc:
        raise Busy("Another upload is being saved. Try again in a few seconds.") from exc


def _register(org_id, actor, question_key, file_id, checked, size, sha256) -> Dict[str, Any]:
    path = ef.storage_path(org_id, file_id)
    with database.get_db() as conn:
        with conn.transaction():
            conn.execute(f"SET LOCAL lock_timeout = '{LOCK_WAIT_MS}ms'")
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"evidence-files:{org_id}",))
            _check_quota(_usage(conn, org_id), size)
            current = conn.execute(
                "SELECT id FROM compliance_attestations WHERE org_id = %s AND question_key = %s "
                "AND superseded_by IS NULL", (org_id, question_key)).fetchone()
            row = conn.execute(
                "INSERT INTO compliance_evidence_files (id, org_id, question_key, attestation_id, display_name, "
                "content_type, size_bytes, sha256, storage_path, uploaded_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING uploaded_at",
                (file_id, org_id, question_key, current["id"] if current else None, checked.display_name,
                 checked.content_type, size, sha256, path, actor)).fetchone()
            _audit(conn, org_id, actor, "compliance.evidence_file.uploaded", file_id,
                   {"file_id": file_id, "question_key": question_key, "size_bytes": size,
                    "content_type": checked.content_type})
    return {"id": file_id, "question_key": question_key, "display_name": checked.display_name,
            "content_type": checked.content_type, "type_label": ef.TYPE_LABELS[checked.kind], "size_bytes": size,
            "sha256": sha256, "uploaded_at": _iso(row["uploaded_at"]), "attestation_id": str(current["id"]) if current else None}


# ── Reads ─────────────────────────────────────────────────────────────────────

_KIND_OF = {v: k for k, v in ef.ALLOWED_TYPES.items()}


def _view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(row["id"]), "question_key": row["question_key"],
            "attestation_id": str(row["attestation_id"]) if row["attestation_id"] else None,
            "display_name": row["display_name"], "content_type": row["content_type"],
            "type_label": ef.TYPE_LABELS[_KIND_OF[row["content_type"]]], "size_bytes": int(row["size_bytes"]),
            "sha256": row["sha256"], "uploaded_at": _iso(row["uploaded_at"]), "uploaded_by": row.get("uploader_name")}


def listing(org_id: str, question_key: Optional[str] = None) -> Dict[str, Any]:
    params: List[Any] = [org_id]
    extra = ""
    if question_key:
        extra, params = " AND f.question_key = %s", params + [question_key]
    rows = execute_query(
        "SELECT f.id, f.question_key, f.attestation_id, f.display_name, f.content_type, f.size_bytes, f.sha256, "
        "f.uploaded_at, p.full_name AS uploader_name FROM compliance_evidence_files f "
        "LEFT JOIN profiles p ON p.id = f.uploaded_by "
        f"WHERE f.org_id = %s AND f.removed_at IS NULL{extra} ORDER BY f.uploaded_at DESC LIMIT 500",
        tuple(params)) or []
    return {"files": [_view(r) for r in rows], "usage": usage(org_id)}


# ── Download link ─────────────────────────────────────────────────────────────


def find_for_download(org_id: str, file_id: str) -> Optional[Dict[str, Any]]:
    """The file's row if it is this organisation's and not removed, else None. Read only."""
    return (execute_query(
        "SELECT id, question_key, display_name, content_type, size_bytes, storage_path "
        "FROM compliance_evidence_files WHERE id = %s AND org_id = %s AND removed_at IS NULL",
        (file_id, org_id)) or [None])[0]


def audit_download_link(org_id: str, actor: str, row: Dict[str, Any]) -> None:
    """Record that a link was issued. Called only after the link exists: a failed signing leaves no row."""
    with database.get_db() as conn:
        with conn.transaction():
            _audit(conn, org_id, actor, "compliance.evidence_file.download_link_issued", str(row["id"]),
                   {"file_id": str(row["id"]), "question_key": row["question_key"], "size_bytes": int(row["size_bytes"]),
                    "content_type": row["content_type"], "expires_in": ef.SIGNED_URL_SECONDS})


# ── Removal ───────────────────────────────────────────────────────────────────


def mark_removed(org_id: str, actor: str, file_id: str) -> Optional[Dict[str, Any]]:
    """Soft delete: set removed_at/removed_by and audit, in one transaction. None when there is no active file."""
    with database.get_db() as conn:
        with conn.transaction():
            row = conn.execute(
                "UPDATE compliance_evidence_files SET removed_at = now(), removed_by = %s "
                "WHERE id = %s AND org_id = %s AND removed_at IS NULL "
                "RETURNING id, question_key, content_type, size_bytes, storage_path", (actor, file_id, org_id)).fetchone()
            if row is None:
                return None
            _audit(conn, org_id, actor, "compliance.evidence_file.removed", file_id,
                   {"file_id": file_id, "question_key": row["question_key"], "size_bytes": int(row["size_bytes"]),
                    "content_type": row["content_type"]})
    return row


def delete_object(storage: Storage, path: str) -> bool:
    """Best effort. False when the delete failed: the row stays marked and `reconcile` retries."""
    try:
        storage.delete(path)
        return True
    except StorageError as exc:
        logger.warning("evidence object delete failed (%s); reconcile will retry", exc)
        return False


# ── Organisation deletion ─────────────────────────────────────────────────────


def has_any_rows(org_id: str) -> bool:
    return bool(execute_query("SELECT 1 FROM compliance_evidence_files WHERE org_id = %s LIMIT 1", (org_id,)))


def queue_purge(org_id: str) -> bool:
    """Queue the organisation's stored objects for deletion, before its rows go. Only when it has file rows.
    True when queued."""
    row = execute_query(
        "INSERT INTO compliance_evidence_purge_queue (org_id) SELECT %s WHERE EXISTS "
        "(SELECT 1 FROM compliance_evidence_files WHERE org_id = %s) ON CONFLICT (org_id) DO NOTHING RETURNING org_id",
        (org_id, org_id))
    return bool(row)


def purge_organization(storage: Storage, org_id: str) -> int:
    """Delete every stored object of an organisation, then its queue entry. Raises StorageError when storage fails;
    the entry stays queued and `process_purge_queue` retries."""
    removed = storage.delete_prefix(ef.org_prefix(str(org_id)))
    execute_query("DELETE FROM compliance_evidence_purge_queue WHERE org_id = %s", (str(org_id),))
    return removed


def process_purge_queue(storage: Storage, *, delete: bool = False) -> Dict[str, Any]:
    """Retry queued purges. An entry whose organisation still exists (the closing failed) is dropped unused."""
    rows = execute_query("SELECT org_id FROM compliance_evidence_purge_queue ORDER BY queued_at LIMIT 1000") or []
    done, dropped, failed = 0, 0, 0
    for row in rows:
        org_id = str(row["org_id"])
        if not delete:
            continue
        if execute_query("SELECT 1 FROM organizations WHERE id = %s", (org_id,)):
            execute_query("DELETE FROM compliance_evidence_purge_queue WHERE org_id = %s", (org_id,))
            dropped += 1
            continue
        try:
            purge_organization(storage, org_id)
            done += 1
        except StorageError as exc:
            logger.warning("evidence purge retry failed (%s)", exc)
            failed += 1
    return {"queued": len(rows), "purged": done, "dropped": dropped, "failed": failed}


# ── Reconcile ─────────────────────────────────────────────────────────────────


class ReconcileRefused(RuntimeError):
    """A delete run that looks unsafe (for example the database table is empty but storage is not)."""


def reconcile(storage: Storage, *, delete: bool = False, min_age_seconds: int = RECONCILE_MIN_AGE_SECONDS,
              max_delete: int = RECONCILE_MAX_DELETE, now: Optional[float] = None) -> Dict[str, Any]:
    """Compare storage with the rows. Orphans are objects with no row, or whose row is marked removed. An object with
    no row that is younger than `min_age_seconds`, or whose age is unknown, is left alone: an upload may be between
    its put and its insert. Report only unless `delete` is true. A delete run refuses when the table has no rows at
    all but storage has objects (a wrong database would make everything look orphaned) and removes at most
    `max_delete` objects per run. Also lists active rows whose object is missing (never changed here)."""
    import time
    now = time.time() if now is None else now
    objects = storage.list_objects("org/")
    paths = [o.path for o in objects]
    if delete and objects and not execute_query("SELECT 1 FROM compliance_evidence_files LIMIT 1"):
        raise ReconcileRefused("The database has no evidence-file rows but storage has objects: refusing to delete. "
                               "Check that DATABASE_URL points at the right database.")
    rows: Dict[str, Optional[datetime]] = {}
    for i in range(0, len(paths), 1000):
        for r in execute_query(
                "SELECT storage_path, removed_at FROM compliance_evidence_files WHERE storage_path = ANY(%s)",
                (paths[i:i + 1000],)) or []:
            rows[r["storage_path"]] = r["removed_at"]
    orphans, removed_pending, young = [], [], 0
    for obj in objects:
        if obj.path in rows:
            if rows[obj.path] is not None:
                removed_pending.append(obj.path)
            continue
        if obj.created_at is None or now - obj.created_at < min_age_seconds:
            young += 1
            continue
        orphans.append(obj.path)
    have = set(paths)
    missing = [r["storage_path"] for r in execute_query(
        "SELECT storage_path FROM compliance_evidence_files WHERE removed_at IS NULL ORDER BY uploaded_at LIMIT 10000") or []
        if r["storage_path"] not in have]
    deleted, failed = 0, 0
    candidates = removed_pending + orphans
    if delete:
        for path in candidates[:max_delete]:
            if delete_object(storage, path):
                deleted += 1
            else:
                failed += 1
    return {"objects": len(objects), "orphans": orphans, "removed_but_present": removed_pending,
            "too_new_to_judge": young, "rows_missing_object": missing, "deleted": deleted, "failed": failed,
            "left_for_next_run": max(0, len(candidates) - max_delete) if delete else 0}
