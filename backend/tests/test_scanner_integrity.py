"""
Regression tests: the scanner must never fabricate hosts, IPs, or
certificate findings. (2026-10-01 incident: a demo fallback invented
www/api/auth/vpn/admin.internal.<domain> + mock 102.134.x.x IPs when
crt.sh was down, and failed TLS handshakes were graded as critical
"certificate expired" findings.)
"""
import asyncio
from backend.app.scanner import discovery, dns_resolver
from backend.app.scanner.security_checks import run_security_checks

REAL_DOMAIN = "example.com"


def test_discovery_returns_only_apex_when_passive_sources_fail(monkeypatch):
    async def empty(_domain):
        return set()

    monkeypatch.setattr(discovery, "query_crt_sh", empty)
    monkeypatch.setattr(discovery, "query_hackertarget", empty)
    monkeypatch.setattr(discovery, "run_subfinder_async", empty)
    monkeypatch.setattr(discovery, "query_certspotter", empty)

    hosts = asyncio.run(discovery.discover_subdomains(REAL_DOMAIN))

    assert hosts == [REAL_DOMAIN], (
        "discovery must return only what passive sources found — "
        f"got invented entries: {[h for h in hosts if h != REAL_DOMAIN]}"
    )
    for banned in ("www", "api", "auth", "vpn", "admin.internal", "mail", "app"):
        assert f"{banned}.{REAL_DOMAIN}" not in hosts


def test_unresolved_host_gets_no_mock_ip(monkeypatch):
    monkeypatch.setattr(
        "socket.gethostbyname",
        lambda _h: (_ for _ in ()).throw(OSError("NXDOMAIN")),
    )
    monkeypatch.setattr(dns_resolver, "resolve_with_dnspython", lambda _h: {
        "A": [], "AAAA": [], "CNAME": [], "MX": [], "TXT": [], "NS": [],
        "SPF": None, "DMARC": None,
    })

    async def no_doh(_h):
        return {
            "A": [], "AAAA": [], "CNAME": [], "MX": [], "TXT": [], "NS": [],
            "SPF": None, "DMARC": None,
        }

    monkeypatch.setattr(dns_resolver, "resolve_with_doh", no_doh)

    result = asyncio.run(dns_resolver.resolve_host_dns("ghost.internal.example.com"))

    assert result["primary_ip"] is None, "unresolved hosts must not get an IP"
    assert result["records"]["A"] == [], "no synthetic A records"
    assert "127.0.0.1" not in str(result)


def test_failed_tls_handshake_is_not_a_cert_finding():
    # Exactly what http_probe returns when the host is unreachable.
    tls_info = {
        "valid": False,
        "issuer": None,
        "subject": "auth.example.com",
        "valid_to": None,
        "days_remaining": 0,
        "protocol": None,
        "cipher": None,
        "error": "socket.gaierror: [Errno -2] Name or service not known",
    }
    findings = asyncio.run(run_security_checks(
        "auth.example.com",
        {"records": {}},
        {"http_status": None, "tls_info": tls_info},
        is_apex=False,
    ))
    cert_titles = [f["title"] for f in findings if "Certificate" in f["title"]]
    assert cert_titles == [], (
        "an unreachable host must not produce certificate findings, "
        f"got: {cert_titles}"
    )


def test_observed_expired_cert_is_still_reported():
    tls_info = {
        "valid": False,
        "issuer": "Let's Encrypt",
        "subject": "www.example.com",
        "valid_to": "2026-09-01T00:00:00+00:00",
        "days_remaining": 0,
        "protocol": "TLSv1.3",
        "cipher": "TLS_AES_256_GCM_SHA384",
        "error": None,
    }
    findings = asyncio.run(run_security_checks(
        "www.example.com",
        {"records": {}},
        {"http_status": 200, "tls_info": tls_info},
        is_apex=False,
    ))
    assert any(
        f["title"] == "SSL/TLS Certificate Expired or Invalid"
        and f["severity"] == "critical"
        for f in findings
    ), "a genuinely observed expired certificate must still raise a critical"


class _CertSpotterResp:
    status_code = 200

    def json(self):
        return [
            {"dns_names": ["auth.example.com", "*.example.com", "other.test"]},
            {"dns_names": ["WWW.EXAMPLE.COM", "bad name.example.com"]},
        ]


class _CertSpotterClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, **kwargs):
        assert "certspotter.com" in url
        assert "include_subdomains=true" in url
        return _CertSpotterResp()


def test_certspotter_ct_redundancy_parses_names(monkeypatch):
    """crt.sh outages must not blind CT discovery: certspotter is the
    redundant CT source (incident: auth.cyphward.com missed while crt.sh
    returned 502)."""
    monkeypatch.setattr(discovery.httpx, "AsyncClient", _CertSpotterClient)
    names = asyncio.run(discovery.query_certspotter("example.com"))
    assert names == {"auth.example.com", "example.com", "www.example.com"}


def test_discovery_merges_redundant_ct_source(monkeypatch):
    async def empty(_domain):
        return set()

    async def ct_names(_domain):
        return {"auth.example.com"}

    monkeypatch.setattr(discovery, "query_crt_sh", empty)
    monkeypatch.setattr(discovery, "query_hackertarget", empty)
    monkeypatch.setattr(discovery, "run_subfinder_async", empty)
    monkeypatch.setattr(discovery, "query_certspotter", ct_names)
    assert asyncio.run(discovery.discover_subdomains("example.com")) == [
        "auth.example.com",
        "example.com",
    ]
