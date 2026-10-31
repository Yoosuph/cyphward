"""Transactional policy for accepting manual and scheduled scans."""
from dataclasses import dataclass
from typing import Any, Dict, Optional
import json
import re

from fastapi import HTTPException
from psycopg.errors import LockNotAvailable, QueryCanceled, UniqueViolation

from backend.app.billing.subscriptions import resolve_plan
from backend.app.core.database import get_db
from shared.contracts import empty_stage_progress
from backend.app.core.cron_claim import lock_cron_claim


_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass
class Admission:
    outcome: str  # created | replayed | active | quota | suspended
    scan: Optional[Dict[str, Any]] = None
    domain: Optional[str] = None
    limit: Optional[int] = None
    used: Optional[int] = None
    plan_label: Optional[str] = None


class AdmissionConflict(Exception):
    def __init__(self, code: str, message: str, scan_id: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.scan_id = scan_id


def admit_scan(
    org_id: str,
    requested_domain_id: Optional[str],
    *,
    request_scope: str,
    request_key: Optional[str] = None,
    cron_authority: Optional[Dict[str, Any]] = None,
) -> Admission:
    """Serialize tenant scan admissions and commit scan/key together.

    The lock order is organization, domain, subscription. Dispatch must happen
    after this function returns, outside the transaction.
    """
    if request_key is not None and not _KEY_RE.fullmatch(request_key):
        raise HTTPException(status_code=422, detail="Idempotency-Key must be 1–128 letters, digits, '.', '_', ':' or '-'.")
    if not request_scope or len(request_scope) > 128:
        raise ValueError("Invalid scan request namespace")

    resolved_domain_id: Optional[str] = None
    try:
        with get_db() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL lock_timeout = '5s'")
                    cur.execute("SET LOCAL statement_timeout = '15s'")
                    if cron_authority is not None:
                        lock_cron_claim(cur, cron_authority)
                    cur.execute("SELECT id, plan FROM organizations WHERE id = %s FOR UPDATE", (org_id,))
                    org = cur.fetchone()
                    if not org:
                        raise HTTPException(status_code=404, detail="Workspace not found.")
                    # Suspension (core/suspension.py), read under the organization row lock the owner's suspend
                    # also takes first, so a scan can't slip in while a suspension commits. Checked before the
                    # replay lookup: a suspended organisation gets no scan, not even a replayed one.
                    cur.execute("SELECT status FROM organization_suspensions WHERE org_id = %s", (org_id,))
                    suspension = cur.fetchone()
                    if suspension and suspension["status"] == "suspended":
                        return Admission("suspended")

                    # Request mapping first: a retry remains a replay even after
                    # quota exhaustion or the original scan becomes terminal.
                    if request_key is not None:
                        cur.execute(
                            """SELECT r.requested_domain_id, r.domain_id, s.*, d.domain
                               FROM scan_launch_requests r
                               JOIN scans s ON s.id = r.scan_id AND s.org_id = r.org_id
                               JOIN domains d ON d.id = r.domain_id AND d.org_id = r.org_id
                               WHERE r.org_id = %s AND r.request_scope = %s AND r.request_key = %s
                                 AND r.expires_at > clock_timestamp()
                               FOR UPDATE OF r""",
                            (org_id, request_scope, request_key),
                        )
                        replay = cur.fetchone()
                        if replay:
                            original_selector = str(replay["requested_domain_id"]) if replay["requested_domain_id"] else None
                            current_selector = str(requested_domain_id) if requested_domain_id else None
                            if original_selector != current_selector:
                                raise AdmissionConflict("idempotency_key_reused", "This Idempotency-Key was already used for a different domain selection.")
                            scan = {k: v for k, v in replay.items() if k not in ("requested_domain_id", "domain")}
                            return Admission("replayed", scan=scan, domain=replay["domain"])
                        cur.execute(
                            "DELETE FROM scan_launch_requests WHERE org_id = %s AND request_scope = %s AND request_key = %s AND expires_at <= clock_timestamp()",
                            (org_id, request_scope, request_key),
                        )

                    if requested_domain_id:
                        cur.execute(
                            "SELECT id, org_id, domain, verification_status FROM domains WHERE id = %s AND org_id = %s FOR SHARE",
                            (requested_domain_id, org_id),
                        )
                    else:
                        cur.execute(
                            "SELECT id, org_id, domain, verification_status FROM domains WHERE org_id = %s AND verification_status = 'verified' ORDER BY created_at ASC LIMIT 1 FOR SHARE",
                            (org_id,),
                        )
                    domain = cur.fetchone()
                    if not domain:
                        if requested_domain_id:
                            raise HTTPException(status_code=404, detail="Domain not found.")
                        raise HTTPException(status_code=400, detail="No verified domain found. Add and verify a domain before scanning.")
                    resolved_domain_id = str(domain["id"])
                    if domain["verification_status"] != "verified":
                        raise HTTPException(status_code=403, detail=f"Domain {domain['domain']} is not verified. Please verify DNS TXT ownership before initiating scans.")

                    cur.execute("SELECT * FROM subscriptions WHERE org_id = %s FOR SHARE", (org_id,))
                    sub = cur.fetchone()
                    ent = resolve_plan(org, sub)
                    limit = ent["monthly_scans"]

                    cur.execute("SELECT clock_timestamp() AS admitted_at")
                    admitted_at = cur.fetchone()["admitted_at"]

                    cur.execute(
                        """SELECT id FROM scans
                           WHERE org_id = %s AND domain_id = %s AND status IN ('queued', 'running')
                           LIMIT 1""",
                        (org_id, domain["id"]),
                    )
                    active = cur.fetchone()
                    if active:
                        return Admission("active", scan={"id": active["id"]}, domain=domain["domain"])

                    cur.execute(
                        """SELECT count(*) AS n FROM scans
                           WHERE org_id = %s AND created_at >=
                             (date_trunc('month', %s::timestamptz AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')""",
                        (org_id, admitted_at),
                    )
                    used = int(cur.fetchone()["n"])
                    if limit is not None and used >= limit:
                        return Admission("quota", domain=domain["domain"], limit=limit, used=used, plan_label=ent["label"])

                    cur.execute(
                        """INSERT INTO scans
                           (org_id, domain_id, scan_type, status, current_stage, stage_progress, created_at)
                           VALUES (%s, %s, 'EXTERNAL_ASSESSMENT', 'queued', 'queued', %s::jsonb, %s)
                           RETURNING *""",
                        (org_id, domain["id"], json.dumps(empty_stage_progress()), admitted_at),
                    )
                    scan = cur.fetchone()
                    if request_key is not None:
                        cur.execute(
                            """INSERT INTO scan_launch_requests
                               (org_id, request_scope, request_key, requested_domain_id, domain_id, scan_id, created_at, expires_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s + interval '90 days')""",
                            (org_id, request_scope, request_key, requested_domain_id, domain["id"], scan["id"], admitted_at, admitted_at),
                        )
                    return Admission("created", scan=scan, domain=domain["domain"])
    except (LockNotAvailable, QueryCanceled) as exc:
        raise HTTPException(status_code=503, detail="Scan admission is busy. Please retry the same request shortly.") from exc
    except UniqueViolation:
        # Database uniqueness is the final guard if a writer bypasses the
        # tenant lock. Do not expose a raw constraint error as HTTP 500.
        with get_db() as conn:
            with conn.cursor() as cur:
                if not resolved_domain_id:
                    raise
                cur.execute(
                    "SELECT s.id, d.domain FROM scans s JOIN domains d ON d.id = s.domain_id WHERE s.org_id = %s AND s.domain_id = %s AND s.status IN ('queued', 'running') LIMIT 1",
                    (org_id, resolved_domain_id),
                )
                existing = cur.fetchone()
        if existing:
            return Admission("active", scan={"id": existing["id"]}, domain=existing["domain"])
        raise
