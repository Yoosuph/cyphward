"""
Cyphward Domain Verification Worker
Generates secure domain verification tokens and performs DNS TXT record validation.
"""
import uuid
import secrets
import httpx
try:
    import dns.resolver
except ImportError:
    dns = None


def generate_verification_token() -> str:
    """Generate a unique verification token for domain ownership proof."""
    return f"cyphward-verify-{secrets.token_hex(8)}"


async def verify_domain_dns_txt(domain: str, expected_token: str) -> dict:
    """
    Verify ownership of a domain by querying its DNS TXT records.
    Checks apex, '_cyphward.{domain}', and the common double-appended
    '_cyphward.{domain}.{domain}' mistake made by registrar panels.
    Checks for 'cyphward-verification=<token>', 'cyphward-verify=<token>', 'cyphward=<token>', or direct token match.
    Uses dnspython primary resolver, with DoH (Cloudflare / Google) fallback.
    """
    domain = domain.strip().lower()
    if "://" in domain:
        domain = domain.split("://")[1]
    domain = domain.split("/")[0].split(":")[0]

    expected_token = expected_token.strip()
    # Extract core token hex if prefixed
    raw_token = expected_token.replace("cyphward-verify-", "").replace("cyphward-verification=", "").replace("cyphward-verify=", "")

    records_found = []
    hosts_to_query = [domain]
    if not domain.startswith("_cyphward."):
        hosts_to_query.append(f"_cyphward.{domain}")
        # Panels like Namecheap append the domain to whatever is typed in the
        # Host field — users who paste the full record name end up with
        # _cyphward.<domain>.<domain>. Accept that too so one wrong paste
        # doesn't block an otherwise valid record.
        hosts_to_query.append(f"_cyphward.{domain}.{domain}")

    for host in hosts_to_query:
        # 1. Try dnspython resolver
        if dns:
            try:
                resolver = dns.resolver.Resolver()
                resolver.timeout = 3.0
                resolver.lifetime = 3.0
                answers = resolver.resolve(host, 'TXT')
                for rdata in answers:
                    for string in rdata.strings:
                        txt = string.decode('utf-8', errors='ignore').strip('"\'')
                        if txt and txt not in records_found:
                            records_found.append(txt)
            except Exception:
                pass

        # 2. Try DNS over HTTPS (Cloudflare)
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(
                    "https://cloudflare-dns.com/dns-query",
                    params={"name": host, "type": "TXT"},
                    headers={"accept": "application/dns-json"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for ans in data.get("Answer", []):
                        val = ans.get("data", "").strip('"\'')
                        if val and val not in records_found:
                            records_found.append(val)
        except Exception:
            pass

    # 3. Check for matching token
    is_verified = False
    matched_record = None

    for r in records_found:
        r_clean = r.strip()
        # Direct match, substring match, or key=value formats
        if (
            r_clean == expected_token
            or expected_token in r_clean
            or (raw_token and raw_token in r_clean)
            or f"cyphward-verification={expected_token}" in r_clean
            or f"cyphward-verify={expected_token}" in r_clean
            or f"cyphward={expected_token}" in r_clean
        ):
            is_verified = True
            matched_record = r_clean
            break

    return {
        "domain": domain,
        "verified": is_verified,
        "expected_token": expected_token,
        "matched_record": matched_record,
        "txt_records_observed": records_found,
    }

