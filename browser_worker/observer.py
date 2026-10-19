"""One first-visit observation: load the homepage in a clean headless Chromium, click nothing.

Everything the page does goes through the filtering proxy in netguard.py, and every request is
also checked in the route handler (scheme, port, credentials, literal addresses, and for the
main frame the verified scope). Hard limits are enforced here regardless of what the job asked for.
"""
import asyncio
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlsplit

from browser_worker.netguard import Budget, ConnectProxy, EgressPolicy, Refused, check_url, host_in_scope
from browser_worker.page_script import BANNER_SCRIPT
from shared.browser_contracts import (
    CMS_MARKERS, MAX_COOKIES, MAX_JOB_SECONDS, MAX_PAGE_TIMEOUT_SECONDS, MAX_SUBREQUESTS,
    MAX_THIRD_PARTY_HOSTS, MAX_TOTAL_BYTES,
)
from shared.scanner_identity import SCANNER_INFO_URL

logger = logging.getLogger("cyphward.browser.observer")

USER_AGENT = f"Cyphward-Consent-Observer/1.0 (+{SCANNER_INFO_URL})"
_COOKIE_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# Flags for a small, clean, single-renderer browser. --disable-dev-shm-usage is deliberately NOT here:
# the container gives /dev/shm at least 256 MiB, and the flag would move shared memory to slower disk.
CHROMIUM_FLAGS = (
    "--renderer-process-limit=1", "--disable-gpu", "--disable-extensions", "--disable-sync",
    "--disable-background-networking", "--disable-component-update", "--disable-default-apps",
    "--disable-client-side-phishing-detection", "--disable-breakpad", "--disable-domain-reliability",
    "--disable-notifications", "--disable-quic", "--no-pings", "--no-first-run", "--no-default-browser-check",
    "--mute-audio", "--password-store=basic", "--use-mock-keychain", "--js-flags=--max-old-space-size=192",
    "--disable-features=Translate,MediaRouter,OptimizationHints,InterestFeedContentSuggestions,PrivacySandboxSettings4",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp", "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--proxy-bypass-list=<-loopback>",
)


class ObservationFailed(Exception):
    """The visit could not be observed. `reason` is one of JobFailure.reason."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Limits:
    page_timeout_seconds: float = MAX_PAGE_TIMEOUT_SECONDS
    job_timeout_seconds: float = MAX_JOB_SECONDS
    max_requests: int = MAX_SUBREQUESTS
    max_total_bytes: int = MAX_TOTAL_BYTES
    settle_seconds: float = 3.0

    def clamped(self) -> "Limits":
        """Never above the hard ceilings, whatever a job asks for."""
        return Limits(min(self.page_timeout_seconds, MAX_PAGE_TIMEOUT_SECONDS), min(self.job_timeout_seconds, MAX_JOB_SECONDS),
                      min(self.max_requests, MAX_SUBREQUESTS), min(self.max_total_bytes, MAX_TOTAL_BYTES),
                      min(self.settle_seconds, 5.0))


def lifetime_bucket(expires: Optional[float], now: Optional[float] = None) -> str:
    """Session cookies have no expiry (Playwright reports -1). Others by remaining lifetime."""
    if expires is None or expires < 0:
        return "session"
    seconds = expires - (time.time() if now is None else now)
    if seconds < 86400:
        return "under_1_day"
    if seconds <= 30 * 86400:
        return "under_30_days"
    if seconds <= 366 * 86400:
        return "under_1_year"
    return "over_1_year"


def same_site(value: Optional[str]) -> str:
    return {"strict": "strict", "lax": "lax", "none": "none"}.get((value or "").lower(), "unset")


def summarise_cookies(raw: Sequence[Dict[str, Any]], scope: Sequence[str], now: Optional[float] = None):
    """Names, flags and lifetime bucket only. Cookie values never leave the browser."""
    out: List[Dict[str, Any]] = []
    capped = False
    for c in raw:
        name = _CONTROL.sub("", str(c.get("name") or ""))[:128]
        domain = str(c.get("domain") or "").lower().lstrip(".")
        if not name or not _COOKIE_DOMAIN.match(domain):
            continue
        if len(out) >= MAX_COOKIES:
            capped = True
            break
        out.append({"name": name, "domain": domain, "secure": bool(c.get("secure")), "http_only": bool(c.get("httpOnly")),
                    "same_site": same_site(c.get("sameSite")), "lifetime": lifetime_bucket(c.get("expires"), now),
                    "third_party": not host_in_scope(domain, scope)})
    return out, capped


def safe_final_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path or '/'}"[:300]


def normalise_banner(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Whatever the page script returned, reduced to the contract's closed vocabulary."""
    marker = raw.get("cms_marker")
    detected = bool(raw.get("detected"))
    reject = raw.get("reject_control")
    return {
        "detected": detected,
        "in_first_view": detected and bool(raw.get("in_first_view")),
        "cms_marker": marker if marker in CMS_MARKERS else None,
        "accept_control": detected and bool(raw.get("accept_control")),
        "reject_control": reject if detected and reject in ("same_level", "less_prominent") else "not_detected",
    }


async def observe(url: str, scope: Sequence[str], policy: EgressPolicy, *, limits: Limits = Limits(),
                  chromium_path: Optional[str] = None, sandbox: bool = False, allow_http: bool = False) -> Dict[str, Any]:
    """Return a ConsentObservation-shaped dict, or raise ObservationFailed / Refused."""
    limits = limits.clamped()
    try:
        check_url(url, policy, scope=scope, main_frame=True, allow_http=allow_http)
    except Refused as refusal:
        raise ObservationFailed(refusal.reason if refusal.reason in ("refused_address", "off_scope_redirect") else "invalid_job",
                                f"start url refused: {refusal}")
    try:
        return await asyncio.wait_for(_observe(url, scope, policy, limits, chromium_path, sandbox, allow_http),
                                      timeout=limits.job_timeout_seconds)
    except asyncio.TimeoutError:
        raise ObservationFailed("timeout", "the job time limit was reached")


async def _observe(url, scope, policy, limits: Limits, chromium_path, sandbox, allow_http) -> Dict[str, Any]:
    from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout, async_playwright

    started = time.monotonic()
    budget = Budget(max_bytes=limits.max_total_bytes)
    proxy = ConnectProxy(policy, budget)
    await proxy.start()
    refusals: List[Refused] = []
    first_party = 0
    third_party: Counter = Counter()
    total = 0
    requests_capped = False
    try:
        async with async_playwright() as pw:
            args = list(CHROMIUM_FLAGS) + [f"--proxy-server=http://127.0.0.1:{proxy.port}"]
            if not sandbox:
                args.append("--no-sandbox")  # see docs/runbooks/browser-worker.md, "Sandbox"
            try:
                browser = await pw.chromium.launch(executable_path=chromium_path, headless=True, args=args)
            except PlaywrightError as exc:
                raise ObservationFailed("browser_error", f"browser did not start: {str(exc)[:200]}")
            try:
                context = await browser.new_context(
                    user_agent=USER_AGENT, accept_downloads=False, service_workers="block", permissions=[],
                    viewport={"width": 1280, "height": 800}, locale="en-US", ignore_https_errors=False)

                async def on_route(route):
                    nonlocal first_party, total, requests_capped
                    request = route.request
                    is_main = request.is_navigation_request() and request.frame.parent_frame is None
                    try:
                        host = check_url(request.url, policy, scope=scope, main_frame=is_main, allow_http=allow_http or not is_main)
                    except Refused as refusal:
                        refusals.append(refusal)
                        await route.abort("blockedbyclient")
                        return
                    if total >= limits.max_requests:
                        requests_capped = True
                        await route.abort("blockedbyclient")
                        return
                    total += 1
                    if host_in_scope(host, scope):
                        first_party += 1
                    elif ":" not in host and (host in third_party or len(third_party) < MAX_THIRD_PARTY_HOSTS):
                        third_party[host] += 1
                    await route.continue_()

                await context.route("**/*", on_route)
                page = await context.new_page()
                context.on("page", lambda popup: asyncio.ensure_future(popup.close()) if popup != page else None)
                def on_request(request):
                    # Redirect hops of the main frame are announced here before the next one is followed:
                    # leaving the verified scope stops the visit at once instead of after the page loaded.
                    if request.is_navigation_request() and request.frame.parent_frame is None:
                        try:
                            check_url(request.url, policy, scope=scope, main_frame=True, allow_http=allow_http)
                        except Refused as refusal:
                            refusals.append(refusal)
                            asyncio.ensure_future(page.close())

                page.on("request", on_request)
                page.on("download", lambda d: asyncio.ensure_future(d.cancel()))
                page.on("filechooser", lambda chooser: None)  # never answered: no file is ever chosen
                page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.dismiss()))

                caps = {"requests": False, "bytes": False, "cookies": False, "page_timeout": False}
                nav_start = time.monotonic()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=limits.page_timeout_seconds * 1000)
                except PlaywrightTimeout:
                    raise ObservationFailed("timeout", "the page did not respond in time")
                except PlaywrightError as exc:
                    main_refusal = next((r for r in refusals if r.reason in ("off_scope_redirect", "refused_address")), None)
                    proxy_refusal = next((r for r in proxy.refused if r.reason == "refused_address"), None)
                    chosen = main_refusal or proxy_refusal
                    if chosen:
                        raise ObservationFailed(chosen.reason, f"navigation refused: {chosen.detail or chosen.reason}")
                    raise ObservationFailed("navigation_failed", f"navigation failed: {str(exc).splitlines()[0][:200]}")
                navigation_ms = int((time.monotonic() - nav_start) * 1000)

                settle_start = time.monotonic()
                remaining = max(0.5, limits.page_timeout_seconds - (settle_start - nav_start))
                try:
                    await page.wait_for_load_state("load", timeout=min(remaining, 10) * 1000)
                except PlaywrightTimeout:
                    caps["page_timeout"] = True
                await asyncio.sleep(limits.settle_seconds)  # late scripts and tag managers get their moment
                raw_banner = await page.evaluate(BANNER_SCRIPT)
                raw_cookies = await context.cookies()
                final_url = page.url
                settle_ms = int((time.monotonic() - settle_start) * 1000)
                try:
                    check_url(final_url, policy, scope=scope, main_frame=True, allow_http=allow_http)
                except Refused as refusal:
                    raise ObservationFailed(refusal.reason if refusal.reason in ("off_scope_redirect", "refused_address") else "navigation_failed",
                                            f"final address refused: {refusal}")
                version = f"Chromium {browser.version}"
            finally:
                await browser.close()
    finally:
        await proxy.stop()

    cookies, cookies_capped = summarise_cookies(raw_cookies, scope)
    caps["requests"], caps["bytes"], caps["cookies"] = requests_capped, budget.bytes_capped, cookies_capped
    return {
        "version": 1, "final_url": safe_final_url(final_url), "browser_version": version[:64], "cookies": cookies,
        "requests": {"total": total, "first_party": first_party,
                     "third_party_hosts": [{"host": h, "count": n} for h, n in sorted(third_party.items())]},
        "banner": normalise_banner(raw_banner if isinstance(raw_banner, dict) else {}),
        "timings": {"navigation_ms": navigation_ms, "settle_ms": settle_ms, "total_ms": int((time.monotonic() - started) * 1000)},
        "caps": caps,
    }
