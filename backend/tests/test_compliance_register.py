"""Register loading and validation (compliance packet C1)."""
import copy
import json

import pytest

from backend.app.compliance import register as reg
from backend.app.compliance.rule_keys import NUCLEI_PREFIX, RULES
from backend.app.risk.check_set import DECLARED_CHECKS

RAW = json.loads(reg.REGISTER_FILE.read_text())


def test_register_v1_2_loads_with_29_requirements_in_11_groups():
    assert reg.REGISTER["version"] == "ndpa-gaid-v1.2"
    assert len(reg.requirements()) == 29 and len(reg.REGISTER["groups"]) == 11
    assert len(reg.tool_requirements()) == 5
    assert [r["key"] for r in reg.privacy_requirements()] == [
        "gaid.notice.privacy_policy", "gaid.notice.cookie_notice", "gaid.consent.no_trackers_before_consent",
        "gaid.dpo.contact_published"]


def test_every_clause_ships_pending_review():
    assert all(r["clause_verified"] is False for r in reg.requirements())


def test_every_tool_mapping_names_real_checks_and_rule_keys():
    for r in reg.requirements():
        mapping = r.get("tool_mapping")
        if not mapping or "scan_history" in mapping:
            continue
        if "privacy" in mapping:
            assert mapping["privacy"]["signal"] in reg.PRIVACY_SIGNALS and "externally_observed" in r["evidence_types"]
            continue
        assert set(mapping["checks"]) <= set(DECLARED_CHECKS), r["key"]
        for rule in mapping["rules"]:
            assert rule in RULES or rule == f"{NUCLEI_PREFIX}*", (r["key"], rule)


def test_tool_backed_requirements_state_what_was_and_was_not_checked():
    for r in reg.requirements():
        if r.get("tool_mapping"):
            assert r["checks_performed"].strip() and r["not_checked"].strip(), r["key"]


def _broken(change):
    data = copy.deepcopy(RAW)
    change(data)
    with pytest.raises(reg.RegisterError):
        reg.validate(data)


def _first(data, key):
    return next(r for r in data["requirements"] if r["key"] == key)


@pytest.mark.parametrize("change", [
    lambda d: d["requirements"][0].pop("summary"),
    lambda d: d["requirements"].append(copy.deepcopy(d["requirements"][0])),
    lambda d: d["requirements"][0].update(group="nope"),
    lambda d: d["requirements"][0].update(applies_to="sometimes"),
    lambda d: d["requirements"][0].update(evidence_types=["tool_observed", "rumour"]),
    lambda d: _first(d, "ndpa.s39.email_anti_spoofing")["tool_mapping"].update(checks=["dns.dkim"]),
    lambda d: _first(d, "ndpa.s39.email_anti_spoofing")["tool_mapping"].update(rules=["dns.made_up"]),
    lambda d: _first(d, "ndpa.s39.email_anti_spoofing").pop("not_checked"),
    lambda d: _first(d, "ndpa.s39.email_anti_spoofing").update(clause_verified=True),
    lambda d: _first(d, "gaid.dpia.high_risk_processing").pop("applicability_question"),
    lambda d: _first(d, "gaid.training.in_place").update(evidence_types=["tool_observed"]),
    lambda d: d["requirements"][0].update(freshness_days=0),
    lambda d: d.update(version=""),
    lambda d: _first(d, "gaid.notice.privacy_policy")["tool_mapping"]["privacy"].update(signal="vibes"),
    lambda d: _first(d, "gaid.notice.privacy_policy").update(evidence_types=["tool_observed"]),
    lambda d: _first(d, "gaid.notice.privacy_policy").pop("checks_performed"),
    lambda d: _first(d, "gaid.notice.privacy_policy")["tool_mapping"].update(checks=["http.headers"]),
])
def test_invalid_registers_are_rejected(change):
    _broken(change)


def test_a_reviewed_clause_needs_a_reviewer():
    data = copy.deepcopy(RAW)
    _first(data, "ndpa.s39.email_anti_spoofing").update(clause_verified=True, clause_reviewed_by="Founder, 2026-10-20")
    reg.validate(data)
