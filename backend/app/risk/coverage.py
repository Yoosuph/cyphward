"""Assessment coverage against the declared check set (version 2).

The rules, reason codes and payload keys are defined in check_set.py. Version 1
payloads stored by earlier workers are still read by coverage_state unchanged.
Only conclusive evidence counts. Inventory or process success alone is not a
clean security evaluation.
"""
from backend.app.risk.check_set import (
    CHECK_SET_VERSION,
    COVERAGE_VERSION,
    DECLARED_CHECKS,
    HOST_CHECKS,
    HTTP_PORT,
    HTTPS_PORT,
    TARGET_SELECTION_CHECK,
    coverage_label,
    nuclei_summary,
)
from backend.app.scanner.dns_coverage import query_evaluated
from shared.scan_scope import canonical_host

APEX_QUERIES = {"dns.spf": "TXT", "dns.dmarc": "DMARC"}
LEGACY_REASON = "Target selection was not recorded."
COMPLETE_REASON = "All declared checks have conclusive evidence."
PARTIAL_REASON = "Some declared checks lack conclusive evidence."
NO_PUBLIC_REASON = "no_public_hosts"


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _strings(value):
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def _group_by_hostname(items):
    grouped = {}
    for data in _list(items):
        if isinstance(data, dict) and isinstance(data.get("hostname"), str):
            grouped.setdefault(data["hostname"], []).append(data)
    return grouped


def _query_observed(records, query):
    for data in records:
        coverage = _dict(data.get("records")).get("query_coverage")
        if (isinstance(coverage, dict) and type(coverage.get("version")) is int
                and coverage.get("version") == 1
                and isinstance(_dict(coverage.get("queries")).get(query), dict)):
            return True
    return False


def _query_evaluated(records, query):
    return any(query_evaluated(data, query) for data in records)


def _http_usable(probe):
    return probe.get("http_status") is not None and not probe.get("error")


def _tls_observed(probe):
    tls = _dict(probe.get("tls_info"))
    return bool(tls.get("valid_to") or tls.get("issuer"))


def _open_ports(ports):
    grouped = {}
    for item in _list(ports.get("open_ports")):
        if not isinstance(item, dict) or not isinstance(item.get("hostname"), str):
            continue
        try:
            grouped.setdefault(item["hostname"], set()).add(int(item.get("port")))
        except (TypeError, ValueError):
            continue
    return grouped


def _nuclei_groups(observations):
    groups = set()
    for finding in _list(_dict(observations.get("nuclei")).get("nuclei_findings")):
        if not isinstance(finding, dict):
            continue
        evidence = _dict(finding.get("evidence"))
        template = evidence.get("template_id")
        host = finding.get("_hostname") or evidence.get("host")
        if host and template:
            groups.add((host, f"nuclei.match:{template}"))
    return groups


def _apex_reason(records, query, domain, checked):
    if not _query_observed(records, query):
        return "dns_not_observed"
    if domain not in checked:
        return "security_checks_failed"
    return "dns_query_failed"


def _http_reason(host, checked, http_omitted, host_probes):
    if host not in checked:
        return "security_checks_failed"
    if http_omitted.get(host):
        return http_omitted[host]
    return "no_usable_http_response" if host_probes else "http_not_observed"


def _tls_reason(host, checked, http_omitted):
    # The certificate comes from the HTTP probe, not the sslyze TLS stage, so
    # only HTTP-stage omissions explain a missing certificate.
    if host not in checked:
        return "security_checks_failed"
    return http_omitted.get(host) or "certificate_not_observed"


def _legacy_coverage(domain, observations, checked, dns_by_host, probes, nuclei_groups):
    """Version 1 semantics for workers that did not record target selection."""
    declared = set()
    if domain in checked:
        records = dns_by_host.get(domain, [])
        for check, query in APEX_QUERIES.items():
            if _query_evaluated(records, query):
                declared.add((domain, check))
    for host, host_probes in probes.items():
        if host not in checked:
            continue
        if any(_http_usable(probe) for probe in host_probes):
            declared.add((host, "http.headers"))
        if any(_tls_observed(probe) for probe in host_probes):
            declared.add((host, "tls.certificate"))
    evaluated = declared | nuclei_groups
    has_query_evidence = any(
        isinstance(_dict(data.get("records")).get("query_coverage"), dict)
        for records in dns_by_host.values() for data in records
    )
    state = "partial" if evaluated else "unassessed" if has_query_evidence else "unknown"
    return {
        "version": COVERAGE_VERSION,
        "check_set": CHECK_SET_VERSION,
        "domain": domain,
        "state": state,
        "requested_checks": None,
        "evaluated_checks": len(evaluated),
        "evaluated_groups": [{"hostname": host, "check": check} for host, check in sorted(evaluated)],
        "missing": [],
        "omitted_checks": [],
        "families": {
            check: {"requested": None,
                    "evaluated": sum(1 for _, name in declared if name == check),
                    "omitted": None}
            for check in DECLARED_CHECKS
        },
        "targets": {"selected": None, "in_scope": 0, "assessed": 0, "omitted": {}},
        "nuclei": nuclei_summary(observations.get("nuclei")),
        "label": coverage_label(domain, state, len(declared), None, 0),
        "reason": LEGACY_REASON,
    }


def assessment_coverage(domain, observations, checked_hosts, registered_hosts=()):
    observations = _dict(observations)
    checked = {host for host in (checked_hosts or ()) if isinstance(host, str)}
    selection = _dict(_dict(observations.get("discovery")).get("target_selection"))
    dns_by_host = _group_by_hostname(_dict(observations.get("dns")).get("dns_records"))
    probes = _group_by_hostname(_dict(observations.get("http")).get("http_probes"))
    nuclei_groups = _nuclei_groups(observations)
    if type(selection.get("version")) is not int or selection.get("version") != 1:
        return _legacy_coverage(domain, observations, checked, dns_by_host, probes, nuclei_groups)

    ports = _dict(observations.get("ports"))
    ports_successful = set(_strings(ports.get("successful_hosts")))
    ports_failed = _dict(ports.get("failed_hosts"))
    ports_omitted = _dict(ports.get("omitted_hosts"))
    open_ports = _open_ports(ports)
    http_omitted = _dict(_dict(observations.get("http")).get("omitted_hosts"))
    selected_raw = _list(selection.get("selected_hosts"))
    selected = set(_strings(selected_raw))
    selection_omitted = _dict(selection.get("omitted_hosts"))
    targets_omitted = dict(selection_omitted)

    outcomes = {}  # (host, check) -> ("evaluated" | "missing" | "omitted", reason or None)
    apex_records = dns_by_host.get(domain, [])
    for check, query in APEX_QUERIES.items():
        if domain in checked and _query_evaluated(apex_records, query):
            outcomes[(domain, check)] = ("evaluated", None)
        else:
            outcomes[(domain, check)] = ("missing", _apex_reason(apex_records, query, domain, checked))

    in_scope = []
    for host in sorted(selected):
        records = dns_by_host.get(host, [])
        if not any(data.get("primary_ip") for data in records):
            if _query_evaluated(records, "A") and _query_evaluated(records, "AAAA"):
                targets_omitted[host] = "no_public_dns_address"
            else:
                for check in HOST_CHECKS:
                    outcomes[(host, check)] = ("missing", "dns_address_unknown")
            continue

        in_scope.append(host)
        host_probes = probes.get(host, [])
        host_checked = host in checked
        http_direct = host_checked and any(_http_usable(probe) for probe in host_probes)
        tls_direct = host_checked and any(_tls_observed(probe) for probe in host_probes)
        ports_ok = host in ports_successful and host not in ports_failed
        open_here = open_ports.get(host, set())
        http_open = HTTP_PORT in open_here
        https_open = HTTPS_PORT in open_here

        if ports_ok:
            outcomes[(host, "ports.inventory")] = ("evaluated", None)
        else:
            reason = ports_omitted.get(host) or ("port_scan_failed" if host in ports_failed else "ports_not_observed")
            outcomes[(host, "ports.inventory")] = ("missing", reason)

        if http_direct:
            outcomes[(host, "http.headers")] = ("evaluated", None)
        elif ports_ok and not http_open and not https_open:
            outcomes[(host, "http.headers")] = ("omitted", "no_web_service")
        else:
            outcomes[(host, "http.headers")] = ("missing", _http_reason(host, checked, http_omitted, host_probes))

        if tls_direct:
            outcomes[(host, "tls.certificate")] = ("evaluated", None)
        elif ports_ok and not https_open:
            outcomes[(host, "tls.certificate")] = ("omitted", "no_web_service" if not http_open else "no_https")
        else:
            outcomes[(host, "tls.certificate")] = ("missing", _tls_reason(host, checked, http_omitted))

    # Selection stores canonical names; compare registered hosts the same way.
    for raw in _strings(registered_hosts):
        host = canonical_host(raw) or raw
        if host not in selected:
            reason = selection_omitted.get(host) or selection_omitted.get(raw) or "not_selected"
            outcomes[(host, TARGET_SELECTION_CHECK)] = ("missing", reason)

    evaluated_declared = {key for key, (status, _) in outcomes.items() if status == "evaluated"}
    evaluated_groups = evaluated_declared | nuclei_groups
    missing = sorted(
        ({"hostname": host, "check": check, "reason": reason}
         for (host, check), (status, reason) in outcomes.items() if status == "missing"),
        key=lambda item: (item["hostname"], item["check"]),
    )
    omitted_checks = sorted(
        ({"hostname": host, "check": check, "reason": reason}
         for (host, check), (status, reason) in outcomes.items() if status == "omitted"),
        key=lambda item: (item["hostname"], item["check"]),
    )
    requested = sum(1 for status, _ in outcomes.values() if status != "omitted")
    families = {}
    for check in DECLARED_CHECKS:
        statuses = [status for (_, name), (status, _) in outcomes.items() if name == check]
        families[check] = {
            "requested": sum(1 for status in statuses if status != "omitted"),
            "evaluated": statuses.count("evaluated"),
            "omitted": statuses.count("omitted"),
        }

    host_missing = {host for (host, check), (status, _) in outcomes.items()
                    if status == "missing" and check in HOST_CHECKS}
    assessed = sum(1 for host in in_scope if host not in host_missing)
    if not missing and in_scope:
        state = "complete"
    else:
        state = "partial" if evaluated_groups else "unassessed"

    if state == "complete":
        reason = COMPLETE_REASON
    elif not in_scope and not missing:
        reason = NO_PUBLIC_REASON
    else:
        reason = PARTIAL_REASON

    return {
        "version": COVERAGE_VERSION,
        "check_set": CHECK_SET_VERSION,
        "domain": domain,
        "state": state,
        "requested_checks": requested,
        "evaluated_checks": len(evaluated_groups),
        "evaluated_groups": [{"hostname": host, "check": check} for host, check in sorted(evaluated_groups)],
        "missing": missing,
        "omitted_checks": omitted_checks,
        "families": families,
        "targets": {
            "selected": len(selected_raw),
            "in_scope": len(in_scope),
            "assessed": assessed,
            "omitted": {key: targets_omitted[key] for key in sorted(targets_omitted, key=str)},
        },
        "nuclei": nuclei_summary(observations.get("nuclei")),
        "label": coverage_label(domain, state, len(evaluated_declared), requested, len(in_scope)),
        "reason": reason,
    }


def _coverage_state_v1(coverage):
    count = coverage.get("evaluated_checks")
    if type(count) is not int or count < 0:
        return "unknown"
    if coverage.get("state") in ("partial", "complete") and count > 0:
        return coverage["state"]
    return "unassessed" if coverage.get("state") == "unassessed" and count == 0 else "unknown"


def _coverage_state_v2(coverage):
    if coverage.get("check_set") != CHECK_SET_VERSION:
        return "unknown"
    count = coverage.get("evaluated_checks")
    if type(count) is not int or count < 0:
        return "unknown"
    state = coverage.get("state")
    if state == "complete":
        missing = coverage.get("missing")
        requested = coverage.get("requested_checks")
        if (count > 0 and isinstance(missing, list) and not missing
                and type(requested) is int and requested > 0):
            return "complete"
        return "partial" if count > 0 else "unknown"
    if state == "partial" and count > 0:
        return "partial"
    if state == "unassessed" and count == 0:
        return "unassessed"
    return "unknown"


def coverage_state(assessment):
    coverage = (assessment or {}).get("coverage")
    if not isinstance(coverage, dict) or type(coverage.get("version")) is not int:
        return "unknown"
    if coverage["version"] == 1:
        return _coverage_state_v1(coverage)
    if coverage["version"] == COVERAGE_VERSION:
        return _coverage_state_v2(coverage)
    return "unknown"
