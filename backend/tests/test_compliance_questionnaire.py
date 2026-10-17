"""Questionnaire validation and the attestation truth table (packet C3a, sections 2, 3 and 8).

Pure tests against an in-memory fake store: no database. Every case is one
row of the truth table in C3-plan.md section 3, plus the validator's rejections.
"""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.compliance import attestations as truth
from backend.app.compliance import mapping
from backend.app.compliance import questionnaire as qn
from backend.app.compliance import register
from backend.app.compliance import status as compliance_status

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
RAW = json.loads(qn.QUESTIONNAIRE_FILE.read_text())
BANNED = ("compliant", "certified", "satisfies", "satisfied", "passes audit", "pass the audit",
          "compliance score", "fully meets", "meets the requirement", "is met")


def answer(qkey, value, *, days=365, date_value=None, text=None, when=NOW):
    """A current answer row, as the store returns it (expiry relative to NOW)."""
    body = {"value": value}
    if date_value:
        body["date"] = date_value
    if text:
        body["text"] = text
    return {"id": f"id-{qkey}", "question_key": qkey, "answer": body, "owner_user_id": "u",
            "owner_name": "Owner", "attested_at": when, "expires_at": when + timedelta(days=days)}


def outcome(requirement, *rows):
    current = {r["question_key"]: r for r in rows}
    return truth.requirement_outcome(requirement, current, NOW)


def statuses(requirement, *rows):
    result = outcome(requirement, *rows)
    return result["status"], result["reason"]


# ── Validator ─────────────────────────────────────────────────────────────


def _validate(mutate):
    data = copy.deepcopy(RAW)
    mutate(data)
    return qn.validate(data)


def _question(data, key):
    return next(q for q in data["questions"] if q["key"] == key)


def test_questionnaire_v1_has_the_twenty_plan_questions():
    keys = [q["key"] for q in qn.QUESTIONS]
    assert len(keys) == 20 and len(set(keys)) == 20
    assert {"registration.major_importance", "registration.tier", "dpia.high_risk_processing",
            "transfers.outside_nigeria"} <= set(keys)
    assert qn.QUESTIONNAIRE["register_version"] == register.REGISTER["version"]


def test_every_customer_answered_requirement_has_a_question():
    customer = {r["key"] for r in register.requirements() if "customer_attested" in r["evidence_types"]}
    covered = {k for q in qn.QUESTIONS for k in q["evidences"]}
    assert customer <= covered


def test_rejects_unknown_requirement_key():
    with pytest.raises(qn.QuestionnaireError, match="unknown requirement"):
        _validate(lambda d: _question(d, "dpo.designated")["evidences"].append("gaid.made.up"))


def test_rejects_requirement_that_does_not_take_customer_answers():
    with pytest.raises(qn.QuestionnaireError, match="does not take customer answers"):
        _validate(lambda d: _question(d, "dpo.designated")["evidences"].append("ndpa.s39.encryption_in_transit"))


def test_rejects_requirement_in_another_group():
    with pytest.raises(qn.QuestionnaireError, match="belongs to group"):
        _validate(lambda d: _question(d, "dpo.designated").update(group="breach"))


def test_rejects_bad_type_and_missing_options():
    with pytest.raises(qn.QuestionnaireError, match="type must be one of"):
        _validate(lambda d: _question(d, "dpo.designated").update(type="free_text"))
    with pytest.raises(qn.QuestionnaireError, match="choice needs"):
        _validate(lambda d: _question(d, "registration.tier").update(options=[]))


def test_rejects_evidence_on_that_is_not_an_answer():
    with pytest.raises(qn.QuestionnaireError, match="not allowed"):
        _validate(lambda d: _question(d, "dpo.designated")["evidence_on"].update(maybe="present"))
    with pytest.raises(qn.QuestionnaireError, match="not allowed"):
        _validate(lambda d: _question(d, "dpo.designated")["evidence_on"].update(no="awaiting_input"))


def test_rejects_not_applicable_without_permission_to_answer_it():
    with pytest.raises(qn.QuestionnaireError, match="not allowed"):
        _validate(lambda d: _question(d, "dpo.designated")["evidence_on"].update(not_applicable="not_applicable"))


def test_rejects_applicability_target_the_question_does_not_decide():
    with pytest.raises(qn.QuestionnaireError, match="not decided by this question"):
        _validate(lambda d: _question(d, "transfers.outside_nigeria")["applicability"].append(
            {"target": "gaid.registration.annual_car", "when": "no"}))


def test_rejects_unknown_applicability_target():
    with pytest.raises(qn.QuestionnaireError, match="unknown applicability target"):
        _validate(lambda d: _question(d, "transfers.outside_nigeria")["applicability"].append(
            {"target": "ndpa.nope", "when": "no"}))


def test_rejects_applicability_answer_that_is_not_a_value_of_the_question():
    with pytest.raises(qn.QuestionnaireError, match="is not an answer"):
        _validate(lambda d: _question(d, "transfers.outside_nigeria")["applicability"][0].update(when="ohl"))


def test_rejects_conditional_requirement_that_no_question_decides():
    def drop(data):
        _question(data, "registration.major_importance")["applicability"] = []
    with pytest.raises(qn.QuestionnaireError, match="no question decides it"):
        _validate(drop)


def test_rejects_customer_requirement_with_no_question():
    def drop(data):
        data["questions"] = [q for q in data["questions"] if q["key"] != "dpo.designated"]
    with pytest.raises(qn.QuestionnaireError, match="no question asks for them"):
        _validate(drop)


def test_rejects_show_if_that_names_a_later_or_unknown_question():
    with pytest.raises(qn.QuestionnaireError, match="earlier question"):
        _validate(lambda d: _question(d, "dpo.designated").update(
            show_if={"question": "dpia.done", "value": "yes"}))


def test_rejects_duplicate_key_and_unknown_register_version():
    with pytest.raises(qn.QuestionnaireError, match="duplicate key"):
        _validate(lambda d: d["questions"].append(copy.deepcopy(_question(d, "dpo.designated"))))
    with pytest.raises(qn.QuestionnaireError, match="register_version"):
        _validate(lambda d: d.update(register_version="ndpa-gaid-v0"))


def test_rejects_expiry_on_a_non_date_question():
    with pytest.raises(qn.QuestionnaireError, match="expiry_days_from_date"):
        _validate(lambda d: _question(d, "dpo.designated").update(expiry_days_from_date=30))


def test_every_question_text_avoids_verdict_language():
    texts = []
    for q in RAW["questions"]:
        texts += [q["prompt"], q.get("date_label") or "", q.get("text_label") or ""]
    texts += [compliance_status.REASON_TEXT[k] for k in truth.REASON_TEXT]
    for text in texts:
        for phrase in BANNED:
            assert phrase not in text.lower(), (phrase, text)


# ── Answer validation ────────────────────────────────────────────────────


def test_not_sure_is_accepted_on_every_question_type():
    for key in ("dpo.designated", "registration.tier", "dpo.six_monthly_report"):
        question = qn.question(key)
        assert truth.normalize_answer(question, {"value": "not_sure"}, NOW.date()) == {"value": "not_sure"}


def test_rejects_answers_that_do_not_fit_the_question():
    yes_no = qn.question("dpo.designated")
    with pytest.raises(truth.AnswerError, match="not an answer"):
        truth.normalize_answer(yes_no, {"value": "maybe"}, NOW.date())
    with pytest.raises(truth.AnswerError, match="does not take text"):
        truth.normalize_answer(qn.question("breach.response_plan"), {"value": "yes", "text": "x"}, NOW.date())
    with pytest.raises(truth.AnswerError, match="does not take a date"):
        truth.normalize_answer(qn.question("breach.response_plan"), {"value": "yes", "date": "2026-01-01"},
                               NOW.date())
    with pytest.raises(truth.AnswerError, match="Give the date"):
        truth.normalize_answer(qn.question("dpo.six_monthly_report"), {"value": "date"}, NOW.date())


def test_rejects_bad_and_future_dates():
    question = qn.question("dpo.six_monthly_report")
    for bad in ("2026-13-01", "17/10/2026", "2026-10-18"):
        with pytest.raises(truth.AnswerError):
            truth.normalize_answer(question, {"value": "date", "date": bad}, NOW.date())


def test_text_is_bounded_and_refuses_long_numbers():
    question = qn.question("dpo.designated")
    assert truth.normalize_answer(question, {"value": "yes", "text": "  Ada, DPO  "}, NOW.date())["text"] == "Ada, DPO"
    with pytest.raises(truth.AnswerError, match="at most 120"):
        truth.normalize_answer(question, {"value": "yes", "text": "x" * 121}, NOW.date())
    with pytest.raises(truth.AnswerError, match="personal ID"):
        truth.normalize_answer(question, {"value": "yes", "text": "ID 12345678"}, NOW.date())


def test_expiry_defaults_to_twelve_months_and_is_capped_at_twenty_four():
    question = qn.question("breach.response_plan")
    assert truth.expiry_for(question, {"value": "yes"}, None, NOW) == NOW + timedelta(days=365)
    with pytest.raises(truth.AnswerError, match="24 months"):
        truth.expiry_for(question, {"value": "yes"}, NOW + timedelta(days=731), NOW)
    with pytest.raises(truth.AnswerError, match="in the future"):
        truth.expiry_for(question, {"value": "yes"}, NOW - timedelta(days=1), NOW)


def test_date_questions_expire_from_their_date_and_refuse_a_chosen_expiry():
    six_monthly = qn.question("dpo.six_monthly_report")
    expiry = truth.expiry_for(six_monthly, {"value": "date", "date": "2026-04-01"}, None, NOW)
    assert expiry == datetime(2026, 4, 1, tzinfo=timezone.utc) + timedelta(days=183)
    training = qn.question("training.last_session")
    assert truth.expiry_for(training, {"value": "date", "date": "2026-02-01"}, None, NOW) == \
        datetime(2026, 2, 1, tzinfo=timezone.utc) + timedelta(days=365)
    with pytest.raises(truth.AnswerError, match="follows its date"):
        truth.expiry_for(six_monthly, {"value": "date", "date": "2026-04-01"}, NOW + timedelta(days=5), NOW)


# ── Truth table (C3-plan section 3) ──────────────────────────────────────


def test_yes_is_present_with_the_answer_expiry():
    result = outcome("gaid.dpo.designated", answer("dpo.designated", "yes", days=200))
    assert result["status"] == "present" and result["reason"] == "answer_present"
    assert result["expires_at"] == NOW + timedelta(days=200)


def test_no_is_a_gap():
    assert statuses("gaid.dpo.designated", answer("dpo.designated", "no")) == ("gap", "answer_gap")


def test_not_sure_is_awaiting_input_never_a_gap():
    assert statuses("gaid.dpo.designated", answer("dpo.designated", "not_sure")) == \
        ("awaiting_input", "answer_not_sure")


def test_unanswered_is_awaiting_input():
    assert statuses("gaid.dpo.designated") == ("awaiting_input", "awaiting_answer")


def test_expired_yes_is_awaiting_renewal_never_present():
    assert statuses("gaid.dpo.designated", answer("dpo.designated", "yes", days=-1)) == \
        ("awaiting_input", "answer_expired")


def test_expired_no_is_also_awaiting_renewal_not_a_gap():
    assert statuses("gaid.dpo.designated", answer("dpo.designated", "no", days=-1)) == \
        ("awaiting_input", "answer_expired")


def test_applicability_no_excludes_the_dependent_requirement_with_the_reason():
    # A1 = no: registration.registered leaves the denominator, recorded against A1.
    result = outcome("gaid.registration.registered", answer("registration.major_importance", "no"))
    assert result["status"] == "not_applicable" and result["reason"] == "answered_not_applicable"
    assert result["answers"][0]["question_key"] == "registration.major_importance"


def test_major_importance_answer_is_evidence_either_way():
    assert statuses("gaid.registration.major_importance_status",
                    answer("registration.major_importance", "yes"))[0] == "present"
    assert statuses("gaid.registration.major_importance_status",
                    answer("registration.major_importance", "no"))[0] == "present"


def test_unsure_applicability_keeps_the_requirement_applicable():
    result = outcome("gaid.registration.registered", answer("registration.major_importance", "not_sure"))
    assert result["status"] == "awaiting_input" and result["reason"] == "awaiting_answer"


def test_expired_applicability_answer_does_not_exclude_the_requirement():
    result = outcome("gaid.registration.registered", answer("registration.major_importance", "no", days=-1))
    assert result["status"] == "awaiting_input" and result["reason"] == "answer_expired"


def test_applicability_yes_does_not_exclude_and_evidence_decides():
    rows = (answer("registration.major_importance", "yes"), answer("registration.registered", "yes"))
    assert statuses("gaid.registration.registered", *rows) == ("present", "answer_present")


def test_ohl_tier_excludes_annual_car_and_uhl_leaves_it_applicable():
    major = answer("registration.major_importance", "yes")  # the tier question shows only when this is yes
    assert statuses("gaid.registration.annual_car", major, answer("registration.tier", "ohl"))[0] == "not_applicable"
    assert statuses("gaid.registration.annual_car", major, answer("registration.tier", "uhl")) == \
        ("awaiting_input", "awaiting_answer")


def test_hidden_follow_up_question_does_not_count():
    # The tier question shows only when A1 = yes. With A1 unanswered, its answer is ignored.
    rows = (answer("registration.tier", "ohl"),)
    assert statuses("gaid.registration.annual_car", *rows) == ("awaiting_input", "awaiting_answer")


def test_dpia_follow_up_only_shows_when_high_risk_processing_is_yes():
    rows = (answer("dpia.high_risk_processing", "no"), answer("dpia.done", "yes"))
    assert statuses("gaid.dpia.high_risk_processing", *rows)[0] == "not_applicable"
    rows = (answer("dpia.high_risk_processing", "yes"), answer("dpia.done", "yes", date_value=None))
    assert statuses("gaid.dpia.high_risk_processing", *rows)[0] == "present"


def test_consent_records_not_applicable_answer_leaves_the_denominator():
    result = outcome("gaid.consent.records_kept", answer("consent.records_kept", "not_applicable"))
    assert result["status"] == "not_applicable"


def test_six_monthly_date_is_present_until_183_days_after_it():
    six_monthly = qn.question("dpo.six_monthly_report")
    expires = truth.expiry_for(six_monthly, {"value": "date", "date": "2026-07-01"}, None, NOW)
    row = {**answer("dpo.six_monthly_report", "date", date_value="2026-07-01"), "expires_at": expires}
    assert statuses("gaid.dpo.six_monthly_report", row) == ("present", "answer_present")
    stale_expiry = truth.expiry_for(six_monthly, {"value": "date", "date": "2025-01-01"}, None, NOW)
    stale = {**answer("dpo.six_monthly_report", "date", date_value="2025-01-01"), "expires_at": stale_expiry}
    assert statuses("gaid.dpo.six_monthly_report", stale) == ("awaiting_input", "answer_expired")


def test_training_needs_yes_and_a_recent_session_date():
    assert statuses("gaid.training.in_place", answer("training.in_place", "yes"),
                    answer("training.last_session", "date", date_value="2026-06-01"))[0] == "present"
    assert statuses("gaid.training.in_place", answer("training.in_place", "yes"))[0] == "awaiting_input"
    assert statuses("gaid.training.in_place", answer("training.in_place", "no"),
                    answer("training.last_session", "date", date_value="2026-06-01"))[0] == "gap"


def test_training_expiry_is_the_earlier_of_its_answers():
    result = outcome("gaid.training.in_place",
                     answer("training.in_place", "yes", days=300),
                     answer("training.last_session", "date", date_value="2026-06-01", days=100))
    assert result["expires_at"] == NOW + timedelta(days=100)


def test_requirement_without_any_question_has_no_customer_outcome():
    assert truth.requirement_outcome("ndpa.s39.encryption_in_transit", {}, NOW) is None


def test_not_applicable_leaves_the_readiness_denominator():
    statuses_ = ["not_applicable", "present", "awaiting_input", "gap"]
    counts = mapping.readiness(statuses_)
    assert counts["applicable"] == 3 and counts["present"] == 1 and counts["awaiting_input"] == 1


# ── Mixed sources and labels ─────────────────────────────────────────────


def _observed(status, reason="x", source="externally_observed"):
    return {"status": status, "reason": reason, "domains": [{"domain": "a.test", "status": status,
                                                             "source": source, "reason": reason}],
            "unlinked_finding_ids": []}


def test_dpo_contact_present_from_either_source_and_both_sources_are_shown():
    attested = truth.requirement_outcome("gaid.dpo.contact_published",
                                         {"dpo.contact_published": answer("dpo.contact_published", "yes")}, NOW)
    merged = truth.merge(_observed("awaiting_input", "dpo_contact_not_found_in_policy"), attested, True)
    assert merged["status"] == "present" and merged["headline_source"] == "customer_attested"
    assert {s["source"] for s in merged["sources"]} == {"externally_observed", "customer_attested"}


def test_observed_present_is_not_overridden_by_a_no_answer_but_the_gap_is_shown():
    attested = truth.requirement_outcome("gaid.dpo.contact_published",
                                         {"dpo.contact_published": answer("dpo.contact_published", "no")}, NOW)
    merged = truth.merge(_observed("present", "dpo_contact_in_policy"), attested, True)
    assert merged["status"] == "present" and merged["headline_source"] == "externally_observed"
    gap = next(s for s in merged["sources"] if s["source"] == "customer_attested")
    assert gap["status"] == "gap"


def test_observed_gap_is_shown_beside_a_yes_answer():
    attested = truth.requirement_outcome("gaid.dpo.contact_published",
                                         {"dpo.contact_published": answer("dpo.contact_published", "yes")}, NOW)
    merged = truth.merge(_observed("gap", "policy_missing"), attested, True)
    assert merged["status"] == "present"
    assert any(s["source"] == "externally_observed" and s["status"] == "gap" for s in merged["sources"])


def test_observed_gap_is_the_headline_when_the_answer_is_not_yet_given():
    unanswered = truth.requirement_outcome("gaid.dpo.contact_published", {}, NOW)
    merged = truth.merge(_observed("gap", "policy_missing"), unanswered, True)
    assert merged["status"] == "gap" and merged["headline_source"] == "externally_observed"


def test_customer_gap_is_the_headline_when_observed_is_only_awaiting():
    attested_gap = truth.requirement_outcome("gaid.dpo.contact_published",
                                             {"dpo.contact_published": answer("dpo.contact_published", "no")}, NOW)
    merged = truth.merge(_observed("awaiting_input", "x"), attested_gap, True)
    assert merged["status"] == "gap" and merged["headline_source"] == "customer_attested"


def test_customer_answer_is_only_ever_labelled_customer_attested():
    attested = truth.requirement_outcome("gaid.dpo.designated",
                                         {"dpo.designated": answer("dpo.designated", "yes")}, NOW)
    merged = truth.merge(None, attested, False)
    assert merged["headline_source"] == "customer_attested"
    assert [s["source"] for s in merged["sources"]] == ["customer_attested"]


def test_customer_answer_never_inherits_a_tool_label_from_a_domain():
    observed = {"status": "awaiting_input", "reason": "awaiting_customer_input", "domains": [],
                "unlinked_finding_ids": []}
    attested = truth.requirement_outcome("gaid.dpo.designated",
                                         {"dpo.designated": answer("dpo.designated", "yes")}, NOW)
    merged = truth.merge(observed, attested, False)
    assert merged["headline_source"] == "customer_attested"
    assert "tool_observed" not in {s["source"] for s in merged["sources"]}


# ── Overview: customer answers reach the page, labelled, through the same path ──


def test_overview_labels_answers_customer_attested_and_excludes_not_applicable(monkeypatch):
    ctx = {"domains": [{"id": "d1", "domain": "acme.test"}], "latest": {}, "live": [], "history": [],
           "answers": {
               "registration.major_importance": answer("registration.major_importance", "no"),
               "dpo.designated": answer("dpo.designated", "yes"),
           }}
    monkeypatch.setattr(compliance_status, "_context", lambda org_id: ctx)
    monkeypatch.setattr(compliance_status, "_plan", lambda org: "growth")
    monkeypatch.setattr(compliance_status, "_findings", lambda org_id, ids: {})
    payload = compliance_status.overview({"id": "org"})
    by_key = {r["key"]: r for g in payload["groups"] for r in g["requirements"]}
    registered = by_key["gaid.registration.registered"]
    assert registered["status"] == "not_applicable" and registered["reason"] == "answered_not_applicable"
    designated = by_key["gaid.dpo.designated"]
    assert designated["status"] == "present" and designated["source"] == "customer_attested"
    assert designated["source_label"] == "Customer attested"
    assert designated["answers"][0]["owner_name"] == "Owner"
    assert "tool_observed" not in {s["source"] for s in designated["sources"]}
    assert payload["readiness"]["applicable"] == 28  # 29 requirements, one excluded by the answer
