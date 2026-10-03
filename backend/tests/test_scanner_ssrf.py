"""
Regression tests: scanner network boundary (review item "P1 — scanner
network boundary", SSRF).

Rules under test:
- is_public_ip rejects loopback/private/link-local/cloud-metadata/CGNAT/
  ULA/multicast/reserved/mapped forms; only global unicast passes.
- resolve_host_dns: raw records stay as observed, but primary_ip is None
  unless an approved public address exists (inventory-only, no probes).
- probe_http_service: refuses non-public hosts, connects pinned by IP with
  the hostname in Host, follows redirects manually — every hop must be in
  scope and resolve public, capped at 5 hops; the block is recorded honestly.
- naabu/sslyze/nuclei never hand a non-public target to a subprocess.
"""
import asyncio

import pytest

import backend.app.scanner.ip_guard as ip_guard
import backend.app.scanner.dns_resolver as dns_resolver
import backend.app.scanner.naabu_runner as naabu_runner
import backend.app.scanner.sslyze_runner as sslyze_runner
import backend.app.scanner.nuclei_runner as nuclei_runner
import backend.app.scanner.http_probe as http_probe
from backend.app.scanner.http_probe import _pinned_url


# ---------------------------------------------------------------------------
# ip_guard: address classification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ip", [
    "10.0.0.1", "172.16.0.9", "192.168.1.1", "127.0.0.1", "127.0.0.53",
    "169.254.169.254",       # cloud metadata
    "169.254.0.1",           # link-local
    "100.64.0.1",            # CGNAT
    "0.0.0.0", "224.0.0.1", "255.255.255.255", "198.18.0.1",
    "::1", "fe80::1", "fc00::1", "fd12:3456::1", "ff02::1",
    "::ffff:10.0.0.1",       # IPv4-mapped private
    "::ffff:169.254.169.254",
    "", "not-an-ip", "evil.example;10.0.0.1", None,
])
def test_is_public_ip_rejects_non_public(ip):
    assert ip_guard.is_public_ip(ip) is False


@pytest.mark.parametrize("ip", [
    "8.8.8.8", "1.1.1.1", "93.184.216.34",
    "2606:4700:4700::1111", "2001:4860:4860::8888",
])
def test_is_public_ip_accepts_global_unicast(ip):
    assert ip_guard.is_public_ip(ip) is True


def test_resolve_connect_ips_filters_and_dedupes(monkeypatch):
    answers = [
        (2, 1, 6, "", ("10.0.0.5", 0)),
        (2, 1, 6, "", ("93.184.216.34", 0)),
        (2, 1, 6, "", ("169.254.169.254", 0)),
        (2, 1, 6, "", ("93.184.216.34", 0)),
        (2, 1, 6, "", ("127.0.0.1", 0)),
    ]
    monkeypatch.setattr(ip_guard.socket, "getaddrinfo", lambda *a, **k: answers)
    assert ip_guard.resolve_connect_ips("victim.target.test") == ["93.184.216.34"]


def test_resolve_connect_ips_all_private_is_empty(monkeypatch):
    answers = [(2, 1, 6, "", ("10.1.2.3", 0)), (2, 1, 6, "", ("192.168.0.1", 0))]
    monkeypatch.setattr(ip_guard.socket, "getaddrinfo", lambda *a, **k: answers)
    assert ip_guard.resolve_connect_ips("victim.target.test") == []
    assert ip_guard.resolve_connect_ip("victim.target.test") is None


def test_resolve_connect_ips_literal_ip():
    assert ip_guard.resolve_connect_ips("8.8.8.8") == ["8.8.8.8"]
    assert ip_guard.resolve_connect_ips("10.0.0.1") == []


def test_hostname_in_scope_dot_boundary():
    scope = ["acme.test"]
    assert ip_guard.hostname_in_scope("acme.test", scope)
    assert ip_guard.hostname_in_scope("www.acme.test", scope)
    assert ip_guard.hostname_in_scope("WWW.Acme.TEST.", scope)
    assert not ip_guard.hostname_in_scope("notacme.test", scope)
    assert not ip_guard.hostname_in_scope("acme.test.evil.com", scope)
    assert not ip_guard.hostname_in_scope("", scope)
    assert not ip_guard.hostname_in_scope("x", [])


# ---------------------------------------------------------------------------
# dns_resolver: primary_ip public-only, records stay raw
# ---------------------------------------------------------------------------
def test_dns_primary_ip_refused_when_only_private(monkeypatch):
    monkeypatch.setattr(dns_resolver.socket, "gethostbyname", lambda h: "10.0.0.5")
    monkeypatch.setattr(
        dns_resolver, "resolve_with_dnspython",
        lambda h: {"A": ["10.0.0.5"], "AAAA": [], "CNAME": [], "MX": [],
                   "TXT": [], "NS": [], "SPF": None, "DMARC": None},
    )

    out = asyncio.run(dns_resolver.resolve_host_dns("internal.target.test"))

    assert out["primary_ip"] is None, "private-only host must not expose a probe target"
    assert out["records"]["A"] == ["10.0.0.5"], "raw DNS records stay as observed"


def test_dns_primary_ip_kept_when_public(monkeypatch):
    monkeypatch.setattr(dns_resolver.socket, "gethostbyname", lambda h: "93.184.216.34")
    monkeypatch.setattr(
        dns_resolver, "resolve_with_dnspython",
        lambda h: {"A": ["93.184.216.34"], "AAAA": [], "CNAME": [], "MX": [],
                   "TXT": [], "NS": [], "SPF": None, "DMARC": None},
    )

    out = asyncio.run(dns_resolver.resolve_host_dns("www.target.test"))
    assert out["primary_ip"] == "93.184.216.34"


def test_dns_primary_ip_prefers_public_over_private(monkeypatch):
    monkeypatch.setattr(dns_resolver.socket, "gethostbyname", lambda h: "10.0.0.5")
    monkeypatch.setattr(
        dns_resolver, "resolve_with_dnspython",
        lambda h: {"A": ["10.0.0.5", "93.184.216.34"], "AAAA": [], "CNAME": [],
                   "MX": [], "TXT": [], "NS": [], "SPF": None, "DMARC": None},
    )

    out = asyncio.run(dns_resolver.resolve_host_dns("mixed.target.test"))
    assert out["primary_ip"] == "93.184.216.34"


# ---------------------------------------------------------------------------
# http probe: refusal, pinning, redirect scoping
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, status, headers=None, text="<html><title>T</title></html>"):
        self.status_code = status
        self.headers = headers or {}
        self.text = text


class _FakeHttpClient:
    calls = []
    responses = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, **kwargs):
        _FakeHttpClient.calls.append((url, dict(headers or {})))
        if not _FakeHttpClient.responses:
            raise AssertionError("unexpected extra request")
        return _FakeHttpClient.responses.pop(0)


@pytest.fixture
def fake_http_env(monkeypatch):
    _FakeHttpClient.calls = []
    _FakeHttpClient.responses = []
    monkeypatch.setattr(http_probe.httpx, "AsyncClient", _FakeHttpClient)
    monkeypatch.setattr(
        http_probe, "inspect_tls_certificate",
        lambda hostname, port=443: {"valid": True, "error": None},
    )
    return _FakeHttpClient


def test_probe_refuses_non_public_host(monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda h: None)

    def boom(*a, **k):
        raise AssertionError("must not build an HTTP client for a non-public host")

    monkeypatch.setattr(http_probe.httpx, "AsyncClient", boom)

    out = asyncio.run(http_probe.probe_http_service("internal.target.test"))

    assert out["http_status"] is None
    assert "non-public" in out["error"]
    assert "non-public" in out["tls_info"]["error"]


def test_probe_pinned_request_and_in_scope_redirects(fake_http_env, monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda h: "93.184.216.34")
    fake_http_env.responses = [
        _FakeResp(301, {"location": "https://www.target.test/page"}),
        _FakeResp(200, {"server": "nginx", "strict-transport-security": "max-age=1"}),
    ]

    out = asyncio.run(
        http_probe.probe_http_service("target.test", scope=["target.test"])
    )

    assert out["http_status"] == 200
    assert out["redirect_chain"] == ["https://www.target.test/page"]
    assert out["url"] == "https://www.target.test/page"
    assert out["error"] is None
    assert out["security_headers"].get("strict-transport-security") == "max-age=1"

    calls = fake_http_env.calls
    assert len(calls) == 2
    # Pinned to the validated IP; hostname travels in the Host header.
    assert calls[0][0] == "https://93.184.216.34/"
    assert calls[0][1]["Host"] == "target.test"
    assert calls[1][0] == "https://93.184.216.34/"
    assert calls[1][1]["Host"] == "www.target.test"


def test_probe_blocks_redirect_to_out_of_scope_host(fake_http_env, monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda h: "93.184.216.34")
    fake_http_env.responses = [
        _FakeResp(301, {"location": "http://169.254.169.254/latest/meta-data/"}),
    ]

    out = asyncio.run(
        http_probe.probe_http_service("target.test", scope=["target.test"])
    )

    assert len(fake_http_env.calls) == 1, "blocked hop must never be requested"
    assert out["http_status"] == 301
    assert "out of scope" in out["error"]
    assert out["redirect_chain"] == ["http://169.254.169.254/latest/meta-data/"]


def test_probe_blocks_in_scope_redirect_resolving_private(fake_http_env, monkeypatch):
    def guard(h):
        if h == "internal.target.test":
            return None  # in scope by name, but resolves private
        return "93.184.216.34"

    monkeypatch.setattr(ip_guard, "resolve_connect_ip", guard)
    fake_http_env.responses = [
        _FakeResp(302, {"location": "http://internal.target.test/admin"}),
    ]

    out = asyncio.run(
        http_probe.probe_http_service("target.test", scope=["target.test"])
    )

    assert len(fake_http_env.calls) == 1, "private redirect target must never be requested"
    assert out["http_status"] == 302
    assert "non-public" in out["error"]


def test_probe_redirect_hop_cap(fake_http_env, monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda h: "93.184.216.34")
    fake_http_env.responses = [
        _FakeResp(302, {"location": f"https://target.test/r{i}"}) for i in range(10)
    ]

    out = asyncio.run(
        http_probe.probe_http_service("target.test", scope=["target.test"])
    )

    assert "exceeded 5 hops" in out["error"]
    assert len(fake_http_env.calls) == 6, "initial request + 5 followed redirects"


def test_pinned_url_formats_v4_and_v6():
    assert _pinned_url("https", "93.184.216.34") == "https://93.184.216.34/"
    assert _pinned_url("http", "2606:4700:4700::1111") == "http://[2606:4700:4700::1111]/"


# ---------------------------------------------------------------------------
# subprocess runners never touch non-public targets
# ---------------------------------------------------------------------------
def test_naabu_skips_non_public_target(monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda h: None)

    def boom(*a, **k):
        raise AssertionError("naabu must not be spawned for a non-public target")

    monkeypatch.setattr(naabu_runner.asyncio, "create_subprocess_exec", boom)
    monkeypatch.setattr(naabu_runner.shutil, "which", lambda n: "/usr/bin/naabu")

    assert asyncio.run(naabu_runner.run_naabu("internal.target.test")) == []


def test_sslyze_skips_non_public_target(monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda h: None)

    def boom(*a, **k):
        raise AssertionError("sslyze must not be spawned for a non-public target")

    monkeypatch.setattr(sslyze_runner.asyncio, "create_subprocess_exec", boom)
    monkeypatch.setattr(sslyze_runner.shutil, "which", lambda n: "/usr/bin/sslyze")

    assert asyncio.run(sslyze_runner.run_sslyze("internal.target.test")) is None


def test_nuclei_single_run_refuses_non_public_target(monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda h: None)

    def boom(*a, **k):
        raise AssertionError("nuclei must not be spawned for a non-public target")

    monkeypatch.setattr(nuclei_runner.asyncio, "create_subprocess_exec", boom)
    monkeypatch.setattr(nuclei_runner.shutil, "which", lambda n: "/usr/bin/nuclei")

    assert asyncio.run(nuclei_runner.run_nuclei("internal.target.test")) == []


def test_nuclei_template_rerun_refuses_non_public_target(monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda h: None)

    def boom(*a, **k):
        raise AssertionError("nuclei must not be spawned for a non-public target")

    monkeypatch.setattr(nuclei_runner.asyncio, "create_subprocess_exec", boom)
    monkeypatch.setattr(nuclei_runner.shutil, "which", lambda n: "/usr/bin/nuclei")

    out = asyncio.run(nuclei_runner.run_nuclei_template("internal.target.test", "x"))
    assert out["ok"] is False
    assert "non-public" in out["error"]
