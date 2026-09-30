"""
Cyphward HTTP/HTTPS probing worker.
Raw observations only: real HTTP responses and real TLS handshakes.
Unreachable services yield honest nulls and an error string — never
fabricated statuses, certificates, titles, or technologies.
"""
from typing import Dict, Any, List
import ssl
import socket
import datetime
import os
import re
import tempfile
import httpx


SECURITY_HEADER_KEYS = [
    "strict-transport-security",
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
]


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
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # read cert details even if untrusted/self-signed

        with socket.create_connection((hostname, port), timeout=3.5) as sock:
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


async def probe_http_service(hostname: str) -> Dict[str, Any]:
    """
    Probe a host: real TLS handshake, then HTTPS request with HTTP fallback.
    Only observed values are recorded; failures set error/http_status accordingly.
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

    last_error = None
    async with httpx.AsyncClient(verify=False, timeout=4.0, follow_redirects=True) as client:
        for scheme in ("https", "http"):
            try:
                resp = await client.get(
                    f"{scheme}://{hostname}",
                    headers={"User-Agent": "Cyphward-Security-Scanner/1.0"},
                )
            except httpx.HTTPError as e:
                last_error = f"{scheme}://{hostname}: {type(e).__name__}: {e}"[:300]
                continue

            res["scheme"] = scheme
            res["url"] = str(resp.url)
            res["http_status"] = resp.status_code
            res["raw_headers"] = dict(resp.headers)
            res["server_header"] = resp.headers.get("server")
            res["powered_by_header"] = resp.headers.get("x-powered-by")
            res["title"] = extract_title(resp.text)
            res["technologies"] = detect_technologies(dict(resp.headers), resp.text[:10000])
            res["redirect_chain"] = [str(r.url) for r in resp.history]
            for sk in SECURITY_HEADER_KEYS:
                if sk in resp.headers:
                    res["security_headers"][sk] = resp.headers[sk]
            break
        else:
            res["error"] = last_error

    return res
