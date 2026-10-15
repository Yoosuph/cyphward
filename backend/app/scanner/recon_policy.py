"""Shared target eligibility and batch evidence. No network or database I/O."""
from shared.scan_scope import canonical_host, in_scope
from shared.scan_budget import BudgetExceeded
from backend.app.scanner.tool_results import ToolBatchResult, ToolExecutionError, collect_tool_results


def stage_plan(stage, hosts, scope, dns_records=(), http_records=(), *, cap=None, available=True):
    if stage not in {"dns", "http", "ports", "tls", "nuclei"}:
        raise ValueError("unknown recon stage")
    if cap is not None and cap < 0:
        raise ValueError("stage cap cannot be negative")
    ordered = list(dict.fromkeys(hosts))
    dns = {item["hostname"]: item for item in dns_records if item.get("hostname")}
    http = {item["hostname"]: item for item in http_records if item.get("hostname")}
    scope = [host for value in scope if (host := canonical_host(value))]
    selected, omitted = [], {}
    for host in ordered:
        probe = http.get(host) or {}
        if canonical_host(host) != host or not in_scope(host, scope):
            reason = "outside_authorised_scope"
        elif stage in {"http", "ports"} and not (dns.get(host) or {}).get("primary_ip"):
            reason = "no_public_dns_address"
        elif stage in {"tls", "nuclei"} and (probe.get("http_status") is None or probe.get("error")):
            reason = "no_usable_http_response"
        elif stage == "tls" and not str(probe.get("url") or "").startswith("https://"):
            reason = "no_https_response"
        elif not available:
            reason = "tool_unavailable"
        elif cap is not None and len(selected) >= cap:
            reason = "stage_host_cap"
        else:
            selected.append(host)
            continue
        omitted[host] = reason
    return {"version": 1, "stage": stage, "requested_hosts": ordered,
            "selected_hosts": selected, "omitted_hosts": omitted, "host_cap": cap}


async def evaluate_stage(budget, plan, factory):
    omitted = dict(plan["omitted_hosts"])
    if not plan["selected_hosts"]:
        result = ToolBatchResult([], [], [], {})
    else:
        try:
            result = await budget.run(factory)
        except BudgetExceeded as error:
            if str(error) == "recon_budget_exhausted":
                omitted.update({host: "recon_budget_exhausted" for host in plan["selected_hosts"]})
                result = ToolBatchResult([], [], [], {})
            else:
                result = ToolBatchResult([], plan["selected_hosts"], [],
                                        {host: "recon_stage_deadline" for host in plan["selected_hosts"]})
    if not isinstance(result, ToolBatchResult):
        raise TypeError("recon stage must preserve per-target batch evidence")
    result.stage_plan = plan
    result.omitted_hosts = omitted
    result.execution_budget = budget.payload()
    return result


def collect_http_results(hosts, results):
    valid = [result if isinstance(result, BaseException) or (
        isinstance(result, dict) and result.get("hostname") == host
    ) else ToolExecutionError("Invalid or mismatched HTTP observation")
        for host, result in zip(hosts, results)]
    batch = collect_tool_results(hosts, valid)
    batch.successful_hosts = []
    for data in batch:
        host = data.get("hostname")
        if host not in hosts:
            continue
        if data.get("http_status") is not None and not data.get("error"):
            batch.successful_hosts.append(host)
        else:
            batch.failed_hosts[host] = str(data.get("error") or "No HTTP response")[:300]
    return batch
