"""AI-drafted documents (packet C5): pure checks, no database and no network.

Covers: placeholders come from the inputs (never from the model); a 'no' answer is never a statement of fact;
every deterministic template passes the banned-phrase lists; model output that drops a token, invents a fact or
claims compliance is rejected; customer text is cleaned and never reaches the model prompt.
"""
import asyncio
import itertools
import re
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.compliance import document_store as store
from backend.app.compliance import documents as docs
from backend.tests.test_compliance_claims import BANNED as CLAIMS_BANNED
from backend.tests.test_compliance_claims import READINESS_BANNED
from backend.tests.test_compliance_questionnaire import BANNED as QUESTIONNAIRE_BANNED

NOW = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)
ALL_BANNED = set(CLAIMS_BANNED) | set(READINESS_BANNED) | set(QUESTIONNAIRE_BANNED) | {
    "guarantee", "fully compliant", "meets the requirements", "adequate", "adequacy", "legally sufficient"}


def row(value, text=None, days=100):
    answer = {"value": value}
    if text is not None:
        answer["text"] = text
    return {"answer": answer, "expires_at": NOW + timedelta(days=days)}


def ctx(answers=None, observed=None, org="Acme Traders", domains=("acme.example",)):
    return {"org_name": org, "domains": list(domains), "answers": answers or {}, "observed": observed or {}}


def obs(status, days=30):
    return {"d1": {"status": status, "expires_at": NOW + timedelta(days=days)}}


FULL = {"dpo.designated": row("yes", "Ada Obi, Head of Legal"), "transfers.outside_nigeria": row("yes"),
        "rights.process": row("yes"), "breach.notification_process": row("yes"), "breach.incident_log": row("yes")}
OBSERVED = {"gaid.consent.accept_and_reject": obs("present"), "gaid.consent.purpose_and_withdrawal": obs("present")}


def inputs_for(kind, answers=None, observed=None, **kw):
    return docs.build_inputs(kind, ctx(answers, observed, **kw), NOW)


def draft(kind, answers=None, observed=None):
    inputs = inputs_for(kind, answers, observed)
    template = docs.build_template(inputs)
    text = docs.compose(docs.fill_slots(template, inputs), inputs, version=1, generated_at=NOW)
    return inputs, template, text


# ── Placeholders and grounding ────────────────────────────────────────────────


def test_every_draft_starts_with_the_label_and_carries_version_and_date():
    for kind in docs.KINDS:
        _, _, text = draft(kind, FULL, OBSERVED)
        assert text.startswith("Draft — not legal advice\n")
        assert "Version 1 · Generated 2026-10-18 (UTC)" in text
        assert text.rstrip().endswith("has not checked it.")


def test_empty_inputs_leave_visible_placeholders_and_invent_nothing():
    inputs, _, text = draft("privacy_policy")
    assert "[MISSING: name of your data protection officer]" in text
    assert "[MISSING: whether personal data is stored or sent outside Nigeria]" in text
    for item in docs.placeholders_for(inputs):
        assert item["text"] in text
    assert "Ada" not in text and "outside Nigeria, for example" not in text


def test_placeholder_list_comes_from_the_inputs_not_the_text():
    inputs = inputs_for("privacy_policy", FULL)
    keys = {p["key"] for p in docs.placeholders_for(inputs)}
    assert "dpo_name" not in keys and "transfers_outside_nigeria" not in keys
    assert {"controller_address", "dpo_contact", "retention"} <= keys  # nothing collects these


def test_answers_fill_the_draft_and_the_name_is_substituted_by_code():
    inputs, template, text = draft("privacy_policy", FULL)
    assert "Ada Obi, Head of Legal" not in template and "{{DPO_NAME}}" in template
    assert "Ada Obi, Head of Legal" in text and "Acme Traders" in text and "acme.example" in text
    assert "Personal data may be stored or sent outside Nigeria" in text


def test_a_no_answer_is_not_stated_as_fact_except_where_it_describes_practice():
    answers = {"rights.process": row("no"), "breach.incident_log": row("no"), "transfers.outside_nigeria": row("no")}
    _, _, policy = draft("privacy_policy", answers)
    assert "you reported this is not in place yet" in policy
    assert "You can ask to see, correct" not in policy
    assert "We do not store or send personal data outside Nigeria." in policy
    _, _, plan = draft("breach_response_plan", answers)
    assert "Every incident is written in our incident log" not in plan
    assert "[MISSING: whether you keep an incident log — you reported this is not in place yet]" in plan


def test_expired_not_sure_and_hidden_answers_count_as_missing():
    answers = {"dpo.designated": row("yes", "Ada Obi", days=-1), "rights.process": row("not_sure")}
    inputs = inputs_for("privacy_policy", answers)
    states = {f["key"]: f["state"] for f in inputs["facts"]}
    assert states["dpo_name"] == "missing" and states["rights_process"] == "missing"


def test_cookie_notice_uses_only_current_observed_signals():
    _, _, text = draft("cookie_notice", observed=OBSERVED)
    assert "a banner lets you accept or reject" in text and "change or withdraw your choice" in text
    _, _, text = draft("cookie_notice", observed={"gaid.consent.accept_and_reject": obs("gap"),
                                                  "gaid.consent.purpose_and_withdrawal": obs("present", days=-1)})
    assert "a banner lets you accept or reject" not in text and "change or withdraw your choice" not in text
    assert "your last scan did not confirm it" in text
    assert "[MISSING: how a visitor changes or withdraws cookie consent]" in text


def test_retention_schedule_is_placeholders_only_for_periods():
    inputs, _, text = draft("retention_schedule", FULL)
    assert text.count("[MISSING: retention period for each data category]") == 3
    assert not re.search(r"\b\d+ (days|months|years)\b", text)
    assert "[MISSING: data category]" in text


def test_hash_changes_with_the_inputs_and_is_stable_otherwise():
    a = docs.inputs_hash(inputs_for("privacy_policy", FULL))
    assert a == docs.inputs_hash(inputs_for("privacy_policy", FULL))
    assert a != docs.inputs_hash(inputs_for("privacy_policy", {**FULL, "rights.process": row("no")}))


# ── Banned phrases in the deterministic templates ─────────────────────────────


def test_no_template_or_assembled_draft_uses_a_banned_phrase():
    combos = [None, FULL, {"rights.process": row("no"), "dpo.designated": row("no")}]
    for kind, answers, observed in itertools.product(docs.KINDS, combos, (None, OBSERVED)):
        _, template, text = draft(kind, answers, observed)
        assert docs.final_problems(text, inputs_for(kind, answers, observed)) == [], kind
        for body in (template, text):
            lowered = body.lower()
            for phrase in ALL_BANNED | set(docs.BANNED):
                assert phrase not in lowered, f"{kind}: {phrase!r}"


def test_banned_list_covers_every_phrase_in_the_existing_tests():
    for phrase in ALL_BANNED:
        assert docs.banned_hits(f"the text says {phrase}."), phrase


def test_customer_text_with_a_claim_is_not_used():
    assert docs.clean_slot("Certified DPO") is None
    assert docs.clean_slot("fully compliant officer") is None
    answers = {"dpo.designated": row("yes", "Certified DPO")}
    inputs = inputs_for("privacy_policy", answers)
    assert next(f for f in inputs["facts"] if f["key"] == "dpo_name")["state"] == "missing"
    org = inputs_for("privacy_policy", org="Certified Traders")
    assert next(f for f in org["facts"] if f["key"] == "org_name")["state"] == "missing"


def test_clean_slot_removes_markup_that_could_fake_or_hide_a_placeholder():
    cleaned = docs.clean_slot("Ada {{ORG_NAME}} [MISSING: x]\n## <b>Obi</b> | `x`")
    assert cleaned and not re.search(r"[{}\[\]<>|`#]", cleaned) and "\n" not in cleaned
    assert docs.clean_slot("x" * 500) == "x" * docs.MAX_SLOT
    assert docs.clean_slot("   ") is None and docs.clean_slot(None) is None


# ── Model output checks ───────────────────────────────────────────────────────


def _template():
    inputs = inputs_for("privacy_policy", FULL)
    return docs.build_template(inputs)


def test_a_faithful_rewording_passes():
    template = _template()
    reworded = template.replace("This policy explains how", "This policy describes how")
    assert docs.validate_model_text(reworded, template) is None
    assert docs.validate_model_text(template, template) is None


@pytest.mark.parametrize("mutate,reason", [
    (lambda t: t.replace("{{DPO_NAME}}", "the officer"), "slot_changed"),
    (lambda t: t + "\n\n{{ORG_NAME}}", "slot_changed"),
    (lambda t: t.replace("[MISSING: your registered address]", "12 Marina Road"), "placeholder_changed"),
    (lambda t: t + "\n\n[MISSING: a new thing]", "placeholder_changed"),
    (lambda t: t + "\n\nWe keep records for 7 years.", "number_added"),
    (lambda t: t + "\n\nWrite to privacy@acme.example for help.", "address_added"),
    (lambda t: t + "\n\nSee our partner Globex Holdings.", "name_added"),
    (lambda t: t + "\n\nThis policy is fully compliant with the NDPA.", "banned_phrase"),
    (lambda t: t + "\n\nWe guarantee your data is safe.", "banned_phrase"),
    (lambda t: t + "\n\nThis is legally sufficient.", "banned_phrase"),
    (lambda t: "", "empty_output"),
    (lambda t: "```\n" + t + "\n```", "markup_added"),
    (lambda t: t + "\n\nWe keep records for seven years.", "number_added"),
    (lambda t: t + "\n\nThe policy is reviewed every March.", "number_added"),
    (lambda t: t + "\n\nWe review it twice a year, usually on a Monday.", "number_added"),
    (lambda t: t + "\n\nLogs are kept for 6 months.", "number_added"),  # 6 occurs once in a list elsewhere
    (lambda t: t + "\n\nContact: Globex.", "name_added"),
    (lambda t: t + "\n\nGlobex hosts our website.", "name_added"),
    (lambda t: t + "\n\nSee the Sandbox page.", "name_added"),
])
def test_invented_or_unsafe_model_output_is_rejected(mutate, reason):
    template = _template()
    assert docs.validate_model_text(mutate(template), template) == reason


def test_a_digit_may_not_be_reused_more_often_than_the_template_uses_it():
    inputs = inputs_for("breach_response_plan", FULL)
    template = docs.build_template(inputs)
    assert docs.validate_model_text(template + "\n\nWe act within 72 hours.", template) == "number_added"
    assert docs.validate_model_text(template, template) is None


def test_ordinary_sentence_openers_are_not_mistaken_for_names():
    template = _template()
    assert docs.validate_model_text(template + "\n\nIf you have a question, please ask us.", template) is None


def test_non_string_output_is_rejected():
    assert docs.validate_model_text(None, _template()) == "empty_output"
    assert docs.validate_model_text({"text": "x"}, _template()) == "empty_output"


# ── Provider orchestration with a stub (no network) ───────────────────────────


class Stub:
    def __init__(self, outputs):
        self.outputs, self.prompts = list(outputs), []

    async def draft_document(self, system_prompt, template):
        self.prompts.append((system_prompt, template))
        out = self.outputs.pop(0) if self.outputs else None
        if isinstance(out, Exception):
            raise out
        return out(template) if callable(out) else out


def run_model(monkeypatch, outputs, template):
    stub = Stub(outputs)
    monkeypatch.setattr(store, "get_ai_provider", lambda: stub)
    return stub, asyncio.run(store._model_body(template))


def test_valid_output_is_used_and_the_prompt_holds_no_customer_text(monkeypatch):
    template = _template()
    reworded = template.replace("This policy explains how", "This policy describes how")
    stub, (body, name, reason) = run_model(monkeypatch, [reworded], template)
    assert body == reworded and name == "Stub" and reason is None
    prompt = " ".join(p + t for p, t in stub.prompts)
    for secret in ("Ada Obi", "Acme Traders", "acme.example"):
        assert secret not in prompt


def test_banned_output_is_blocked_then_retried_then_dropped(monkeypatch):
    template = _template()
    bad = template + "\n\nWe are fully compliant and certified."
    stub, (body, _, reason) = run_model(monkeypatch, [bad, bad], template)
    assert body is None and reason == "rejected:banned_phrase" and len(stub.prompts) == docs.MODEL_ATTEMPTS


def test_second_attempt_can_succeed(monkeypatch):
    template = _template()
    good = template.replace("This policy explains how", "This policy describes how")
    _, (body, _, reason) = run_model(monkeypatch, [template + "\n\nCall 0800 123.", good], template)
    assert body == good and reason is None


def test_provider_errors_and_no_provider_fall_back(monkeypatch):
    template = _template()
    _, (body, _, reason) = run_model(monkeypatch, [RuntimeError("down"), RuntimeError("down")], template)
    assert body is None and reason.startswith("provider_error")
    _, (body, _, reason) = run_model(monkeypatch, [None], template)
    assert body is None and reason == "provider_unavailable"


def test_default_provider_has_no_text_generation():
    from backend.app.ai.heuristic_provider import HeuristicAIProvider
    assert asyncio.run(HeuristicAIProvider().draft_document(docs.SYSTEM_PROMPT, "x")) is None


def test_final_checks_catch_a_dropped_placeholder_or_leftover_slot():
    inputs, template, text = draft("privacy_policy", FULL)
    assert docs.final_problems(text, inputs) == []
    assert "placeholder_dropped:retention" in docs.final_problems(text.replace("how long you keep", "x"), inputs)
    assert "slot_left" in docs.final_problems(text + "{{DPO_NAME}}", inputs)
    assert "label_missing" in docs.final_problems("Hello\n" + text, inputs)



# ── Review round 1: the filter folds what a reader sees, and the model path is off by default ────────────

DISGUISED_CLAIMS = [
    "this draft is com\u200bpliant", "this draft is c\u043empliant", "this draft is \uff43\uff4f\uff4d\uff50\uff4c\uff49\uff41\uff4e\uff54",
    "this draft is com-pliant", "this draft is c.o.m.p.l.i.a.n.t", "a Cert\u200bified policy", "an ad\u0435quate policy",
    "we g\u200buarantee it", "a fully\u00adcompliant draft",
]


@pytest.mark.parametrize("text", DISGUISED_CLAIMS)
def test_disguised_claims_are_found(text):
    assert docs.banned_hits(text), text


def test_a_customer_value_with_a_disguised_claim_is_not_used_but_real_names_are():
    assert docs.clean_slot("Cert\u200bified DPO") is None
    assert docs.clean_slot("DPO, c\u043empliant officer") is None
    assert docs.clean_slot("Ọlá Adéwálé") == "Ọlá Adéwálé", "legitimate letters with diacritics stay"
    assert docs.clean_slot("Ada Obi, Chief Privacy Officer") == "Ada Obi, Chief Privacy Officer"
    assert docs.clean_slot("Ada\u200b Obi") == "Ada Obi", "invisible characters are removed, not rejected"


def test_ordinary_text_has_no_false_hits_across_word_boundaries():
    for text in ("The cat sat is fine for us.", "We keep a log of who has access, and we review it.", "Contact us at the address above."):
        assert docs.banned_hits(text) == [], text


def test_the_model_path_is_off_by_default():
    assert docs.MODEL_ENABLED is False and docs.MODEL_TIMEOUT_SECONDS > 0
