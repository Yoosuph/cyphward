"""
Cyphward Curated Safe Vulnerability Checks Worker
Implements deterministic, non-destructive security checks inspired by Nuclei safe templates.
"""
from typing import List, Dict, Any
import httpx


async def run_security_checks(
    hostname: str,
    dns_data: Dict[str, Any],
    http_data: Dict[str, Any],
    is_apex: bool = True
) -> List[Dict[str, Any]]:
    """
    Execute deterministic safe vulnerability and misconfiguration checks against host observations.
    Returns normalized raw finding candidates.
    """
    findings = []
    sec_headers = http_data.get("security_headers", {})
    raw_headers = http_data.get("raw_headers", {})
    tls_info = http_data.get("tls_info", {})
    records = dns_data.get("records", {})
    server = http_data.get("server_header") or raw_headers.get("server", "")
    powered_by = http_data.get("powered_by_header") or raw_headers.get("x-powered-by", "")

    # -------------------------------------------------------------------------
    # 1. Email Security: DMARC Policy Evaluation (Apex Domain & Mail Hosts Only)
    # -------------------------------------------------------------------------
    if is_apex:
        dmarc_record = dns_data.get("dmarc_record")
        if not dmarc_record:
            findings.append({
                "title": "Missing Email DMARC Authentication Policy",
                "description": f"Domain {hostname} does not publish a DMARC DNS record at _dmarc.{hostname}. Without DMARC, threat actors can freely forge transactional emails purporting to originate from this domain, leading to severe phishing and brand impersonation.",
                "severity": "critical",
                "category": "DNS & Email Security",
                "evidence": {
                    "dns_query": f"_dmarc.{hostname}",
                    "record_type": "TXT",
                    "observed_value": None,
                    "risk_impact": "Inbound recipient mail systems (Gmail, Microsoft 365) cannot verify email authenticity."
                },
                "remediation": f"Publish a DNS TXT record at _dmarc.{hostname} specifying 'v=DMARC1; p=reject; rua=mailto:dmarc-reports@{hostname};'"
            })
        elif "p=none" in dmarc_record.lower():
            findings.append({
                "title": "Permissive Email DMARC Policy (p=none)",
                "description": f"The DMARC policy for {hostname} is set to 'p=none' (monitoring only). Malicious spoofed messages are delivered to users without quarantine or rejection.",
                "severity": "high",
                "category": "DNS & Email Security",
                "evidence": {
                    "dns_query": f"_dmarc.{hostname}",
                    "record_type": "TXT",
                    "observed_value": dmarc_record,
                    "mode": "monitoring_only"
                },
                "remediation": "Elevate DMARC enforcement policy from 'p=none' to 'p=quarantine' or 'p=reject' once legitimate sender sources are verified."
            })

        # -------------------------------------------------------------------------
        # 2. Email Security: SPF Record Evaluation (Apex Domain & Mail Hosts Only)
        # -------------------------------------------------------------------------
        spf_record = dns_data.get("spf_record")
        if not spf_record:
            findings.append({
                "title": "Missing Sender Policy Framework (SPF) Record",
                "description": f"No valid SPF record (v=spf1) was detected on {hostname}. Spammers can impersonate outgoing corporate email addresses.",
                "severity": "medium",
                "category": "DNS & Email Security",
                "evidence": {
                    "domain": hostname,
                    "record_type": "TXT",
                    "observed_records": records.get("TXT", [])
                },
                "remediation": f"Create an SPF TXT record for {hostname} detailing authorized mail servers (e.g., 'v=spf1 include:_spf.google.com -all')."
            })
        elif "~all" in spf_record:
            findings.append({
                "title": "SPF Record Configured with Softfail (~all)",
                "description": f"The SPF record for {hostname} specifies '~all' (Softfail) instead of '-all' (Hardfail). Unauthorized mail transfers are flagged rather than definitively blocked.",
                "severity": "low",
                "category": "DNS & Email Security",
                "evidence": {
                    "domain": hostname,
                    "observed_spf": spf_record
                },
                "remediation": "Transition SPF mechanism qualifier from '~all' to '-all' to enforce strict rejection of unauthenticated relays."
            })

    # -------------------------------------------------------------------------
    # 3. HTTP Security Headers & Web Vulnerability Checks (Active HTTP Only)
    # -------------------------------------------------------------------------
    has_http = http_data.get("http_status") is not None
    if has_http:
        # 3.1 Strict-Transport-Security (HSTS)
        hsts = sec_headers.get("strict-transport-security")
        if not hsts:
            findings.append({
                "title": "Strict-Transport-Security (HSTS) Header Missing",
                "description": f"The endpoint https://{hostname} does not transmit an HSTS header. Browsers will allow unencrypted HTTP connections or SSL-stripping man-in-the-middle attacks.",
                "severity": "high",
                "category": "HTTP Headers",
                "evidence": {
                    "url": f"https://{hostname}",
                    "observed_headers": list(raw_headers.keys())[:10],
                    "missing_header": "Strict-Transport-Security"
                },
                "remediation": "Configure your reverse proxy/web server to send: 'Strict-Transport-Security: max-age=31536000; includeSubDomains; preload'."
            })
        elif "includesubdomains" not in hsts.lower():
            findings.append({
                "title": "Strict-Transport-Security Missing includeSubDomains",
                "description": f"HSTS is present on {hostname}, but lacks the 'includeSubDomains' directive. Subdomains remain vulnerable to downgrade attacks.",
                "severity": "medium",
                "category": "HTTP Headers",
                "evidence": {
                    "url": f"https://{hostname}",
                    "observed_hsts": hsts,
                    "recommendation": "Add 'includeSubDomains; preload'"
                },
                "remediation": "Update HSTS header to include 'includeSubDomains'."
            })

        # 3.2 Content-Security-Policy (CSP)
        csp = sec_headers.get("content-security-policy")
        if not csp:
            findings.append({
                "title": "Missing Content-Security-Policy (CSP) Header",
                "description": f"The response from https://{hostname} does not define a Content-Security-Policy. This header helps mitigate Cross-Site Scripting (XSS) and packet-injection attacks.",
                "severity": "medium",
                "category": "HTTP Headers",
                "evidence": {
                    "url": f"https://{hostname}",
                    "missing_header": "Content-Security-Policy"
                },
                "remediation": "Deploy a restrictive Content-Security-Policy header such as: default-src 'self'; script-src 'self'; object-src 'none'."
            })

        # 3.3 Clickjacking (X-Frame-Options)
        xfo = sec_headers.get("x-frame-options")
        if not xfo and (not csp or "frame-ancestors" not in csp.lower()):
            findings.append({
                "title": "Missing X-Frame-Options (Clickjacking Protection)",
                "description": f"Endpoint {hostname} lacks both X-Frame-Options and CSP frame-ancestors. The page can be embedded inside an attacker-controlled iframe, facilitating UI redressing / clickjacking.",
                "severity": "medium",
                "category": "HTTP Headers",
                "evidence": {
                    "url": f"https://{hostname}",
                    "missing_header": "X-Frame-Options"
                },
                "remediation": "Add 'X-Frame-Options: DENY' or 'X-Frame-Options: SAMEORIGIN' to all HTTP response headers."
            })

        # 3.4 MIME Sniffing (X-Content-Type-Options)
        xcto = sec_headers.get("x-content-type-options")
        if not xcto or "nosniff" not in xcto.lower():
            findings.append({
                "title": "Missing X-Content-Type-Options: nosniff Header",
                "description": f"The response does not specify 'X-Content-Type-Options: nosniff'. Older browsers may override the declared Content-Type, executing scripts disguised as images or text.",
                "severity": "low",
                "category": "HTTP Headers",
                "evidence": {
                    "url": f"https://{hostname}",
                    "observed_value": xcto
                },
                "remediation": "Set header 'X-Content-Type-Options: nosniff'."
            })

        # 3.5 Server & Runtime Banners
        if server and any(c.isdigit() for c in server):
            findings.append({
                "title": "Server Software Version Disclosed in HTTP Header",
                "description": f"The web server exposes its explicit build version in the Server header: '{server}'. Attackers use automated tools to query CVE databases for vulnerabilities affecting this exact release.",
                "severity": "medium",
                "category": "Information Disclosure",
                "evidence": {
                    "header_name": "Server",
                    "disclosed_banner": server,
                    "curl_reproduction": f"curl -sI https://{hostname} | grep -i server"
                },
                "remediation": "Configure web server to suppress granular version banners (e.g. 'ServerTokens Prod' in Apache, or 'server_tokens off;' in Nginx)."
            })

        if powered_by:
            findings.append({
                "title": "Technology Stack Disclosed via X-Powered-By Header",
                "description": f"The application returns header 'X-Powered-By: {powered_by}'. Disclosing backend frameworks assists attackers in targeting framework-specific exploit chains.",
                "severity": "low",
                "category": "Information Disclosure",
                "evidence": {
                    "header_name": "X-Powered-By",
                    "disclosed_value": powered_by
                },
                "remediation": "Disable or remove the X-Powered-By header in your application framework or reverse proxy."
            })

    # -------------------------------------------------------------------------
    # 8. SSL / TLS Certificate Status
    # -------------------------------------------------------------------------
    # Only claim anything about a certificate when one was actually observed.
    # A failed handshake (host down / NXDOMAIN) yields issuer=None,
    # valid_to=None, valid=False — that is "unreachable", not "expired".
    days_rem = tls_info.get("days_remaining", 90)
    cert_observed = bool(tls_info.get("valid_to") or tls_info.get("issuer"))
    if cert_observed and (days_rem < 0 or not tls_info.get("valid", True)):
        findings.append({
            "title": "SSL/TLS Certificate Expired or Invalid",
            "description": f"The TLS certificate presented by https://{hostname} is invalid or has expired. All inbound HTTPS traffic will encounter critical browser security blocks.",
            "severity": "critical",
            "category": "SSL/TLS",
            "evidence": {
                "issuer": tls_info.get("issuer"),
                "valid_to": tls_info.get("valid_to"),
                "days_remaining": days_rem
            },
            "remediation": "Immediately reissue and deploy a valid certificate via Let's Encrypt or your commercial Certificate Authority."
        })
    elif cert_observed and days_rem <= 30:
        findings.append({
            "title": "SSL/TLS Certificate Expiring Soon",
            "description": f"The TLS certificate on {hostname} will expire in {days_rem} days ({tls_info.get('valid_to')}). Failure to renew will result in service outage and user warnings.",
            "severity": "high",
            "category": "SSL/TLS",
            "evidence": {
                "issuer": tls_info.get("issuer"),
                "valid_to": tls_info.get("valid_to"),
                "days_remaining": days_rem
            },
            "remediation": "Trigger automated ACME certificate renewal process or deploy updated certificate."
        })

    # -------------------------------------------------------------------------
    # 9. Passive Safe Endpoint Check: Robots.txt & Environment Probe
    # -------------------------------------------------------------------------
    if http_data.get("http_status") and http_data.get("http_status") < 500:
        try:
            async with httpx.AsyncClient(verify=False, timeout=1.5) as client:
                r_resp = await client.get(f"https://{hostname}/robots.txt")
                if r_resp.status_code == 200 and ("disallow:" in r_resp.text.lower()):
                    disallowed = [l.strip() for l in r_resp.text.splitlines() if l.lower().startswith("disallow:")][:5]
                    if disallowed:
                        findings.append({
                            "title": "Robots.txt Discloses Sensitive Endpoint Paths",
                            "description": f"The public robots.txt file on {hostname} lists internal or administrative directories, giving threat actors a direct roadmap to unlinked administrative interfaces.",
                            "severity": "info",
                            "category": "Exposure",
                            "evidence": {
                                "url": f"https://{hostname}/robots.txt",
                                "disallowed_paths": disallowed
                            },
                            "remediation": "Ensure disallowed administrative panels require strong multi-factor authentication and IP allowlisting."
                        })
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 10. Modern Cipher Verification (Informational / Positive Control)
    # -------------------------------------------------------------------------
    protocol = tls_info.get("protocol")
    if protocol in ["TLSv1.3", "TLSv1.2"]:
        findings.append({
            "title": "Modern Cryptographic Protocols Active",
            "description": f"Endpoint {hostname} enforces modern cryptographic protocols ({protocol}) with strong forward-secrecy cipher suites. Insecure legacy protocols are appropriately prohibited.",
            "severity": "info",
            "category": "SSL/TLS",
            "evidence": {
                "protocol": protocol,
                "cipher": tls_info.get("cipher", "Modern GCM Suite")
            },
            "remediation": "Continue routine security configuration audits to preserve cryptographic posture."
        })

    return findings
