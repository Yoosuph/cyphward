"""Issue and read evidence packs (packet C4).

Issue takes a per-organisation advisory lock, renders from the snapshot's frozen content, stores the
HTML and PDF bytes with their sha256 and audits, all in one transaction. Reads serve the stored bytes.
A second issue is a new row; nothing ever updates a pack. Every query is scoped by organisation.
"""
import hashlib
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg.errors
from psycopg.types.json import Jsonb

from backend.app.core import database
from backend.app.core.plans import require_quota
from backend.app.core.database import execute_one, execute_query
from backend.app.packs import document, dpo, render
from backend.app.snapshots import store as snapshots

KINDS = ("readiness_pack", "dpo_section")
META = ("id, org_id, snapshot_id, kind, pack_version, issued_at, issued_by, window_start, window_end, "
        "html_sha256, pdf_sha256, request_key")


class SnapshotMissing(LookupError):
    """The snapshot is not in this organisation. The API maps it to 404."""


class SnapshotAltered(RuntimeError):
    """The stored snapshot no longer matches its hash. The API refuses to issue from it (409)."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def issue(org: Dict[str, Any], user_id: Optional[str], snapshot_id: str, kind: str, *, include_dpo: bool = True,
          request_key: Optional[str] = None) -> Dict[str, Any]:
    """Issue a pack. It counts as one unit of the plan's monthly reports quota, charged under the same
    per-organisation lock as snapshots so a pack and a snapshot cannot both take the last unit. The build is
    one of the few allowed at once per process (waiters hold no connection) and its lock wait is bounded:
    both raise snapshots.Busy, which the API maps to a 503."""
    if kind not in KINDS:
        raise ValueError("unknown pack kind")
    try:
        with snapshots.build_slot():
            return _issue(org, user_id, snapshot_id, kind, include_dpo, request_key)
    except psycopg.errors.LockNotAvailable as exc:
        raise snapshots.Busy("Another pack or snapshot for this organisation is still being prepared.") from exc


def _uuid(value: Any) -> Optional[str]:
    try:
        return str(UUID(str(value)))
    except ValueError:
        return None


def _insert_pack(conn, org: Dict[str, Any], user_id: Optional[str], snap: Dict[str, Any], kind: str,
                 include_dpo: bool, request_key: Optional[str]) -> Dict[str, Any]:
    """Render and store one pack on an open transaction (the caller holds the organisation lock and has charged the quota)."""
    org_id = str(org["id"])
    content = snap["content"]
    end = snap["created_at"]
    section = dpo.build(org_id, end, content) if (kind == "dpo_section" or include_dpo) else None
    issued_at = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"].astimezone(timezone.utc)
    pack_id = str(uuid4())  # made before rendering, so the id can appear inside the document
    doc = document.build(kind, snap, content, issued_at, section, pack_id=pack_id)
    html_bytes = render.to_html(doc).encode("utf-8")
    pdf_bytes = render.to_pdf(doc)
    win = dpo.window_for(end) if section else {"start": None, "end": None}
    row = conn.execute(
        f"INSERT INTO evidence_packs (id, org_id, snapshot_id, kind, pack_version, issued_at, issued_by, window_start, "
        f"window_end, dpo, html, html_sha256, pdf, pdf_sha256, request_key) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {META}",
        (pack_id, org_id, str(snap["id"]), kind, document.PACK_VERSION, issued_at, user_id, win["start"], win["end"],
         Jsonb(section) if section else None, html_bytes.decode("utf-8"), _sha(html_bytes), pdf_bytes,
         _sha(pdf_bytes), request_key)).fetchone()
    conn.execute(
        "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
        "VALUES (%s, %s, 'compliance.pack.issued', 'evidence_pack', %s, %s)",
        (org_id, user_id, str(row["id"]), Jsonb({"kind": kind, "snapshot_id": str(snap["id"]),
                                                  "html_sha256": row["html_sha256"]})))
    return row


def _issue(org: Dict[str, Any], user_id: Optional[str], snapshot_id: str, kind: str, include_dpo: bool,
           request_key: Optional[str]) -> Dict[str, Any]:
    org_id = str(org["id"])
    valid = _uuid(snapshot_id)
    snap = snapshots.get(org_id, valid) if valid else None
    if not snap:
        raise SnapshotMissing()
    if not snapshots.verify(snap):
        raise SnapshotAltered()
    with database.get_db() as conn:
        with conn.transaction():
            conn.execute(f"SET LOCAL lock_timeout = '{snapshots.LOCK_WAIT_MS}ms'")
            # The snapshot lock key: snapshots, reports and packs share one lock per organisation, so the quota
            # check below and the insert are atomic across all three.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"snapshot:{org_id}",))
            if request_key:
                row = conn.execute(f"SELECT {META} FROM evidence_packs WHERE org_id = %s AND request_key = %s",
                                   (org_id, request_key)).fetchone()
                if row:
                    return {"pack": row, "created": False}
            require_quota(org, "reports", exclude_snapshot_id=str(snap["id"]))
            row = _insert_pack(conn, org, user_id, snap, kind, include_dpo, request_key)
    return {"pack": row, "created": True}


class KeyUsedWithoutPack(RuntimeError):
    """The request key already belongs to a snapshot that has no pack. The API maps it to 409."""


def issue_with_new_snapshot(org: Dict[str, Any], user_id: Optional[str], kind: str, *, include_dpo: bool = True,
                            request_key: Optional[str] = None) -> Dict[str, Any]:
    """Freeze the organisation's state and issue a pack from it in ONE transaction under one lock.

    The snapshot, the pack and the quota charge commit together or not at all, so a failure (a busy slot, a
    lock timeout, a render error) or N concurrent retries with one key can never leave a charged snapshot
    behind. The snapshot write takes the build slot; the pack is built inside it (no second slot)."""
    if kind not in KINDS:
        raise ValueError("unknown pack kind")
    org_id = str(org["id"])

    def insert(conn, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        return _insert_pack(conn, org, user_id, snapshot, kind, include_dpo, request_key)

    made = snapshots.create(org, user_id, request_key=request_key, on_insert=insert)
    if made["created"]:
        return {"pack": made["extra"], "created": True, "snapshot": made["snapshot"]}
    existing = by_request_key(org_id, request_key) if request_key else None
    if not existing:
        raise KeyUsedWithoutPack()
    return {"pack": existing, "created": False, "snapshot": made["snapshot"]}


def summary(row: Dict[str, Any], months: int = snapshots.DEFAULT_RETENTION_MONTHS) -> Dict[str, Any]:
    iso = lambda v: v.astimezone(timezone.utc).isoformat() if v else None  # noqa: E731
    return {"id": str(row["id"]), "snapshot_id": str(row["snapshot_id"]), "kind": row["kind"],
            "pack_version": row["pack_version"], "issued_at": iso(row["issued_at"]),
            "retain_until": iso(snapshots.add_months(row["issued_at"].astimezone(timezone.utc), months)),
            "issued_by": str(row["issued_by"]) if row.get("issued_by") else None,
            "window_start": iso(row.get("window_start")), "window_end": iso(row.get("window_end")),
            "html_sha256": row["html_sha256"], "pdf_sha256": row["pdf_sha256"]}


def listing(org_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    return execute_query(f"SELECT {META} FROM evidence_packs WHERE org_id = %s ORDER BY issued_at DESC, id LIMIT %s",
                         (str(org_id), limit)) or []


def get(org_id: str, pack_id: str, *, body: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One pack of this organisation; `body` is 'html' or 'pdf' to include those stored bytes."""
    columns = META + {"html": ", html", "pdf": ", pdf"}.get(body or "", "")
    valid = _uuid(pack_id)
    if not valid:  # a malformed id is the same 404 as another organisation's id
        return None
    return execute_one(f"SELECT {columns} FROM evidence_packs WHERE org_id = %s AND id = %s", (str(org_id), valid))


def count(org_id: str) -> int:
    return (execute_one("SELECT count(*) AS n FROM evidence_packs WHERE org_id = %s", (str(org_id),)) or {}).get("n", 0)


def by_request_key(org_id: str, request_key: str) -> Optional[Dict[str, Any]]:
    return execute_one(f"SELECT {META} FROM evidence_packs WHERE org_id = %s AND request_key = %s",
                       (str(org_id), request_key))
