"""Conservative assessment eligibility from authoritative producing observations.

Only security-check groups with actual evidence count. Inventory/process success
is not a clean security evaluation. Current adapters cannot prove full coverage.
"""
from backend.app.scanner.dns_coverage import query_evaluated


def assessment_coverage(domain, observations, checked_hosts):
    evaluated = set()
    dns_records = (observations.get("dns") or {}).get("dns_records") or []
    for data in dns_records:
        host = data.get("hostname")
        if host == domain and host in checked_hosts:
            for query in ("TXT", "DMARC"):
                if query_evaluated(data, query):
                    evaluated.add((host, f"dns.{query.lower()}"))
    for data in (observations.get("http") or {}).get("http_probes") or []:
        host = data.get("hostname")
        if host not in checked_hosts:
            continue
        if data.get("http_status") is not None and not data.get("error"):
            evaluated.add((host, "http.headers"))
        tls = data.get("tls_info") or {}
        if tls.get("valid_to") or tls.get("issuer"):
            evaluated.add((host, "tls.certificate"))
    for finding in (observations.get("nuclei") or {}).get("nuclei_findings") or []:
        evidence = finding.get("evidence") or {}
        template = evidence.get("template_id")
        host = finding.get("_hostname") or evidence.get("host")
        if host and template:
            evaluated.add((host, f"nuclei.match:{template}"))
    selection = (observations.get("discovery") or {}).get("target_selection") or {}
    has_query_evidence = any(isinstance((data.get("records") or {}).get("query_coverage"), dict)
                             for data in dns_records)
    state = "partial" if evaluated else "unassessed" if selection.get("version") == 1 or has_query_evidence else "unknown"
    return {"version": 1, "state": state, "evaluated_checks": len(evaluated),
            "evaluated_groups": [{"hostname": host, "check": check} for host, check in sorted(evaluated)],
            "requested_checks": None,
            "omitted_targets": len(selection.get("omitted_hosts") or {}) if selection.get("version") == 1 else None,
            "reason": "Template and full assessment coverage are not proven." if evaluated
                      else "No security checks have conclusive evaluation evidence."}


def coverage_state(assessment):
    coverage = (assessment or {}).get("coverage")
    if (not isinstance(coverage, dict) or type(coverage.get("version")) is not int
            or coverage.get("version") != 1):
        return "unknown"
    count = coverage.get("evaluated_checks")
    if type(count) is not int or count < 0:
        return "unknown"
    if coverage.get("state") in ("partial", "complete") and count > 0:
        return coverage["state"]
    return "unassessed" if coverage.get("state") == "unassessed" and count == 0 else "unknown"
