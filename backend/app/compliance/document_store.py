"""Draft documents (packet C5): generation, storage, approval and the daily cap.

Order of a generation, so no transaction is open while the model runs:
  1. read the organisation's own answers and observations and build the inputs;
  2. reserve one slot of the daily quota (committed before the model is called);
  3. ask the provider to reword the tokenised template, at most `MODEL_ATTEMPTS` times, checking each answer;
     the deterministic template is used when no answer passes;
  4. in one transaction: lock (organisation, kind), take the next version, compose the stored text, insert
     the row and write `audit_log`. A failed audit write leaves no document.

Every query is scoped by organisation. Documents and approvals are append-only (the app role has SELECT and
INSERT only). An approval is the customer's own statement (`customer_attested`); it never changes a register
requirement and is shown only on the Documents page and in the audit log.
"""
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from psycopg.types.json import Jsonb
from starlette.concurrency import run_in_threadpool

from backend.app.ai.factory import get_ai_provider
from backend.app.compliance import attestation_store
from backend.app.compliance import documents as docs
from backend.app.core import database
from backend.app.core.database import execute_query

HISTORY_LIMIT = 50


class QuotaExceeded(RuntimeError):
    """The organisation used today's generations. The API maps it to 429."""


class DocumentConflict(RuntimeError):
    """The request cannot apply to the document as it is now. The API maps it to 409."""


class DocumentError(RuntimeError):
    """A draft that failed the final checks and has no fallback. The API maps it to 500."""


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


# ── Inputs ────────────────────────────────────────────────────────────────────


def gather(org: Dict[str, Any]) -> Dict[str, Any]:
    """The organisation's own data that can feed a draft. Statuses only: no evidence details are read."""
    org_id = str(org["id"])
    domains = execute_query(
        "SELECT domain FROM domains WHERE org_id = %s AND verification_status = 'verified' "
        "AND revoked_at IS NULL ORDER BY domain", (org_id,)) or []
    rows = execute_query(
        "SELECT DISTINCT ON (requirement_key, domain_id) requirement_key, domain_id, status, expires_at "
        "FROM compliance_evidence WHERE org_id = %s AND requirement_key = ANY(%s) "
        "ORDER BY requirement_key, domain_id, observed_at DESC, created_at DESC",
        (org_id, list(docs.OBSERVED_KEYS))) or []
    observed: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        observed.setdefault(row["requirement_key"], {})[str(row["domain_id"])] = row
    return {"org_name": org.get("name"), "domains": [d["domain"] for d in domains],
            "answers": attestation_store.current_rows(org_id), "observed": observed}


# ── Quota ─────────────────────────────────────────────────────────────────────


def used_today(org_id: str) -> int:
    row = (execute_query(
        "SELECT n FROM compliance_document_quota WHERE org_id = %s AND day = (now() AT TIME ZONE 'utc')::date",
        (org_id,)) or [{"n": 0}])[0]
    return int(row["n"])


def reserve(org_id: str) -> int:
    """Take one generation from today's cap, committed before any model call. The CHECK on the table is the
    backstop: the conditional upsert and the constraint both refuse an eleventh."""
    with database.get_db() as conn:
        with conn.transaction():
            row = conn.execute(
                "INSERT INTO compliance_document_quota (org_id, day, n) "
                "VALUES (%s, (now() AT TIME ZONE 'utc')::date, 1) "
                "ON CONFLICT (org_id, day) DO UPDATE SET n = compliance_document_quota.n + 1 "
                "WHERE compliance_document_quota.n < %s RETURNING n", (org_id, docs.DAILY_CAP)).fetchone()
    if row is None:
        raise QuotaExceeded(f"Today's limit of {docs.DAILY_CAP} drafts for your organisation is used. Try again tomorrow.")
    return int(row["n"])


# ── Drafting ──────────────────────────────────────────────────────────────────


async def _model_body(template: str) -> Tuple[Optional[str], str, Optional[str]]:
    """(text, generator, reason) from the provider; text is None when nothing usable came back."""
    provider = get_ai_provider()
    name = type(provider).__name__
    reason = "provider_unavailable"
    for _ in range(docs.MODEL_ATTEMPTS):
        try:
            output = await provider.draft_document(docs.SYSTEM_PROMPT, template)
        except Exception as exc:  # a provider failure must never fail the request
            output, reason = None, f"provider_error:{type(exc).__name__}"[:120]
            continue
        if output is None:
            reason = "provider_unavailable"
            break
        problem = docs.validate_model_text(output, template)
        if problem is None:
            return output, name, None
        reason = f"rejected:{problem}"
    return None, name, reason


async def generate(org: Dict[str, Any], actor_id: str, kind: str) -> Dict[str, Any]:
    if kind not in docs.KINDS:
        raise ValueError("unknown document kind")
    org_id = str(org["id"])
    ctx = await run_in_threadpool(gather, org)
    inputs = docs.build_inputs(kind, ctx)
    template = docs.build_template(inputs)
    await run_in_threadpool(reserve, org_id)
    body, provider_name, reason = await _model_body(template)
    candidates = []
    if body is not None:
        candidates.append((body, provider_name, None))
    candidates.append((template, "template", reason))
    return await run_in_threadpool(_save, org_id, str(actor_id), inputs, candidates)


def _save(org_id: str, actor: str, inputs: Dict[str, Any], candidates: List[Tuple[str, str, Optional[str]]]
          ) -> Dict[str, Any]:
    kind = inputs["kind"]
    fingerprint = docs.inputs_hash(inputs)
    placeholders = docs.placeholders_for(inputs)
    doc_id = str(uuid.uuid4())
    with database.get_db() as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"compliance-doc:{org_id}:{kind}",))
            at = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
            version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM compliance_documents WHERE org_id = %s AND kind = %s",
                (org_id, kind)).fetchone()["v"]
            chosen = None
            fallback = None
            for body, generator, reason in candidates:
                text = docs.compose(docs.fill_slots(body, inputs), inputs, version=version, generated_at=at)
                problems = docs.final_problems(text, inputs)
                if not problems:
                    chosen = (text, generator, reason)
                    break
                fallback = problems[0]
            if chosen is None:
                raise DocumentError("The draft failed its final checks and was not saved.")
            text, generator, reason = chosen
            if generator == "template" and fallback and reason is None:
                reason = f"rejected:{fallback}"
            conn.execute(
                "INSERT INTO compliance_documents (id, org_id, kind, version, generated_at, generated_by, generator, "
                "fallback_reason, inputs_hash, text_sha256, text, placeholders, questionnaire_version) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (doc_id, org_id, kind, version, at, actor, generator, reason, fingerprint,
                 hashlib.sha256(text.encode()).hexdigest(), text, Jsonb(placeholders),
                 inputs["questionnaire_version"]))
            # The draft text, answers and names stay out of the audit trail.
            conn.execute(
                "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (org_id, actor, "compliance.document.generated", "compliance_document", doc_id,
                 Jsonb({"kind": kind, "version": version, "generator": generator, "fallback_reason": reason,
                        "inputs_hash": fingerprint, "placeholder_count": len(placeholders)})))
    return {"id": doc_id, "kind": kind, "version": version, "generator": generator,
            "fallback_reason": reason, "placeholder_count": len(placeholders)}


# ── Approval ──────────────────────────────────────────────────────────────────


def approve(org_id: str, actor_id: str, document_id: str) -> Optional[Dict[str, Any]]:
    """Record the actor's approval of the latest version of a document. None when the id is not this
    organisation's. The approval changes no register requirement."""
    org_id, actor = str(org_id), str(actor_id)
    with database.get_db() as conn:
        with conn.transaction():
            doc = conn.execute(
                "SELECT id, kind, version, text_sha256, placeholders FROM compliance_documents "
                "WHERE id = %s AND org_id = %s", (document_id, org_id)).fetchone()
            if doc is None:
                return None
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"compliance-doc:{org_id}:{doc['kind']}",))
            latest = conn.execute(
                "SELECT MAX(version) AS v FROM compliance_documents WHERE org_id = %s AND kind = %s",
                (org_id, doc["kind"])).fetchone()["v"]
            if doc["version"] != latest:
                raise DocumentConflict("A newer version exists. Review and approve the newest version.")
            open_count = len(doc["placeholders"])
            approval_id = str(uuid.uuid4())
            try:
                with conn.transaction():
                    row = conn.execute(
                        "INSERT INTO compliance_document_approvals (id, org_id, document_id, approved_by, "
                        "text_sha256, open_placeholders) VALUES (%s, %s, %s, %s, %s, %s) RETURNING approved_at",
                        (approval_id, org_id, document_id, actor, doc["text_sha256"], open_count)).fetchone()
            except psycopg.errors.UniqueViolation:
                raise DocumentConflict("This version is already approved.")
            conn.execute(
                "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (org_id, actor, "compliance.document.approved", "compliance_document", document_id,
                 Jsonb({"kind": doc["kind"], "version": doc["version"], "source": "customer_attested",
                        "open_placeholders": open_count, "approval_id": approval_id})))
    return {"id": approval_id, "document_id": document_id, "kind": doc["kind"], "version": doc["version"],
            "approved_at": _iso(row["approved_at"]), "open_placeholders": open_count}


# ── Reads ─────────────────────────────────────────────────────────────────────

LIST_SQL = (
    "SELECT d.id, d.kind, d.version, d.generated_at, d.generator, d.fallback_reason, d.inputs_hash, d.placeholders, "
    "g.full_name AS generated_by_name, a.approved_at, a.open_placeholders AS approved_open_placeholders, "
    "ap.full_name AS approved_by_name "
    "FROM compliance_documents d LEFT JOIN profiles g ON g.id = d.generated_by "
    "LEFT JOIN compliance_document_approvals a ON a.document_id = d.id AND a.org_id = d.org_id "
    "LEFT JOIN profiles ap ON ap.id = a.approved_by "
    "WHERE d.org_id = %s ORDER BY d.kind, d.version DESC"
)


def _version_view(row: Dict[str, Any]) -> Dict[str, Any]:
    placeholders = row["placeholders"] or []
    approval = None
    if row.get("approved_at"):
        approval = {"approved_by": row.get("approved_by_name"), "approved_at": _iso(row["approved_at"]),
                    "source": "customer_attested", "open_placeholders": row["approved_open_placeholders"]}
    return {"id": str(row["id"]), "version": row["version"], "generated_at": _iso(row["generated_at"]),
            "generated_by": row.get("generated_by_name"), "generator": row["generator"],
            "fallback_reason": row["fallback_reason"], "placeholders": placeholders,
            "open_placeholders": len(placeholders), "approval": approval}


def listing(org: Dict[str, Any]) -> Dict[str, Any]:
    org_id = str(org["id"])
    rows = execute_query(LIST_SQL, (org_id,)) or []
    by_kind: Dict[str, List[Dict[str, Any]]] = {k: [] for k in docs.KINDS}
    for row in rows:
        by_kind[row["kind"]].append(row)
    fresh: Dict[str, str] = {}
    if rows:
        ctx = gather(org)
        fresh = {k: docs.inputs_hash(docs.build_inputs(k, ctx)) for k in docs.KINDS}
    documents = []
    for kind in docs.KINDS:
        versions = by_kind[kind][:HISTORY_LIMIT]
        latest = versions[0] if versions else None
        view = _version_view(latest) if latest else None
        if view:
            view["stale"] = latest["inputs_hash"] != fresh.get(kind)
        documents.append({
            "kind": kind, "title": docs.TITLES[kind],
            "status": "not_generated" if latest is None else ("approved" if view["approval"] else "draft"),
            "latest": view, "history": [_version_view(r) for r in versions]})
    return {"label": docs.LABEL, "daily_cap": docs.DAILY_CAP, "generated_today": used_today(org_id),
            "documents": documents}


def get(org_id: str, document_id: str) -> Optional[Dict[str, Any]]:
    row = (execute_query(
        "SELECT d.id, d.kind, d.version, d.generated_at, d.generator, d.fallback_reason, d.inputs_hash, "
        "d.placeholders, d.text, g.full_name AS generated_by_name, a.approved_at, "
        "a.open_placeholders AS approved_open_placeholders, ap.full_name AS approved_by_name, "
        "d.version = (SELECT MAX(version) FROM compliance_documents x WHERE x.org_id = d.org_id AND x.kind = d.kind) "
        "AS is_latest "
        "FROM compliance_documents d LEFT JOIN profiles g ON g.id = d.generated_by "
        "LEFT JOIN compliance_document_approvals a ON a.document_id = d.id AND a.org_id = d.org_id "
        "LEFT JOIN profiles ap ON ap.id = a.approved_by "
        "WHERE d.id = %s AND d.org_id = %s", (document_id, org_id)) or [None])[0]
    if row is None:
        return None
    return {**_version_view(row), "kind": row["kind"], "title": docs.TITLES[row["kind"]], "label": docs.LABEL,
            "text": row["text"], "is_latest": bool(row["is_latest"])}
