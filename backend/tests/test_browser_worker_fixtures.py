"""Browser worker against localhost fixture sites, with a real headless Chromium.

Skipped cleanly (with the reason) when playwright or a Chromium binary is missing; the browser-worker
CI job installs both and fails on any skip. The observation logic and the egress guard are also tested
without a browser in test_browser_worker_logic.py, which always runs.
"""
import asyncio
import os
import shutil
import time

import pytest

pytest.importorskip("playwright")

from backend.tests.browser_fixture_sites import FixtureServer  # noqa: E402
from browser_worker.netguard import Refused  # noqa: E402
from browser_worker.observer import Limits, ObservationFailed, observe  # noqa: E402
from shared.browser_contracts import ConsentObservation  # noqa: E402


def _chromium():
    """CYPHWARD_TEST_CHROMIUM, then Playwright's own download, then a system Chromium."""
    explicit = os.environ.get("CYPHWARD_TEST_CHROMIUM")
    if explicit:
        return explicit if os.path.exists(explicit) else None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            bundled = p.chromium.executable_path
        if os.path.exists(bundled):
            return bundled
    except Exception:  # noqa: BLE001 - any failure here only means "no bundled browser"
        pass
    for candidate in (shutil.which("chromium"), "/usr/sbin/chromium", shutil.which("google-chrome")):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


CHROMIUM = _chromium()
pytestmark = pytest.mark.skipif(CHROMIUM is None, reason="no Chromium binary available")
FAST = Limits(page_timeout_seconds=6, job_timeout_seconds=40, settle_seconds=0.6)


@pytest.fixture(scope="module")
def site():
    server = FixtureServer()
    yield server
    server.close()


def run(site, host, limits=FAST, scope=None, **kw):
    return asyncio.run(observe(site.url(host), scope or [host], site.policy(), limits=limits, chromium_path=CHROMIUM,
                               sandbox=False, allow_http=True, **kw))


def valid(result):
    return ConsentObservation.model_validate(result)  # the exact model Core applies


def test_cookies_set_before_any_choice_are_recorded_with_flags_and_third_party_hosts(site):
    result = run(site, "cookies.test")
    obs = valid(result)
    names = {c.name: c for c in obs.cookies}
    assert {"_ga", "sid", "_fbp"} <= set(names)
    assert names["_ga"].lifetime == "over_1_year" and names["_ga"].third_party is False
    assert names["sid"].http_only is True and names["sid"].same_site == "lax" and names["sid"].lifetime == "session"
    assert names["_fbp"].http_only is False and names["_fbp"].lifetime == "under_1_year"
    assert [h.host for h in obs.requests.third_party_hosts] == ["tracker.test"]
    assert obs.requests.first_party >= 1 and obs.final_url == site.url("cookies.test")
    assert obs.browser_version.startswith("Chromium ") and obs.timings.total_ms > 0
    assert "value" not in str(result["cookies"])  # cookie values never leave the browser
    assert obs.caps.requests is False and obs.caps.bytes is False


def test_clean_first_visit(site):
    obs = valid(run(site, "clean.test"))
    assert obs.cookies == [] and obs.requests.third_party_hosts == []
    assert obs.banner.detected is False and obs.banner.reject_control == "not_detected"


def test_banner_with_accept_and_reject_at_the_same_level(site):
    banner = valid(run(site, "banner-both.test")).banner
    assert (banner.detected, banner.in_first_view, banner.cms_marker) == (True, True, "onetrust")
    assert banner.accept_control is True and banner.reject_control == "same_level"


def test_banner_without_a_reject_button(site):
    banner = valid(run(site, "banner-accept-only.test")).banner
    assert banner.detected and banner.accept_control and banner.reject_control == "not_detected"
    assert banner.cms_marker == "generic_dialog"


def test_banner_with_a_small_reject_link_is_less_prominent(site):
    banner = valid(run(site, "banner-small-reject.test")).banner
    assert banner.accept_control and banner.reject_control == "less_prominent"


@pytest.mark.parametrize("host,reason", [
    ("redirect-metadata.test", "refused_address"),            # cloud metadata address
    ("redirect-private.test", "refused_address"),             # RFC 1918
    ("redirect-offscope.test", "off_scope_redirect"),         # a public host outside the verified scope
    ("redirect-hostname-private.test", "off_scope_redirect"), # a name that resolves privately is also out of scope
])
def test_redirects_to_private_or_off_scope_addresses_are_refused(site, host, reason):
    with pytest.raises(ObservationFailed) as caught:
        run(site, host)
    assert caught.value.reason == reason
    assert "169.254.169.254" not in site.seen_hosts and "10.0.0.5" not in site.seen_hosts


def test_in_scope_redirect_is_followed(site):
    obs = valid(run(site, "redirect-inscope.test"))
    assert obs.final_url.endswith("/landing") and "www.redirect-inscope.test" in obs.final_url


def test_sub_request_to_a_private_name_is_refused_and_the_visit_still_completes(site):
    before = len(site.seen_hosts)
    obs = valid(run(site, "subresource-private.test"))
    assert obs.banner.detected is False
    assert "private.test" not in site.seen_hosts[before:]


def test_slow_site_times_out(site):
    started = time.monotonic()
    with pytest.raises(ObservationFailed) as caught:
        run(site, "slow.test", limits=Limits(page_timeout_seconds=3, job_timeout_seconds=30, settle_seconds=0.2))
    assert caught.value.reason == "timeout" and time.monotonic() - started < 15


def test_job_time_limit_is_a_hard_stop(site):
    started = time.monotonic()
    with pytest.raises(ObservationFailed) as caught:
        run(site, "slow.test", limits=Limits(page_timeout_seconds=30, job_timeout_seconds=3, settle_seconds=0.2))
    assert caught.value.reason == "timeout" and time.monotonic() - started < 12


def test_huge_page_is_capped_by_bytes(site):
    obs = valid(run(site, "huge.test", limits=Limits(page_timeout_seconds=15, job_timeout_seconds=40,
                                                    max_total_bytes=2 * 1024 * 1024, settle_seconds=0.3)))
    assert obs.caps.bytes is True


def test_sub_request_count_is_capped(site):
    obs = valid(run(site, "images.test", limits=Limits(page_timeout_seconds=10, job_timeout_seconds=40,
                                                      max_requests=20, settle_seconds=0.5)))
    assert obs.requests.total <= 20 and obs.caps.requests is True


def test_a_download_is_not_saved_and_does_not_crash(site):
    with pytest.raises(ObservationFailed):
        run(site, "download.test")


def test_a_popup_does_not_break_the_visit(site):
    obs = valid(run(site, "popup.test"))
    assert obs.final_url == site.url("popup.test")


def test_a_script_redirect_off_scope_after_load_is_reported_not_raised_raw(site):
    with pytest.raises(ObservationFailed) as caught:
        run(site, "script-redirect.test", limits=Limits(page_timeout_seconds=6, job_timeout_seconds=40, settle_seconds=1.5))
    assert caught.value.reason in ("off_scope_redirect", "browser_error")


def test_the_browser_process_does_not_inherit_the_workers_key(site, monkeypatch):
    from browser_worker import observer
    monkeypatch.setenv("BROWSER_API_KEY", "super-secret-worker-key")
    monkeypatch.setenv("SOME_SERVICE_TOKEN", "t")
    seen = {}
    real = observer.browser_env

    def spy(environ=None):
        seen.update(real(environ))
        return real(environ)

    monkeypatch.setattr(observer, "browser_env", spy)
    valid(run(site, "clean.test"))
    assert seen and "BROWSER_API_KEY" not in seen and "SOME_SERVICE_TOKEN" not in seen and "PATH" in seen


def test_the_environment_handed_to_chromium_never_holds_the_workers_key(site, monkeypatch):
    """Checks what is actually passed to the browser launch, with the key in the worker's own environment.

    (Reading /proc/<pid>/environ of the live browser was tried and rejected: Chromium rewrites its
    environment block, so a positive control marker did not even show up there.)"""
    from playwright._impl import _browser_type
    secret = "super-secret-worker-key-for-launch-test"
    monkeypatch.setenv("BROWSER_API_KEY", secret)
    monkeypatch.setenv("UPSTREAM_SERVICE_TOKEN", secret)
    monkeypatch.setenv("CYPHWARD_CONTROL_MARKER", "visible-to-chromium")
    launched = []
    real = _browser_type.BrowserType.launch

    async def spy(self, **kwargs):
        launched.append(kwargs.get("env"))
        return await real(self, **kwargs)

    monkeypatch.setattr(_browser_type.BrowserType, "launch", spy)
    valid(run(site, "clean.test"))
    assert len(launched) == 1 and isinstance(launched[0], dict)
    assert secret not in " ".join(launched[0].values()) and "BROWSER_API_KEY" not in launched[0]
    assert launched[0].get("CYPHWARD_CONTROL_MARKER") == "visible-to-chromium" and "PATH" in launched[0]  # the control: it is the real environment


def test_hard_ceilings_override_a_generous_job():
    wide = Limits(page_timeout_seconds=9999, job_timeout_seconds=9999, max_requests=10 ** 6, max_total_bytes=10 ** 12,
                  settle_seconds=99).clamped()
    assert (wide.page_timeout_seconds, wide.job_timeout_seconds, wide.max_requests, wide.settle_seconds) == (45, 90, 150, 5.0)
    assert wide.max_total_bytes == 25 * 1024 * 1024


def test_production_address_rule_refuses_a_name_that_resolves_to_loopback_through_the_browser(site):
    """No test widening of the address rule: the proxy sees the name resolve to 127.0.0.1 and refuses."""
    from browser_worker.netguard import EgressPolicy

    async def resolver(host):
        return ["127.0.0.1"]

    class AnyPort:
        def __contains__(self, port):
            return True

    policy = EgressPolicy(resolver=resolver, allowed_ports=AnyPort())  # default allow_ip: public addresses only
    before = len(site.seen_hosts)
    with pytest.raises(ObservationFailed) as caught:
        asyncio.run(observe(f"http://looks-public.test:{site.port}/", ["looks-public.test"], policy, limits=FAST,
                            chromium_path=CHROMIUM, allow_http=True))
    assert caught.value.reason == "refused_address"
    assert len(site.seen_hosts) == before  # the fixture server never saw a request


def test_refusal_class_is_exported():
    assert issubclass(Refused, Exception)
