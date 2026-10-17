"""Snapshot write and read paths (Packet 04).

One request writes one snapshot. The write holds a per-organisation advisory lock from before the
state is read until the insert commits, so two requests for the same organisation are serialised:
each reads a settled state and gets the next `seq`. The read helpers use their own connections, so
the state is also fenced (see builder.FENCE_SQL): if anything moved while it was being read, it is
read again, up to MAX_ATTEMPTS, and then the request fails with a retryable error rather than
freezing a mixed state.

A retried request that carries the same `request_key` finds the first snapshot instead of making
another. An optional `on_insert` runs in the same transaction (a report row), so a snapshot and the
report generated from it appear together or not at all.
"""
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from psycopg.types.json import Jsonb

from backend.app.core import database
from backend.app.core.database import execute_one, execute_query
from backend.app.snapshots import builder

MAX_ATTEMPTS = 3
REQUEST_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,80}$")
COLUMNS = "id, org_id, seq, schema_version, scope, content_sha256, request_key, created_by, created_at"


class StateChanging(RuntimeError):
    """The organisation's data kept changing while the snapshot was read. The API maps it to 409."""


def valid_request_key(value: Optional[str]) -> bool:
    return value is None or bool(REQUEST_KEY.match(value))


def create(org: Dict[str, Any], user_id: Optional[str], *, request_key: Optional[str] = None,
           on_insert: Optional[Callable[[Any, Dict[str, Any]], Any]] = None) -> Dict[str, Any]:
    """Freeze the organisation's current state. Returns {"snapshot": row, "created": bool, "extra": ...}."""
    org_id = str(org["id"])
    with database.get_db() as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"snapshot:{org_id}",))
            if request_key:
                row = conn.execute(f"SELECT {COLUMNS} FROM assessment_snapshots WHERE org_id = %s AND request_key = %s",
                                   (org_id, request_key)).fetchone()
                if row:
                    return {"snapshot": row, "created": False, "extra": None}
            for _ in range(MAX_ATTEMPTS):
                before = builder.fence(org_id)
                now = datetime.now(timezone.utc)
                content = builder.build(org, now)
                if builder.fence(org_id) == before:
                    break
            else:
                raise StateChanging("The organisation's data changed while the snapshot was being read.")
            text = builder.canonical(content)
            content = json.loads(text)  # exactly what is hashed and stored
            seq = conn.execute("SELECT coalesce(max(seq), 0) + 1 AS seq FROM assessment_snapshots WHERE org_id = %s",
                               (org_id,)).fetchone()["seq"]
            row = conn.execute(
                f"INSERT INTO assessment_snapshots (org_id, seq, schema_version, content, content_sha256, request_key, "
                f"created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {COLUMNS}",
                (org_id, seq, builder.SCHEMA_VERSION, Jsonb(content), builder.sha256_of(text), request_key,
                 user_id, now)).fetchone()
            conn.execute(
                "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
                "VALUES (%s, %s, 'snapshot.created', 'assessment_snapshot', %s, %s)",
                (org_id, user_id, str(row["id"]), Jsonb({"seq": seq, "sha256": row["content_sha256"]})))
            extra = on_insert(conn, {**row, "content": content}) if on_insert else None
    return {"snapshot": row, "created": True, "extra": extra}


def get(org_id: str, snapshot_id: str) -> Optional[Dict[str, Any]]:
    """One snapshot with its content, only if it belongs to this organisation."""
    return execute_one(f"SELECT {COLUMNS}, content FROM assessment_snapshots WHERE org_id = %s AND id = %s",
                       (str(org_id), str(snapshot_id)))


def listing(org_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    return execute_query(f"SELECT {COLUMNS} FROM assessment_snapshots WHERE org_id = %s "
                         "ORDER BY created_at DESC, seq DESC LIMIT %s", (str(org_id), limit)) or []


def verify(row: Dict[str, Any]) -> bool:
    """True when the stored content still hashes to the stored hash."""
    return builder.sha256_of(builder.canonical(row["content"])) == row["content_sha256"]


def for_plan(content: Dict[str, Any], starter: bool) -> Dict[str, Any]:
    """Starter sees the readiness counts and the security group only (decision D1); the rest is withheld on read."""
    if not starter:
        return content
    compliance = content.get("compliance") or {}
    open_groups = {"security"}
    shown = [r for r in compliance.get("requirements", []) if r["group"] in open_groups]
    locked = {**compliance, "requirements": shown, "attestations": [], "locked": True,
              "locked_requirement_count": len(compliance.get("requirements", [])) - len(shown)}
    return {**content, "compliance": locked}


def summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(row["id"]), "seq": row["seq"], "schema_version": row["schema_version"], "scope": row["scope"],
            "content_sha256": row["content_sha256"], "created_by": str(row["created_by"]) if row.get("created_by") else None,
            "created_at": row["created_at"].astimezone(timezone.utc).isoformat()}
