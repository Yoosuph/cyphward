"""Browser observation -> tool_observed evidence rows and the read-side merge (C2b). Pure, no database."""
import itertools
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.compliance import browser_observation as bo, mapping, status
from backend.app.compliance.register import requirement
from shared.browser_contracts import ConsentObservation

ROOT = pathlib.Path(__file__).resolve().parents[2]
BANNED = ("compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "compliance score",
          "fully meets", "meets the requirement", "is met", "adequate", "adequacy", "guarantee", "violates", "unlawful",
          "illegal", "breach of", "lawful", "legal requirement")
NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def cookie(name, third=False):
    return {"name": name, "domain": "acme.test", "secure": True, "http_only": False, "same_site": "lax",
            "lifetime": "session", "third_party": third}


def obs(cookies=(), hosts=(), banner=None, caps=None):
    return ConsentObservation.model_validate({
        "final_url": "https://acme.test/", "browser_version": "Chromium 153",
        "cookies": [cookie(n) for n in cookies],
        "requests": {"total": 5 + len(hosts), "first_party": 5, "third_party_hosts": [{"host": h, "count": 1} for h in hosts]},
        "banner": banner or {"detected": False, "in_first_view": False, "accept_control": False, "reject_control": "not_detected"},
        "timings": {"navigation_ms": 1, "settle_ms": 1, "total_ms": 3}, "caps": caps or {}})


BOTH = {"detected": True, "in_first_view": True, "cms_marker": "cookiebot", "accept_control": True, "reject_control": "same_level"}


def results(**kw):
    return {k: (v["status"], v["reason"]) for k, v in bo.results_for(obs(**kw)).items()}


def test_banner_requirement():
    assert results(banner=BOTH)[bo.BANNER_KEY] == ("present", "browser_banner_in_first_view")
    below = {**BOTH, "in_first_view": False}
    assert results(banner=below)[bo.BANNER_KEY] == ("gap", "browser_banner_below_first_view")
    # Not detecting a banner is never a gap: a heuristic cannot prove absence.
    assert results()[bo.BANNER_KEY] == ("not_assessed", "browser_banner_not_detected")


def test_accept_and_reject_requirement():
    assert results(banner=BOTH)[bo.CHOICE_KEY] == ("present", "browser_accept_and_reject_same_level")
    assert results(banner={**BOTH, "reject_control": "less_prominent"})[bo.CHOICE_KEY] == ("gap", "browser_reject_less_prominent")
    assert results(banner={**BOTH, "reject_control": "not_detected"})[bo.CHOICE_KEY] == ("gap", "browser_no_reject_control")
    assert results(banner={**BOTH, "accept_control": False, "reject_control": "not_detected"})[bo.CHOICE_KEY] == \
        ("not_assessed", "browser_controls_not_identified")
    assert results()[bo.CHOICE_KEY] == ("not_assessed", "browser_banner_not_detected")


def test_trackers_requirement():
    assert results(cookies=["_ga"])[bo.TRACKERS_KEY] == ("gap", "browser_tracking_before_choice")
    assert results(hosts=["www.google-analytics.com"])[bo.TRACKERS_KEY] == ("gap", "browser_tracking_before_choice")
    assert results(hosts=["connect.facebook.net"])[bo.TRACKERS_KEY][0] == "gap"
    assert results(cookies=["sessionid", "__cf_bm"])[bo.TRACKERS_KEY] == ("present", "browser_no_known_tracking")
    assert results()[bo.TRACKERS_KEY] == ("present", "browser_no_known_tracking")
    assert results(cookies=["mystery_cookie"])[bo.TRACKERS_KEY] == ("not_assessed", "browser_cookies_unclassified")
    assert results(hosts=["cdn.example.com"])[bo.TRACKERS_KEY][0] == "present"
    assert results(hosts=["notgoogle-analytics.com"])[bo.TRACKERS_KEY][0] == "present"  # suffix match is on a dot boundary


@pytest.mark.parametrize("cap", ["requests", "bytes", "cookies", "page_timeout"])
def test_a_capped_observation_can_show_a_gap_but_never_evidence_present(cap):
    out = results(banner=BOTH, caps={cap: True})
    assert out[bo.BANNER_KEY] == ("not_assessed", "browser_observation_capped")
    assert out[bo.TRACKERS_KEY] == ("not_assessed", "browser_observation_capped")
    assert results(cookies=["_ga"], caps={cap: True})[bo.TRACKERS_KEY][0] == "gap"
    assert results(banner={**BOTH, "reject_control": "not_detected"}, caps={cap: True})[bo.CHOICE_KEY][0] == "gap"


def test_rows_are_tool_observed_under_existing_register_keys_and_never_scan_linked():
    rows = bo.evidence_rows(obs(cookies=["_ga", "sid"], banner=BOTH), org_id="o", domain_id="d", job_id="j", observed_at=NOW)
    assert sorted(r["requirement_key"] for r in rows) == sorted(bo.KEYS)
    for row in rows:
        req = requirement(row["requirement_key"])
        assert req is not None and row["source"] == "tool_observed" and "scan_id" not in row
        assert row["expires_at"] == NOW + timedelta(days=req["freshness_days"])
        assert row["details"]["observation"] == "browser_consent_v1" and row["details"]["heuristic"] is True
        assert row["status"] in ("present", "gap", "not_assessed")  # never not_applicable
    label = next(r for r in rows if r["requirement_key"] == bo.TRACKERS_KEY)["details"]["browser_label"]
    assert label.startswith("The browser observed 2 cookies set before any choice was made")


@pytest.mark.parametrize("n,text", [(0, "0 cookies"), (1, "1 cookie "), (7, "7 cookies")])
def test_plain_language_cookie_count(n, text):
    names = [f"c{i}" for i in range(n)]
    label = bo.results_for(obs(cookies=names))[bo.TRACKERS_KEY]["label"]
    assert text in label and "before any choice was made" in label


def test_register_requirements_are_untouched_by_the_browser_mapping():
    for key in bo.KEYS:
        assert requirement(key)["evidence_types"] == ["externally_observed"]


def test_no_text_this_feature_can_produce_claims_a_verdict():
    texts = list(bo.all_static_text()) + [status.BROWSER_NOTE]
    banner_options = [None, BOTH, {**BOTH, "in_first_view": False}, {**BOTH, "reject_control": "less_prominent"},
                      {**BOTH, "reject_control": "not_detected"}, {**BOTH, "accept_control": False, "reject_control": "not_detected"}]
    for cookies, hosts, banner, caps in itertools.product(
            ([], ["_ga"], ["sid"], ["mystery"] * 3, [f"c{i}" for i in range(12)]),
            ([], ["www.google-analytics.com", "connect.facebook.net"], ["cdn.example.com"]),
            banner_options, ({}, {"bytes": True})):
        for result in bo.results_for(obs(cookies=cookies, hosts=hosts, banner=banner, caps=caps)).values():
            texts.append(result["label"])
    assert len(texts) > 100
    for text in texts:
        lowered = text.lower()
        for phrase in BANNED:
            assert phrase not in lowered, f"{phrase!r} in {text!r}"
        assert lowered.startswith(("the browser", "on a first visit", "no browser observation", "a separate browser worker",
                                   " a separate browser worker"))


def test_source_files_and_contract_strings_carry_no_verdict_language():
    paths = [ROOT / "backend/app/compliance/browser_observation.py", ROOT / "shared/browser_contracts.py",
             ROOT / "backend/app/api/browser_worker.py", ROOT / "backend/app/core/browser_jobs.py",
             *sorted((ROOT / "browser_worker").glob("*.py"))]
    runbook = ROOT / "docs/runbooks/browser-worker.md"
    if runbook.exists():
        paths.append(runbook)
    for path in paths:
        text = path.read_text().lower()
        for phrase in ("compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "compliance score",
                       "fully meets", "meets the requirement", "is met", "adequate", "adequacy", "guarantee", "violates", "unlawful"):
            assert phrase not in text, f"{path.name}: {phrase!r}"


# ── read-side merge ──────────────────────────────────────────────────────
D1, D2 = {"id": "00000000-0000-0000-0000-000000000001", "domain": "a.test"}, {"id": "00000000-0000-0000-0000-000000000002", "domain": "b.test"}


def row(key, state, reason, expires=NOW + timedelta(days=10)):
    return {"requirement_key": key, "status": state, "source": "tool_observed", "observed_at": NOW, "expires_at": expires,
            "scan_id": None, "finding_ids": [], "details": {"reason": reason, "observation": "browser_consent_v1", "browser_label": "L"}}


def awaiting():
    return {"status": "awaiting_input", "reason": "check_not_available_yet", "domains": [], "unlinked_finding_ids": []}


def test_no_browser_rows_returns_the_fallback_object_untouched():
    fallback = awaiting()
    assert bo.requirement_status(requirement(bo.BANNER_KEY), [D1], {}, fallback, NOW) is fallback


def test_merge_per_domain_expiry_and_static_gap_precedence():
    req = requirement(bo.BANNER_KEY)
    out = bo.requirement_status(req, [D1, D2], {D1["id"]: row(bo.BANNER_KEY, "present", "browser_banner_in_first_view")}, awaiting(), NOW)
    assert out["status"] == "not_assessed" and [d["status"] for d in out["domains"]] == ["present", "not_assessed"]
    assert out["domains"][0]["source"] == "tool_observed" and out["domains"][1]["reason"] == "no_browser_observation"
    both = {D1["id"]: row(bo.BANNER_KEY, "present", "x"), D2["id"]: row(bo.BANNER_KEY, "present", "x")}
    assert bo.requirement_status(req, [D1, D2], both, awaiting(), NOW)["status"] == "present"
    expired = {D1["id"]: row(bo.BANNER_KEY, "present", "x", expires=NOW - timedelta(seconds=1))}
    stale = bo.requirement_status(req, [D1], expired, awaiting(), NOW)
    assert stale["status"] == "not_assessed" and stale["domains"][0]["reason"] == "evidence_expired"

    tracker_req = requirement(bo.TRACKERS_KEY)
    static_gap = {"status": "gap", "reason": "tracker_before_consent", "unlinked_finding_ids": [],
                  "domains": [mapping._domain_result("gap", "tracker_before_consent", D1, {"details": {}},
                                                     source="externally_observed")]}
    merged = bo.requirement_status(tracker_req, [D1], {D1["id"]: row(bo.TRACKERS_KEY, "present", "browser_no_known_tracking")}, static_gap, NOW)
    assert merged["status"] == "gap" and merged["domains"][0]["source"] == "externally_observed"
    # The static not-assessed ("needs a browser test") is superseded by the browser's observation.
    static_open = {"status": "not_assessed", "reason": "needs_browser_test", "unlinked_finding_ids": [],
                   "domains": [mapping._domain_result("not_assessed", "needs_browser_test", D1, {"details": {}},
                                                      source="externally_observed")]}
    merged = bo.requirement_status(tracker_req, [D1], {D1["id"]: row(bo.TRACKERS_KEY, "present", "browser_no_known_tracking")}, static_open, NOW)
    assert merged["status"] == "present" and merged["domains"][0]["source"] == "tool_observed"


def test_feature_is_off_unless_the_flag_is_set(monkeypatch):
    from backend.app.core import config
    assert config.BROWSER_CONSENT_ENABLED is False and bo.enabled() is False
    monkeypatch.setattr(config, "BROWSER_CONSENT_ENABLED", True)
    assert bo.enabled() is True


# ── contract strictness without a database ───────────────────────────────
def test_contract_size_caps_and_unknown_fields():
    base = obs().model_dump()
    ConsentObservation.model_validate(base)
    for bad in ({"cookies": [cookie(f"c{i}") for i in range(101)]}, {"unknown": 1}, {"final_url": "https://a.test/#x"},
                {"browser_version": "x" * 65}):
        with pytest.raises(Exception):
            ConsentObservation.model_validate({**base, **bad})
    hosts = [{"host": f"h{i}.example", "count": 1} for i in range(101)]
    with pytest.raises(Exception):
        ConsentObservation.model_validate({**base, "requests": {"total": 500, "first_party": 0, "third_party_hosts": hosts}})
