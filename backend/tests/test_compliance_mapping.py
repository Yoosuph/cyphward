"""Compliance mapping truth table (C1-plan section 4). Pure functions, no database."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.compliance import mapping as m
from backend.app.compliance.register import requirement

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
ENC = requirement("ndpa.s39.encryption_in_transit")
EMAIL = requirement("ndpa.s39.email_anti_spoofing")
HEADERS = requirement("ndpa.s39.web_security_headers")
PORTS = requirement("ndpa.s39.exposed_services_inventoried")
CVE = requirement("ndpa.s39.known_vulnerability_testing")
PERIODIC = requirement("ndpa.s39.periodic_risk_assessment")
DPO = requirement("gaid.dpo.designated")
D1 = {"id": "11111111-1111-4111-8111-111111111111", "domain": "acme.test"}
D2 = {"id": "22222222-2222-4222-8222-222222222222", "domain": "shop.test"}


def coverage(evaluated=(), missing=(), omitted=(), version=2, requested=5):
    g = lambda items, extra=None: [{"hostname": h, "check": c, **({"reason": r} if r else {})} for h, c, r in items]
    return {"version": version, "check_set": "cyphward-checks-v1", "state": "partial",
            "requested_checks": requested, "evaluated_groups": g([(h, c, None) for h, c in evaluated]),
            "missing": g(missing), "omitted_checks": g(omitted)}


def finding(title, category, fid="f1", status="open", evidence=None, domain_id=None):
    return {"id": fid, "title": title, "category": category, "status": status, "evidence": evidence or {},
            "domain_id": domain_id}


HSTS = ("Strict-Transport-Security (HSTS) Header Missing", "HTTP Headers")
DMARC = ("Missing Email DMARC Authentication Policy", "DNS & Email Security")
ROBOTS = ("Robots.txt Discloses Sensitive Endpoint Paths", "Exposure")
MODERN = ("Modern Cryptographic Protocols Active", "SSL/TLS")
CLEAN_WEB = coverage(evaluated=[("acme.test", "http.headers"), ("acme.test", "tls.certificate")])


# ── Write side: rows 1-6 ───────────────────────────────────────────────────
def test_evaluated_and_clean_is_present():
    r = m.evaluate_domain(ENC, CLEAN_WEB, [])
    assert r["status"] == "present" and r["details"]["evaluated"]


def test_open_issue_finding_is_a_gap_with_its_id():
    r = m.evaluate_domain(ENC, CLEAN_WEB, [finding(*HSTS, fid="hsts-1")])
    assert r["status"] == "gap" and r["finding_ids"] == ["hsts-1"] and r["details"]["rules"] == ["http.hsts.missing"]


@pytest.mark.parametrize("status", ["open", "acknowledged", "in_progress"])
def test_every_unresolved_status_is_still_a_gap(status):
    assert m.evaluate_domain(EMAIL, None, [finding(*DMARC, status=status)])["status"] == "gap"


def test_gap_is_written_even_with_legacy_coverage():
    assert m.evaluate_domain(EMAIL, coverage(version=1, requested=None), [finding(*DMARC)])["status"] == "gap"


def test_resolved_unmapped_and_other_requirement_findings_are_ignored():
    found = [finding(*HSTS, status="resolved"), finding("rls-probe", "Security Configuration"), finding(*DMARC)]
    assert m.evaluate_domain(ENC, CLEAN_WEB, found)["status"] == "present"


def test_informational_finding_is_shown_but_not_a_gap():
    cov = coverage(evaluated=[("acme.test", "http.headers")])
    r = m.evaluate_domain(HEADERS, cov, [finding(*ROBOTS, fid="robots-1")])
    assert r["status"] == "present" and r["details"]["informational_finding_ids"] == ["robots-1"]


def test_positive_finding_never_creates_evidence():
    cov = coverage(missing=[("acme.test", "tls.certificate", "certificate_not_observed")])
    assert m.evaluate_domain(ENC, cov, [finding(*MODERN)])["status"] == "not_assessed"


@pytest.mark.parametrize("cov,reason", [
    (None, "no_coverage"),
    (coverage(version=1, requested=None), "legacy_coverage"),
    (coverage(version=2, requested=None), "legacy_coverage"),
])
def test_missing_or_legacy_coverage_is_not_assessed(cov, reason):
    r = m.evaluate_domain(ENC, cov, [])
    assert (r["status"], r["reason"]) == ("not_assessed", reason)


def test_any_missing_check_is_not_assessed_even_if_others_are_clean():
    cov = coverage(evaluated=[("acme.test", "http.headers")],
                   missing=[("www.acme.test", "tls.certificate", "certificate_not_observed")])
    r = m.evaluate_domain(ENC, cov, [])
    assert r["status"] == "not_assessed" and r["details"]["missing"][0]["reason"] == "certificate_not_observed"


def test_all_checks_omitted_is_not_assessed_never_not_applicable():
    cov = coverage(omitted=[("acme.test", "http.headers", "no_web_service"), ("acme.test", "tls.certificate", "no_web_service")])
    r = m.evaluate_domain(ENC, cov, [])
    assert (r["status"], r["reason"]) == ("not_assessed", "checks_omitted")


def test_nuclei_is_never_present_but_a_match_is_a_gap():
    assert m.evaluate_domain(CVE, CLEAN_WEB, [])["reason"] == "clean_result_not_provable"
    match = finding("Some CVE", "Nuclei Scan", fid="cve-1", evidence={"template_id": "CVE-2024-1"})
    assert m.evaluate_domain(CVE, CLEAN_WEB, [match])["status"] == "gap"


def test_ports_requirement_records_the_open_ports():
    cov = coverage(evaluated=[("acme.test", "ports.inventory")])
    r = m.evaluate_domain(PORTS, cov, [], open_ports={"acme.test": [443, 3389], "other.test": [22]})
    assert r["status"] == "present" and r["details"]["open_ports"] == {"acme.test": [443, 3389]}


def test_domain_rows_cover_each_tool_requirement_with_expiry():
    from backend.app.compliance.register import tool_requirements
    rows = m.domain_rows(tool_requirements(), CLEAN_WEB, [], org_id="o", domain_id=D1["id"], scan_id="s",
                         observed_at=NOW, register_version="ndpa-gaid-v1")
    assert len(rows) == 5 and {r["source"] for r in rows} == {"tool_observed"}
    enc = next(r for r in rows if r["requirement_key"] == ENC["key"])
    assert enc["expires_at"] == NOW + timedelta(days=30) and enc["details"]["reason"] == "checks_conclusive"


# ── Read side ──────────────────────────────────────────────────────────────
def row(status, observed=NOW - timedelta(days=1), days=30, finding_ids=()):
    return {"status": status, "observed_at": observed, "expires_at": observed + timedelta(days=days),
            "scan_id": "s1", "finding_ids": list(finding_ids), "details": {"reason": "checks_conclusive"}}


def status(req, domains=(D1,), latest=None, live=(), history=()):
    return m.requirement_status(req, domains=list(domains), latest_rows=latest or {}, live_findings=list(live),
                                history=list(history), now=NOW)


def test_no_verified_domain_is_not_assessed():
    assert (status(ENC, domains=())["status"], status(ENC, domains=())["reason"]) == ("not_assessed", "no_verified_domain")


def test_domain_without_rows_is_not_assessed():
    assert status(ENC)["domains"][0]["reason"] == "no_assessment"
    assert status(ENC)["domains"][0]["source"] is None, "no source tag without evidence"


def test_current_present_row_is_present():
    assert status(ENC, latest={D1["id"]: row("present")})["status"] == "present"


def test_expired_present_row_is_not_assessed():
    old = row("present", observed=NOW - timedelta(days=40))
    assert status(ENC, latest={D1["id"]: old})["domains"][0]["reason"] == "evidence_expired"


def test_live_open_finding_overrides_a_stored_present_row():
    live = [finding(*HSTS, fid="reopened", domain_id=D1["id"])]
    r = status(ENC, latest={D1["id"]: row("present")}, live=live)
    assert r["status"] == "gap" and r["domains"][0]["finding_ids"] == ["reopened"]


def test_gap_row_whose_findings_were_resolved_waits_for_a_rescan():
    r = status(ENC, latest={D1["id"]: row("gap", finding_ids=["old"])})
    assert (r["status"], r["domains"][0]["reason"]) == ("not_assessed", "findings_resolved_awaiting_rescan")


def test_unlinked_open_finding_makes_the_requirement_a_gap():
    r = status(EMAIL, latest={D1["id"]: row("present")}, live=[finding(*DMARC, fid="loose", domain_id=None)])
    assert (r["status"], r["reason"], r["unlinked_finding_ids"]) == ("gap", "unlinked_finding", ["loose"])


def test_one_unassessed_domain_keeps_the_requirement_not_assessed():
    r = status(ENC, domains=(D1, D2), latest={D1["id"]: row("present")})
    assert r["status"] == "not_assessed"


def test_finding_on_another_domain_only_affects_that_domain():
    r = status(ENC, domains=(D1, D2), latest={D1["id"]: row("present"), D2["id"]: row("present")},
               live=[finding(*HSTS, domain_id=D2["id"])])
    assert [d["status"] for d in r["domains"]] == ["present", "gap"] and r["status"] == "gap"


def test_requirement_without_an_evidence_source_is_not_assessed():
    r = status(DPO, latest={})
    assert (r["status"], r["reason"]) == ("not_assessed", "collection_not_available")


def hist(domain, days_ago, state):
    return {"scan_id": f"s-{domain['domain']}-{days_ago}", "domain_id": domain["id"],
            "completed_at": NOW - timedelta(days=days_ago), "state": state}


def test_scan_history_needs_a_complete_scan_per_domain_in_window():
    assert status(PERIODIC, history=[hist(D1, 10, "complete")])["status"] == "present"
    assert status(PERIODIC, history=[hist(D1, 10, "partial")])["status"] == "not_assessed"
    assert status(PERIODIC, history=[hist(D1, 120, "complete")])["status"] == "not_assessed"
    mixed = status(PERIODIC, domains=(D1, D2), history=[hist(D1, 10, "complete"), hist(D2, 5, "partial")])
    assert mixed["status"] == "not_assessed" and mixed["domains"][1]["details"]["not_counted"][0]["state"] == "partial"


def test_scan_history_is_never_a_gap():
    assert status(PERIODIC, history=[])["status"] == "not_assessed"


def test_readiness_counts_present_only():
    r = m.readiness(["present", "gap", "gap", "not_assessed", "present", "not_applicable"])
    assert r == {"percent": 40, "present": 2, "gap": 2, "not_assessed": 1, "applicable": 5}
    assert m.readiness([])["percent"] == 0
    assert m.readiness(["present", "not_assessed", "not_assessed"])["percent"] == 33  # rounded down
