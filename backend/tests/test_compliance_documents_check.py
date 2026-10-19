"""C5b: the check on reworded drafts. Pure: stub providers only, no database, no network.

Covers: the adversarial and faithful corpora (backend/tests/c5b_corpus.py); property tests over every document
kind and many answer combinations; each rule on its own and with the rule removed (mutation check); the
normaliser; claim-bearing customer values and their visible note; the startup warning; the pipeline with a stub
provider when the flag is on.
"""
import asyncio
import itertools
import logging
import random
import re
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.compliance import document_check as check
from backend.app.compliance import document_store as store
from backend.app.compliance import documents as docs
from backend.tests import c5b_corpus as corpus
from backend.tests.test_compliance_claims import BANNED as CLAIMS_BANNED
from backend.tests.test_compliance_claims import READINESS_BANNED
from backend.tests.test_compliance_questionnaire import BANNED as QUESTIONNAIRE_BANNED

# The full list of phrases no copy, template, prompt or note may contain (negative-assertion data).
C5B_BANNED = (
    "compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit",
    "compliance score", "fully meets", "meets the requirement", "is met", "partial compliance", "fully compliant",
    "is compliant", "satisfy ndpa", "adequate", "adequacy", "guarantee",
)
ALL_BANNED = set(C5B_BANNED) | set(CLAIMS_BANNED) | set(READINESS_BANNED) | set(QUESTIONNAIRE_BANNED)

ADVERSARIAL = {cid: (setup, ops) for cid, setup, ops in corpus.ADVERSARIAL}
FAITHFUL = {cid: (setup, ops) for cid, setup, ops in corpus.FAITHFUL}


def reworded(setup, ops):
    template = corpus.template_for(setup)
    return template, corpus.apply(template, ops)


# ── The corpora ──────────────────────────────────────────────────────────────


def test_the_corpora_are_large_and_every_case_changes_the_text():
    assert len(ADVERSARIAL) >= 400 and len(FAITHFUL) >= 20
    assert len(ADVERSARIAL) == len(corpus.ADVERSARIAL) and len(FAITHFUL) == len(corpus.FAITHFUL), "duplicate ids"
    for cid, (setup, ops) in ADVERSARIAL.items():
        template, out = reworded(setup, ops)
        assert out != template, cid


@pytest.mark.parametrize("cid", sorted(ADVERSARIAL))
def test_adversarial_rewordings_are_rejected(cid):
    template, out = reworded(*ADVERSARIAL[cid])
    assert docs.validate_model_text(out, template) is not None, cid


@pytest.mark.parametrize("cid", sorted(ADVERSARIAL))
def test_the_structural_check_alone_rejects_them_too(cid):
    # The older checks (tokens, numbers, banned wording, names) are not what keeps the corpus out.
    template, out = reworded(*ADVERSARIAL[cid])
    assert check.structural_problem(out, template) is not None, cid


@pytest.mark.parametrize("cid", sorted(FAITHFUL))
def test_faithful_rewordings_are_accepted(cid):
    template, out = reworded(*FAITHFUL[cid])
    assert docs.validate_model_text(out, template) is None, (cid, docs.validate_model_text(out, template))


def test_the_faithful_corpus_changes_the_text_and_has_no_banned_stem():
    changed = 0
    for cid, (setup, ops) in FAITHFUL.items():
        template, out = reworded(setup, ops)
        changed += out != template
        assert docs.banned_hits(out) == [], cid
    assert changed >= len(FAITHFUL) - 1


def test_rejection_reasons_name_the_kind_of_change():
    expect = {
        "neg-dropped-1": "negation_changed", "neg-added-1": "negation_changed", "modal-0": "commitment_changed",
        "number-0": "number_changed", "split-1": "sentences_changed", "add-glue-only-line": "lines_changed",
        "heading-reworded": "structure_changed", "neg-moved-2": "order_changed", "order-1": "order_changed", "synonym-2": "words_added",
        "drop-clause-1": "words_dropped", "homoglyph-template-word-0": "non_ascii_added",
    }
    for cid, reason in expect.items():
        template, out = reworded(*ADVERSARIAL[cid])
        assert check.structural_problem(out, template) == reason, cid


# ── Rules: each on its own, and the corpus with a rule removed ───────────────

RULES = dict(check.RULES)
# Rules that give a specific reason, or are defence in depth, but whose work the clause-order rule (the same words
# in the same order inside each clause) already does. Removing one of these on its own flips nothing in the
# corpus; they are tested on their own, and removed together with `clause_order` below.
REDUNDANT = {"negations", "commitments", "numbers", "content_words", "scope", "claim_shape"}
LOAD_BEARING = [name for name in RULES if name not in REDUNDANT]


def _only(name, out, template):
    return check.structural_problem(out, template, [(name, RULES[name])])


def test_every_rule_rejects_something_on_its_own():
    own = {
        "non_ascii": "homoglyph-template-word-0", "lines": "add-glue-only-line", "sentence_count": "split-1",
        "negations": "neg-dropped-1", "commitments": "modal-0", "numbers": "number-0",
        "content_words": "synonym-2", "clause_order": "order-1", "scope": "neg-moved-2",
    }
    for name, cid in own.items():
        template, out = reworded(*ADVERSARIAL[cid])
        assert _only(name, out, template) is not None, (name, cid)
        assert _only(name, template, template) is None, name


def test_claim_shape_rejects_an_obligation_that_the_template_sentence_lacks():
    template = "We keep logs for all."
    out = "For all we keep logs."
    assert check.structural_problem(out, template, [("claim_shape", check.rule_claim_shape)]) == "claim_shape"
    assert check.structural_problem(template, template, [("claim_shape", check.rule_claim_shape)]) is None
    for text in ("We will protect your data.", "We always delete data.", "Every file is encrypted.",
                 "This is in accordance with the law.", "We fulfil our duties.", "We ensure this."):
        assert check.structural_problem(text, "Reword this.", [("claim_shape", check.rule_claim_shape)]) == "claim_shape"
    # A shape the template sentence has is let through (the breach plan says "what we will change").
    assert check.structural_problem("Record what we will change.", "Record what we will change.",
                                    [("claim_shape", check.rule_claim_shape)]) is None


@pytest.mark.parametrize("name", LOAD_BEARING)
def test_removing_a_rule_lets_part_of_the_corpus_through(name):
    rules = [(n, r) for n, r in check.RULES if n != name]
    let_through = []
    for cid, (setup, ops) in ADVERSARIAL.items():
        template, out = reworded(setup, ops)
        if check.structural_problem(out, template, rules) is None:
            let_through.append(cid)
    assert let_through, f"no corpus case depends on the {name!r} rule"


def test_without_the_clause_order_rule_a_reshuffle_inside_a_clause_gets_through():
    # The word rules alone cannot see this; it is why the clause-order rule exists.
    template, out = reworded(*ADVERSARIAL["order-1"])
    assert "We do not store personal data or send it outside Nigeria." in out
    rest = [(n, r) for n, r in check.RULES if n != "clause_order"]
    assert check.structural_problem(out, template, rest) is None
    assert check.structural_problem(out, template) == "order_changed"


def test_with_no_rules_the_whole_corpus_gets_through_the_structural_check():
    survivors = 0
    for cid, (setup, ops) in ADVERSARIAL.items():
        template, out = reworded(setup, ops)
        survivors += check.structural_problem(out, template, []) is None
    assert survivors == len(ADVERSARIAL)


def test_the_glue_list_holds_no_claim_word():
    claim_words = (check.NEGATIONS | check.MODALS | check.QUANTIFIERS | check.COMMITMENT_VERBS | check.CONNECTIVES
                   | check.FACT_WORDS)
    assert not (check.FREE & claim_words)
    for word in ("will", "shall", "must", "may", "can", "should", "would", "always", "never", "all", "every", "any",
                 "only", "ensure", "guarantee", "commit", "promise", "undertake", "require", "secure", "encrypt",
                 "not", "no", "none", "cannot", "without", "and", "or", "if"):
        assert word not in check.FREE, word


def test_the_check_never_raises():
    template = corpus.template_for("policy")
    for bad in (None, 5, b"x", ["a"], {"text": "x"}, "", "   ", "\x00" * 10, "{{" * 50, "[MISSING: " * 50):
        assert docs.validate_model_text(bad, template) is not None
    assert check.structural_problem(object(), template) == "check_failed"


# ── Properties over every kind and many answer combinations ──────────────────

QUESTIONS = ("dpo.designated", "transfers.outside_nigeria", "rights.process", "breach.notification_process",
             "breach.incident_log")
CHOICES = (None, "yes", "no")


def _answers(combo):
    answers = {}
    for key, choice in zip(QUESTIONS, combo):
        if choice is not None:
            answers[key] = corpus._row(choice, "Ada Obi" if key == "dpo.designated" and choice == "yes" else None)
    return answers


def all_templates():
    seen = {}
    for kind, combo, observed in itertools.product(docs.KINDS, itertools.product(CHOICES, repeat=5),
                                                   (None, corpus.OBSERVED)):
        ctx = {"org_name": "Acme Traders", "domains": ["acme.example"], "answers": _answers(combo),
               "observed": observed or {}}
        template = docs.build_template(docs.build_inputs(kind, ctx, corpus.NOW))
        seen.setdefault(template, kind)
    return list(seen)


TEMPLATES = all_templates()


def test_the_template_itself_is_accepted_for_every_kind_and_combination():
    assert len(TEMPLATES) > 40
    assert {t.splitlines()[0].split(" of ")[0] for t in TEMPLATES} == {
        "# Privacy policy", "# Cookie notice", "# Breach response plan", "# Retention schedule"}
    for template in TEMPLATES:
        assert docs.validate_model_text(template, template) is None
        assert check.structural_problem(template, template) is None


def _gaps(template):
    """Positions of single spaces that are not inside a token."""
    inside = set()
    for m in check.TOKEN.finditer(template):
        inside.update(range(m.start(), m.end()))
    return [i for i, ch in enumerate(template) if ch == " " and i not in inside]


CLAIM_WORDS = ("always", "never", "all", "every", "any", "only", "will", "shall", "must", "may", "can", "should",
               "would", "ensure", "guarantee", "commit", "promise", "undertake", "require", "secure", "securely",
               "encrypt", "encrypted", "delete", "protect", "comply", "fully", "none", "no", "not", "cannot",
               "without", "fulfil", "satisfy", "lawfully", "safely", "immediately", "within", "30", "seven",
               "monday", "daily", "ndpa", "gdpr", "google", "thirdparty")


def test_inserting_any_claim_word_anywhere_is_rejected():
    rng = random.Random(20261019)
    tried = 0
    for template in TEMPLATES:
        gaps = _gaps(template)
        for pos in rng.sample(gaps, min(len(gaps), 25)):
            word = rng.choice(CLAIM_WORDS)
            out = template[:pos] + " " + word + template[pos:]
            tried += 1
            assert docs.validate_model_text(out, template) is not None, (word, template[max(0, pos - 30):pos + 30])
    assert tried > 1000


def test_every_claim_word_is_rejected_at_the_start_and_end_of_a_sentence():
    template = corpus.template_for("policy")
    for word in CLAIM_WORDS:
        for old, new in (("You may also complain", f"{word} You may also complain"),
                         ("Nigeria Data Protection Commission.", f"Nigeria Data Protection Commission {word}.")):
            out = template.replace(old, new)
            assert out != template
            assert docs.validate_model_text(out, template) is not None, (word, old)


NEGATION_WORD = re.compile(r"\b(?:not|no|never|without|cannot)\b")


def test_deleting_a_negation_a_placeholder_or_a_token_is_rejected():
    deleted = {"negation": 0, "placeholder": 0, "slot": 0, "number": 0}
    for template in TEMPLATES:
        bare = check.TOKEN.sub(lambda m: "\0" * len(m.group(0)), template)  # so token text is never matched
        spans = [("negation", m.span()) for m in NEGATION_WORD.finditer(bare)]
        spans += [("placeholder", m.span()) for m in check.PLACEHOLDER.finditer(template)]
        spans += [("slot", m.span()) for m in check.SLOT.finditer(template)]
        spans += [("number", m.span()) for m in re.finditer(r"72", bare)]
        for kind, (a, b) in spans:
            out = template[:a] + template[b:]
            deleted[kind] += 1
            assert docs.validate_model_text(out, template) is not None, (kind, template[max(0, a - 30):b + 30])
    assert all(n > 20 for n in deleted.values()), deleted


def test_dropping_or_adding_a_whole_sentence_or_line_is_rejected():
    for template in TEMPLATES:
        lines = template.split("\n\n")
        for i in range(len(lines)):
            dropped = "\n\n".join(lines[:i] + lines[i + 1:])
            assert docs.validate_model_text(dropped, template) is not None
            doubled = "\n\n".join(lines[:i + 1] + lines[i:])
            assert docs.validate_model_text(doubled, template) is not None
        for sentence in ("It is also there.", "We keep your data safe."):
            assert docs.validate_model_text(template + "\n\n" + sentence, template) is not None


def test_a_reordered_pair_of_lines_is_rejected():
    for template in TEMPLATES:
        lines = template.split("\n\n")
        for i in range(1, len(lines) - 1):
            if lines[i] != lines[i + 1]:
                swapped = lines[:i] + [lines[i + 1], lines[i]] + lines[i + 2:]
                assert docs.validate_model_text("\n\n".join(swapped), template) is not None


def test_glue_words_may_be_added_and_the_text_is_still_checked():
    template = corpus.template_for("policy")
    out = template.replace("We collect:", "We also collect:")
    assert docs.validate_model_text(out, template) is None
    assert docs.validate_model_text(out.replace("also", "always"), template) is not None


# ── The normaliser ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "cómpliant", "cómpliant", "com- pliant", "com -pliant", "com‐ pliant", "СOMPLIANT",
    "Cοmpliant", "cօmpliant", "c​ompliant", "ＣＯＭＰＬＩＡＮＴ",
    "c o m p l i a n t", "c.o.m.p.l.i.a.n.t", "certıfied", "sаtisfied", "g‍uarantee", "adеquacy",
    "is\nmet", "is   met", "fully compliant", "Certíficatíon", "passes\taudit", "COMPLIANCE SCORE",
])
def test_the_normaliser_finds_disguised_banned_wording(text):
    assert docs.banned_hits(text), text


def test_the_normaliser_leaves_ordinary_text_alone():
    for text in ("The cat sat is fine for us.", "We keep a log of who has access.", "Contact us at the address above.",
                 "Ọlá Adéwálé, Chief Privacy Officer", "A well-known firm", "Guaranty Trust Bank", "Ngozi Chukwuemeka"):
        assert docs.banned_hits(text) == [], text
    assert docs.fold("Cómpl​iant С") == "compliant c"
    assert docs.fold("com- pliant") == "compliant"


def test_customer_values_with_diacritics_stay_but_disguised_claims_do_not():
    for name in ("Ọlá Adéwálé", "Zoë Müller", "Chidi Nwankwọ", "François Dupont, DPO"):
        assert docs.clean_slot(name) == name
    for value in ("cómpliant officer", "com- pliant officer", "Certífied DPO", "Օffice (cօmpliant)"):
        assert docs.clean_slot(value) is None
        assert docs.slot_wording_blocked(value)
    assert not docs.slot_wording_blocked("   ") and not docs.slot_wording_blocked(None)


# ── A customer value with a claim is never dropped silently ──────────────────


def _ctx(org="Acme Traders", domains=("acme.example",), dpo=None):
    answers = {}
    if dpo is not None:
        answers["dpo.designated"] = corpus._row("yes", dpo)
    return {"org_name": org, "domains": list(domains), "answers": answers, "observed": {}}


def test_a_blocked_organisation_name_becomes_a_placeholder_with_a_visible_note():
    inputs = docs.build_inputs("privacy_policy", _ctx(org="Customer Satisfaction Ltd"), corpus.NOW)
    template = docs.build_template(inputs)
    assert f"[MISSING: name of your organisation — {docs.WORDING_NOTE}]" in template
    assert "Customer Satisfaction" not in template
    keys = {p["key"]: p["text"] for p in docs.placeholders_for(inputs)}
    assert docs.WORDING_NOTE in keys["org_name"]
    # An empty name is still a plain placeholder with no note.
    plain = docs.build_inputs("privacy_policy", _ctx(org=""), corpus.NOW)
    assert docs.WORDING_NOTE not in docs.build_template(plain)


def test_a_blocked_dpo_name_and_website_are_explained_too():
    inputs = docs.build_inputs("privacy_policy", _ctx(dpo="Certified DPO", domains=("certified-shop.example",)), corpus.NOW)
    template = docs.build_template(inputs)
    assert template.count(docs.WORDING_NOTE) == 2
    assert f"[MISSING: name of your data protection officer — {docs.WORDING_NOTE}]" in template
    assert f"[MISSING: your website address — {docs.WORDING_NOTE}]" in template
    assert docs.final_problems(docs.compose(docs.fill_slots(template, inputs), inputs, version=1,
                                            generated_at=corpus.NOW), inputs) == []


def test_one_blocked_domain_among_good_ones_is_reported_in_the_reviewer_notes():
    inputs = docs.build_inputs("cookie_notice", _ctx(domains=("acme.example", "certified.example")), corpus.NOW)
    site = next(f for f in inputs["facts"] if f["key"] == "website")
    assert site["state"] == "set" and site["value"] == "acme.example"
    assert docs.WORDING_NOTE in docs.reviewer_notes(inputs)


def test_inputs_without_a_blocked_value_hash_as_before():
    # The note is added only on the blocked path, so drafts already stored do not all turn "stale".
    inputs = docs.build_inputs("privacy_policy", _ctx(dpo="Ada Obi"), corpus.NOW)
    assert all(f.get("note") is None for f in inputs["facts"] if f["key"] in ("org_name", "website", "dpo_name"))


# ── The startup warning ──────────────────────────────────────────────────────


def test_the_startup_warning_is_logged_once_when_the_flag_is_on(monkeypatch, caplog):
    monkeypatch.setattr(docs, "_warned", False)
    monkeypatch.setattr(docs, "MODEL_ENABLED", True)
    with caplog.at_level(logging.WARNING, logger="cyphward.compliance.documents"):
        assert docs.log_model_path_warning() is True
        assert docs.log_model_path_warning() is False
    messages = [r.getMessage() for r in caplog.records if r.name == "cyphward.compliance.documents"]
    assert len(messages) == 1 and "COMPLIANCE_DOCS_MODEL=on" in messages[0] and "Review a sample" in messages[0]


def test_no_warning_when_the_flag_is_off(monkeypatch, caplog):
    monkeypatch.setattr(docs, "_warned", False)
    monkeypatch.setattr(docs, "MODEL_ENABLED", False)
    with caplog.at_level(logging.WARNING, logger="cyphward.compliance.documents"):
        assert docs.log_model_path_warning() is False
    assert not [r for r in caplog.records if r.name == "cyphward.compliance.documents"]


def test_the_application_runs_the_warning_at_startup():
    from backend.app import main
    names = [getattr(h, "__name__", "") for h in main.app.router.on_startup]
    assert "warn_if_document_rewording_is_on" in names


def test_the_flag_is_off_by_default_and_the_timeout_is_unchanged():
    assert docs.MODEL_ENABLED is False and docs.MODEL_TIMEOUT_SECONDS == 45


# ── Wording of everything this feature adds ──────────────────────────────────


def test_new_copy_the_prompt_and_every_template_avoid_the_banned_phrases():
    copy = [docs.WORDING_NOTE, docs.SYSTEM_PROMPT, docs.LABEL, docs.FOOTER, check.__doc__ or ""]
    copy += TEMPLATES
    copy += [f"{label} {note}" for _, label_note in docs.FIXED_GAPS.items() for label, note in label_note]
    for text in copy:
        lowered = text.lower()
        for phrase in ALL_BANNED:
            assert phrase not in lowered, (phrase, text[:60])
        assert docs.banned_hits(text) == [], text[:60]


def test_the_corpus_modules_use_the_claim_words_only_as_negative_data():
    # The faithful rewordings are the only corpus text meant to reach a stored draft.
    for cid, (setup, ops) in FAITHFUL.items():
        _, out = reworded(setup, ops)
        assert not (set(re.findall(r"[a-z]+", out.lower())) & {"compliant", "certified", "guarantee", "adequate"}), cid


# ── Pipeline with a stub provider (flag on) ──────────────────────────────────


class Stub:
    def __init__(self, outputs):
        self.outputs, self.prompts = list(outputs), []

    async def draft_document(self, system_prompt, template):
        self.prompts.append((system_prompt, template))
        out = self.outputs.pop(0) if self.outputs else None
        return out(template) if callable(out) else out


def run_model(monkeypatch, outputs, template):
    stub = Stub(outputs)
    monkeypatch.setattr(store, "get_ai_provider", lambda: stub)
    return stub, asyncio.run(store._model_body(template))


def test_an_accepted_rewording_is_used_with_the_provider_name(monkeypatch):
    template = corpus.template_for("policy")
    good = template.replace("explains how", "describes how")
    _, (body, name, reason) = run_model(monkeypatch, [good], template)
    assert body == good and name == "Stub" and reason is None


@pytest.mark.parametrize("cid", ["claim-new-line-0", "neg-dropped-1", "drop-sentence-1", "merge-2", "number-0",
                                 "inject-new-line-0", "disguise-cyrillic", "token-dup-1", "placeholder-drop-1"])
def test_a_rejected_rewording_falls_back_with_the_reason(monkeypatch, cid):
    setup, ops = ADVERSARIAL[cid]
    template, bad = reworded(setup, ops)
    stub, (body, name, reason) = run_model(monkeypatch, [bad, bad], template)
    assert body is None and reason.startswith("rejected:") and len(reason) > len("rejected:")
    assert len(stub.prompts) == docs.MODEL_ATTEMPTS


def test_a_rewording_that_adds_a_claim_is_retried_and_a_faithful_second_attempt_is_used(monkeypatch):
    template = corpus.template_for("policy")
    bad = template.replace(corpus.POL_COMPLAIN, corpus.POL_COMPLAIN + "\n\nWe encrypt all personal data.")
    good = template.replace("explains how", "describes how")
    _, (body, _, reason) = run_model(monkeypatch, [bad, good], template)
    assert body == good and reason is None


def test_stored_drafts_from_an_accepted_rewording_pass_the_final_checks():
    for setup in corpus.SETUPS:
        kind, answers, observed = corpus.SETUPS[setup]
        ctx = {"org_name": "Acme Traders", "domains": ["acme.example"], "answers": answers or {}, "observed": observed or {}}
        inputs = docs.build_inputs(kind, ctx, corpus.NOW)
        template = docs.build_template(inputs)
        out = template.replace("explains how", "describes how").replace("lists how", "shows how")
        assert docs.validate_model_text(out, template) is None
        text = docs.compose(docs.fill_slots(out, inputs), inputs, version=1, generated_at=corpus.NOW)
        assert docs.final_problems(text, inputs) == []
