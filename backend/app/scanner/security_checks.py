"""
Cyphward Curated Safe Vulnerability Checks Worker
Implements deterministic, non-destructive security checks inspired by Nuclei safe templates.
"""
from typing import List, Dict, Any
import httpx
from shared.scanner_identity import SCANNER_USER_AGENT

from backend.app.scanner import ip_guard
from backend.app.scanner.dns_coverage import query_evaluated


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
    if is_apex and query_evaluated(dns_data, "DMARC"):
        dmarc_record = dns_data.get("dmarc_record")
        if not dmarc_record:
            findings.append({
                "title": "Missing Email DMARC Authentication Policy",
                "description": f"No DMARC TXT record was found at _dmarc.{hostname}. Receiving mail systems have no published DMARC policy for messages using this domain in the From address. This can increase impersonation risk; this DNS check does not test actual message delivery or mailbox security.",
                "severity": "critical",
                "category": "DNS & Email Security",
                "evidence": {
                    "dns_query": f"_dmarc.{hostname}",
                    "record_type": "TXT",
                    "observed_value": None,
                    "risk_impact": "Recipients have no domain-published DMARC handling policy; other authentication and spam controls may still apply."
                },
                "remediation": f"Inventory every legitimate sender for {hostname} and configure aligned SPF and/or DKIM with your mail provider. Start DMARC in monitoring mode (v=DMARC1; p=none). Add rua only after creating a reporting mailbox or configuring a trusted reporting service; never copy an unconfigured address. Review reports across your normal sending cycles and fix authentication failures before gradually moving to quarantine and then reject. Applying reject immediately can block legitimate email. Recheck DNS after changes; a published record alone does not prove that real messages authenticate or that impersonation is prevented. Rollout guide: https://support.google.com/a/answer/10032473",
            })
        elif "p=none" in dmarc_record.lower():
            findings.append({
                "title": "Permissive Email DMARC Policy (p=none)",
                "description": f"The DMARC policy for {hostname} is set to p=none. It requests monitoring rather than DMARC-based quarantine or rejection. This can be an intentional rollout phase; recipient filtering may still block suspicious messages. Review authentication reports before increasing enforcement.",
                "severity": "high",
                "category": "DNS & Email Security",
                "evidence": {
                    "dns_query": f"_dmarc.{hostname}",
                    "record_type": "TXT",
                    "observed_value": dmarc_record,
                    "mode": "monitoring_only"
                },
                "remediation": "Review DMARC reports for all legitimate senders, including low-frequency services, and correct SPF/DKIM alignment failures. Keep monitoring while unresolved legitimate failures remain, then introduce quarantine gradually and move to reject only when the reports support it. Confirm reporting addresses are configured. A DNS recheck confirms the published policy, not successful mail delivery. Rollout guide: https://support.google.com/a/answer/10032473",
            })

    # Each email check needs its own query; a DMARC failure must not hide SPF.
    if is_apex and query_evaluated(dns_data, "TXT"):
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
                "remediation": f"Inventory every service that sends mail for {hostname}, then build one SPF TXT record using those providers' documented mechanisms. Do not copy another provider's include value or publish multiple SPF records. Check DNS lookup limits and test legitimate senders before choosing a restrictive all policy. If the domain sends no mail, confirm that with its owner before choosing a no-senders policy. SPF results alone do not establish DMARC alignment or guarantee delivery. Guide: https://support.google.com/a/answer/33786"
            })
        elif "~all" in spf_record:
            findings.append({
                "title": "SPF Record Configured with Softfail (~all)",
                "description": f"The SPF record for {hostname} specifies ~all (softfail). This can be intentional during rollout; receiving systems decide how to handle the authentication result. A DNS record does not reveal whether all legitimate senders are configured.",
                "severity": "low",
                "category": "DNS & Email Security",
                "evidence": {
                    "domain": hostname,
                    "observed_spf": spf_record
                },
                "remediation": "Check all legitimate sending services and their SPF results before changing ~all. Review provider guidance and authentication reports; moving to -all without that inventory can disrupt legitimate mail. Receivers decide delivery, so -all does not guarantee rejection. Guide: https://support.google.com/a/answer/33786"
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
                "remediation": "Verify valid HTTPS on this host, then deploy HSTS with a short max-age in a staged rollout and test before increasing it. Inventory every subdomain before adding includeSubDomains: an HTTP-only subdomain can become inaccessible. Treat preload submission as a separate, deliberate change after checking its requirements and removal delay. Do not blindly copy a year-long includeSubDomains/preload policy. Guide: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Strict-Transport-Security"
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
                    "recommendation": "Review subdomain HTTPS readiness before considering includeSubDomains; preload is a separate decision."
                },
                "remediation": "Inventory all subdomains and confirm they support valid HTTPS before considering includeSubDomains. Keep the host-only policy while any affected service still needs HTTP; test a staged rollout. Preload requires a separate review and is not required by this recommendation. Guide: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Strict-Transport-Security"
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
                "remediation": "Inventory the application's scripts, styles, embeds and external services. Trial an application-specific policy with Content-Security-Policy-Report-Only and review violations before enforcement. Choose nonces/hashes and allowed origins to fit the application, then test sign-in, payments and integrations in staging. Do not copy a restrictive policy directly into production. Guide: https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP"
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
                "remediation": "Check whether legitimate customers or partner sites embed this page. Set a CSP frame-ancestors policy for the origins that genuinely need access, or use X-Frame-Options DENY/SAMEORIGIN when that fits the application. Test allowed embeds before enforcing; a blanket DENY can break them."
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
            # SSRF boundary: pin the robots.txt fetch to an approved public
            # IP (Host + SNI carry the hostname); no redirects are followed.
            target_ip = ip_guard.resolve_connect_ip(hostname)
            if target_ip:
                async with httpx.AsyncClient(verify=False, timeout=1.5) as client:
                    r_resp = await client.get(
                        ip_guard.pinned_url("https", target_ip, "/robots.txt"),
                        headers={"Host": hostname, "User-Agent": SCANNER_USER_AGENT},
                        extensions={"sni_hostname": hostname},
                    )
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
            "description": f"The HTTPS probe negotiated {protocol} with {hostname}. This confirms support for that protocol; it does not establish whether legacy protocols are also accepted.",
            "severity": "info",
            "category": "SSL/TLS",
            "evidence": {
                "protocol": protocol,
                "cipher": tls_info.get("cipher", "Modern GCM Suite")
            },
            "remediation": "Continue routine security configuration audits to preserve cryptographic posture."
        })

    return findings
