"""DNS inventory with explicit per-question outcomes, never synthetic success.

DNS failures remain unknown. A negative DNS response is distinct from a failed
query. Socket lookup supports connection inventory only, not email-check proof.
"""
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict
import socket

import dns.rdata
import dns.rdataclass
import dns.rdatatype
import dns.resolver
import httpx

from backend.app.scanner import ip_guard

QUERY_TYPES = {"A": "A", "AAAA": "AAAA", "CNAME": "CNAME", "MX": "MX",
               "TXT": "TXT", "NS": "NS", "DMARC": "TXT"}


def _empty_records() -> dict:
    return {"A": [], "AAAA": [], "CNAME": [], "MX": [], "TXT": [], "NS": [],
            "SPF": None, "DMARC": None,
            "query_coverage": {"version": 1, "queries": {}}}


def _question(host: str, key: str) -> tuple[str, str]:
    return (f"_dmarc.{host}" if key == "DMARC" else host, QUERY_TYPES[key])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _outcome(host: str, key: str, source: str, started: str, status: str,
             error: str | None = None) -> dict:
    name, record_type = _question(host, key)
    return {"name": name, "record_type": record_type, "source": source,
            "status": status, "started_at": started, "completed_at": _now(),
            **({"error": error} if error else {})}


def _record_answer(result: dict, key: str, answers) -> None:
    for rdata in answers:
        if QUERY_TYPES[key] == "TXT":
            value = b"".join(rdata.strings).decode("utf-8", errors="replace")
            if key == "DMARC":
                if value.lower().startswith("v=dmarc1"):
                    result["DMARC"] = value
            else:
                result["TXT"].append(value)
                if value.lower().startswith("v=spf1"):
                    result["SPF"] = value
        elif key == "MX":
            result[key].append(f"{rdata.preference} {str(rdata.exchange).rstrip('.')}")
        else:
            result[key].append(str(rdata).rstrip("."))


def resolve_with_dnspython(host: str) -> Dict[str, Any]:
    result = _empty_records()
    resolver = dns.resolver.Resolver()
    resolver.timeout = resolver.lifetime = 2.0
    for key in QUERY_TYPES:
        name, record_type = _question(host, key)
        started = _now()
        try:
            answers = list(resolver.resolve(name, record_type))
            _record_answer(result, key, answers)
            status, error = ("answered" if answers else "no_data"), None
        except dns.resolver.NXDOMAIN:
            status, error = "nxdomain", None
        except dns.resolver.NoAnswer:
            status, error = "no_data", None
        except Exception as exc:
            status, error = "failed", type(exc).__name__
        result["query_coverage"]["queries"][key] = _outcome(
            host, key, "dnspython", started, status, error)
    return result


async def resolve_with_doh(host: str, query_keys=None) -> Dict[str, Any]:
    """Retry failed questions only; validate DNS status and answer record types."""
    result = _empty_records()
    async with httpx.AsyncClient(timeout=3.0) as client:
        for key in (QUERY_TYPES if query_keys is None else query_keys):
            name, record_type = _question(host, key)
            started = _now()
            try:
                response = await client.get(
                    "https://cloudflare-dns.com/dns-query",
                    params={"name": name, "type": record_type},
                    headers={"accept": "application/dns-json"})
                response.raise_for_status()
                data = response.json()
                if data.get("TC") or type(data.get("Status")) is not int:
                    raise ValueError("Truncated or invalid DNS response")
                if data.get("Status") == 3:
                    status = "nxdomain"
                elif data.get("Status") == 0:
                    answers = [dns.rdata.from_text(dns.rdataclass.IN, record_type, answer["data"])
                               for answer in data.get("Answer", [])
                               if answer.get("type") == dns.rdatatype.from_text(record_type)]
                    _record_answer(result, key, answers)
                    status = "answered" if answers else "no_data"
                else:
                    raise ValueError("DNS response was not successful")
                error = None
            except Exception as exc:
                status, error = "failed", type(exc).__name__
            result["query_coverage"]["queries"][key] = _outcome(
                host, key, "cloudflare_doh", started, status, error)
    return result


async def resolve_host_dns(hostname: str) -> Dict[str, Any]:
    hostname = hostname.strip().lower().rstrip(".")
    # Blocking DNS work must not prevent the event loop renewing scan leases.
    try:
        primary_ip = await asyncio.to_thread(socket.gethostbyname, hostname)
    except Exception:
        primary_ip = None
    records = await asyncio.to_thread(resolve_with_dnspython, hostname)
    coverage = records.get("query_coverage") or {}
    queries = coverage.get("queries") or {}
    failed = [key for key, outcome in queries.items() if outcome.get("status") == "failed"]
    if failed:
        fallback = await resolve_with_doh(hostname, failed)
        fallback_queries = (fallback.get("query_coverage") or {}).get("queries") or {}
        for key in failed:
            outcome = fallback_queries.get(key)
            if outcome is None:
                continue
            # Keep native and fallback outcomes so failed retries remain visible.
            queries[key] = {**outcome, "prior_attempts": [queries[key]]}
            if outcome["status"] in {"answered", "no_data", "nxdomain"}:
                records[key] = fallback[key]
                if key == "TXT":
                    records["SPF"] = fallback["SPF"]
    elif not queries and not records["A"] and not records["MX"] and not records["TXT"]:
        # Compatibility with legacy/custom resolvers: keep inventory but never
        # manufacture query evidence that those resolvers did not return.
        fallback = await resolve_with_doh(hostname)
        for key in ("A", "AAAA", "CNAME", "MX", "TXT", "NS", "SPF", "DMARC"):
            if fallback.get(key):
                records[key] = fallback[key]
    if not records["A"] and primary_ip:
        records["A"].append(primary_ip)
    candidates = ([primary_ip] if primary_ip else []) + list(records["A"]) + list(records["AAAA"])
    safe_primary = next((ip for ip in candidates if ip_guard.is_public_ip(ip)), None)
    return {"hostname": hostname, "primary_ip": safe_primary, "records": records,
            "has_spf": records["SPF"] is not None, "has_dmarc": records["DMARC"] is not None,
            "spf_record": records["SPF"], "dmarc_record": records["DMARC"]}
