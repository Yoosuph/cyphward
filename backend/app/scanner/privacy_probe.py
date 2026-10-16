"""Static privacy checks (compliance packet C2a). No browser, no JavaScript.

Per host: one unauthenticated GET of a few public pages. Records what is
observed, labelled heuristic where it is a guess; never judges adequacy.

* Privacy policy and cookie notice: links found on the homepage, then fixed
  paths. A page only counts when its title or first heading names the topic
  and its body differs from the homepage. A host that answers 200 for a path
  that cannot exist is "catch-all": its fixed paths prove nothing.
* Policy content signals (heuristic): mentioned / not found, plus a SHA-256
  of the normalised policy text. The text itself is never stored.
* First-response cookies: names and attributes only, never values, each
  classified tracker / infrastructure / necessary / unknown.
* Tracker scripts, whether they are blocked until consent, consent managers,
  and security.txt.

Network safety is http_probe's: every hop re-resolved and pinned to a public
IP, redirects followed only inside the authorised scope, bounded bodies.
"""
import asyncio
import hashlib
import re
import secrets
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from backend.app.scanner import ip_guard
from shared.scan_budget import ensure_stage_budget

OBSERVATION_VERSION = 1
USER_AGENT = "Cyphward-Security-Scanner/1.0"
REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5
DEFAULT_MAX_PAGES = 10  # home + catch-all probe + links + 6 fixed paths + security.txt
DEFAULT_MAX_BYTES = 512 * 1024
DEFAULT_TIMEOUT = 4.0

KINDS = ("privacy_policy", "cookie_notice")
LINK_PATTERNS = {
    "privacy_policy": re.compile(r"privacy|data[\s_-]*protection|privacy[\s_-]*(policy|notice)", re.I),
    "cookie_notice": re.compile(r"cookie", re.I),
}
FIXED_PATHS = {
    "privacy_policy": ("/privacy", "/privacy-policy", "/privacy-notice", "/data-protection"),
    "cookie_notice": ("/cookie-policy", "/cookies"),
}
TITLE_PATTERNS = {
    "privacy_policy": re.compile(r"privacy|data\s+protection", re.I),
    "cookie_notice": re.compile(r"cookie", re.I),
}

POLICY_SIGNALS = {
    "lawful_basis": re.compile(r"lawful\s+bas[ie]s|legal\s+bas[ie]s|legitimate\s+interest|"
                               r"performance\s+of\s+(a\s+)?contract|legal\s+obligation", re.I),
    "data_subject_rights": re.compile(r"right\s+(to|of)\s+(access|rectification|erasure|object|data\s+portability|"
                                      r"be\s+forgotten|withdraw)|data\s+subject\s+rights|your\s+rights", re.I),
    "dpo_contact": re.compile(r"(data\s+protection\s+officer|\bDPO\b)[^.@]{0,160}[\w.+-]+@[\w-]+\.[\w.-]+|"
                              r"[\w.+-]+@[\w-]+\.[\w.-]+[^.]{0,80}(data\s+protection\s+officer|\bDPO\b)", re.I),
    "nigeria_law": re.compile(r"\bNDPA\b|\bNDPR\b|\bGAID\b|Nigeria(n)?\s+Data\s+Protection", re.I),
}

TRACKER_COOKIES = (
    (re.compile(r"^(_ga|_gid|_gat|_gcl_\w+|__utm[a-z])(_|$)", re.I), "google_analytics"),
    (re.compile(r"^(_fbp|_fbc|fr)$", re.I), "meta"),
    (re.compile(r"^_hj", re.I), "hotjar"),
    (re.compile(r"^(_ttp|_tt_enable_cookie|tt_)", re.I), "tiktok"),
    (re.compile(r"^(_clck|_clsk|MUID|_uetsid|_uetvid)$", re.I), "microsoft"),
    (re.compile(r"^(li_sugr|bcookie|lidc|_li_ss|AnalyticsSyncHistory|UserMatchHistory)$", re.I), "linkedin"),
    (re.compile(r"^(_scid|_sctr)$", re.I), "snap"),
)
INFRASTRUCTURE_COOKIES = re.compile(
    r"^(__cf_bm|__cfruid|cf_clearance|_cfuvid|__cflb|AWSALB\w*|AWSELB\w*|ARRAffinity\w*|incap_ses_\w+|visid_incap_\w+|"
    r"__vercel\w*|_vcrcs|BIGipServer\w*|TS[0-9a-f]{6,}\w*|ak_bmsc|bm_sz|_abck)$", re.I)
NECESSARY_COOKIES = re.compile(
    r"^(sessionid|session|sid|connect\.sid|PHPSESSID|JSESSIONID|ASP\.NET_SessionId|csrftoken|_csrf|XSRF-TOKEN|"
    r"laravel_session|__Host-\w+|__Secure-\w+|cookie_?consent\w*|CookieConsent|OptanonConsent|cookieyes-consent)$", re.I)

TRACKER_SCRIPTS = (
    (re.compile(r"(www\.)?google-analytics\.com|googletagmanager\.com/gtag/js", re.I), "google_analytics", "direct"),
    (re.compile(r"googletagmanager\.com/gtm\.js", re.I), "google_tag_manager", "loader"),
    (re.compile(r"connect\.facebook\.net", re.I), "meta", "direct"),
    (re.compile(r"static\.hotjar\.com|script\.hotjar\.com", re.I), "hotjar", "direct"),
    (re.compile(r"analytics\.tiktok\.com", re.I), "tiktok", "direct"),
    (re.compile(r"snap\.licdn\.com", re.I), "linkedin", "direct"),
    (re.compile(r"clarity\.ms", re.I), "microsoft_clarity", "direct"),
    (re.compile(r"sc-static\.net/scevent", re.I), "snap", "direct"),
)
INLINE_TRACKERS = (
    (re.compile(r"\bfbq\(\s*['\"]init", re.I), "meta"),
    (re.compile(r"\bgtag\(\s*['\"]config['\"]\s*,\s*['\"](G|UA)-", re.I), "google_analytics"),
    (re.compile(r"\bttq\.load\(", re.I), "tiktok"),
    (re.compile(r"\bhj\(\s*['\"]|_hjSettings", re.I), "hotjar"),
)
CONSENT_MANAGERS = (
    (re.compile(r"consent\.cookiebot\.com|data-cookieconsent", re.I), "cookiebot"),
    (re.compile(r"cdn\.cookielaw\.org|onetrust", re.I), "onetrust"),
    (re.compile(r"cmp\.osano\.com", re.I), "osano"),
    (re.compile(r"app\.termly\.io|termly", re.I), "termly"),
    (re.compile(r"iubenda\.com", re.I), "iubenda"),
    (re.compile(r"cdn-cookieyes\.com|cookieyes", re.I), "cookieyes"),
    (re.compile(r"usercentrics", re.I), "usercentrics"),
    (re.compile(r"complianz", re.I), "complianz"),
    (re.compile(r"quantcast\.mgr\.consensu\.org|quantcast\s*choice", re.I), "quantcast"),
)


# ── Pure parsing ───────────────────────────────────────────────────────────
class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: List[Dict[str, str]] = []
        self.scripts: List[Dict[str, Any]] = []
        self.title = ""
        self.heading = ""
        self.text: List[str] = []
        self._stack: List[str] = []
        self._link: Optional[Dict[str, str]] = None
        self._script: Optional[Dict[str, Any]] = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        self._stack.append(tag)
        if tag == "a" and a.get("href"):
            self._link = {"href": a["href"], "text": ""}
        elif tag == "script":
            self._script = {"src": a.get("src", ""), "type": a.get("type", "").lower(),
                            "consent_attr": any(k in a for k in ("data-cookieconsent", "data-category",
                                                                 "data-cookiecategory", "data-consent")) or
                            "optanon-category" in a.get("class", "").lower(), "body": ""}

    def handle_endtag(self, tag):
        if tag == "a" and self._link is not None:
            self.links.append(self._link)
            self._link = None
        elif tag == "script" and self._script is not None:
            self.scripts.append(self._script)
            self._script = None
        if tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass

    def handle_data(self, data):
        current = self._stack[-1] if self._stack else ""
        if self._script is not None:
            self._script["body"] += data
            return
        if current == "style":
            return
        if current == "title" and not self.title:
            self.title = data.strip()[:200]
        if current == "h1" and not self.heading:
            self.heading = data.strip()[:200]
        if self._link is not None:
            self._link["text"] += data
        self.text.append(data)


def parse_page(html: str) -> _Page:
    page = _Page()
    try:
        page.feed(html or "")
        page.close()
    except Exception:  # malformed markup: keep what was parsed
        pass
    return page


def normalise_text(page: _Page) -> str:
    return re.sub(r"\s+", " ", " ".join(page.text)).strip().lower()


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def policy_signals(text: str) -> Dict[str, Dict[str, Optional[str]]]:
    """Heuristic phrase signals in policy text: mentioned / not_found. Never 'adequate'."""
    out = {}
    for key, pattern in POLICY_SIGNALS.items():
        match = pattern.search(text or "")
        phrase = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", match.group(0))[:120] if match else None
        out[key] = {"state": "mentioned" if match else "not_found", "phrase": phrase}
    return out


def classify_cookie(name: str) -> Dict[str, Optional[str]]:
    for pattern, vendor in TRACKER_COOKIES:
        if pattern.search(name):
            return {"category": "tracker", "vendor": vendor}
    if INFRASTRUCTURE_COOKIES.match(name):
        return {"category": "infrastructure", "vendor": None}
    if NECESSARY_COOKIES.match(name):
        return {"category": "necessary", "vendor": None}
    return {"category": "unknown", "vendor": None}


def first_response_cookies(set_cookie_headers: List[str]) -> List[Dict[str, Any]]:
    """Cookie names and attributes from Set-Cookie headers. Values are never kept."""
    cookies = []
    for header in set_cookie_headers or []:
        parts = [p.strip() for p in header.split(";")]
        if not parts or "=" not in parts[0]:
            continue
        name = parts[0].split("=", 1)[0].strip()[:100]
        attrs = {p.split("=", 1)[0].strip().lower(): (p.split("=", 1)[1].strip() if "=" in p else True) for p in parts[1:] if p}
        cookies.append({
            "name": name, **classify_cookie(name),
            "secure": "secure" in attrs, "httponly": "httponly" in attrs,
            "samesite": str(attrs.get("samesite") or "")[:10] or None,
            "domain": str(attrs.get("domain") or "")[:100] or None,
            "max_age": str(attrs.get("max-age") or "")[:12] or None,
        })
    return cookies


def detect_trackers(page: _Page) -> List[Dict[str, Any]]:
    found: Dict[tuple, Dict[str, Any]] = {}
    for script in page.scripts:
        blocked = script["type"] in ("text/plain", "text/x-template") and script["consent_attr"]
        if script["src"]:
            for pattern, vendor, strength in TRACKER_SCRIPTS:
                if pattern.search(script["src"]):
                    key = (vendor, "script_src")
                    found.setdefault(key, {"vendor": vendor, "source": "script_src", "strength": strength,
                                           "consent_blocked": True})
                    found[key]["consent_blocked"] = found[key]["consent_blocked"] and blocked
        else:
            for pattern, vendor in INLINE_TRACKERS:
                if pattern.search(script["body"]):
                    key = (vendor, "inline")
                    found.setdefault(key, {"vendor": vendor, "source": "inline", "strength": "direct",
                                           "consent_blocked": True})
                    found[key]["consent_blocked"] = found[key]["consent_blocked"] and blocked
    return sorted(found.values(), key=lambda t: (t["vendor"], t["source"]))


def detect_consent_manager(html: str) -> Optional[str]:
    for pattern, vendor in CONSENT_MANAGERS:
        if pattern.search(html or ""):
            return vendor
    return None


def parse_security_txt(text: str) -> Dict[str, bool]:
    return {"present": True, "has_contact": bool(re.search(r"^\s*Contact\s*:", text or "", re.I | re.M))}


def candidate_links(page: _Page, base_url: str, kind: str) -> List[str]:
    pattern = LINK_PATTERNS[kind]
    urls = []
    for link in page.links:
        href = link["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        if pattern.search(link["text"]) or pattern.search(href):
            url = urljoin(base_url, href).split("#", 1)[0]
            if urlparse(url).scheme in ("http", "https") and url not in urls:
                urls.append(url)
    return urls[:3]


def page_matches(kind: str, page: _Page, home_hash: Optional[str], body_hash: str) -> bool:
    """A page counts only when its title or first heading names the topic and it isn't the homepage."""
    named = bool(TITLE_PATTERNS[kind].search(page.title) or TITLE_PATTERNS[kind].search(page.heading))
    return named and body_hash != home_hash


# ── Network (pinned, in-scope, bounded) ────────────────────────────────────
async def fetch_in_scope(client: httpx.AsyncClient, url: str, scope: List[str], *,
                         max_bytes: int = DEFAULT_MAX_BYTES) -> Dict[str, Any]:
    """GET url following redirects only inside scope; each hop pinned to a public IP."""
    result = {"url": url, "final_url": None, "status": None, "error": None, "off_scope_host": None,
              "set_cookie": [], "body": ""}
    parsed = urlparse(url)
    scheme, host = parsed.scheme, (parsed.hostname or "").lower()
    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    for hop in range(MAX_REDIRECTS + 1):
        if not ip_guard.hostname_in_scope(host, scope):
            result["error"] = f"redirect blocked: {host} out of scope"
            result["off_scope_host"] = host
            return result
        target_ip = await asyncio.to_thread(ip_guard.resolve_connect_ip, host)
        if not target_ip:
            result["error"] = f"refused: {host} resolves only to non-public addresses"
            return result
        ensure_stage_budget()
        try:
            async with client.stream("GET", ip_guard.pinned_url(scheme, target_ip, path),
                                     headers={"User-Agent": USER_AGENT, "Host": host},
                                     extensions={"sni_hostname": host}) as resp:
                if resp.status_code in REDIRECT_CODES and resp.headers.get("location"):
                    nxt = urljoin(f"{scheme}://{host}{path}", resp.headers["location"])
                    p = urlparse(nxt)
                    if p.scheme not in ("http", "https") or not p.hostname:
                        result["error"] = "redirect blocked: unsupported location"
                        return result
                    if hop == 0:
                        result["set_cookie"] = resp.headers.get_list("set-cookie")
                    scheme, host = p.scheme, p.hostname.lower()
                    path = (p.path or "/") + (f"?{p.query}" if p.query else "")
                    continue
                chunks, size = [], 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        chunks.append(chunk[: max(0, max_bytes - (size - len(chunk)))])
                        break
                    chunks.append(chunk)
                result.update(status=resp.status_code, final_url=f"{scheme}://{host}{path}",
                              body=b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace"))
                if not result["set_cookie"]:
                    result["set_cookie"] = resp.headers.get_list("set-cookie")
                return result
        except httpx.HTTPError as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"[:300]
            return result
    result["error"] = f"redirect blocked: exceeded {MAX_REDIRECTS} hops"
    return result


async def probe_privacy_host(host: str, scope: List[str], client: httpx.AsyncClient, *,
                             max_pages: int = DEFAULT_MAX_PAGES, max_bytes: int = DEFAULT_MAX_BYTES) -> Dict[str, Any]:
    """Observations for one host. Raises when the homepage can't be fetched (host failed, not 'not found')."""
    fetches = 0

    async def get(path_or_url: str) -> Dict[str, Any]:
        nonlocal fetches
        fetches += 1
        url = path_or_url if "://" in path_or_url else f"https://{host}{path_or_url}"
        return await fetch_in_scope(client, url, scope, max_bytes=max_bytes)

    home = await get("/")
    if home["status"] is None or home["status"] >= 400:
        raise RuntimeError(home["error"] or f"homepage returned HTTP {home['status']}")
    home_page = parse_page(home["body"])
    home_hash = fingerprint(normalise_text(home_page))

    probe = await get(f"/cyphward-{secrets.token_hex(6)}-not-a-page")
    probe_hash = fingerprint(normalise_text(parse_page(probe["body"]))) if probe["status"] == 200 else None
    catch_all = probe["status"] == 200 or (probe_hash is not None and probe_hash == home_hash)

    out: Dict[str, Any] = {
        "hostname": host,
        "homepage": {"url": home["url"], "status": home["status"], "final_url": home["final_url"]},
        "catch_all": catch_all,
        "pages": [],
        "first_response_cookies": first_response_cookies(home["set_cookie"]),
        "trackers": detect_trackers(home_page),
        "consent_manager": detect_consent_manager(home["body"]),
        "policy_signals": None,
        "fetches": 0,
    }

    for kind in KINDS:
        entry: Dict[str, Any] = {"kind": kind, "url": None, "found_by": None, "status": None, "off_domain": False,
                                 "matched": False, "fingerprint": None, "fixed_paths": {}}
        for url in candidate_links(home_page, home["final_url"] or home["url"], kind):
            if fetches >= max_pages:
                break
            if not ip_guard.hostname_in_scope(urlparse(url).hostname or "", scope):
                entry.update(url=url, found_by="link", off_domain=True)
                break
            res = await get(url)
            page = parse_page(res["body"])
            text = normalise_text(page)
            if res["status"] == 200 and page_matches(kind, page, home_hash, fingerprint(text)):
                entry.update(url=res["final_url"] or url, found_by="link", status=200, matched=True,
                             fingerprint=fingerprint(text))
                if kind == "privacy_policy":
                    out["policy_signals"] = policy_signals(text)
                break
            if res["off_scope_host"]:
                entry.update(url=url, found_by="link", off_domain=True)
                break
        if not entry["matched"] and not entry["off_domain"]:
            for path in FIXED_PATHS[kind]:
                if fetches >= max_pages:
                    break
                res = await get(path)
                entry["fixed_paths"][path] = res["status"]
                page = parse_page(res["body"])
                text = normalise_text(page)
                if res["status"] == 200 and page_matches(kind, page, home_hash, fingerprint(text)):
                    entry.update(url=res["final_url"], found_by="fixed_path", status=200, matched=True,
                                 fingerprint=fingerprint(text))
                    if kind == "privacy_policy":
                        out["policy_signals"] = policy_signals(text)
                    break
        out["pages"].append(entry)

    if fetches < max_pages:
        sec = await get("/.well-known/security.txt")
        out["security_txt"] = (parse_security_txt(sec["body"]) if sec["status"] == 200 and "<html" not in sec["body"][:200].lower()
                               else {"present": False, "has_contact": False})
    out["fetches"] = fetches
    return out


async def run_privacy_batch(hosts: List[str], scope: List[str], *, max_pages: int = DEFAULT_MAX_PAGES,
                            concurrency: int = 2, client: Optional[httpx.AsyncClient] = None):
    """Probe hosts (at most `concurrency` at a time). A host that can't be fetched is failed, not 'not found'."""
    from backend.app.scanner.tool_results import collect_tool_results
    owns = client is None
    client = client or httpx.AsyncClient(verify=False, timeout=DEFAULT_TIMEOUT, follow_redirects=False)
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(host):
        async with sem:
            return await probe_privacy_host(host, scope, client, max_pages=max_pages)
    try:
        results = await asyncio.gather(*(one(h) for h in hosts), return_exceptions=True)
    finally:
        if owns:
            await client.aclose()
    return collect_tool_results(hosts, results)
