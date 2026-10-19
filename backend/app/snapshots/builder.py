"""Assemble the frozen content of one assessment snapshot (Packet 04).

A snapshot is ORGANISATION-scoped with a per-domain section: since scoring v3 the score and the
readiness counts belong to the organisation, so a snapshot never labels an organisation-wide figure
as the result for one historical domain scan. Every query is scoped by org_id.

The content is plain JSON data. `canonical()` is the one serialisation: sorted keys, no spaces,
UTF-8, datetimes as UTC ISO text. The stored hash is the sha256 of that text, and re-canonicalising
the stored JSONB gives the same text, so anyone can re-verify an issued snapshot.

Left out on purpose: raw finding evidence blobs, attestation free text and notes, question answers
beyond the recorded value/date, and anything about incidents (the DPO section counts those itself).
"""
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from backend.app.compliance import mapping, practitioner, questionnaire as qn, status as cstatus
from backend.app.compliance.register import DISCLAIMER, REGISTER
from backend.app.core.database import execute_one, execute_query
from backend.app.risk.check_set import CHECK_SET_VERSION, COVERAGE_VERSION, NUCLEI_LINE, domain_coverage_line
from backend.app.risk.engine import SCORE_MODEL, SCORE_SCOPE, compute_risk_score, latest_assessment

SCHEMA_VERSION = 1
REPORT_VERSION = "cyphward-report-v2"
RECENT_RESOLVED_DAYS = 30

DOMAIN_SCANS_SQL = """
    SELECT d.id AS domain_id, d.domain, s.id AS scan_id, s.completed_at, s.stage_progress, n.tool_coverage
    FROM domains d
    LEFT JOIN LATERAL (
        SELECT sc.id, sc.completed_at, sc.stage_progress FROM scans sc
        WHERE sc.org_id = d.org_id AND sc.domain_id = d.id AND sc.status = 'completed'
        ORDER BY sc.completed_at DESC NULLS LAST, sc.id DESC LIMIT 1
    ) s ON true
    LEFT JOIN LATERAL (
        SELECT sr.raw_data -> 'tool_coverage' AS tool_coverage FROM scan_results sr
        WHERE sr.scan_id = s.id AND sr.stage = 'nuclei'
        ORDER BY sr.created_at DESC LIMIT 1
    ) n ON true
    WHERE d.org_id = %s AND d.verification_status = 'verified'
    ORDER BY d.created_at ASC, d.domain ASC
"""
FINDINGS_SQL = """
    SELECT f.id, f.title, f.severity, f.status, f.category, f.description, f.remediation, f.confidence,
           f.first_seen_at, f.last_seen_at, f.scan_id, f.evidence, a.hostname, a.domain_id, d.domain
    FROM findings f
    LEFT JOIN assets a ON a.id = f.asset_id AND a.org_id = f.org_id
    LEFT JOIN domains d ON d.id = a.domain_id AND d.org_id = a.org_id
    WHERE f.org_id = %s AND f.status != 'resolved'
    ORDER BY f.created_at, f.id
"""
# Anything a later write could change. Compared before and after gathering: a mismatch means the data
# moved while the snapshot was being read, so it is read again (the helpers use separate connections).
FENCE_SQL = """
    SELECT md5(concat_ws('|',
      (SELECT count(*) || ':' || coalesce(max(completed_at)::text, '') || ':' || coalesce(max(id::text), '')
         FROM scans WHERE org_id = %(o)s AND status = 'completed'),
      (SELECT count(*) || ':' || coalesce(max(updated_at)::text, '') || ':' || count(*) FILTER (WHERE status = 'resolved')
         FROM findings WHERE org_id = %(o)s),
      (SELECT count(*) || ':' || coalesce(max(created_at)::text, '') FROM compliance_evidence WHERE org_id = %(o)s),
      (SELECT count(*) || ':' || coalesce(max(created_at)::text, '') || ':' || count(superseded_by)
         FROM compliance_attestations WHERE org_id = %(o)s),
      (SELECT count(*) || ':' || coalesce(max(reviewed_at)::text, '') FROM compliance_practitioner_reviews WHERE org_id = %(o)s),
      (SELECT count(*) || ':' || coalesce(max(verified_at)::text, '') FROM compliance_clause_verifications WHERE org_id = %(o)s),
      (SELECT string_agg(id::text || verification_status || coalesce(revoked_at::text, ''), ',' ORDER BY id)
         FROM domains WHERE org_id = %(o)s)
    )) AS fence
"""


def fence(org_id: str) -> str:
    return (execute_one(FENCE_SQL, {"o": org_id}) or {}).get("fence") or ""


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
    if isinstance(value, (date, UUID)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (set, tuple)):
        return list(value)
    raise TypeError(f"not serialisable: {type(value).__name__}")


def canonical(content: Dict[str, Any]) -> str:
    """The one serialisation hashed and stored."""
    return json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_jsonable)


def sha256_of(canonical_text: str) -> str:
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


def _iso(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else _jsonable(value) if value else None


def _coverage_summary(stage_progress: Any, tool_coverage: Any) -> Dict[str, Any]:
    scoring = stage_progress.get("scoring") if isinstance(stage_progress, dict) else None
    coverage = scoring.get("coverage") if isinstance(scoring, dict) else None
    if not isinstance(coverage, dict):
        return {"recorded": False}
    targets = coverage.get("targets") if isinstance(coverage.get("targets"), dict) else {}
    nuclei = coverage.get("nuclei") if isinstance(coverage.get("nuclei"), dict) else {}
    return {
        "recorded": True, "version": coverage.get("version"), "check_set": coverage.get("check_set"),
        "state": coverage.get("state"), "label": coverage.get("label"),
        "requested_checks": coverage.get("requested_checks"), "evaluated_checks": coverage.get("evaluated_checks"),
        "missing_checks": len(coverage.get("missing") or []), "omitted_checks": len(coverage.get("omitted_checks") or []),
        "targets": {k: targets.get(k) for k in ("selected", "in_scope", "assessed")},
        "nuclei": {"state": nuclei.get("state"), "hosts_run": nuclei.get("hosts_run"), "matches": nuclei.get("matches")},
    }


def _domain_sections(org_id: str) -> List[Dict[str, Any]]:
    sections = []
    for row in execute_query(DOMAIN_SCANS_SQL, (org_id,)) or []:
        scanned = row.get("scan_id") is not None
        tool = row.get("tool_coverage") if isinstance(row.get("tool_coverage"), dict) else {}
        sections.append({
            "domain_id": str(row["domain_id"]), "domain": row["domain"],
            "scan_id": str(row["scan_id"]) if scanned else None,
            "observed_at": _iso(row.get("completed_at")),
            "coverage": _coverage_summary(row.get("stage_progress"), tool) if scanned else {"recorded": False},
            "tools": {"nuclei": {"tool_version": tool.get("tool_version"),
                                 "template_set_version": tool.get("template_set_version")}} if tool else {},
        })
    return sections


def _finding_rows(org_id: str) -> List[Dict[str, Any]]:
    return execute_query(FINDINGS_SQL, (org_id,)) or []


def _frozen_findings(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{
        "id": str(r["id"]), "title": r["title"], "severity": r.get("severity"), "status": r.get("status"),
        "category": r.get("category"), "description": r.get("description") or "",
        "remediation": r.get("remediation") or "", "confidence": r.get("confidence"), "host": r.get("hostname"), "domain": r.get("domain"),
        "first_seen_at": _iso(r.get("first_seen_at")), "last_seen_at": _iso(r.get("last_seen_at")),
        "scan_id": str(r["scan_id"]) if r.get("scan_id") else None,
    } for r in rows]


def _scoring(rows: List[Dict[str, Any]], assessment: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = compute_risk_score(rows, assessment=assessment)
    scan = result.get("assessment") or {}
    return {
        "model": result.get("model"), "scope": result.get("scope"), "assessed": result.get("assessed"),
        "score": result.get("score"), "max_score": result.get("max_score", 100), "grade": result.get("grade"),
        "posture_label": result.get("posture_label"), "risk_points": result.get("risk_points"),
        "counts": (result.get("counts") or {}), "subscores": (result.get("subscores") or []),
        "factors": [{k: f.get(k) for k in ("impact", "type", "label", "scan_id", "assessed_at")}
                    for f in (result.get("factors") or [])],
        "scope_label": result.get("scope_label"), "domain_coverage_line": result.get("domain_coverage_line") or "",
        "domain_states": [dict(d) for d in result.get("domain_coverage") or []],
        "assessment": {"scan_id": scan.get("scan_id"), "completed_at": scan.get("completed_at"),
                       "status": scan.get("status")} if scan else None,
        "coverage_label": ((scan.get("coverage") or {}).get("label") if scan else None),
        "nuclei_line": NUCLEI_LINE if ((scan.get("coverage") or {}).get("version") == COVERAGE_VERSION) else None,
    }


def _compliance(org_id: str, now: datetime) -> Dict[str, Any]:
    ctx = cstatus._context(org_id)
    views = [cstatus._requirement_view(req, ctx, now) for req in REGISTER["requirements"]]
    cstatus._attach_findings(org_id, views)
    requirements = []
    for v in views:
        requirements.append({
            "key": v["key"], "group": v["group"], "title": v["title"], "clause": v["clause"],
            "clause_verified": v["clause_verified"], "summary": v["summary"],
            "status": v["status"], "status_label": v["status_label"],
            "reason": v["reason"], "reason_text": v["reason_text"],
            "source": v["source"], "source_label": v["source_label"],
            "sources": [{k: s.get(k) for k in ("source", "source_label", "status", "status_label", "reason")}
                        for s in v["sources"]],
            "domains": [{
                "domain": d.get("domain"), "status": d["status"], "status_label": d["status_label"],
                "source": d.get("source"), "source_label": d.get("source_label"),
                "reason": d["reason"], "reason_text": d["reason_text"],
                "observed_at": _iso(d.get("observed_at")), "expires_at": _iso(d.get("expires_at")),
                "scan_id": str(d["scan_id"]) if d.get("scan_id") else None,
                "finding_ids": [str(i) for i in d.get("finding_ids") or []],
            } for d in v["domains"]],
            "answers": [{k: a.get(k) for k in ("question_key", "status", "reason", "owner_name", "expires_at")}
                        for a in v["answers"]],
            "findings": [{k: f[k] for k in ("id", "title", "severity", "status")} for f in v["findings"]],
            "remediation_hint": v["remediation_hint"], "freshness_days": v["freshness_days"],
        })
    # Practitioner notes (C6) are frozen with the snapshot, but only where they exist: a snapshot of an
    # organisation without any is byte-identical to one made before they existed (schema_version stays 1).
    for entry, v in zip(requirements, views):
        if v.get("practitioner_review"):
            entry["practitioner_review"] = v["practitioner_review"]
        if v.get("clause_review"):
            entry["clause_review"] = v["clause_review"]
    attestations = []
    for key, row in sorted(ctx["answers"].items()):
        question = qn.question(key)
        answer = row["answer"] if isinstance(row["answer"], dict) else {}
        attestations.append({
            "question_key": key, "prompt": question["prompt"] if question else None,
            "value": answer.get("value"), "date": answer.get("date"),
            "owner_user_id": str(row["owner_user_id"]) if row.get("owner_user_id") else None,
            "owner_name": row.get("owner_name"), "attested_at": _iso(row["attested_at"]),
            "expires_at": _iso(row["expires_at"]), "expired": bool(row["expires_at"] and row["expires_at"] <= now),
            "evidence_link": row.get("evidence_link"), "source": "customer_attested",
        })
    return {
        "disclaimer": DISCLAIMER,
        "register": {"version": REGISTER["version"], "title": REGISTER["title"],
                     "references_pending_review": practitioner.pending_count(REGISTER["requirements"], ctx["clauses"])},
        "questionnaire_version": qn.QUESTIONNAIRE["version"],
        "readiness": mapping.readiness(v["status"] for v in views),
        "groups": [{"key": g["key"], "title": g["title"]} for g in REGISTER["groups"]],
        "requirements": requirements, "attestations": attestations,
    }


def build(org: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Read the organisation's current state once and return the content to freeze."""
    now = now or datetime.now(timezone.utc)
    org_id = str(org["id"])
    rows = _finding_rows(org_id)
    assessment = latest_assessment(org_id)
    scoring = _scoring(rows, assessment)
    sections = _domain_sections(org_id)
    resolved = execute_one(
        "SELECT COUNT(*) AS count FROM findings WHERE org_id = %s AND status = 'resolved' "
        "AND resolved_at > %s - make_interval(days => %s)", (org_id, now, RECENT_RESOLVED_DAYS)) or {"count": 0}
    assets = (execute_one("SELECT COUNT(*) AS count FROM assets WHERE org_id = %s", (org_id,)) or {}).get("count", 0)
    observed = [s["observed_at"] for s in sections if s["observed_at"]]
    findings = _frozen_findings(rows)
    for section in sections:
        section["open_findings"] = sum(1 for f in findings if f["domain"] == section["domain"])
    return {
        "schema_version": SCHEMA_VERSION,
        "report_version": REPORT_VERSION,
        "generated_at": _iso(now),
        "scope": {
            "type": SCORE_SCOPE, "org_name": org.get("name", ""),
            "note": "The score and readiness counts belong to the whole organisation. Each domain below shows "
                    "its own latest assessment.",
            "domains": sections, "assets": assets,
            "domain_line": domain_coverage_line([{"domain": s["domain"], "state": (
                "not_scanned" if not s["scan_id"] else (s["coverage"].get("state") or "unknown"))} for s in sections]),
        },
        "dates": {"generated_at": _iso(now), "earliest_observation": min(observed) if observed else None,
                  "latest_observation": max(observed) if observed else None,
                  "assessment_completed_at": (scoring["assessment"] or {}).get("completed_at")},
        "scoring": scoring,
        "findings": {"open": findings, "resolved_last_30d": resolved["count"]},
        "provenance": {
            "scoring_model": SCORE_MODEL, "check_set": CHECK_SET_VERSION, "coverage_version": COVERAGE_VERSION,
            "register_version": REGISTER["version"], "report_version": REPORT_VERSION,
            "tools": [{"domain": s["domain"], "scan_id": s["scan_id"], "tools": s["tools"]} for s in sections],
        },
        "compliance": _compliance(org_id, now),
    }
