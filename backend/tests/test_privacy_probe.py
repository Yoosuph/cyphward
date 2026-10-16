"""Static privacy probe (C2a): parsers and the fetcher against fixture websites only.

Sites are served by httpx.MockTransport (no network, no live third-party site).
Fixture hostnames resolve to a documentation IP through a patched resolver;
the private-IP test uses the real ip_guard.
"""
import asyncio
import pathlib

import httpx
import pytest

from backend.app.scanner import ip_guard, privacy_probe as pp

FIX = pathlib.Path(__file__).parent / "fixtures" / "privacy_sites"
HTML = lambda name: (FIX / name).read_text()
NOT_FOUND = (404, {}, "<html><title>Not found</title><h1>404</h1></html>")
PUBLIC_IP = "93.184.216.34"


class Site:
    """host -> {path: (status, headers, body)}; anything else 404 (or the catch-all page)."""

    def __init__(self, pages, catch_all=None):
        self.pages, self.catch_all, self.requests = pages, catch_all, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        path = request.url.raw_path.decode()
        self.requests.append((host, path))
        status, headers, body = self.pages.get((host, path)) or (
            (200, {}, self.catch_all) if self.catch_all is not None else NOT_FOUND)
        return httpx.Response(status, headers=headers, text=body)


@pytest.fixture(autouse=True)
def public_resolver(monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip",
                        lambda host: None if host.startswith("private.") else PUBLIC_IP)


def probe(site, host="acme.example.test", scope=("acme.example.test",), **kw):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(site.handler)) as client:
            return await pp.probe_privacy_host(host, list(scope), client, **kw)
    return asyncio.run(run())


def page(result, kind):
    return next(p for p in result["pages"] if p["kind"] == kind)


H = "acme.example.test"


def test_policy_and_cookie_notice_linked_in_the_footer():
    site = Site({(H, "/"): (200, {}, HTML("policy_footer.html")),
                 (H, "/legal/privacy"): (200, {}, HTML("privacy_page.html")),
                 (H, "/legal/cookies"): (200, {}, HTML("cookie_page.html"))})
    r = probe(site)
    pol, cookie = page(r, "privacy_policy"), page(r, "cookie_notice")
    assert (pol["matched"], pol["found_by"], pol["url"]) == (True, "link", f"https://{H}/legal/privacy")
    assert cookie["matched"] and cookie["found_by"] == "link"
    assert len(pol["fingerprint"]) == 64 and r["catch_all"] is False


def test_policy_signals_are_heuristic_mentions_and_emails_are_masked():
    site = Site({(H, "/"): (200, {}, HTML("policy_footer.html")),
                 (H, "/legal/privacy"): (200, {}, HTML("privacy_page.html"))})
    signals = probe(site)["policy_signals"]
    assert {k: v["state"] for k, v in signals.items()} == {
        "lawful_basis": "mentioned", "data_subject_rights": "mentioned", "dpo_contact": "mentioned",
        "nigeria_law": "mentioned"}
    assert "@" not in (signals["dpo_contact"]["phrase"] or "")
    assert all(v == {"state": "not_found", "phrase": None} for v in pp.policy_signals("we sell shoes").values())


def test_policy_only_at_a_fixed_path():
    site = Site({(H, "/"): (200, {}, HTML("plain_home.html")),
                 (H, "/privacy-policy"): (200, {}, HTML("privacy_page.html"))})
    pol = page(probe(site), "privacy_policy")
    assert (pol["matched"], pol["found_by"]) == (True, "fixed_path")
    assert pol["fixed_paths"]["/privacy"] == 404


def test_no_policy_records_real_404s_for_every_fixed_path():
    site = Site({(H, "/"): (200, {}, HTML("plain_home.html"))})
    r = probe(site)
    pol = page(r, "privacy_policy")
    assert pol["matched"] is False and r["catch_all"] is False
    assert pol["fixed_paths"] == {p: 404 for p in pp.FIXED_PATHS["privacy_policy"]}


def test_catch_all_site_without_a_policy_is_flagged_and_its_200s_do_not_count():
    site = Site({(H, "/"): (200, {}, HTML("spa_shell.html"))}, catch_all=HTML("spa_shell.html"))
    r = probe(site)
    pol = page(r, "privacy_policy")
    assert r["catch_all"] is True and pol["matched"] is False
    assert all(status == 200 for status in pol["fixed_paths"].values()), "the shell answered every path"


def test_catch_all_site_with_a_linked_policy_still_finds_it():
    home = HTML("spa_shell.html").replace('<div id="root"></div>', '<a href="/privacy">Privacy</a>')
    site = Site({(H, "/"): (200, {}, home), (H, "/privacy"): (200, {}, HTML("privacy_page.html"))},
                catch_all=HTML("spa_shell.html"))
    r = probe(site)
    assert r["catch_all"] is True and page(r, "privacy_policy")["matched"] is True


def test_a_200_page_whose_title_is_not_a_policy_does_not_count():
    site = Site({(H, "/"): (200, {}, HTML("plain_home.html")),
                 (H, "/privacy"): (200, {}, "<html><title>Blog</title><h1>Latest posts</h1></html>")})
    assert page(probe(site), "privacy_policy")["matched"] is False


def test_off_domain_policy_is_recorded_not_fetched():
    site = Site({(H, "/"): (200, {}, HTML("offsite_policy.html"))})
    pol = page(probe(site), "privacy_policy")
    assert pol["off_domain"] is True and pol["url"].startswith("https://app.termly.io/")
    assert not any(host == "app.termly.io" for host, _ in site.requests), "never fetched"


def test_first_response_cookies_keep_names_and_attributes_never_values():
    headers = [("set-cookie", "_ga=GA1.2.SECRETVALUE; Max-Age=63072000; Path=/; Secure; SameSite=Lax"),
               ("set-cookie", "__cf_bm=CFSECRET; HttpOnly; Secure; SameSite=None"),
               ("set-cookie", "sessionid=SESSSECRET; HttpOnly; Secure"),
               ("set-cookie", "PHPSESSID=X1; path=/"), ("set-cookie", "connect.sid=X2; HttpOnly"),
               ("set-cookie", "mystery_pref=dark")]
    site = Site({(H, "/"): (200, headers, HTML("plain_home.html"))})
    cookies = probe(site)["first_response_cookies"]
    assert {c["name"]: c["category"] for c in cookies} == {
        "_ga": "tracker", "__cf_bm": "infrastructure", "sessionid": "necessary", "PHPSESSID": "necessary",
        "connect.sid": "necessary", "mystery_pref": "unknown"}
    assert "SECRET" not in repr(cookies) and "X1" not in repr(cookies)
    ga = next(c for c in cookies if c["name"] == "_ga")
    assert ga["vendor"] == "google_analytics" and ga["secure"] and ga["samesite"] == "Lax"


def test_trackers_consent_blocking_and_consent_managers():
    direct = pp.detect_trackers(pp.parse_page(HTML("policy_footer.html")))
    assert {(t["vendor"], t["source"], t["strength"], t["consent_blocked"]) for t in direct} == {
        ("google_analytics", "script_src", "direct", False), ("google_analytics", "inline", "direct", False)}
    blocked = pp.detect_trackers(pp.parse_page(HTML("consent_blocked.html")))
    assert blocked == [{"vendor": "google_analytics", "source": "script_src", "strength": "direct", "consent_blocked": True}]
    assert pp.detect_consent_manager(HTML("consent_blocked.html")) == "cookiebot"
    assert [t["vendor"] for t in pp.detect_trackers(pp.parse_page(HTML("meta_inline.html")))] == ["meta"]
    loader = pp.detect_trackers(pp.parse_page(HTML("gtm_only.html")))
    assert {t["strength"] for t in loader} == {"loader"}, "a tag manager alone is only a loader"
    assert pp.detect_consent_manager(HTML("plain_home.html")) is None


def test_security_txt_with_and_without_contact():
    with_contact = Site({(H, "/"): (200, {}, HTML("plain_home.html")),
                         (H, "/.well-known/security.txt"): (200, {}, "Contact: mailto:sec@acme.example.test\n")})
    assert probe(with_contact)["security_txt"] == {"present": True, "has_contact": True}
    assert probe(Site({(H, "/"): (200, {}, HTML("plain_home.html"))}))["security_txt"]["present"] is False
    assert pp.parse_security_txt("Expires: 2027-01-01")["has_contact"] is False


# ── Fetcher safety ─────────────────────────────────────────────────────────
def test_in_scope_redirect_is_followed_and_off_scope_redirect_is_stopped():
    site = Site({(H, "/"): (301, {"location": f"https://www.{H}/"}, ""),
                 (f"www.{H}", "/"): (200, {}, HTML("plain_home.html")),
                 (H, "/out"): (302, {"location": "https://tracker.example.org/x"}, "")})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(site.handler)) as client:
            ok = await pp.fetch_in_scope(client, f"https://{H}/", [H])
            out = await pp.fetch_in_scope(client, f"https://{H}/out", [H])
            return ok, out
    ok, out = asyncio.run(run())
    assert ok["status"] == 200 and ok["final_url"] == f"https://www.{H}/"
    assert out["status"] is None and out["off_scope_host"] == "tracker.example.org"
    assert not any(host == "tracker.example.org" for host, _ in site.requests)


def test_private_ip_is_refused_with_the_real_guard(monkeypatch):
    monkeypatch.undo()  # real ip_guard: 127.0.0.1 is never connected to
    site = Site({("127.0.0.1", "/"): (200, {}, "x")})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(site.handler)) as client:
            return await pp.fetch_in_scope(client, "http://127.0.0.1/", ["127.0.0.1"])
    r = asyncio.run(run())
    assert r["status"] is None and r["error"].startswith("refused") and site.requests == []


def test_dns_change_between_hops_is_revalidated(monkeypatch):
    answers = {f"www.{H}": "10.0.0.5"}  # the redirect target now resolves privately
    monkeypatch.setattr(ip_guard, "resolve_connect_ip",
                        lambda host: None if ip_guard.is_public_ip(answers.get(host, PUBLIC_IP)) is False else PUBLIC_IP)
    site = Site({(H, "/"): (301, {"location": f"https://www.{H}/"}, "")})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(site.handler)) as client:
            return await pp.fetch_in_scope(client, f"https://{H}/", [H])
    r = asyncio.run(run())
    assert r["status"] is None and "non-public" in r["error"]


def test_body_is_capped():
    site = Site({(H, "/"): (200, {}, "<html>" + "a" * 50_000 + "</html>")})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(site.handler)) as client:
            return await pp.fetch_in_scope(client, f"https://{H}/", [H], max_bytes=1000)
    assert len(asyncio.run(run())["body"]) == 1000


def test_page_budget_is_respected_and_never_becomes_not_found():
    site = Site({(H, "/"): (200, {}, HTML("plain_home.html"))})
    r = probe(site, max_pages=4)
    assert r["fetches"] <= 4
    pol = page(r, "privacy_policy")
    assert pol["matched"] is False and len(pol["fixed_paths"]) < len(pp.FIXED_PATHS["privacy_policy"])


def test_timeout_or_unreachable_homepage_fails_the_host_instead_of_not_found():
    def boom(request):
        raise httpx.ConnectTimeout("timed out")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
            return await pp.run_privacy_batch([H], [H], client=client)
    batch = asyncio.run(run())
    assert batch.successful_hosts == [] and H in batch.failed_hosts and "ConnectTimeout" in batch.failed_hosts[H]
