"""Issue and read evidence packs (packet C4).

Issue takes a per-organisation advisory lock, renders from the snapshot's frozen content, stores the
HTML and PDF bytes with their sha256 and audits, all in one transaction. Reads serve the stored bytes.
A second issue is a new row; nothing ever updates a pack. Every query is scoped by organisation.
"""
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from psycopg.types.json import Jsonb

from backend.app.core import database
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
    if kind not in KINDS:
        raise ValueError("unknown pack kind")
    org_id = str(org["id"])
    try:
        snap = snapshots.get(org_id, snapshot_id)
    except Exception:
        snap = None
    if not snap:
        raise SnapshotMissing()
    if not snapshots.verify(snap):
        raise SnapshotAltered()
    content = snap["content"]
    with database.get_db() as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"pack:{org_id}",))
            if request_key:
                row = conn.execute(f"SELECT {META} FROM evidence_packs WHERE org_id = %s AND request_key = %s",
                                   (org_id, request_key)).fetchone()
                if row:
                    return {"pack": row, "created": False}
            end = snap["created_at"]
            section = dpo.build(org_id, end, content) if (kind == "dpo_section" or include_dpo) else None
            issued_at = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"].astimezone(timezone.utc)
            doc = document.build(kind, snap, content, issued_at, section)
            html_bytes = render.to_html(doc).encode("utf-8")
            pdf_bytes = render.to_pdf(doc)
            win = dpo.window_for(end) if section else {"start": None, "end": None}
            row = conn.execute(
                f"INSERT INTO evidence_packs (org_id, snapshot_id, kind, pack_version, issued_at, issued_by, window_start, "
                f"window_end, dpo, html, html_sha256, pdf, pdf_sha256, request_key) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {META}",
                (org_id, str(snap["id"]), kind, document.PACK_VERSION, issued_at, user_id, win["start"], win["end"],
                 Jsonb(section) if section else None, html_bytes.decode("utf-8"), _sha(html_bytes), pdf_bytes,
                 _sha(pdf_bytes), request_key)).fetchone()
            conn.execute(
                "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
                "VALUES (%s, %s, 'compliance.pack.issued', 'evidence_pack', %s, %s)",
                (org_id, user_id, str(row["id"]), Jsonb({"kind": kind, "snapshot_id": str(snap["id"]),
                                                          "html_sha256": row["html_sha256"]})))
    return {"pack": row, "created": True}


def summary(row: Dict[str, Any]) -> Dict[str, Any]:
    iso = lambda v: v.astimezone(timezone.utc).isoformat() if v else None  # noqa: E731
    return {"id": str(row["id"]), "snapshot_id": str(row["snapshot_id"]), "kind": row["kind"],
            "pack_version": row["pack_version"], "issued_at": iso(row["issued_at"]),
            "issued_by": str(row["issued_by"]) if row.get("issued_by") else None,
            "window_start": iso(row.get("window_start")), "window_end": iso(row.get("window_end")),
            "html_sha256": row["html_sha256"], "pdf_sha256": row["pdf_sha256"]}


def listing(org_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    return execute_query(f"SELECT {META} FROM evidence_packs WHERE org_id = %s ORDER BY issued_at DESC, id LIMIT %s",
                         (str(org_id), limit)) or []


def get(org_id: str, pack_id: str, *, body: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One pack of this organisation; `body` is 'html' or 'pdf' to include those stored bytes."""
    columns = META + {"html": ", html", "pdf": ", pdf"}.get(body or "", "")
    try:
        return execute_one(f"SELECT {columns} FROM evidence_packs WHERE org_id = %s AND id = %s",
                           (str(org_id), str(pack_id)))
    except Exception:
        return None


def by_request_key(org_id: str, request_key: str) -> Optional[Dict[str, Any]]:
    return execute_one(f"SELECT {META} FROM evidence_packs WHERE org_id = %s AND request_key = %s",
                       (str(org_id), request_key))
