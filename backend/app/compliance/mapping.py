"""Scan evidence → requirement status (compliance packet C1). Pure functions.

Two halves:

* `domain_rows` runs at scan finalisation for the scanned domain only and
  returns append-only `compliance_evidence` rows for the tool-backed
  requirements (written inside the fenced completion transaction).
* `requirement_status` runs on read. It combines the latest row per domain
  with live findings: any currently open mapped issue finding is a gap
  whatever the stored row says, and nothing becomes `present` without a
  current, unexpired row that recorded conclusive checks.

Missing, legacy, omitted or expired evidence is `not_assessed`, never
`present`. Tool evidence never produces `not_applicable` (decision D6).
See docs/compliance-build-plan-2026-10-16/C1-plan.md section 4.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from backend.app.compliance.register import rule_matches
from backend.app.compliance.rule_keys import rule_for, rule_key_for

PRESENT, GAP, NOT_ASSESSED, NOT_APPLICABLE = "present", "gap", "not_assessed", "not_applicable"
# Read-only status: no evidence source exists yet (a customer answer or a check a later release adds).
# Distinct from NOT_ASSESSED, which means a check could have run but did not finish. Never stored.
AWAITING_INPUT = "awaiting_input"
TOOL_SOURCE = "tool_observed"


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _rules(requirement: Dict[str, Any]) -> List[str]:
    return list((requirement.get("tool_mapping") or {}).get("rules") or [])


def _checks(requirement: Dict[str, Any]) -> List[str]:
    return list((requirement.get("tool_mapping") or {}).get("checks") or [])


def classify_findings(requirement: Dict[str, Any], findings: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Split open findings mapped to this requirement into issue / informational.
    Resolved, unmapped and positive findings are dropped."""
    patterns = _rules(requirement)
    out: Dict[str, List[Dict[str, Any]]] = {"issue": [], "informational": []}
    for finding in findings:
        if (finding.get("status") or "open") == "resolved":
            continue
        key = finding.get("rule_key") or rule_key_for(finding.get("category"), finding.get("evidence"), finding.get("title"))
        rule = rule_for(key)
        if not rule or not any(rule_matches(p, key) for p in patterns):
            continue
        if rule.kind in out:
            out[rule.kind].append({**finding, "rule_key": key})
    return out


def _groups(coverage: Dict[str, Any], field: str, checks: List[str]) -> List[Dict[str, Any]]:
    return [dict(g) for g in coverage.get(field) or [] if isinstance(g, dict) and g.get("check") in checks]


def evaluate_domain(requirement: Dict[str, Any], coverage: Any, findings: Iterable[Dict[str, Any]],
                    open_ports: Optional[Dict[str, List[int]]] = None) -> Dict[str, Any]:
    """Status of one tool-backed requirement for one domain from one assessment (truth table rows 1-6)."""
    checks = _checks(requirement)
    mapped = classify_findings(requirement, findings)
    details: Dict[str, Any] = {
        "checks": checks,
        "informational_finding_ids": sorted(str(f["id"]) for f in mapped["informational"] if f.get("id")),
    }
    if isinstance(coverage, dict):
        details.update(coverage_version=coverage.get("version"), coverage_state=coverage.get("state"),
                       check_set=coverage.get("check_set"))
    issues = mapped["issue"]
    if issues:
        details["rules"] = sorted({f["rule_key"] for f in issues})
        return {"status": GAP, "reason": "open_findings", "finding_ids": sorted(str(f["id"]) for f in issues if f.get("id")),
                "details": details}
    if not isinstance(coverage, dict):
        return {"status": NOT_ASSESSED, "reason": "no_coverage", "finding_ids": [], "details": details}
    if coverage.get("version") != 2 or coverage.get("requested_checks") is None:
        return {"status": NOT_ASSESSED, "reason": "legacy_coverage", "finding_ids": [], "details": details}
    if not checks:
        return {"status": NOT_ASSESSED, "reason": "clean_result_not_provable", "finding_ids": [], "details": details}
    evaluated = _groups(coverage, "evaluated_groups", checks)
    missing = _groups(coverage, "missing", checks)
    omitted = _groups(coverage, "omitted_checks", checks)
    details.update(evaluated=evaluated, missing=missing, omitted=omitted)
    if "ports.inventory" in checks:
        hosts = {g["hostname"] for g in evaluated}
        details["open_ports"] = {h: sorted(p) for h, p in (open_ports or {}).items() if h in hosts}
    if missing:
        return {"status": NOT_ASSESSED, "reason": "checks_missing", "finding_ids": [], "details": details}
    if not evaluated:
        return {"status": NOT_ASSESSED, "reason": "checks_omitted", "finding_ids": [], "details": details}
    return {"status": PRESENT, "reason": "checks_conclusive", "finding_ids": [], "details": details}


def domain_rows(tool_requirements: Iterable[Dict[str, Any]], coverage: Any, findings: List[Dict[str, Any]], *,
                org_id: str, domain_id: str, scan_id: str, observed_at: datetime, register_version: str,
                open_ports: Optional[Dict[str, List[int]]] = None) -> List[Dict[str, Any]]:
    """Evidence rows for the scanned domain, one per tool-backed requirement."""
    observed = _aware(observed_at) or datetime.now(timezone.utc)
    rows = []
    for requirement in tool_requirements:
        result = evaluate_domain(requirement, coverage, findings, open_ports)
        rows.append({
            "org_id": org_id, "domain_id": domain_id, "scan_id": scan_id,
            "requirement_key": requirement["key"], "register_version": register_version,
            "source": TOOL_SOURCE, "status": result["status"], "observed_at": observed,
            "expires_at": observed + timedelta(days=requirement["freshness_days"]),
            "finding_ids": result["finding_ids"],
            "details": {**result["details"], "reason": result["reason"]},
        })
    return rows


# ── Read side ──────────────────────────────────────────────────────────────
def _domain_result(status: str, reason: str, domain: Dict[str, Any], row: Optional[Dict[str, Any]] = None,
                   finding_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "domain_id": str(domain["id"]), "domain": domain.get("domain"), "status": status, "reason": reason,
        "source": TOOL_SOURCE if (row or finding_ids) else None,
        "observed_at": row.get("observed_at") if row else None,
        "expires_at": row.get("expires_at") if row else None,
        "scan_id": str(row["scan_id"]) if row and row.get("scan_id") else None,
        "finding_ids": finding_ids if finding_ids is not None else [str(i) for i in (row or {}).get("finding_ids") or []],
        "details": (row or {}).get("details") or {},
    }


def _combine(results: List[Dict[str, Any]]) -> str:
    statuses = {r["status"] for r in results}
    if GAP in statuses:
        return GAP
    if not results or NOT_ASSESSED in statuses or statuses != {PRESENT}:
        return NOT_ASSESSED
    return PRESENT


def _tool_status(requirement, domains, latest_rows, live_findings, now) -> Dict[str, Any]:
    results = []
    for domain in domains:
        did = str(domain["id"])
        live = classify_findings(requirement, [f for f in live_findings if str(f.get("domain_id") or "") == did])["issue"]
        row = latest_rows.get(did)
        if live:
            results.append(_domain_result(GAP, "open_findings", domain, row, sorted(str(f["id"]) for f in live)))
            continue
        if row is None:
            results.append(_domain_result(NOT_ASSESSED, "no_assessment", domain))
            continue
        expires = _aware(row.get("expires_at"))
        if expires is not None and expires <= now:
            results.append(_domain_result(NOT_ASSESSED, "evidence_expired", domain, row))
        elif row.get("status") == PRESENT:
            results.append(_domain_result(PRESENT, (row.get("details") or {}).get("reason") or "checks_conclusive", domain, row))
        elif row.get("status") == GAP:
            # The findings behind the gap have since been resolved; only a new assessment can show more.
            results.append(_domain_result(NOT_ASSESSED, "findings_resolved_awaiting_rescan", domain, row))
        else:
            results.append(_domain_result(NOT_ASSESSED, (row.get("details") or {}).get("reason") or "not_assessed", domain, row))
    unlinked = classify_findings(requirement, [f for f in live_findings if not f.get("domain_id")])["issue"]
    status = GAP if unlinked else _combine(results)
    reason = "unlinked_finding" if unlinked else (
        "no_verified_domain" if not domains else next((r["reason"] for r in results if r["status"] == status), status))
    return {"status": status, "reason": reason, "domains": results,
            "unlinked_finding_ids": sorted(str(f["id"]) for f in unlinked)}


def _history_status(requirement, domains, history, now) -> Dict[str, Any]:
    window = timedelta(days=requirement["freshness_days"])
    needed = requirement["tool_mapping"]["scan_history"]["min_complete_scans"]
    results = []
    for domain in domains:
        did = str(domain["id"])
        scans = [h for h in history if str(h.get("domain_id")) == did
                 and (_aware(h.get("completed_at")) or now - window) > now - window]
        complete = sorted((h for h in scans if h.get("state") == "complete"), key=lambda h: str(h["completed_at"]), reverse=True)
        counted = [{"scan_id": str(h["scan_id"]), "completed_at": h["completed_at"]} for h in complete]
        not_counted = [{"scan_id": str(h["scan_id"]), "completed_at": h["completed_at"], "state": h.get("state") or "unknown"}
                       for h in scans if h.get("state") != "complete"]
        ok = len(complete) >= needed
        results.append({
            "domain_id": did, "domain": domain.get("domain"), "status": PRESENT if ok else NOT_ASSESSED,
            "reason": "complete_scans_in_window" if ok else "no_complete_scan_in_window",
            "source": TOOL_SOURCE if scans else None, "observed_at": counted[0]["completed_at"] if counted else None,
            "expires_at": None, "scan_id": counted[0]["scan_id"] if counted else None, "finding_ids": [],
            "details": {"window_days": requirement["freshness_days"], "complete_scans": counted,
                        "not_counted": not_counted[:10]},
        })
    status = _combine(results)
    reason = "no_verified_domain" if not domains else next(r["reason"] for r in results if r["status"] == status)
    return {"status": status, "reason": reason, "domains": results, "unlinked_finding_ids": []}


def requirement_status(requirement: Dict[str, Any], *, domains: List[Dict[str, Any]],
                       latest_rows: Dict[str, Dict[str, Any]], live_findings: List[Dict[str, Any]],
                       history: List[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Current status of one requirement for an organization (C1-plan section 4, read side)."""
    now = now or datetime.now(timezone.utc)
    mapping = requirement.get("tool_mapping")
    if not isinstance(mapping, dict):
        reason = "awaiting_customer_input" if "customer_attested" in requirement["evidence_types"] else "check_not_available_yet"
        return {"status": AWAITING_INPUT, "reason": reason, "domains": [], "unlinked_finding_ids": []}
    if "scan_history" in mapping:
        return _history_status(requirement, domains, history, now)
    return _tool_status(requirement, domains, latest_rows, live_findings, now)


def readiness(statuses: Iterable[str]) -> Dict[str, Any]:
    """Readiness as counts, never a bare percentage or a score (decision D5, revised).

    "With evidence" = present + gap: Cyphward holds current evidence either way.
    Awaiting input = no evidence source exists yet. Not assessed = a check could
    have run but did not finish.
    """
    statuses = list(statuses)
    applicable = [s for s in statuses if s != NOT_APPLICABLE]
    count = lambda status: sum(1 for s in applicable if s == status)
    return {
        "with_evidence": count(PRESENT) + count(GAP),
        "present": count(PRESENT),
        "gap": count(GAP),
        "awaiting_input": count(AWAITING_INPUT),
        "not_assessed": count(NOT_ASSESSED),
        "applicable": len(applicable),
    }
