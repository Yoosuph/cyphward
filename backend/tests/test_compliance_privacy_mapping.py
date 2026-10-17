"""Privacy evidence truth table (C2a-plan section 4, D8, founder additions). Pure, no database."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.compliance import mapping as m
from backend.app.compliance.register import privacy_requirements, requirement
from backend.app.scanner.privacy_probe import FIXED_PATHS

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
APEX = "acme.example.test"
POLICY = requirement("gaid.notice.privacy_policy")
COOKIE = requirement("gaid.notice.cookie_notice")
TRACKERS = requirement("gaid.consent.no_trackers_before_consent")
DPO = requirement("gaid.dpo.contact_published")
D1 = {"id": "11111111-1111-4111-8111-111111111111", "domain": APEX}
D2 = {"id": "22222222-2222-4222-8222-222222222222", "domain": "other.example.test"}


def page(kind, matched=False, off_domain=False, fixed=None, url=None, fingerprint=None, found_by=None):
    return {"kind": kind, "matched": matched, "off_domain": off_domain, "url": url, "found_by": found_by,
            "fingerprint": fingerprint, "fixed_paths": fixed if fixed is not None else {}}


def gone(kind, status=404):
    return {path: status for path in FIXED_PATHS[kind]}


def host(name=APEX, *, catch_all=False, pages=(), cookies=(), trackers=(), consent=None, signals=None):
    return {"hostname": name, "catch_all": catch_all, "pages": list(pages), "first_response_cookies": list(cookies),
            "trackers": list(trackers), "consent_manager": consent, "policy_signals": signals}


def obs(*hosts, failed=None):
    hosts = list(hosts)
    return {"privacy_observations": hosts, "attempted_hosts": [h["hostname"] for h in hosts] + list(failed or {}),
            "successful_hosts": [h["hostname"] for h in hosts], "failed_hosts": dict(failed or {})}


def ev(req, observation, previous=None):
    return m.evaluate_privacy(req, observation, APEX, previous)


# ── Write side ─────────────────────────────────────────────────────────────
def test_no_privacy_stage_writes_no_row_so_the_previous_one_stands():
    assert ev(POLICY, None) is None
    assert m.privacy_rows(privacy_requirements(), {"http_probes": []}, org_id="o", domain_id="d", scan_id="s",
                          observed_at=NOW, register_version="v", apex=APEX) == []


def test_all_hosts_failed_is_not_assessed():
    r = ev(POLICY, obs(failed={APEX: "ConnectTimeout"}))
    assert (r["status"], r["reason"]) == ("not_assessed", "privacy_check_failed")


def test_found_policy_is_present_with_url_and_fingerprint():
    r = ev(POLICY, obs(host(pages=[page("privacy_policy", matched=True, url=f"https://{APEX}/privacy",
                                         fingerprint="a" * 64, found_by="link")])))
    assert (r["status"], r["reason"]) == ("present", "page_found")
    assert r["details"]["url"] == f"https://{APEX}/privacy" and "changed_since_last_scan" not in r["details"]


def test_policy_change_since_last_scan_is_flagged_and_never_changes_status():
    found = obs(host(pages=[page("privacy_policy", matched=True, url="u", fingerprint="b" * 64)]))
    changed = ev(POLICY, found, {"details": {"url": "u", "fingerprint": "a" * 64}})
    same = ev(POLICY, found, {"details": {"url": "u", "fingerprint": "b" * 64}})
    moved = ev(POLICY, found, {"details": {"url": "other", "fingerprint": "a" * 64}})
    assert changed["details"]["changed_since_last_scan"] is True and changed["status"] == "present"
    assert same["details"]["changed_since_last_scan"] is False
    assert "changed_since_last_scan" not in moved["details"], "a different URL is not a change of the same policy"


def test_policy_linked_off_domain_is_present_as_a_recorded_link():
    r = ev(POLICY, obs(host(pages=[page("privacy_policy", off_domain=True, url="https://app.termly.io/x")])))
    assert (r["status"], r["reason"]) == ("present", "linked_off_domain") and r["details"]["off_domain"]


def test_d8_gap_needs_every_fixed_path_gone_on_a_non_catch_all_apex():
    r = ev(POLICY, obs(host(pages=[page("privacy_policy", fixed=gone("privacy_policy"))])))
    assert (r["status"], r["reason"]) == ("gap", "not_found_by_static_check")
    assert ev(POLICY, obs(host(pages=[page("privacy_policy", fixed=gone("privacy_policy", 410))])))["status"] == "gap"


@pytest.mark.parametrize("fixed", [
    {**gone("privacy_policy"), "/privacy": 500},                      # a server error is not "not found"
    {p: 404 for p in list(FIXED_PATHS["privacy_policy"])[:2]},        # page budget ran out
    {**gone("privacy_policy"), "/privacy": None},                     # fetch failed
])
def test_anything_short_of_a_conclusive_not_found_is_not_assessed(fixed):
    r = ev(POLICY, obs(host(pages=[page("privacy_policy", fixed=fixed)])))
    assert (r["status"], r["reason"]) == ("not_assessed", "not_found_inconclusive")


def test_catch_all_site_without_a_policy_is_not_assessed():
    r = ev(POLICY, obs(host(catch_all=True, pages=[page("privacy_policy", fixed={p: 200 for p in FIXED_PATHS["privacy_policy"]})])))
    assert (r["status"], r["reason"]) == ("not_assessed", "site_serves_every_path")


def test_not_found_on_a_subdomain_only_is_not_a_gap():
    r = ev(POLICY, obs(host(f"www.{APEX}", pages=[page("privacy_policy", fixed=gone("privacy_policy"))])))
    assert (r["status"], r["reason"]) == ("not_assessed", "apex_not_checked")


def test_cookie_notice_follows_the_same_rule():
    assert ev(COOKIE, obs(host(pages=[page("cookie_notice", matched=True, url="u")])))["status"] == "present"
    assert ev(COOKIE, obs(host(pages=[page("cookie_notice", fixed=gone("cookie_notice"))])))["status"] == "gap"


# Cookies: only known trackers can create a gap (founder addition 2).
def cookie(name, category, vendor=None):
    return {"name": name, "category": category, "vendor": vendor}


def test_tracker_cookie_on_first_response_is_a_gap_naming_the_vendor():
    r = ev(TRACKERS, obs(host(cookies=[cookie("_ga", "tracker", "google_analytics")])))
    assert (r["status"], r["reason"]) == ("gap", "tracker_before_consent")
    assert r["details"]["observed"] == [{"host": APEX, "how": "cookie_on_first_response",
                                         "vendor": "google_analytics", "name": "_ga"}]


def test_infrastructure_necessary_and_unknown_cookies_are_listed_never_a_gap():
    cookies = [cookie("__cf_bm", "infrastructure"), cookie("sessionid", "necessary"),
               cookie("PHPSESSID", "necessary"), cookie("connect.sid", "necessary"), cookie("mystery", "unknown")]
    r = ev(TRACKERS, obs(host(cookies=cookies)))
    assert (r["status"], r["reason"]) == ("not_assessed", "needs_browser_test")
    assert {c["name"] for c in r["details"]["cookies"]} == {"__cf_bm", "sessionid", "PHPSESSID", "connect.sid", "mystery"}


def test_direct_tracker_script_without_a_consent_manager_is_a_gap():
    t = {"vendor": "meta", "source": "inline", "strength": "direct", "consent_blocked": False}
    assert ev(TRACKERS, obs(host(trackers=[t])))["status"] == "gap"


@pytest.mark.parametrize("trackers,consent", [
    ([{"vendor": "meta", "source": "inline", "strength": "direct", "consent_blocked": False}], "cookiebot"),
    ([{"vendor": "google_analytics", "source": "script_src", "strength": "direct", "consent_blocked": True}], None),
    ([{"vendor": "google_tag_manager", "source": "script_src", "strength": "loader", "consent_blocked": False}], None),
    ([], None),
])
def test_trackers_behind_consent_loaders_alone_or_nothing_need_the_browser_test(trackers, consent):
    r = ev(TRACKERS, obs(host(trackers=trackers, consent=consent)))
    assert (r["status"], r["reason"]) == ("not_assessed", "needs_browser_test")


def test_trackers_before_consent_is_never_present():
    for observation in (obs(host()), obs(host(consent="onetrust"))):
        assert ev(TRACKERS, observation)["status"] != "present"


def test_dpo_contact_in_the_policy_is_present_otherwise_a_not_found_row():
    mentioned = {"dpo_contact": {"state": "mentioned", "phrase": "Data Protection Officer at <email>"}}
    assert ev(DPO, obs(host(signals=mentioned)))["status"] == "present"
    r = ev(DPO, obs(host(signals={"dpo_contact": {"state": "not_found", "phrase": None}})))
    assert (r["status"], r["reason"]) == ("not_assessed", "dpo_contact_not_found_in_policy")


def test_privacy_rows_are_externally_observed_with_expiry():
    rows = m.privacy_rows(privacy_requirements(), obs(host(pages=[page("privacy_policy", matched=True, url="u")])),
                          org_id="o", domain_id=D1["id"], scan_id="s", observed_at=NOW, register_version="v", apex=APEX)
    assert {r["source"] for r in rows} == {"externally_observed"} and len(rows) == 4
    policy = next(r for r in rows if r["requirement_key"] == POLICY["key"])
    assert policy["expires_at"] == NOW + timedelta(days=POLICY["freshness_days"]) and policy["finding_ids"] == []


# ── Read side: newest row wins; expiry only marks staleness ────────────────
def row(status, reason, days_old=1, freshness=90):
    observed = NOW - timedelta(days=days_old)
    return {"status": status, "observed_at": observed, "expires_at": observed + timedelta(days=freshness),
            "scan_id": "s", "finding_ids": [], "details": {"reason": reason}}


def status(req, latest, domains=(D1,)):
    return m.requirement_status(req, domains=list(domains), latest_rows=latest, live_findings=[], history=[], now=NOW)


def test_a_privacy_gap_stands_without_findings_unlike_tool_gaps():
    r = status(POLICY, {D1["id"]: row("gap", "not_found_by_static_check")})
    assert (r["status"], r["reason"]) == ("gap", "not_found_by_static_check")
    assert r["domains"][0]["source"] == "externally_observed"


def test_expired_privacy_rows_read_not_assessed():
    for latest in ({D1["id"]: row("gap", "x", days_old=100)}, {D1["id"]: row("present", "page_found", days_old=100)}):
        r = status(POLICY, latest)
        assert (r["status"], r["domains"][0]["reason"]) == ("not_assessed", "evidence_expired")


def test_no_privacy_row_is_not_assessed():
    r = status(POLICY, {})
    assert (r["status"], r["domains"][0]["reason"]) == ("not_assessed", "no_privacy_observation")


def test_one_domain_gap_makes_the_requirement_a_gap():
    r = status(POLICY, {D1["id"]: row("present", "page_found"), D2["id"]: row("gap", "not_found_by_static_check")},
               domains=(D1, D2))
    assert r["status"] == "gap"


def test_dpo_present_on_any_site_wins_and_otherwise_awaits_input():
    assert status(DPO, {D1["id"]: row("present", "dpo_contact_in_policy")})["status"] == "present"
    present_elsewhere = status(DPO, {D1["id"]: row("not_assessed", "dpo_contact_not_found_in_policy"),
                                     D2["id"]: row("present", "dpo_contact_in_policy")}, domains=(D1, D2))
    assert present_elsewhere["status"] == "present", "a present row is never overridden by awaiting input"
    assert status(DPO, {D1["id"]: row("not_assessed", "dpo_contact_not_found_in_policy")})["status"] == "awaiting_input"
    assert status(DPO, {})["status"] == "awaiting_input"


# ── Blocked hosts: not_assessed, never a gap, never "no trackers" ──────────
def blocked_host(name=APEX, reason="bot_protection:cloudflare"):
    return {**host(name), "blocked": True, "block_reason": reason}


def test_a_blocked_apex_is_not_assessed_for_every_privacy_signal():
    o = obs(blocked_host())
    for req in (POLICY, COOKIE, TRACKERS, DPO):
        r = ev(req, o)
        assert (r["status"], r["reason"]) == ("not_assessed", "blocked_by_bot_protection"), req["key"]
        assert r["details"]["block_reason"] == "bot_protection:cloudflare"


def test_a_blocked_apex_never_produces_a_tracker_gap():
    # Even if the probe somehow listed a tracker, a blocked host must not gap.
    o = obs({**blocked_host(), "first_response_cookies": [cookie("_ga", "tracker", "google_analytics")]})
    assert ev(TRACKERS, o)["status"] == "not_assessed"


def test_present_evidence_on_another_host_still_wins_over_a_blocked_apex():
    o = obs(blocked_host(), host("www.acme.test", pages=[page("privacy_policy", matched=True, url="https://www.acme.test/privacy")]))
    assert ev(POLICY, o)["status"] == "present"
