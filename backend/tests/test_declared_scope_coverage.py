"""Declared-scope coverage (cyphward-checks-v1, coverage version 2) and the organisation grade gate."""
import copy
import json

from backend.app.risk.coverage import assessment_coverage, coverage_state
from backend.app.risk.engine import SCORE_MODEL, compute_risk_score

DOMAIN = "example.com"
WWW = "www.example.com"
CHECKED = {DOMAIN, WWW}
NOW = "2026-10-15T00:00:00Z"


def outcome(host, record_type, status="answered"):
    if record_type == "DMARC":
        name, rtype = f"_dmarc.{host}", "TXT"
    else:
        name, rtype = host, record_type
    return {"status": status, "name": name, "record_type": rtype}


def dns_record(host, ip="203.0.113.10", *, a="answered", aaaa="answered", txt="answered", dmarc="answered"):
    queries = {
        "A": outcome(host, "A", a),
        "AAAA": outcome(host, "AAAA", aaaa),
        "TXT": outcome(host, "TXT", txt),
        "DMARC": outcome(host, "DMARC", dmarc),
    }
    return {"hostname": host, "primary_ip": ip, "records": {"query_coverage": {"version": 1, "queries": queries}}}


def probe(host, status=200, error=None, cert=True):
    tls = {"issuer": "CN=Example CA", "valid_to": "2027-01-01T00:00:00Z"} if cert else {}
    return {"hostname": host, "http_status": status, "error": error, "tls_info": tls}


def failed_probe(host):
    return probe(host, status=None, error="connection refused", cert=False)


def clean_observations():
    hosts = [DOMAIN, WWW]
    return {
        "discovery": {"target_selection": {
            "version": 1,
            "policy": "apex_registered_passive",
            "requested_hosts": [DOMAIN, WWW],
            "selected_hosts": [DOMAIN, WWW],
            "omitted_hosts": {},
            "limits": {"max_hosts": 25, "dns_max_hosts": 25},
        }},
        "dns": {"dns_records": [dns_record(DOMAIN), dns_record(WWW)]},
        "http": {"http_probes": [probe(DOMAIN), probe(WWW)], "omitted_hosts": {}},
        "ports": {
            "open_ports": [{"hostname": host, "port": port} for host in hosts for port in (80, 443)],
            "attempted_hosts": hosts,
            "successful_hosts": hosts,
            "failed_hosts": {},
            "omitted_hosts": {},
        },
        "nuclei": {"attempted_hosts": hosts, "successful_hosts": hosts, "nuclei_findings": []},
    }


def coverage(observations, checked=CHECKED, registered=()):
    return assessment_coverage(DOMAIN, observations, checked, registered)


def completed(cov, domains=None):
    assessment = {"scan_id": "s1", "status": "completed", "completed_at": NOW, "model": SCORE_MODEL, "coverage": cov}
    if domains is not None:
        assessment["domains"] = domains
    return assessment


def missing_map(cov):
    return {(item["hostname"], item["check"]): item["reason"] for item in cov["missing"]}


def omitted_map(cov):
    return {(item["hostname"], item["check"]): item["reason"] for item in cov["omitted_checks"]}


def evaluated_set(cov):
    return {(item["hostname"], item["check"]) for item in cov["evaluated_groups"]}


def test_clean_domain_is_complete_and_graded():
    cov = coverage(clean_observations())
    assert cov["state"] == "complete"
    assert cov["requested_checks"] == 8
    assert cov["evaluated_checks"] == 8
    assert cov["missing"] == []

    result = compute_risk_score([], assessment=completed(cov, [{"domain": DOMAIN, "state": "complete"}]))
    assert result["score"] == 100.0
    assert result["grade"] == "A"
    assert result["scope_label"] == "Within declared scope"
    positive = [factor["label"] for factor in result["factors"] if factor["type"] == "positive"]
    assert positive == ["No scored open findings within declared scope."]


def test_failed_dmarc_query_is_partial_and_not_a_clean_score():
    observations = clean_observations()
    observations["dns"]["dns_records"][0] = dns_record(DOMAIN, dmarc="failed")
    cov = coverage(observations)
    assert cov["state"] == "partial"
    assert {"hostname": DOMAIN, "check": "dns.dmarc", "reason": "dns_query_failed"} in cov["missing"]

    clean = compute_risk_score([], assessment=completed(cov))
    assert clean["score"] is None
    assert clean["grade"] is None

    known = compute_risk_score([{"title": "Known", "severity": "high", "status": "open"}], assessment=completed(cov))
    assert known["score"] == 83.3
    assert known["grade"] is None
    assert known["scope_label"] is None


def test_legacy_without_target_selection_is_never_complete():
    observations = clean_observations()
    del observations["discovery"]
    cov = coverage(observations)
    assert cov["requested_checks"] is None
    assert cov["state"] == "partial"
    assert cov["evaluated_checks"] > 0
    assert cov["missing"] == []
    assert coverage_state(completed(cov, [{"domain": DOMAIN, "state": "complete"}])) == "partial"


def test_legacy_without_evaluated_evidence_is_unassessed_not_complete():
    observations = clean_observations()
    del observations["discovery"]
    cov = coverage(observations, checked=set())
    assert cov["requested_checks"] is None
    assert cov["state"] == "unassessed"
    assert cov["evaluated_checks"] == 0
    assert coverage_state(completed(cov)) == "unassessed"


def test_legacy_with_nothing_recorded_is_unknown():
    cov = coverage({}, checked=set())
    assert cov["state"] == "unknown"
    assert coverage_state(completed(cov)) == "unknown"


def test_stored_version_one_coverage_keeps_its_old_result():
    assert coverage_state({"coverage": {"version": 1, "state": "complete", "evaluated_checks": 4}}) == "complete"
    assert coverage_state({"coverage": {"version": 1, "state": "partial", "evaluated_checks": 2}}) == "partial"
    assert coverage_state({"coverage": {"version": 1, "state": "unassessed", "evaluated_checks": 0}}) == "unassessed"
    assert coverage_state({"coverage": {"version": 1, "state": "complete", "evaluated_checks": 0}}) == "unknown"


def test_nuclei_no_match_and_absent_nuclei_both_stay_complete():
    no_match = coverage(clean_observations())
    assert no_match["state"] == "complete"
    assert no_match["nuclei"]["state"] == "matches_only"
    assert no_match["nuclei"]["matches"] == 0

    observations = clean_observations()
    del observations["nuclei"]
    absent = coverage(observations)
    assert absent["state"] == "complete"
    assert absent["nuclei"]["state"] == "not_run"

    observations = clean_observations()
    observations["nuclei"]["nuclei_findings"] = [
        {"_hostname": WWW, "evidence": {"template_id": "exposed-panel", "host": WWW}},
    ]
    matched = coverage(observations)
    assert matched["state"] == "complete"
    assert matched["evaluated_checks"] == 9
    assert matched["nuclei"]["matches"] == 1


def test_host_without_public_address_is_omitted_not_missing():
    observations = clean_observations()
    observations["dns"]["dns_records"][1] = dns_record(WWW, ip=None, a="no_data", aaaa="no_data")
    cov = coverage(observations)
    assert cov["targets"]["omitted"][WWW] == "no_public_dns_address"
    assert WWW not in {item["hostname"] for item in cov["missing"]}
    assert cov["targets"]["in_scope"] == 1
    assert cov["requested_checks"] == 5
    assert cov["state"] == "complete"


def test_neither_web_port_open_omits_web_checks_when_ports_are_conclusive():
    observations = clean_observations()
    observations["ports"]["open_ports"] = []
    observations["http"]["http_probes"] = [failed_probe(DOMAIN), failed_probe(WWW)]
    cov = coverage(observations)
    omitted = omitted_map(cov)
    for host in (DOMAIN, WWW):
        assert omitted[(host, "http.headers")] == "no_web_service"
        assert omitted[(host, "tls.certificate")] == "no_web_service"
    assert cov["state"] == "complete"


def test_only_port_80_open_omits_tls_but_still_requires_http_headers():
    observations = clean_observations()
    observations["ports"]["open_ports"] = [{"hostname": host, "port": 80} for host in (DOMAIN, WWW)]
    observations["http"]["http_probes"] = [probe(DOMAIN, cert=False), probe(WWW, cert=False)]
    cov = coverage(observations)
    assert omitted_map(cov)[(DOMAIN, "tls.certificate")] == "no_https"
    assert (DOMAIN, "http.headers") in evaluated_set(cov)
    assert cov["state"] == "complete"


def test_only_port_80_open_with_http_error_keeps_http_headers_missing():
    observations = clean_observations()
    observations["ports"]["open_ports"] = [{"hostname": host, "port": 80} for host in (DOMAIN, WWW)]
    observations["http"]["http_probes"] = [failed_probe(DOMAIN), failed_probe(WWW)]
    cov = coverage(observations)
    assert missing_map(cov)[(DOMAIN, "http.headers")] == "no_usable_http_response"
    assert cov["state"] == "partial"


def test_both_web_ports_open_without_usable_response_stays_missing():
    observations = clean_observations()
    observations["http"]["http_probes"] = [failed_probe(DOMAIN), failed_probe(WWW)]
    cov = coverage(observations)
    missing = missing_map(cov)
    assert missing[(DOMAIN, "http.headers")] == "no_usable_http_response"
    assert missing[(DOMAIN, "tls.certificate")] == "certificate_not_observed"
    assert cov["state"] == "partial"


def test_observed_certificate_wins_over_closed_443():
    observations = clean_observations()
    observations["ports"]["open_ports"] = [{"hostname": DOMAIN, "port": 80}, {"hostname": WWW, "port": 80},
                                           {"hostname": WWW, "port": 443}]
    cov = coverage(observations)
    assert (DOMAIN, "tls.certificate") in evaluated_set(cov)
    assert (DOMAIN, "tls.certificate") not in omitted_map(cov)
    assert cov["state"] == "complete"


def test_unknown_address_requests_three_host_checks_as_missing():
    observations = clean_observations()
    observations["dns"]["dns_records"][1] = dns_record(WWW, ip=None, a="failed")
    cov = coverage(observations)
    missing = missing_map(cov)
    for check in ("ports.inventory", "http.headers", "tls.certificate"):
        assert missing[(WWW, check)] == "dns_address_unknown"
    assert cov["state"] == "partial"


def test_registered_host_omitted_by_selection_cap_blocks_complete():
    observations = clean_observations()
    observations["discovery"]["target_selection"]["omitted_hosts"] = {"api.example.com": "dns_max_hosts"}
    cov = coverage(observations, registered=("api.example.com",))
    assert {"hostname": "api.example.com", "check": "target.selection", "reason": "dns_max_hosts"} in cov["missing"]
    assert cov["state"] == "partial"


def test_passive_host_omitted_by_selection_cap_is_reported_without_blocking():
    observations = clean_observations()
    observations["discovery"]["target_selection"]["omitted_hosts"] = {"old.example.com": "dns_max_hosts"}
    cov = coverage(observations)
    assert cov["targets"]["omitted"]["old.example.com"] == "dns_max_hosts"
    assert cov["state"] == "complete"


def test_ports_omitted_by_unavailable_tool_is_missing_inventory():
    observations = clean_observations()
    observations["ports"]["successful_hosts"] = [DOMAIN]
    observations["ports"]["omitted_hosts"] = {WWW: "tool_unavailable"}
    cov = coverage(observations)
    assert missing_map(cov)[(WWW, "ports.inventory")] == "tool_unavailable"
    assert cov["state"] == "partial"


def test_checker_not_completed_for_www_fails_its_host_checks():
    cov = coverage(clean_observations(), checked={DOMAIN})
    missing = missing_map(cov)
    assert missing[(WWW, "http.headers")] == "security_checks_failed"
    assert missing[(WWW, "tls.certificate")] == "security_checks_failed"
    assert cov["state"] == "partial"


def test_apex_only_without_public_address_is_partial_no_public_hosts():
    observations = clean_observations()
    observations["discovery"]["target_selection"]["selected_hosts"] = [DOMAIN]
    observations["discovery"]["target_selection"]["requested_hosts"] = [DOMAIN]
    observations["dns"]["dns_records"] = [dns_record(DOMAIN, ip=None, a="no_data", aaaa="no_data")]
    cov = coverage(observations)
    assert cov["state"] == "partial"
    assert cov["reason"] == "no_public_hosts"
    assert cov["targets"]["in_scope"] == 0
    assert cov["targets"]["omitted"] == {DOMAIN: "no_public_dns_address"}
    assert cov["missing"] == []


def test_unscanned_verified_domain_blocks_grade_but_keeps_known_risk():
    cov = coverage(clean_observations())
    domains = [{"domain": DOMAIN, "state": "complete"}, {"domain": "other.ng", "state": "not_scanned"}]
    finding = {"title": "Known issue", "severity": "medium", "status": "open"}
    result = compute_risk_score([finding], assessment=completed(cov, domains))
    assert result["score"] == 95.2
    assert result["grade"] is None
    assert result["posture_label"] == "Not all domains assessed"
    assert result["scope_label"] is None
    assert result["domain_coverage_line"] == "example.com: complete · other.ng: not scanned"
    assert compute_risk_score([], assessment=completed(cov, domains))["score"] is None


def test_complete_coverage_without_domains_is_never_graded():
    cov = coverage(clean_observations())
    finding = {"title": "Known issue", "severity": "low", "status": "open"}
    result = compute_risk_score([finding], assessment=completed(cov))
    assert result["grade"] is None
    assert result["scope_label"] is None
    assert result["posture_label"] == "Not all domains assessed"
    assert result["domain_coverage"] == []
    assert result["domain_coverage_line"] == ""
    assert compute_risk_score([], assessment=completed(cov))["score"] is None


def test_forged_complete_payload_with_missing_entries_is_not_complete():
    cov = coverage(clean_observations())
    entry = {"hostname": WWW, "check": "tls.certificate", "reason": "certificate_not_observed"}
    assert coverage_state(completed({**cov, "state": "complete", "missing": [entry]})) == "partial"
    assert coverage_state(completed({**cov, "state": "complete", "requested_checks": None})) == "partial"
    assert coverage_state(completed({**cov, "state": "complete", "evaluated_checks": 0})) == "unknown"
    assert coverage_state(completed({**cov, "state": "complete", "missing": [entry]})) != "complete"


def reversed_order(value):
    if isinstance(value, dict):
        return {key: reversed_order(item) for key, item in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reversed_order(item) for item in reversed(value)]
    return value


def test_identical_inputs_in_any_order_produce_identical_payload():
    observations = clean_observations()
    observations["http"]["http_probes"] = [probe(DOMAIN), probe(WWW), failed_probe(WWW)]
    shuffled = reversed_order(copy.deepcopy(observations))
    first = coverage(observations, registered=(WWW, "api.example.com"))
    second = assessment_coverage(DOMAIN, shuffled, set(reversed(sorted(CHECKED))),
                                 ("api.example.com", WWW))
    assert first == second
    assert json.dumps(first) == json.dumps(second)
    assert [item["check"] for item in first["missing"]] == ["target.selection"]


def test_registered_host_is_compared_in_canonical_form():
    # Selection stores canonical names; a registered "WWW.Example.com." is the selected www host.
    cov = coverage(clean_observations(), registered=["WWW.Example.com."])
    assert cov["state"] == "complete"
    assert (WWW, "target.selection") not in missing_map(cov)


def test_missing_certificate_reason_ignores_the_sslyze_stage():
    observations = clean_observations()
    observations["http"]["http_probes"] = [probe(DOMAIN), probe(WWW, cert=False)]
    observations["tls"] = {"omitted_hosts": {WWW: "tool_unavailable"}}
    cov = coverage(observations)
    assert cov["state"] == "partial"
    assert missing_map(cov)[(WWW, "tls.certificate")] == "certificate_not_observed"


def test_third_party_handoff_omits_web_checks_and_can_still_complete():
    observations = clean_observations()
    handoff = probe(WWW, status=302, error="redirect blocked: img.mailin.fr out of scope", cert=False)
    handoff["third_party_redirect"] = "img.mailin.fr"
    observations["http"]["http_probes"] = [probe(DOMAIN), handoff]
    observations["http"]["omitted_hosts"] = {WWW: "third_party_service"}
    cov = coverage(observations)
    omitted = omitted_map(cov)
    assert omitted[(WWW, "http.headers")] == "third_party_service"
    assert omitted[(WWW, "tls.certificate")] == "third_party_service"
    assert (WWW, "http.headers") not in missing_map(cov)
    assert cov["state"] == "complete"


def test_third_party_handoff_keeps_a_directly_observed_certificate():
    observations = clean_observations()
    handoff = probe(WWW, status=302, error="redirect blocked: img.mailin.fr out of scope", cert=True)
    observations["http"]["http_probes"] = [probe(DOMAIN), handoff]
    observations["http"]["omitted_hosts"] = {WWW: "third_party_service"}
    cov = coverage(observations)
    assert (WWW, "tls.certificate") in evaluated_set(cov)
    assert omitted_map(cov)[(WWW, "http.headers")] == "third_party_service"


def test_other_http_omissions_still_count_as_missing():
    observations = clean_observations()
    observations["http"]["http_probes"] = [probe(DOMAIN), failed_probe(WWW)]
    observations["http"]["omitted_hosts"] = {WWW: "recon_stage_deadline"}
    cov = coverage(observations)
    assert missing_map(cov)[(WWW, "http.headers")] == "recon_stage_deadline"
    assert cov["state"] == "partial"

