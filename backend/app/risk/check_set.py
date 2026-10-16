"""Declared check set and assessment coverage contract, version 2.

Completeness is defined against a versioned, declared set of checks, not
against everything that might exist on the internet. "Complete" means every
declared check has a conclusive outcome for every in-scope target of the
scanned domain. It never means the organisation, or the domain, is secure
beyond those checks. Missing evidence is never converted into a clean result.

Declared checks (CHECK_SET_VERSION):

  apex (the scanned domain only)
    dns.spf          TXT question on the apex has a conclusive outcome
                     (query_evaluated(record, "TXT")) AND the security checker
                     completed for the apex.
    dns.dmarc        _dmarc TXT question has a conclusive outcome
                     (query_evaluated(record, "DMARC")) AND the checker
                     completed for the apex.

  each in-scope host
    ports.inventory  the host is in the ports observation's successful_hosts
                     and not in its failed_hosts. Inventory only: it produces
                     no findings, but it is required.
    http.headers     the HTTP probe for the host has http_status not None and
                     no error (a blocked redirect sets error) AND the checker
                     completed for the host.
    tls.certificate  the probe's tls_info has valid_to or issuer AND the
                     checker completed for the host.

Targets. Iterate discovery.target_selection.selected_hosts (version 1):
  * DNS record has a truthy primary_ip (the resolver only keeps a public,
    connectable address) -> in scope.
  * Otherwise, A and AAAA both conclusive -> omitted, reason
    no_public_dns_address. Not missing; requests no host checks.
  * Otherwise (no record, or an address question failed) -> the three host
    checks are requested and missing, reason dns_address_unknown.
  * Each registered host that is not in selected_hosts is a requested
    "target.selection" check, missing with the selection's omission reason
    (or "not_selected"). It blocks complete.
  * Passive hosts omitted by selection are reported in targets.omitted and do
    not block complete.

Web applicability (from conclusive port inventory only):
  * Direct evidence wins: a check that is conclusive by its own evidence is
    evaluated even if the port inventory says the port was not open.
  * ports.inventory conclusive, neither 80 nor 443 open -> http.headers and
    tls.certificate omitted, reason no_web_service.
  * ports.inventory conclusive, 80 open and 443 not open -> tls.certificate
    omitted, reason no_https; http.headers still required.
  * HTTP stage omitted the host as third_party_service (its response only
    redirects off the verified domain, e.g. a mail provider's tracking link)
    -> http.headers and tls.certificate omitted with that reason, unless the
    certificate was observed directly on the host (then it is evaluated).
  * Otherwise both are required. A host with 80/443 open but no usable
    response stays missing.
  Naabu's -top-ports accepts 100, 1000 or full; all include 80 and 443, so a
  successful run that lists neither port reports them not open. Connect scans
  can miss an open port under packet loss; that limit is documented.

Missing reasons, in precedence order for a host check:
  dns_address_unknown, security_checks_failed (http/tls only, host not in
  checked_hosts), the relevant stage's omitted_hosts reason (ports: the
  ports stage; http.headers and tls.certificate: the HTTP stage, because the
  certificate comes from the HTTP probe, never the sslyze TLS stage),
  then: ports -> port_scan_failed (in failed_hosts) / ports_not_observed;
  http.headers -> no_usable_http_response / http_not_observed;
  tls.certificate -> certificate_not_observed.
Apex reasons: dns_not_observed, security_checks_failed, dns_query_failed.

State:
  * No target_selection version 1 (older workers): v1 fallback semantics.
    requested_checks is null, missing is empty, state is "partial" when any
    evaluated group exists, else "unassessed" when any DNS query_coverage
    exists, else "unknown". Never "complete".
  * missing empty and at least one in-scope host -> "complete".
  * missing empty and no in-scope host -> "partial" when evaluated_checks > 0
    (reason no_public_hosts), else "unassessed".
  * missing non-empty -> "partial" when evaluated_checks > 0, else
    "unassessed".
  evaluated_checks counts conclusive declared groups plus Nuclei match groups
  ("nuclei.match:<template_id>"), so a confirmed Nuclei match keeps a scan
  partial rather than unassessed, as in version 1. Nuclei never makes a scan
  complete and its absence never blocks complete.

Payload (all keys always present):
  {"version": 2, "check_set": CHECK_SET_VERSION, "domain": str,
   "state": str, "requested_checks": int | None, "evaluated_checks": int,
   "evaluated_groups": [{"hostname", "check"}],      # sorted
   "missing": [{"hostname", "check", "reason"}],     # sorted
   "omitted_checks": [{"hostname", "check", "reason"}],  # sorted
   "families": {check: {"requested", "evaluated", "omitted"}},  # DECLARED_CHECKS
   "targets": {"selected": int | None, "in_scope": int, "assessed": int,
               "omitted": {host: reason}},   # selection + no_public omissions
   "nuclei": nuclei_summary(...), "label": coverage_label(...),
   "reason": str}
"targets.assessed" counts in-scope hosts with no missing host check.
"""

CHECK_SET_VERSION = "cyphward-checks-v1"
COVERAGE_VERSION = 2

APEX_CHECKS = ("dns.spf", "dns.dmarc")
HOST_CHECKS = ("ports.inventory", "http.headers", "tls.certificate")
DECLARED_CHECKS = APEX_CHECKS + HOST_CHECKS
TARGET_SELECTION_CHECK = "target.selection"

HTTP_PORT = 80
HTTPS_PORT = 443

FAMILY_LABELS = {
    "dns.spf": "SPF",
    "dns.dmarc": "DMARC",
    "ports.inventory": "port inventory",
    "http.headers": "HTTP headers",
    "tls.certificate": "TLS certificate",
}

NUCLEI_LINE = "Known-CVE templates: matches reported; clean results not proven."

DOMAIN_STATE_WORDS = {
    "complete": "complete",
    "partial": "partial",
    "unassessed": "not assessed",
    "unknown": "coverage unknown",
    "not_scanned": "not scanned",
}


def nuclei_summary(observation):
    """Separate, non-gating Nuclei line. observation is the raw nuclei row or None."""
    if not isinstance(observation, dict) or not isinstance(observation.get("attempted_hosts"), list):
        return {"gating": False, "state": "not_run", "hosts_run": 0, "matches": 0, "label": NUCLEI_LINE}
    successful = observation.get("successful_hosts")
    matches = {
        (finding.get("_hostname") or (finding.get("evidence") or {}).get("host"),
         (finding.get("evidence") or {}).get("template_id"))
        for finding in observation.get("nuclei_findings") or []
        if isinstance(finding, dict) and (finding.get("evidence") or {}).get("template_id")
    }
    return {"gating": False, "state": "matches_only",
            "hosts_run": len(successful) if isinstance(successful, list) else 0,
            "matches": len(matches), "label": NUCLEI_LINE}


def coverage_label(domain, state, evaluated_declared, requested, in_scope):
    """One deterministic scope line shared by API, UI copy, reports and email."""
    if state == "complete":
        hosts = "host" if in_scope == 1 else "hosts"
        return f"{domain}: all declared checks complete on {in_scope} {hosts}"
    if requested is None:
        return f"{domain}: declared checks not recorded"
    return f"{domain}: {evaluated_declared} of {requested} declared checks conclusive"


def domain_coverage_line(domains):
    """'example.com: complete · shop.example.com: partial · other.ng: not scanned'."""
    return " · ".join(f"{item['domain']}: {DOMAIN_STATE_WORDS.get(item.get('state'), 'coverage unknown')}"
                      for item in domains or [])
