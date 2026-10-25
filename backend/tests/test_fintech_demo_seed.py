"""Pure checks for the Fintech Org sample-data seed (no database). The Postgres behaviour is in
test_fintech_demo_seed_postgres.py."""
import re

import pytest

from backend.app.core import demo_org
from backend.scripts import seed_fintech_demo as demo

BANNED = ("compliant", "certified", "certification", "satisfies", "satisfied", "adequate", "adequacy", "guarantee",
          "passes audit", "pass the audit", "compliance score", "meets the requirement", "fully meets",
          "is met", "partial compliance", "fully compliant", "is compliant", "non-compliant", "noncompliant")
LOCAL = "postgresql://cyphward_app@127.0.0.1:55432/cyphward_test"


def _texts():
    out = [demo.DEMO_ORG_NAME, demo.DEMO_NAME, demo.SAMPLE_NOTE, demo.COVERAGE["label"]]
    for finding in demo.FINDINGS:
        out += [finding["title"], finding["description"], finding["remediation"]]
    for item in demo.INCIDENTS:
        out += [item["title"], item["notes"]]
    for _, answer in demo.ATTESTATIONS:
        out.append(repr(answer))
    out += [task["title"] for task in demo.REMEDIATION_TASKS]
    return out


def test_seed_text_carries_no_banned_claim_phrase():
    for text in _texts():
        for phrase in BANNED:
            assert not re.search(r"\b" + re.escape(phrase) + r"\b", text.lower()), (phrase, text)


def test_every_sample_finding_is_labelled_as_sample():
    for finding in demo.FINDINGS:
        assert finding["title"].startswith("SAMPLE:"), finding["title"]
    assert demo.SAMPLE_LABEL in demo.DEMO_ORG_NAME


def test_the_demo_uses_only_reserved_or_sample_identities():
    assert demo.DEMO_EMAIL.endswith(".test")
    assert demo.DEMO_TOKEN.startswith("sample-")
    assert demo.DEMO_DOMAIN == "scanme.nmap.org"
    assert demo.DEMO_ORG_ID == demo_org.DEMO_ORG_ID and demo.DEMO_USER_ID == demo_org.DEMO_USER_ID


def test_observed_findings_follow_first_seen_and_resolution():
    assert [len(demo.observed_in(n)) for n in (1, 2, 3)] == [7, 9, 7]
    latest = {f["key"] for f in demo.observed_in(3)}
    assert latest == {"spf-all", "dmarc-none", "xfo", "version-leak", "security-txt", "samesite", "referrer"}
    assert all(f["resolved"] is None or f["resolved"] > 3 for f in demo.observed_in(3))


@pytest.mark.parametrize("url,target,confirm", [
    ("postgresql://u@db.example.com/cyphward_prod", "local", None),
    ("postgresql://u@127.0.0.1:55432/postgres", "local", None),
    ("postgresql://u@127.0.0.1:55432/cyphward", "local", None),
    (LOCAL, "production", None),
    (LOCAL, "production", "yes"),
    ("", "local", None),
])
def test_refuses_any_destination_it_should_not_write(url, target, confirm):
    with pytest.raises(demo.RefusedTarget):
        demo.check_target(url, target, confirm)


def test_accepts_loopback_test_database_and_explicit_production_confirmation():
    demo.check_target(LOCAL, "local", None)
    demo.check_target("postgresql://u@db.example.com/cyphward", "production", demo.PRODUCTION_CONFIRMATION)


def test_seed_needs_a_password_of_the_apps_minimum_length(monkeypatch):
    with pytest.raises(demo.RefusedTarget):
        demo.seed(LOCAL, "short", apply=True)


def test_the_dry_run_plan_matches_the_constants():
    counts = demo.plan_counts()
    assert counts["scans (completed)"] == len(demo.SCANS) == 3
    assert counts["findings open in latest scan"] == len(demo.observed_in(3)) == 7
    assert counts["findings (across scans)"] == len(demo.FINDINGS)
