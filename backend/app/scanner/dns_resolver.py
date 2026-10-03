"""
Cyphward DNS Resolution Worker
Resolves A, AAAA, CNAME, MX, TXT, NS, SPF, and DMARC records.

Records stay exactly as observed (raw DNS truth), but primary_ip — the
signal later stages gate connections on — is only set for approved public
addresses (SSRF boundary, see scanner.ip_guard).
"""
from typing import Dict, Any, List
import socket
import httpx
from backend.app.scanner import ip_guard
try:
    import dns.resolver
except ImportError:
    dns = None


def resolve_with_dnspython(host: str) -> Dict[str, Any]:
    """Resolve DNS records using dnspython."""
    result = {
        "A": [],
        "AAAA": [],
        "CNAME": [],
        "MX": [],
        "TXT": [],
        "NS": [],
        "SPF": None,
        "DMARC": None,
    }
    if not dns:
        return result

    resolver = dns.resolver.Resolver()
    resolver.timeout = 2.0
    resolver.lifetime = 2.0

    record_types = ["A", "AAAA", "CNAME", "MX", "TXT", "NS"]
    for rtype in record_types:
        try:
            answers = resolver.resolve(host, rtype)
            for rdata in answers:
                if rtype == "TXT":
                    val = " ".join([s.decode('utf-8', errors='ignore') for s in rdata.strings])
                    result["TXT"].append(val)
                    if val.startswith("v=spf1"):
                        result["SPF"] = val
                elif rtype == "MX":
                    result["MX"].append(f"{rdata.preference} {str(rdata.exchange).rstrip('.')}")
                else:
                    result[rtype].append(str(rdata).rstrip('.'))
        except Exception:
            pass

    # Check DMARC at _dmarc.<host>
    try:
        dmarc_answers = resolver.resolve(f"_dmarc.{host}", "TXT")
        for rdata in dmarc_answers:
            val = " ".join([s.decode('utf-8', errors='ignore') for s in rdata.strings])
            if "v=DMARC1" in val:
                result["DMARC"] = val
    except Exception:
        pass

    return result


async def resolve_with_doh(host: str) -> Dict[str, Any]:
    """Fallback DNS resolution using Cloudflare DoH."""
    result = {
        "A": [],
        "AAAA": [],
        "CNAME": [],
        "MX": [],
        "TXT": [],
        "NS": [],
        "SPF": None,
        "DMARC": None,
    }
    async with httpx.AsyncClient(timeout=3.0) as client:
        # Standard types
        for rtype in ["A", "MX", "TXT", "NS"]:
            try:
                resp = await client.get(
                    "https://cloudflare-dns.com/dns-query",
                    params={"name": host, "type": rtype},
                    headers={"accept": "application/dns-json"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for ans in data.get("Answer", []):
                        val = ans.get("data", "").strip('"\'')
                        if val:
                            result[rtype].append(val)
                            if rtype == "TXT" and val.startswith("v=spf1"):
                                result["SPF"] = val
            except Exception:
                pass

        # DMARC
        try:
            resp = await client.get(
                "https://cloudflare-dns.com/dns-query",
                params={"name": f"_dmarc.{host}", "type": "TXT"},
                headers={"accept": "application/dns-json"}
            )
            if resp.status_code == 200:
                data = resp.json()
                for ans in data.get("Answer", []):
                    val = ans.get("data", "").strip('"\'')
                    if "v=DMARC1" in val:
                        result["DMARC"] = val
        except Exception:
            pass

    return result


async def resolve_host_dns(hostname: str) -> Dict[str, Any]:
    """
    Resolve full DNS records for a given hostname.
    Combines socket IP lookup with dnspython/DoH record fetching.
    """
    hostname = hostname.strip().lower()

    # Fast IP lookup
    primary_ip = None
    try:
        primary_ip = socket.gethostbyname(hostname)
    except Exception:
        pass

    records = resolve_with_dnspython(hostname)
    if not records["A"] and primary_ip:
        records["A"].append(primary_ip)

    # Fallback to DoH if no records found
    if not records["A"] and not records["MX"] and not records["TXT"]:
        doh_records = await resolve_with_doh(hostname)
        if doh_records["A"]:
            records = doh_records
            if not primary_ip and doh_records["A"]:
                primary_ip = doh_records["A"][0]

    # Unresolved hosts stay unresolved: primary_ip stays None so later
    # stages can skip them. (This spot previously minted deterministic
    # mock 102.134.x.x addresses, which invented assets for NXDOMAIN names.)
    #
    # primary_ip is public-only: a customer-controlled name pointing at
    # loopback/private/link-local/metadata space resolves to primary_ip=None
    # (inventory-only asset, no probes) while the raw records above remain
    # the observed truth.
    candidates = ([primary_ip] if primary_ip else []) + list(records["A"]) + list(records["AAAA"])
    safe_primary = next((ip for ip in candidates if ip_guard.is_public_ip(ip)), None)

    return {
        "hostname": hostname,
        "primary_ip": safe_primary,
        "records": records,
        "has_spf": records["SPF"] is not None,
        "has_dmarc": records["DMARC"] is not None,
        "spf_record": records["SPF"],
        "dmarc_record": records["DMARC"],
    }
