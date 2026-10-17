"""Compliance read path: register + latest evidence + live findings → page data.

Status is derived on every read (C1-plan section 4). Organization scoping is
explicit in every query. Plan gating (decision D1) only hides detail; it never
changes a status or the readiness figure.
"""
from typing import Any, Dict, List, Optional

from backend.app.billing.subscriptions import resolve_plan
from backend.app.compliance import mapping
from backend.app.compliance.register import DISCLAIMER, REGISTER, requirement as register_requirement
from backend.app.core.database import execute_one, execute_query

OPEN_GROUPS_ON_STARTER = {"security"}
HISTORY_DAYS = 100  # longest scan-history window (90 days) plus margin
C1_NOTE = ("Evidence comes from two sources today: Cyphward's security checks and a static check of your website's "
           "privacy notices, cookies and trackers. Registration, breach response, DPIA, lawful basis, rights, transfers "
           "and training wait for your answers, and the consent-banner checks need a browser test that a later release "
           "adds, so they show as awaiting input or upcoming checks rather than not assessed.")

STATUS_LABELS = {"present": "Evidence present", "gap": "Gap", "not_assessed": "Not assessed",
                 "not_applicable": "Not applicable", "awaiting_input": "Awaiting your input"}
UPCOMING_CHECK_LABEL = "Upcoming check"
SOURCE_LABELS = {"tool_observed": "Tool observed", "externally_observed": "Externally observed",
                 "customer_attested": "Customer attested", "practitioner_reviewed": "Practitioner reviewed"}
REASON_TEXT = {
    "checks_conclusive": "Every requested check finished for this domain.",
    "open_findings": "Open findings linked to this requirement.",
    "unlinked_finding": "An open finding linked to this requirement could not be tied to a domain.",
    "no_assessment": "No scan with recorded coverage has finished for this domain yet.",
    "no_verified_domain": "No verified domain yet.",
    "evidence_expired": "The last evidence is older than this requirement's freshness window.",
    "findings_resolved_awaiting_rescan": "The findings behind the last gap were resolved; the next scan will re-check.",
    "legacy_coverage": "The last scan did not record which checks finished.",
    "no_coverage": "The last scan recorded no coverage.",
    "checks_missing": "Some checks did not finish for this domain.",
    "checks_omitted": "These checks did not apply to any host on this domain, so nothing was observed.",
    "clean_result_not_provable": "Template runs report matches only; a clean result is never shown as evidence.",
    "complete_scans_in_window": "Complete scans within the window.",
    "no_complete_scan_in_window": "No scan in the window finished every declared check.",
    "awaiting_customer_input": "Cyphward has no source for this yet. You will be able to answer it in a later release.",
    "check_not_available_yet": "The check that observes this arrives in a later release.",
    "page_found": "Found by Cyphward's static check of your website.",
    "linked_off_domain": "Your website links to a policy hosted elsewhere; Cyphward recorded the link but did not fetch it.",
    "not_found_by_static_check": "Not found by Cyphward's static check: no link, and the common addresses returned "
                                 "'not found'. Pages built by JavaScript may not be seen.",
    "site_serves_every_path": "Your website answers every address with the same page, so the static check cannot "
                              "tell whether a policy exists. Link it from your footer to be found.",
    "apex_not_checked": "Your main website could not be checked statically this time.",
    "not_found_inconclusive": "Not found, but the static check could not try every common address.",
    "privacy_check_failed": "The static privacy check could not fetch your website this time.",
    "blocked_by_bot_protection": "Your website's bot protection blocked Cyphward's static check, so its privacy pages "
                                 "could not be read. Allowlist the Cyphward scanner (see cyphward.com/scanner) to let "
                                 "this check run.",
    "no_privacy_observation": "No static privacy check has run for this domain yet.",
    "tracker_before_consent": "A known tracker was observed before any consent: see the vendors listed.",
    "needs_browser_test": "No tracker was observed in the first response, but only a browser test can show that "
                          "nothing loads before consent.",
    "dpo_contact_in_policy": "A DPO contact appears in your published privacy policy (heuristic).",
    "dpo_contact_not_found_in_policy": "No DPO contact was found in your published privacy policy.",
}


def _plan(org: Dict[str, Any]) -> str:
    sub = execute_one("SELECT * FROM subscriptions WHERE org_id = %s", (org["id"],))
    return resolve_plan(org, sub)["plan"]


def _context(org_id: str) -> Dict[str, Any]:
    domains = execute_query(
        "SELECT id, domain FROM domains WHERE org_id = %s AND verification_status = 'verified' "
        "AND revoked_at IS NULL ORDER BY domain", (org_id,)) or []
    domain_ids = [str(d["id"]) for d in domains]
    rows: List[Dict[str, Any]] = []
    if domain_ids:
        rows = execute_query(
            "SELECT DISTINCT ON (requirement_key, domain_id) id, requirement_key, domain_id, status, source, "
            "observed_at, expires_at, scan_id, finding_ids, details, register_version "
            "FROM compliance_evidence WHERE org_id = %s AND domain_id = ANY(%s::uuid[]) "
            "ORDER BY requirement_key, domain_id, observed_at DESC, created_at DESC",
            (org_id, domain_ids)) or []
    latest: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        latest.setdefault(row["requirement_key"], {})[str(row["domain_id"])] = row
    live = execute_query(
        "SELECT f.id, f.title, f.category, f.evidence, f.status, f.severity, a.domain_id "
        "FROM findings f LEFT JOIN assets a ON a.id = f.asset_id AND a.org_id = f.org_id "
        "WHERE f.org_id = %s AND f.status != 'resolved'", (org_id,)) or []
    history = execute_query(
        "SELECT s.id AS scan_id, s.domain_id, s.completed_at, ss.assessment_coverage->>'state' AS state "
        "FROM scans s JOIN score_snapshots ss ON ss.scan_id = s.id AND ss.org_id = s.org_id "
        "WHERE s.org_id = %s AND s.status = 'completed' AND s.completed_at > now() - make_interval(days => %s) "
        "AND ss.assessment_coverage->>'version' = '2'",
        (org_id, HISTORY_DAYS)) or []
    return {"domains": domains, "latest": latest, "live": live, "history": history}


def _findings(org_id: str, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not ids:
        return {}
    rows = execute_query("SELECT id, title, severity, status FROM findings WHERE org_id = %s AND id = ANY(%s::uuid[])",
                         (org_id, sorted(set(ids)))) or []
    return {str(r["id"]): {"id": str(r["id"]), "title": r["title"], "severity": r["severity"], "status": r["status"]}
            for r in rows}


def _requirement_view(req: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    result = mapping.requirement_status(req, domains=ctx["domains"], latest_rows=ctx["latest"].get(req["key"], {}),
                                        live_findings=ctx["live"], history=ctx["history"])
    domains = [{**d, "status_label": STATUS_LABELS[d["status"]], "reason_text": REASON_TEXT.get(d["reason"], ""),
                "source_label": SOURCE_LABELS.get(d["source"]) if d.get("source") else None}
               for d in result["domains"]]
    has_evidence = any(d.get("source") for d in domains) or bool(result["unlinked_finding_ids"])
    source = next((d["source"] for d in domains if d.get("source")), mapping.TOOL_SOURCE)
    return {
        "key": req["key"], "group": req["group"], "title": req["title"], "summary": req["summary"],
        "clause": req["clause"], "clause_verified": req["clause_verified"],
        "clause_label": req["clause"] if req["clause_verified"] else f"{req['clause']} · reference pending review",
        "applies_to": req["applies_to"], "evidence_types": req["evidence_types"],
        "evidence_type_labels": [SOURCE_LABELS[e] for e in req["evidence_types"]],
        "checks_performed": req.get("checks_performed"), "not_checked": req.get("not_checked"),
        "freshness_days": req["freshness_days"], "remediation_hint": req["remediation_hint"],
        "status": result["status"],
        "status_label": (UPCOMING_CHECK_LABEL if result["reason"] == "check_not_available_yet"
                         else STATUS_LABELS[result["status"]]),
        "reason": result["reason"], "reason_text": REASON_TEXT.get(result["reason"], ""),
        "source": source if has_evidence else None,
        "source_label": SOURCE_LABELS[source] if has_evidence else None,
        "domains": domains, "unlinked_finding_ids": result["unlinked_finding_ids"],
    }


def _attach_findings(org_id: str, views: List[Dict[str, Any]]) -> None:
    ids = [i for v in views for d in v["domains"] for i in d["finding_ids"] + d["details"].get("informational_finding_ids", [])]
    ids += [i for v in views for i in v["unlinked_finding_ids"]]
    found = _findings(org_id, ids)
    for view in views:
        gap_ids = [i for d in view["domains"] for i in d["finding_ids"]] + view["unlinked_finding_ids"]
        info_ids = [i for d in view["domains"] for i in d["details"].get("informational_finding_ids", [])]
        view["findings"] = [found[i] for i in dict.fromkeys(gap_ids) if i in found]
        view["informational_findings"] = [found[i] for i in dict.fromkeys(info_ids) if i in found]


# Heuristic policy mentions shown on the attested requirements they relate to.
# Informational only: they never change those requirements' status.
POLICY_MENTIONS = {"lawful_basis": "ndpa.s25.lawful_basis_documented",
                   "data_subject_rights": "ndpa.part6.rights_process"}


def _attach_policy_mentions(views: List[Dict[str, Any]]) -> None:
    policy = next((v for v in views if v["key"] == "gaid.notice.privacy_policy"), None)
    if not policy:
        return
    for view in views:
        view.setdefault("policy_mentions", [])
    by_key = {v["key"]: v for v in views}
    for domain in policy["domains"]:
        signals = (domain.get("details") or {}).get("policy_signals") or {}
        for signal, key in POLICY_MENTIONS.items():
            state = (signals.get(signal) or {}).get("state")
            if state and key in by_key:
                by_key[key]["policy_mentions"].append({"domain": domain["domain"], "state": state,
                                                       "url": domain["details"].get("url")})


def overview(org: Dict[str, Any]) -> Dict[str, Any]:
    org_id = str(org["id"])
    plan = _plan(org)
    ctx = _context(org_id)
    views = [_requirement_view(req, ctx) for req in REGISTER["requirements"]]
    _attach_findings(org_id, views)
    _attach_policy_mentions(views)
    groups = []
    for group in REGISTER["groups"]:
        items = [v for v in views if v["group"] == group["key"]]
        locked = plan == "starter" and group["key"] not in OPEN_GROUPS_ON_STARTER
        groups.append({
            "key": group["key"], "title": group["title"], "locked": locked,
            "counts": mapping.readiness(v["status"] for v in items),
            "requirements": [] if locked else items,
            "requirement_count": len(items),
        })
    return {
        "disclaimer": DISCLAIMER,
        "note": C1_NOTE,
        "register": {"version": REGISTER["version"], "title": REGISTER["title"],
                     "references_pending_review": sum(1 for r in REGISTER["requirements"] if not r["clause_verified"])},
        "plan": plan,
        "readiness": mapping.readiness(v["status"] for v in views),
        "domains": [{"id": str(d["id"]), "domain": d["domain"]} for d in ctx["domains"]],
        "groups": groups,
    }


def requirement_detail(org: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    req = register_requirement(key)
    if req is None:
        return None
    org_id = str(org["id"])
    if _plan(org) == "starter" and req["group"] not in OPEN_GROUPS_ON_STARTER:
        return {"locked": True, "key": key, "group": req["group"], "title": req["title"], "disclaimer": DISCLAIMER}
    ctx = _context(org_id)
    view = _requirement_view(req, ctx)
    _attach_findings(org_id, [view])
    history = execute_query(
        "SELECT e.id, e.domain_id, d.domain, e.status, e.source, e.observed_at, e.expires_at, e.scan_id, "
        "e.finding_ids, e.register_version, e.details->>'reason' AS reason "
        "FROM compliance_evidence e LEFT JOIN domains d ON d.id = e.domain_id AND d.org_id = e.org_id "
        "WHERE e.org_id = %s AND e.requirement_key = %s ORDER BY e.observed_at DESC, e.created_at DESC LIMIT 50",
        (org_id, key)) or []
    view["history"] = [{
        **{k: (str(v) if k in ("id", "domain_id", "scan_id") and v else v) for k, v in row.items() if k != "finding_ids"},
        "finding_ids": [str(i) for i in row.get("finding_ids") or []],
        "status_label": STATUS_LABELS.get(row["status"], row["status"]),
        "source_label": SOURCE_LABELS.get(row["source"], row["source"]),
        "reason_text": REASON_TEXT.get(row.get("reason") or "", ""),
    } for row in history]
    view["locked"] = False
    view["disclaimer"] = DISCLAIMER
    return view
