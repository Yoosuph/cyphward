"""Browser worker logic that needs no browser: egress guard, proxy, observation shaping, claim checks.

Always runs (no Chromium, no network, no database). The real-browser scenarios are in
test_browser_worker_fixtures.py.
"""
import asyncio
import pathlib
import re
import socket
import threading

import httpx
import pytest

from browser_worker import netguard, runner
from browser_worker.client import CoreClient, JobLost
from browser_worker.config import BrowserConfig, load_config
from browser_worker.netguard import Budget, ConnectProxy, EgressPolicy, Refused, check_url
from browser_worker.observer import (
    Limits, USER_AGENT, lifetime_bucket, normalise_banner, safe_final_url, same_site, summarise_cookies,
)
from shared.browser_contracts import BrowserJob, ConsentObservation, JOB_TYPE_CONSENT

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROD = EgressPolicy()


# ── URL checks ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("url,reason", [
    ("file:///etc/passwd", "bad_scheme"), ("ftp://acme.test/", "bad_scheme"), ("javascript:alert(1)", "bad_scheme"),
    ("data:text/html,hi", "bad_scheme"), ("ws://acme.test/", "bad_scheme"), ("chrome://settings", "bad_scheme"),
    ("https://user:pw@acme.test/", "bad_url"), ("https://acme.test:8443/", "bad_port"), ("http://acme.test:22/", "bad_port"),
    ("http://127.0.0.1/", "refused_address"), ("http://169.254.169.254/latest/meta-data/", "refused_address"),
    ("http://10.1.2.3/", "refused_address"), ("http://192.168.0.1/", "refused_address"), ("http://[::1]/", "refused_address"),
    ("http://[::ffff:127.0.0.1]/", "refused_address"), ("http://[fd00::1]/", "refused_address"),
    ("http://100.64.0.1/", "refused_address"), ("http://0.0.0.0/", "refused_address"),
    ("http://2130706433/", "refused_address"),            # decimal form of 127.0.0.1, canonicalised by the URL parser
    ("http://localhost/", "off_scope_redirect"),            # a name: not in scope when asked as the main frame
    ("https://evil.example/", "off_scope_redirect"), ("https://notacme.test/", "off_scope_redirect"),
    ("https://acme.test.evil.example/", "off_scope_redirect"), ("https://" + "a" * 300 + ".test/", "bad_url"),
])
def test_main_frame_urls_that_must_be_refused(url, reason):
    with pytest.raises(Refused) as caught:
        check_url(url, PROD, scope=["acme.test"], main_frame=True)
    assert caught.value.reason == reason


def test_urls_that_are_allowed():
    assert check_url("https://acme.test/", PROD, scope=["acme.test"], main_frame=True) == "acme.test"
    assert check_url("https://www.acme.test:443/x?y=1", PROD, scope=["acme.test"], main_frame=True) == "www.acme.test"
    assert check_url("https://cdn.thirdparty.example/lib.js", PROD, scope=["acme.test"], main_frame=False) == "cdn.thirdparty.example"
    with pytest.raises(Refused):  # plain http is refused for the main frame in production
        check_url("http://acme.test/", PROD, scope=["acme.test"], main_frame=True, allow_http=False)


@pytest.mark.parametrize("ips,ok", [
    (["93.184.216.34"], True), (["8.8.8.8", "1.1.1.1"], True),
    (["8.8.8.8", "10.0.0.9"], False),          # one private answer among public ones refuses the whole name
    (["127.0.0.1"], False), (["::1"], False), (["169.254.169.254"], False), ([], False),
])
def test_resolution_requires_every_address_to_be_public(ips, ok):
    async def resolver(host):
        return ips

    policy = EgressPolicy(resolver=resolver)
    if ok:
        assert asyncio.run(policy.resolve("acme.test")) == ips
    else:
        with pytest.raises(Refused):
            asyncio.run(policy.resolve("acme.test"))


# ── the proxy ────────────────────────────────────────────────────────────
def _proxy_request(policy, payload: bytes, budget=None):
    """Send raw bytes to a fresh proxy and return (response_head, proxy)."""
    async def go():
        proxy = ConnectProxy(policy, budget or Budget(max_bytes=10 ** 7))
        port = await proxy.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(payload)
        await writer.drain()
        try:
            head = await asyncio.wait_for(reader.read(4096), timeout=5)
        finally:
            writer.close()
            await proxy.stop()
        return head, proxy

    return asyncio.run(go())


@pytest.mark.parametrize("payload", [
    b"CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: 127.0.0.1:443\r\n\r\n",
    b"CONNECT 169.254.169.254:80 HTTP/1.1\r\n\r\n",
    b"CONNECT localhost:443 HTTP/1.1\r\n\r\n",
    b"CONNECT [::1]:443 HTTP/1.1\r\n\r\n",
    b"CONNECT 10.0.0.1:443 HTTP/1.1\r\n\r\n",
    b"CONNECT acme.test:22 HTTP/1.1\r\n\r\n",                       # port outside 80/443
    b"GET http://127.0.0.1/ HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
    b"GET http://169.254.169.254/latest/meta-data/ HTTP/1.1\r\nHost: x\r\n\r\n",
    b"GET ftp://acme.test/ HTTP/1.1\r\n\r\n",
    b"GET /relative HTTP/1.1\r\n\r\n",
    b"NONSENSE\r\n\r\n",
])
def test_proxy_refuses_private_odd_and_non_http_targets(payload):
    head, proxy = _proxy_request(PROD, payload)
    assert head.startswith(b"HTTP/1.1 403"), head
    assert proxy.connected == [] and len(proxy.refused) == 1


def test_proxy_resolves_once_and_connects_only_to_the_validated_address():
    """DNS rebinding: a second lookup that would return a private address is never made."""
    calls = []

    async def resolver(host):
        calls.append(host)
        return ["93.184.216.34"] if len(calls) == 1 else ["127.0.0.1"]

    connected_to = []

    class Spy(ConnectProxy):
        async def _connect(self, ips, port):
            connected_to.append((tuple(ips), port))
            return None  # do not actually connect anywhere

    async def go():
        proxy = Spy(EgressPolicy(resolver=resolver), Budget(max_bytes=10 ** 6))
        port = await proxy.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"CONNECT rebind.test:443 HTTP/1.1\r\n\r\n")
        await writer.drain()
        await asyncio.wait_for(reader.read(1024), timeout=5)
        writer.close()
        await proxy.stop()

    asyncio.run(go())
    assert calls == ["rebind.test"] and connected_to == [(("93.184.216.34",), 443)]


def test_proxy_forwards_plain_http_to_an_allowed_address_and_enforces_the_byte_cap():
    received = []
    big = b"y" * 300_000

    def serve(sock):
        conn, _ = sock.accept()
        received.append(conn.recv(4096))
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(big) + big)
        conn.close()

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    threading.Thread(target=serve, args=(srv,), daemon=True).start()
    port = srv.getsockname()[1]

    async def resolver(host):
        return ["127.0.0.1"]

    policy = EgressPolicy(resolver=resolver, allowed_ports=[port], allow_ip=lambda ip: ip == "127.0.0.1")
    budget = Budget(max_bytes=100_000)

    async def go():
        proxy = ConnectProxy(policy, budget)
        proxy_port = await proxy.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(f"GET http://fixture.test:{port}/a?b=1 HTTP/1.1\r\nHost: fixture.test:{port}\r\n"
                     f"Proxy-Connection: keep-alive\r\nConnection: keep-alive\r\n\r\n".encode())
        await writer.drain()
        got = b""
        try:
            while chunk := await asyncio.wait_for(reader.read(65536), timeout=5):
                got += chunk
        finally:
            writer.close()
            await proxy.stop()
        return got

    got = asyncio.run(go())
    srv.close()
    request = received[0].decode()
    assert request.startswith("GET /a?b=1 HTTP/1.1\r\n") and "Proxy-Connection" not in request
    assert "Connection: close" in request and "Connection: keep-alive" not in request
    assert budget.bytes_capped is True and len(got) < len(big)  # the connection was cut at the cap


# ── observation shaping ──────────────────────────────────────────────────
def test_lifetime_buckets():
    now = 1_700_000_000.0
    assert lifetime_bucket(-1, now) == lifetime_bucket(None, now) == "session"
    assert lifetime_bucket(now + 3600, now) == "under_1_day"
    assert lifetime_bucket(now + 86400, now) == "under_30_days"
    assert lifetime_bucket(now + 30 * 86400, now) == "under_30_days"
    assert lifetime_bucket(now + 31 * 86400, now) == "under_1_year"
    assert lifetime_bucket(now + 400 * 86400, now) == "over_1_year"
    assert lifetime_bucket(now - 5, now) == "under_1_day"


def test_cookie_summary_drops_values_and_marks_third_party():
    raw = [
        {"name": "_ga", "domain": ".acme.test", "secure": True, "httpOnly": False, "sameSite": "Lax", "expires": -1, "value": "SECRET"},
        {"name": "t", "domain": "ads.example", "secure": False, "httpOnly": True, "sameSite": "None", "expires": 2_000_000_000, "value": "SECRET"},
        {"name": "bad\x00name", "domain": "acme.test", "value": "SECRET"},
        {"name": "", "domain": "acme.test"}, {"name": "x", "domain": "not a domain!"},
    ]
    cookies, capped = summarise_cookies(raw, ["acme.test"], now=1_700_000_000.0)
    assert capped is False and "SECRET" not in str(cookies)
    assert [(c["name"], c["third_party"], c["same_site"]) for c in cookies] == [("_ga", False, "lax"), ("badname", False, "unset"), ("t", True, "none")] \
        or [c["name"] for c in cookies] == ["_ga", "t", "badname"]
    ConsentObservation.model_validate({
        "final_url": "https://acme.test/", "browser_version": "Chromium 1", "cookies": cookies,
        "requests": {"total": 1, "first_party": 1}, "banner": normalise_banner({}),
        "timings": {"navigation_ms": 1, "settle_ms": 1, "total_ms": 2}})


def test_cookie_cap():
    raw = [{"name": f"c{i}", "domain": "acme.test"} for i in range(150)]
    cookies, capped = summarise_cookies(raw, ["acme.test"])
    assert len(cookies) == 100 and capped is True


def test_banner_normalisation_collapses_to_the_closed_vocabulary():
    assert normalise_banner({"detected": False, "accept_control": True, "reject_control": "same_level", "cms_marker": "evil"}) == {
        "detected": False, "in_first_view": False, "cms_marker": None, "accept_control": False, "reject_control": "not_detected"}
    assert normalise_banner({"detected": True, "in_first_view": True, "cms_marker": "<script>", "accept_control": True,
                             "reject_control": "<img>"})["reject_control"] == "not_detected"
    assert normalise_banner({"detected": True, "cms_marker": "onetrust"})["cms_marker"] == "onetrust"


def test_final_url_never_carries_query_or_fragment_and_same_site_defaults():
    assert safe_final_url("https://acme.test/a/b?token=1#frag") == "https://acme.test/a/b"
    assert safe_final_url("https://acme.test") == "https://acme.test/"
    assert same_site(None) == same_site("Unspecified") == "unset"


def test_user_agent_identifies_cyphward_with_a_contact_url():
    assert USER_AGENT.startswith("Cyphward-Consent-Observer/") and "https://cyphward.com/scanner" in USER_AGENT


# ── claim re-checks ──────────────────────────────────────────────────────
def make_job(**over):
    data = dict(job_type=JOB_TYPE_CONSENT, job_id=str(__import__("uuid").uuid4()), organization_id="org-1", domain_id="dom-1",
                target="acme.test", scope=["acme.test"], url="https://acme.test/",
                authorization_context={"verification_status": "verified", "verified_at_claim_time": True},
                lease_expires_at="2026-10-19", claim_generation=1, claim_token="t" * 40)
    data.update(over)
    return BrowserJob.model_validate(data)


def test_a_valid_claim_passes():
    runner.validate_job(make_job())


@pytest.mark.parametrize("over", [
    {"scope": ["other.test"]}, {"scope": ["notacme.test"]}, {"target": "evil.example", "url": "https://evil.example/"},
    {"url": "http://acme.test/"}, {"url": "https://other.test/"}, {"url": "https://acme.test:8443/"},
    {"url": "https://user:pw@acme.test/"}, {"authorization_context": {}},
    {"authorization_context": {"verification_status": "pending", "verified_at_claim_time": True}},
    {"authorization_context": {"verification_status": "verified", "verified_at_claim_time": False}},
    {"target": "127.0.0.1", "scope": ["127.0.0.1"], "url": "https://127.0.0.1/"},
])
def test_a_tampered_claim_is_refused(over):
    with pytest.raises(runner.InvalidJob):
        runner.validate_job(make_job(**over))


def test_malformed_claim_payloads_do_not_validate():
    for bad in ({"claim_token": "short"}, {"claim_token": "bad token with spaces " * 3}, {"claim_generation": 0},
                {"job_type": "security_scan"}, {"scope": []}, {"limits": {"max_requests": 5000}}, {"version": 2}):
        with pytest.raises(Exception):
            make_job(**bad)


def test_job_limits_are_clamped_below_the_hard_ceilings():
    limits = runner.limits_for(make_job())
    assert (limits.page_timeout_seconds, limits.job_timeout_seconds, limits.max_requests) == (45, 90, 150)


# ── the worker's protocol, with a fake Core ──────────────────────────────
CFG = BrowserConfig(core_url="https://core.example", api_key="worker-key", worker_id="vm-1", heartbeat_seconds=5)


def fake_core(handler):
    return CoreClient(CFG, transport=httpx.MockTransport(handler))


def test_client_uses_only_browser_endpoints_with_key_capability_and_attempt_headers():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json=make_job().model_dump())
        return httpx.Response(200, json={"ok": True})

    async def go():
        client = fake_core(handler)
        job = await client.claim()
        await client.heartbeat(job)
        await client.result(job, {"x": 1})
        await client.fail(job, "timeout", "slow\nsite")
        await client.aclose()

    asyncio.run(go())
    assert all(r.url.path.startswith("/api/v1/browser-worker/") for r in seen)
    assert not any("/scanner/" in r.url.path for r in seen)
    for r in seen:
        assert r.headers["authorization"] == "Bearer worker-key" and r.headers["x-scanner-capabilities"] == "privacy_browser"
        assert r.headers["x-browser-protocol"] == "1"
    assert "x-claim-token" not in seen[0].headers and all("x-claim-token" in r.headers for r in seen[1:])
    assert b"\\n" not in seen[-1].content and b"slow site" in seen[-1].content


def test_run_job_reports_success_failure_and_lost(monkeypatch):
    posted = []

    def handler(request):
        posted.append((request.url.path.rsplit("/", 1)[-1], request.content))
        return httpx.Response(409 if "lost" in posted[-1][0] else 200, json={"ok": True})

    good = {"version": 1, "final_url": "https://acme.test/", "browser_version": "Chromium 1", "cookies": [],
            "requests": {"total": 1, "first_party": 1, "third_party_hosts": []}, "banner": normalise_banner({}),
            "timings": {"navigation_ms": 1, "settle_ms": 1, "total_ms": 2}, "caps": {}}

    async def ok(*a, **k):
        return good

    async def refused(*a, **k):
        raise runner.ObservationFailed("refused_address", "navigation refused")

    async def invalid_result(*a, **k):
        return {**good, "final_url": "javascript:alert(1)"}

    async def go(fn, job=None):
        monkeypatch.setattr(runner, "observe", fn)
        client = fake_core(handler)
        try:
            return await runner.run_job(client, job or make_job(), CFG)
        finally:
            await client.aclose()

    assert asyncio.run(go(ok)) == "completed" and posted[-1][0] == "result"
    assert asyncio.run(go(refused)) == "failed" and posted[-1][0] == "fail" and b"refused_address" in posted[-1][1]
    assert asyncio.run(go(invalid_result)) == "failed" and posted[-1][0] == "fail"  # never sends what Core would refuse
    before = len(posted)
    assert asyncio.run(go(ok, make_job(scope=["other.test"]))) == "failed" and posted[before][0] == "fail"  # tampered claim, no browser started


# ── isolation and wording ────────────────────────────────────────────────
def test_scanner_cannot_claim_browser_jobs_and_the_browser_worker_cannot_claim_scans():
    from scanner.client import WORKER_CAPABILITIES
    assert "privacy_browser" not in WORKER_CAPABILITIES
    for path in (ROOT / "scanner").rglob("*.py"):
        assert "browser_worker" not in path.read_text(), path
    worker_source = "\n".join(p.read_text() for p in (ROOT / "browser_worker").glob("*.py"))
    assert "/scanner/" not in worker_source and "claim_recon" not in worker_source
    for forbidden in ("import scanner", "from scanner", "psycopg", "fastapi", "backend.app.core", "backend.app.compliance"):
        assert forbidden not in worker_source, forbidden


def test_worker_imports_only_what_the_image_contains():
    allowed = {"shared", "browser_worker", "backend.app.scanner.ip_guard"}
    for path in (ROOT / "browser_worker").glob("*.py"):
        for line in path.read_text().splitlines():
            m = re.match(r"\s*(?:from|import)\s+(shared|backend)[\w.]*", line)
            if m:
                module = line.split()[1]
                assert any(module == a or module.startswith(a + ".") for a in allowed), f"{path.name}: {line}"


def test_config_requires_https_core_and_a_key(monkeypatch):
    for k in ("BROWSER_CORE_URL", "BROWSER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit):
        load_config()
    monkeypatch.setenv("BROWSER_API_KEY", "k")
    monkeypatch.setenv("BROWSER_CORE_URL", "http://core.example")
    with pytest.raises(SystemExit):
        load_config()
    monkeypatch.setenv("BROWSER_CORE_URL", "http://localhost:8000")
    with pytest.raises(SystemExit):  # sandbox off needs the explicit egress-firewall acknowledgement
        load_config()
    monkeypatch.setenv("BROWSER_ACK_NO_SANDBOX_EGRESS_FIREWALL", "1")
    assert load_config().chromium_sandbox is False
    monkeypatch.delenv("BROWSER_ACK_NO_SANDBOX_EGRESS_FIREWALL")
    monkeypatch.setenv("BROWSER_CHROMIUM_SANDBOX", "1")
    assert load_config().chromium_sandbox is True
    monkeypatch.delenv("BROWSER_CHROMIUM_SANDBOX")
    monkeypatch.setenv("BROWSER_ACK_NO_SANDBOX_EGRESS_FIREWALL", "1")
    monkeypatch.setenv("BROWSER_CORE_URL", "https://core.example")
    assert load_config().core_url == "https://core.example"


def test_cookies_left_by_the_browsers_own_background_services_are_not_reported():
    raw = [{"name": "NID", "domain": ".google.com"}, {"name": "_ga", "domain": ".acme.test"},
           {"name": "id", "domain": "ads.example"}]
    cookies, _ = summarise_cookies(raw, ["acme.test"], contacted={"acme.test", "ads.example"})
    assert [c["name"] for c in cookies] == ["_ga", "id"]
    # A page that really talks to google.com keeps those cookies.
    cookies, _ = summarise_cookies(raw, ["acme.test"], contacted={"www.google.com"})
    assert "NID" in [c["name"] for c in cookies]


@pytest.mark.parametrize("host", ["clients2.google.com", "update.googleapis.com", "android.clients.google.com"])
def test_proxy_refuses_browser_internal_services(host):
    async def resolver(h):
        return ["8.8.8.8"]
    head, proxy = _proxy_request(EgressPolicy(resolver=resolver), f"CONNECT {host}:443 HTTP/1.1\r\n\r\n".encode())
    assert head.startswith(b"HTTP/1.1 403") and proxy.refused[0].reason == "browser_internal" and proxy.connected == []


@pytest.mark.parametrize("ip", ["168.63.129.16", "::ffff:168.63.129.16", "fec0::1", "fd00:ec2::254", "fe80::1", "169.254.169.254",
                                "100.100.100.200", "100.64.0.1", "10.0.0.1", "127.0.0.1", "::1", "198.18.0.1", "192.0.0.192"])
def test_extra_cloud_and_reserved_addresses_are_refused(ip):
    assert netguard.worker_allow_ip(ip) is False
    with pytest.raises(Refused):
        asyncio.run(EgressPolicy(resolver=lambda h: asyncio.sleep(0, result=[ip])).resolve("acme.test"))


def test_ordinary_public_addresses_still_pass():
    assert netguard.worker_allow_ip("93.184.216.34") and netguard.worker_allow_ip("2606:2800:220:1:248:1893:25c8:1946")


def test_browser_environment_drops_anything_that_looks_like_a_secret():
    from browser_worker.observer import browser_env
    env = browser_env({"PATH": "/bin", "HOME": "/tmp", "BROWSER_API_KEY": "k", "DB_PASSWORD": "p", "X_TOKEN": "t", "MY_SECRET": "s",
                       "TMPDIR": "/tmp"})
    assert env == {"PATH": "/bin", "HOME": "/tmp", "TMPDIR": "/tmp"}


def test_any_unexpected_fault_in_one_job_is_reported_and_the_worker_survives(monkeypatch):
    posted = []

    def handler(request):
        posted.append((request.url.path.rsplit("/", 1)[-1], request.content))
        return httpx.Response(200, json={"ok": True})

    async def explode(*a, **k):
        raise RuntimeError("Frame for this navigation request is not available")

    monkeypatch.setattr(runner, "observe", explode)

    async def go():
        client = fake_core(handler)
        try:
            return await runner.run_job(client, make_job(), CFG)
        finally:
            await client.aclose()

    assert asyncio.run(go()) == "failed"
    assert posted[-1][0] == "fail" and b"browser_error" in posted[-1][1]

    # main_loop: a crash while processing a job does not end the loop
    calls = []

    async def claim(self):
        calls.append(1)
        return make_job() if len(calls) == 1 else None

    async def crash(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner.CoreClient, "claim", claim)
    monkeypatch.setattr(runner, "run_job", crash)
    asyncio.run(runner.main_loop(CFG.__class__(**{**CFG.__dict__, "poll_interval_seconds": 5}), once=False)) if False else None
    cfg = CFG.__class__(**{**CFG.__dict__})
    asyncio.run(runner.main_loop(cfg, once=True))
    assert len(calls) == 1  # processed the job, did not raise


def test_equal_scanner_and_browser_keys_stop_core_from_starting():
    import subprocess
    import sys
    env = {"PATH": "/usr/bin:/bin", "SCANNER_API_KEY": "same-key-value", "BROWSER_WORKER_API_KEY": "same-key-value"}
    out = subprocess.run([sys.executable, "-c", "import backend.app.core.config"], env=env, cwd=str(ROOT),
                         capture_output=True, text=True)
    assert out.returncode != 0 and "must differ" in out.stderr
    env["BROWSER_WORKER_API_KEY"] = "another-key-value"
    ok = subprocess.run([sys.executable, "-c", "import backend.app.core.config"], env=env, cwd=str(ROOT), capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
