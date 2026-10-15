"""DNS query evidence required by email checks and resolution/rechecks."""
from typing import Any

from backend.app.scanner.tool_results import collect_tool_results, ToolExecutionError

DNS_QUERIES = ("A", "AAAA", "CNAME", "MX", "TXT", "NS", "DMARC")

DNS_RULE_QUERIES = {
    "Missing Email DMARC Authentication Policy": "DMARC",
    "Permissive Email DMARC Policy (p=none)": "DMARC",
    "Missing Sender Policy Framework (SPF) Record": "TXT",
    "SPF Record Configured with Softfail (~all)": "TXT",
}


def query_evaluated(data: dict, query: str) -> bool:
    coverage = (data.get("records") or {}).get("query_coverage") or {}
    if (not isinstance(coverage, dict)
            or type(coverage.get("version")) is not int
            or coverage.get("version") != 1):
        return False
    queries = coverage.get("queries")
    outcome = queries.get(query) if isinstance(queries, dict) else None
    if not isinstance(outcome, dict):
        return False
    hostname = str(data.get("hostname") or "").strip().lower().rstrip(".")
    expected_name = f"_dmarc.{hostname}" if query == "DMARC" else hostname
    expected_type = "TXT" if query == "DMARC" else query
    return bool(hostname) and (
        isinstance(outcome.get("status"), str)
        and outcome.get("status") in {"answered", "no_data", "nxdomain"}
        and outcome.get("name") == expected_name
        and outcome.get("record_type") == expected_type
    )


def dns_finding_evaluated(data: dict, title: Any) -> bool:
    query = DNS_RULE_QUERIES.get(title)
    return query is not None and query_evaluated(data, query)


def collect_dns_results(hostnames, results):
    """Retain partial observations while marking incompletely assessed hosts."""
    validated = []
    for host, result in zip(hostnames, results):
        if isinstance(result, BaseException) or (
            isinstance(result, dict) and result.get("hostname") == host
        ):
            validated.append(result)
        else:
            validated.append(ToolExecutionError("DNS returned an invalid or mismatched host observation"))
    batch = collect_tool_results(hostnames, validated)
    batch.successful_hosts = []
    for data in batch:
        host = data.get("hostname")
        if host not in batch.attempted_hosts:
            continue
        incomplete = [key for key in DNS_QUERIES if not query_evaluated(data, key)]
        if incomplete:
            batch.failed_hosts[host] = "DNS queries failed or unknown: " + ", ".join(incomplete)
        else:
            batch.successful_hosts.append(host)
    return batch
