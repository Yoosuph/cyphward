"""
Cyphward HTTP/HTTPS probing worker.
Raw observations only: real HTTP responses and real TLS handshakes.
Unreachable services yield honest nulls and an error string — never
fabricated statuses, certificates, titles, or technologies.

SSRF boundary (see scanner.ip_guard): connections pin to a validated public
IP (Host header keeps the hostname), redirects are followed manually — every
hop must stay in scope and resolve public — and a host that resolves only to
non-public addresses is never connected to.
"""
from typing import Dict, Any, List, Optional
import ssl
import socket
import datetime
import os
import re
import tempfile
from urllib.parse import urljoin, urlparse

import httpx

from backend.app.scanner import ip_guard
from backend.app.scanner.ip_guard import pinned_url as _pinned_url


SECURITY_HEADER_KEYS = [
    "strict-transport-security",
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
]

_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5


def inspect_tls_certificate(hostname: str, port: int = 443) -> Dict[str, Any]:
    """Real TLS handshake against hostname:port; records observed cert/protocol/cipher."""
    result = {
        "valid": False,
        "issuer": None,
        "subject": hostname,
        "valid_to": None,
        "days_remaining": 0,
        "protocol": None,
        "cipher": None,
        "error": None,
    }
    try:
        # Pin the TCP connection to an approved public IP; SNI still carries
        # the real hostname so the served certificate stays authentic.
        target_ip = ip_guard.resolve_connect_ip(hostname)
        if not target_ip:
            result["error"] = "refused: host resolves only to non-public addresses"
            return result

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # read cert details even if untrusted/self-signed

        with socket.create_connection((target_ip, port), timeout=3.5) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                result["protocol"] = ssock.version()
                cipher_tuple = ssock.cipher()
                result["cipher"] = cipher_tuple[0] if cipher_tuple else None

                bin_cert = ssock.getpeercert(binary_form=True)
                if bin_cert:
                    pem = ssl.DER_cert_to_PEM_cert(bin_cert)
                    fd, path = tempfile.mkstemp(suffix=".pem")
                    try:
                        with os.fdopen(fd, "w") as f:
                            f.write(pem)
                        cert = ssl._ssl._test_decode_cert(path)
                    finally:
                        try:
                            os.unlink(path)
                        except OSError:
                            pass
                    issuer_dict = dict(x[0] for x in cert.get("issuer", ()))
                    result["issuer"] = (
                        issuer_dict.get("organizationName")
                        or issuer_dict.get("commonName")
                    )
                    not_after = cert.get("notAfter")
                    if not_after:
                        dt = datetime.datetime.strptime(
                            not_after, "%b %d %H:%M:%S %Y %Z"
                        ).replace(tzinfo=datetime.timezone.utc)
                        result["valid_to"] = dt.isoformat()
                        delta = dt - datetime.datetime.now(datetime.timezone.utc)
                        result["days_remaining"] = max(0, delta.days)
                        result["valid"] = delta.days > 0
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"[:300]
    return result


def detect_technologies(headers: Dict[str, str], body: str) -> List[Dict[str, str]]:
    """Detect technologies from observed HTTP response headers and body content."""
    techs = []
    headers_lower = {k.lower(): v.lower() for k, v in headers.items()}
    server = headers_lower.get("server", "")
    powered_by = headers_lower.get("x-powered-by", "")

    # 1. Web Servers / Proxies
    if "nginx" in server:
        ver = re.search(r"nginx/([\d\.]+)", server)
        techs.append({"name": "Nginx", "version": ver.group(1) if ver else None, "category": "Web Server"})
    elif "apache" in server:
        ver = re.search(r"apache/([\d\.]+)", server)
        techs.append({"name": "Apache", "version": ver.group(1) if ver else None, "category": "Web Server"})
    elif "cloudflare" in server or "cf-ray" in headers_lower:
        techs.append({"name": "Cloudflare", "category": "CDN / WAF"})
    elif "caddy" in server:
        techs.append({"name": "Caddy", "category": "Web Server"})
    elif "envoy" in server:
        techs.append({"name": "Envoy", "category": "Proxy / Gateway"})

    # 2. Runtimes & Frameworks
    if "uvicorn" in server or "fastapi" in body.lower():
        techs.append({"name": "FastAPI", "category": "Framework"})
        techs.append({"name": "Python", "category": "Runtime"})
    if "express" in powered_by:
        techs.append({"name": "Express.js", "category": "Framework"})
        techs.append({"name": "Node.js", "category": "Runtime"})
    if "next" in headers_lower or "__NEXT_DATA__" in body:
        techs.append({"name": "Next.js", "category": "Framework"})
        techs.append({"name": "React", "category": "Frontend UI"})
    elif "react" in body:
        techs.append({"name": "React", "category": "Frontend UI"})
    if "wordpress" in body or "wp-content" in body:
        techs.append({"name": "WordPress", "category": "CMS"})
        techs.append({"name": "PHP", "category": "Runtime"})

    if "x-amz-cf-id" in headers_lower:
        techs.append({"name": "AWS CloudFront", "category": "CDN"})
    if "x-vercel-id" in headers_lower:
        techs.append({"name": "Vercel", "category": "Hosting / Edge"})

    return techs


def extract_title(html: str) -> str:
    """Extract page title from HTML body; empty string when absent."""
    match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()[:100]
    return ""


async def probe_http_service(
    hostname: str,
    scope: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Probe a host: real TLS handshake, then HTTPS request with HTTP fallback.
    Only observed values are recorded; failures set error/http_status accordingly.

    scope: authorized suffixes for redirect hops (pass the scan's domain /
    job scope). Without it, redirects may only stay on the same hostname
    (plus its subdomains).
    """
    hostname = hostname.strip().lower()
    res: Dict[str, Any] = {
        "hostname": hostname,
        "scheme": None,
        "url": None,
        "http_status": None,
        "title": "",
        "redirect_chain": [],
        "server_header": None,
        "powered_by_header": None,
        "security_headers": {},
        "raw_headers": {},
        "technologies": [],
        "tls_info": {},
        "error": None,
    }

    res["tls_info"] = inspect_tls_certificate(hostname)

    # Revalidated again per request/hop below — this is the fast honest exit.
    if not ip_guard.resolve_connect_ip(hostname):
        res["error"] = "refused: host resolves only to non-public addresses"
        return res

    hop_scope = list(scope) if scope else [hostname]
    last_error: Optional[str] = None

    async with httpx.AsyncClient(verify=False, timeout=4.0, follow_redirects=False) as client:
        for scheme in ("https", "http"):
            current_host = hostname
            current_scheme = scheme
            logical_url = f"{scheme}://{hostname}"
            redirect_chain: List[str] = []
            block_reason: Optional[str] = None
            resp = None
            hops = 0

            while True:
                if hops > 0 and not ip_guard.hostname_in_scope(current_host, hop_scope):
                    block_reason = f"redirect blocked: {current_host} out of scope"
                    break
                # Revalidate at connect time (defeats DNS rebinding between
                # the discovery resolve and this request).
                target_ip = ip_guard.resolve_connect_ip(current_host)
                if not target_ip:
                    block_reason = (
                        f"redirect blocked: {current_host} resolves to non-public address"
                        if hops > 0
                        else f"refused: {current_host} resolves only to non-public addresses"
                    )
                    break
                try:
                    resp = await client.get(
                        _pinned_url(current_scheme, target_ip),
                        headers={
                            "User-Agent": "Cyphward-Security-Scanner/1.0",
                            "Host": current_host,
                        },
                        # Connect by IP (pin), present the real hostname in
                        # TLS SNI so servers with IP-SNI rejections still
                        # serve the right virtual host.
                        extensions={"sni_hostname": current_host},
                    )
                except httpx.HTTPError as e:
                    last_error = f"{current_scheme}://{current_host}: {type(e).__name__}: {e}"[:300]
                    resp = None
                    break

                location = resp.headers.get("location")
                if resp.status_code in _REDIRECT_CODES and location:
                    nxt = urljoin(f"{current_scheme}://{current_host}", location)
                    parsed = urlparse(nxt)
                    if parsed.scheme not in ("http", "https") or not parsed.hostname:
                        block_reason = f"redirect blocked: unsupported location {nxt[:120]}"
                        redirect_chain.append(nxt)
                        break
                    hops += 1
                    if hops > _MAX_REDIRECTS:
                        block_reason = f"redirect blocked: exceeded {_MAX_REDIRECTS} hops"
                        redirect_chain.append(nxt)
                        break
                    redirect_chain.append(nxt)
                    logical_url = nxt
                    current_host = parsed.hostname.strip().lower()
                    current_scheme = parsed.scheme
                    continue
                break  # final (non-redirect) response

            if resp is None:
                if block_reason:
                    last_error = block_reason
                if last_error and not res["http_status"]:
                    res["error"] = last_error
                continue  # this scheme produced nothing usable — try the next

            res["scheme"] = scheme
            res["url"] = logical_url
            res["http_status"] = resp.status_code
            res["raw_headers"] = dict(resp.headers)
            res["server_header"] = resp.headers.get("server")
            res["powered_by_header"] = resp.headers.get("x-powered-by")
            res["title"] = extract_title(resp.text)
            res["technologies"] = detect_technologies(dict(resp.headers), resp.text[:10000])
            res["redirect_chain"] = redirect_chain
            res["error"] = block_reason  # None on a clean chain
            for sk in SECURITY_HEADER_KEYS:
                if sk in resp.headers:
                    res["security_headers"][sk] = resp.headers[sk]
            break
        else:
            res["error"] = res["error"] or last_error

    return res
