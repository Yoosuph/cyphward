"""Cookie-consent browser observation -> compliance evidence (packet C2b). Pure functions.

A separate browser worker loads a verified domain's homepage once, with no
interaction, and reports what it saw. This module turns that report into
`tool_observed` evidence rows under the three existing consent requirement
keys. Every label says what the browser observed on a first visit. None says
whether the site follows any law: a status here is evidence, never a verdict.

Statuses are deliberately cautious. "Not detected" is never a gap, because a
heuristic cannot prove a banner is absent. "Present" for the trackers
requirement means only that no known tracking was seen on this one visit.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from backend.app.compliance import mapping
from backend.app.compliance.register import REGISTER, requirement as register_requirement
from backend.app.scanner.privacy_probe import classify_cookie
from shared.browser_contracts import ConsentObservation

OBSERVATION_MARKER = "browser_consent_v1"
BANNER_KEY = "gaid.consent.banner_visible"
CHOICE_KEY = "gaid.consent.accept_and_reject"
TRACKERS_KEY = "gaid.consent.no_trackers_before_consent"
KEYS = (BANNER_KEY, CHOICE_KEY, TRACKERS_KEY)

# Registrable-suffix matches for hosts of well-known analytics and advertising services.
TRACKER_HOSTS = (
    ("google-analytics.com", "google_analytics"), ("analytics.google.com", "google_analytics"),
    ("doubleclick.net", "google_ads"), ("connect.facebook.net", "meta"), ("facebook.com", "meta"),
    ("hotjar.com", "hotjar"), ("analytics.tiktok.com", "tiktok"), ("snap.licdn.com", "linkedin"),
    ("ads.linkedin.com", "linkedin"), ("clarity.ms", "microsoft_clarity"), ("bat.bing.com", "microsoft"),
    ("sc-static.net", "snap"),
)

# Plain-language text. Shown beside the requirement; the per-observation sentences with counts are
# built in `evidence_rows` and stored as details.browser_label.
# A page controls what its visitors see, so a browser that announces itself can be shown a different page
# from the one other visitors get. Every "present" sentence says so; the limit is never left implicit.
LIMIT_NOTE = ("This is what the page showed Cyphward's browser on one visit; a page can behave differently for "
              "other visitors.")

REASON_TEXT = {
    "browser_banner_in_first_view": "On a first visit the browser saw a consent banner in the first screen. " + LIMIT_NOTE,
    "browser_banner_below_first_view": "On a first visit the browser detected a consent banner, but not in the "
                                       "first screen.",
    "browser_banner_not_detected": "On a first visit the browser did not detect a consent banner. Banners built "
                                   "with unusual markup can be missed.",
    "browser_accept_and_reject_same_level": "On a first visit the browser saw an accept control and a reject control "
                                            "at the same level. " + LIMIT_NOTE,
    "browser_reject_less_prominent": "On a first visit the browser saw a reject control, but it was smaller or "
                                     "less prominent than the accept control.",
    "browser_no_reject_control": "On a first visit the browser saw an accept control but no reject control at the "
                                 "first level of the banner.",
    "browser_controls_not_identified": "The browser saw a banner but could not identify an accept control.",
    "browser_tracking_before_choice": "The browser observed known analytics or advertising cookies or requests "
                                      "before any choice was made on a first visit.",
    "browser_cookies_unclassified": "The browser observed cookies before any choice was made, and Cyphward could "
                                    "not tell whether they are essential.",
    "browser_no_known_tracking": "On a first visit the browser observed no known analytics or advertising cookies "
                                 "or requests before any choice was made. " + LIMIT_NOTE,
    "browser_observation_capped": "The browser stopped watching this page early at a safety limit, so what it "
                                  "saw may be incomplete.",
    "no_browser_observation": "No browser observation has run for this domain yet.",
}

_NECESSARY_CATEGORIES = ("necessary", "infrastructure")


def enabled() -> bool:
    from backend.app.core import config
    return bool(config.BROWSER_CONSENT_ENABLED)


def tracker_vendor(host: str) -> Optional[str]:
    host = (host or "").lower().rstrip(".")
    for suffix, vendor in TRACKER_HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return vendor
    return None


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def classify(obs: ConsentObservation) -> Dict[str, Any]:
    """Counts the evidence rows are built from. Pure."""
    cookies = [(c, classify_cookie(c.name)) for c in obs.cookies]
    tracker_cookies = sorted({c.name for c, k in cookies if k["category"] == "tracker"})
    unclassified = sorted({c.name for c, k in cookies if k["category"] == "unknown"})
    tracker_hosts = {}
    for item in obs.requests.third_party_hosts:
        vendor = tracker_vendor(item.host)
        if vendor:
            tracker_hosts[item.host] = vendor
    return {
        "cookie_count": len(obs.cookies),
        "third_party_cookie_count": sum(1 for c in obs.cookies if c.third_party),
        "tracker_cookies": tracker_cookies,
        "unclassified_cookies": unclassified,
        "tracker_hosts": dict(sorted(tracker_hosts.items())),
        "third_party_host_count": len(obs.requests.third_party_hosts),
    }


def _banner_result(obs: ConsentObservation) -> Dict[str, Any]:
    b = obs.banner
    if not b.detected:
        return {"status": mapping.NOT_ASSESSED, "reason": "browser_banner_not_detected",
                "label": REASON_TEXT["browser_banner_not_detected"]}
    if b.in_first_view:
        return {"status": mapping.PRESENT, "reason": "browser_banner_in_first_view",
                "label": REASON_TEXT["browser_banner_in_first_view"]}
    return {"status": mapping.GAP, "reason": "browser_banner_below_first_view",
            "label": REASON_TEXT["browser_banner_below_first_view"]}


def _choice_result(obs: ConsentObservation) -> Dict[str, Any]:
    b = obs.banner
    if not b.detected:
        return {"status": mapping.NOT_ASSESSED, "reason": "browser_banner_not_detected",
                "label": REASON_TEXT["browser_banner_not_detected"]}
    if not b.accept_control:
        return {"status": mapping.NOT_ASSESSED, "reason": "browser_controls_not_identified",
                "label": REASON_TEXT["browser_controls_not_identified"]}
    if b.reject_control == "same_level":
        return {"status": mapping.PRESENT, "reason": "browser_accept_and_reject_same_level",
                "label": REASON_TEXT["browser_accept_and_reject_same_level"]}
    if b.reject_control == "less_prominent":
        return {"status": mapping.GAP, "reason": "browser_reject_less_prominent",
                "label": REASON_TEXT["browser_reject_less_prominent"]}
    return {"status": mapping.GAP, "reason": "browser_no_reject_control",
            "label": REASON_TEXT["browser_no_reject_control"]}


def _tracker_result(obs: ConsentObservation, facts: Dict[str, Any]) -> Dict[str, Any]:
    n = facts["cookie_count"]
    cookies = _plural(n, "cookie", "cookies")
    if facts["tracker_cookies"] or facts["tracker_hosts"]:
        label = (f"The browser observed {cookies} set before any choice was made, including "
                 f"{_plural(len(facts['tracker_cookies']), 'known analytics or advertising cookie', 'known analytics or advertising cookies')} "
                 f"and requests to {_plural(len(facts['tracker_hosts']), 'known analytics or advertising service', 'known analytics or advertising services')}.")
        return {"status": mapping.GAP, "reason": "browser_tracking_before_choice", "label": label}
    if facts["unclassified_cookies"]:
        label = (f"The browser observed {cookies} set before any choice was made. "
                 f"{_plural(len(facts['unclassified_cookies']), 'cookie', 'cookies')} could not be classified as "
                 f"essential or not; review them in your cookie list.")
        return {"status": mapping.NOT_ASSESSED, "reason": "browser_cookies_unclassified", "label": label}
    label = (f"The browser observed {cookies} set before any choice was made; none matched known analytics "
             f"or advertising services, and no requests to such services were seen. " + LIMIT_NOTE)
    return {"status": mapping.PRESENT, "reason": "browser_no_known_tracking", "label": label}


def _truncation_adjust(obs: ConsentObservation, result: Dict[str, Any]) -> Dict[str, Any]:
    """A capped observation can show a gap but never evidence present: more may have loaded."""
    capped = obs.caps.requests or obs.caps.bytes or obs.caps.cookies or obs.caps.page_timeout
    if capped and result["status"] == mapping.PRESENT:
        return {**result, "status": mapping.NOT_ASSESSED, "reason": "browser_observation_capped",
                "label": REASON_TEXT["browser_observation_capped"]}
    return result


def results_for(obs: ConsentObservation) -> Dict[str, Dict[str, Any]]:
    facts = classify(obs)
    return {
        BANNER_KEY: _truncation_adjust(obs, _banner_result(obs)),
        CHOICE_KEY: _truncation_adjust(obs, _choice_result(obs)),
        TRACKERS_KEY: _truncation_adjust(obs, _tracker_result(obs, facts)),
    }


def evidence_rows(obs: ConsentObservation, *, org_id: str, domain_id: str, job_id: str,
                  observed_at: datetime, register_version: Optional[str] = None) -> List[Dict[str, Any]]:
    """One `tool_observed` row per consent requirement. `scan_id` stays NULL: the unique
    (scan_id, requirement_key) index belongs to the scan-completion path, and the job's own
    status transition is what makes a replayed result a no-op."""
    observed = mapping._aware(observed_at) or datetime.now(timezone.utc)
    facts = classify(obs)
    rows = []
    for key, result in results_for(obs).items():
        requirement = register_requirement(key)
        if requirement is None:
            raise ValueError(f"register has no requirement {key}")
        rows.append({
            "org_id": org_id, "domain_id": domain_id, "requirement_key": key,
            "register_version": register_version or REGISTER["version"], "source": mapping.TOOL_SOURCE,
            "status": result["status"], "observed_at": observed,
            "expires_at": observed + timedelta(days=requirement["freshness_days"]),
            "details": {
                "observation": OBSERVATION_MARKER, "reason": result["reason"], "browser_label": result["label"],
                "job_id": job_id, "final_url": obs.final_url, "browser_version": obs.browser_version,
                "heuristic": True, "cms_marker": obs.banner.cms_marker,
                "cookie_count": facts["cookie_count"], "third_party_host_count": facts["third_party_host_count"],
                "tracker_cookies": facts["tracker_cookies"][:20], "tracker_hosts": facts["tracker_hosts"],
                "capped": obs.caps.model_dump(), "limit": LIMIT_NOTE,
            },
        })
    return rows


# ── Read side ──────────────────────────────────────────────────────────────
def requirement_status(requirement: Dict[str, Any], domains: List[Dict[str, Any]],
                       browser_rows: Dict[str, Dict[str, Any]], fallback: Dict[str, Any],
                       now: Optional[datetime] = None) -> Dict[str, Any]:
    """Merge the latest browser rows (domain id -> row) over the fallback status.

    No browser row for any domain: the fallback is returned untouched. For the trackers
    requirement a gap already observed by the static check stands, because it is the stronger
    signal; otherwise the newer evidence per domain wins.
    """
    if not browser_rows:
        return fallback
    now = now or datetime.now(timezone.utc)
    static = {d["domain_id"]: d for d in fallback["domains"]}
    results = []
    for domain in domains:
        did = str(domain["id"])
        prior = static.get(did)
        row = browser_rows.get(did)
        expires = mapping._aware(row.get("expires_at")) if row else None
        if requirement["key"] == TRACKERS_KEY and prior and prior["status"] == mapping.GAP:
            results.append(prior)  # a tracker gap the static check saw stands, whatever the browser row says or when it expired
        elif row is None:
            results.append(prior or mapping._domain_result(mapping.NOT_ASSESSED, "no_browser_observation", domain))
        elif expires is not None and expires <= now:
            stale = {**row, "details": {k: v for k, v in (row.get("details") or {}).items() if k != "browser_label"}}
            results.append(mapping._domain_result(mapping.NOT_ASSESSED, "evidence_expired", domain, stale))
        else:
            results.append(mapping._domain_result(row["status"], (row.get("details") or {}).get("reason") or row["status"],
                                                  domain, row, source=mapping.TOOL_SOURCE))
    status = mapping._combine(results)
    reason = "no_verified_domain" if not domains else next((r["reason"] for r in results if r["status"] == status), status)
    return {"status": status, "reason": reason, "domains": results, "unlinked_finding_ids": []}


def latest_rows(execute_query, org_id: str, domain_ids: Iterable[str]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Latest browser row per (requirement key, domain). Only called when the feature is on."""
    ids = list(domain_ids)
    if not ids:
        return {}
    rows = execute_query(
        "SELECT DISTINCT ON (requirement_key, domain_id) id, requirement_key, domain_id, status, source, "
        "observed_at, expires_at, scan_id, finding_ids, details, register_version "
        "FROM compliance_evidence WHERE org_id = %s AND domain_id = ANY(%s::uuid[]) "
        "AND requirement_key = ANY(%s) AND details->>'observation' = %s "
        "ORDER BY requirement_key, domain_id, observed_at DESC, created_at DESC",
        (org_id, ids, list(KEYS), OBSERVATION_MARKER)) or []
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row["requirement_key"], {})[str(row["domain_id"])] = row
    return out


# Referenced by tests: every user-visible string this module can produce.
def all_static_text() -> List[str]:
    return list(REASON_TEXT.values())
