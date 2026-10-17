"""AI-drafted documents (packet C5): inputs, deterministic templates and the checks on model output. Pure.

Four drafts (privacy policy, cookie notice, breach response plan, retention schedule) are built from the
organisation's own answers and observations and from nothing else:

1. `build_inputs` turns those answers into a list of facts. A fact is either `set` (a usable answer or a
   current observation) or `missing`. Placeholders come from the missing facts, never from model output.
2. `build_template` writes the whole draft deterministically. A set fact that is free text or a name becomes
   a `{{SLOT}}` token; a missing fact becomes a visible `[MISSING: ...]` placeholder.
3. The model may only reword the tokenised template. It never sees an answer, a note, a name or a domain:
   `validate_model_text` rejects output that drops or repeats a token or placeholder, adds a number, an
   address, a link or a name, or uses a banned phrase. After two rejected attempts the template is used.
4. Slot values are substituted by code afterwards, so customer text cannot steer the model.

A draft says what the organisation told us. It never claims the organisation complies with anything.
"""
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.app.compliance import attestations as truth
from backend.app.compliance import questionnaire as qn

LABEL = "Draft — not legal advice"
FOOTER = ("Draft — not legal advice. Have a qualified Nigerian data protection practitioner review it before "
          "you publish or rely on it. Cyphward drafted it from your own answers and has not checked it.")
KINDS = ("privacy_policy", "cookie_notice", "breach_response_plan", "retention_schedule")
TITLES = {"privacy_policy": "Privacy policy", "cookie_notice": "Cookie notice",
          "breach_response_plan": "Breach response plan", "retention_schedule": "Retention schedule"}
DAILY_CAP = 10  # generations per organisation per UTC day; the quota table's CHECK enforces the same number
MODEL_ATTEMPTS = 2
MAX_SLOT = 120

# Union of the banned lists in test_compliance_claims.py and test_compliance_questionnaire.py, plus the
# claims a drafting assistant is most tempted to make. Matched as lowercase substrings, like the tests.
BANNED = (
    "partial compliance", "fully compliant", "is compliant", "compliant", "complies", "in compliance",
    "satisfy ndpa", "satisfies", "satisfied", "certif", "ndpa 2023 compliant", "cbn compliant",
    "passes audit", "pass the audit", "compliance score", "fully meets", "meets the requirement",
    "meets the requirements", "is met", "guarantee", "adequate", "adequacy", "legally sufficient",
    "legal sufficiency", "ensures compliance", "sufficient for compliance",
)

SLOT = re.compile(r"\{\{[A-Z_]+\}\}")
PLACEHOLDER = re.compile(r"\[MISSING: [^\[\]\n]{1,200}\]")
URLISH = re.compile(r"https?://|www\.|@|\b[\w-]+\.(?:com|ng|org|net|io|gov|co|edu)\b", re.I)
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
SENTENCE_START = re.compile(r"(?:^|[.!?:|]\s+|\n\s*(?:[-*#>|]+\s*|\d+[.)]\s*)?)$")

# Where each fact comes from, for the reviewer notes at the end of a draft.
SOURCE_LABELS = {"customer_attested": "your answer", "externally_observed": "observed by a Cyphward scan",
                 "organisation_profile": "your organisation profile"}

OBSERVED_KEYS = ("gaid.consent.banner_visible", "gaid.consent.accept_and_reject",
                 "gaid.consent.no_trackers_before_consent", "gaid.consent.purpose_and_withdrawal")


# ── Text checks ──────────────────────────────────────────────────────────────


def banned_hits(text: str) -> List[str]:
    lowered = text.lower()
    return [phrase for phrase in BANNED if phrase in lowered]


def clean_slot(value: Any) -> Optional[str]:
    """A customer-supplied value made safe to drop into a draft, or None when it cannot be used.

    Markup, braces and brackets are removed so a value cannot fake or hide a placeholder; a value that
    contains wording this feature never uses (a claim of compliance) is not used at all.
    """
    if not isinstance(value, str):
        return None
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    text = re.sub(r"[{}\[\]<>|`*_#]", "", text)
    text = re.sub(r"\s+", " ", text).strip()[:MAX_SLOT].strip()
    if not text or banned_hits(text):
        return None
    return text


def _digits(text: str) -> set:
    return set(re.findall(r"\d+", text))


def _vocabulary(text: str) -> set:
    return {w.lower() for w in WORD.findall(text)}


def _strip_tokens(text: str) -> str:
    return PLACEHOLDER.sub(" ", SLOT.sub(" ", text))


def validate_model_text(output: Any, template: str) -> Optional[str]:
    """None when the model's text may be used, otherwise a short reason. Never raises."""
    if not isinstance(output, str) or not output.strip():
        return "empty_output"
    if len(output) > 2 * len(template) + 400 or len(output) < len(template) // 3:
        return "length_out_of_range"
    if Counter(SLOT.findall(output)) != Counter(SLOT.findall(template)):
        return "slot_changed"
    if Counter(PLACEHOLDER.findall(output)) != Counter(PLACEHOLDER.findall(template)):
        return "placeholder_changed"
    bare = _strip_tokens(output)
    if "[" in bare or "]" in bare or "{{" in bare or "}}" in bare or "<" in bare or "```" in bare:
        return "markup_added"
    fixed = _strip_tokens(template)
    if not _digits(bare) <= _digits(fixed):
        return "number_added"
    if URLISH.search(bare) and not URLISH.search(fixed):
        return "address_added"
    if banned_hits(output):
        return "banned_phrase"
    known = _vocabulary(fixed)
    for match in WORD.finditer(bare):
        word = match.group(0)
        if word[0].isupper() and not SENTENCE_START.search(bare[:match.start()]) and word.lower() not in known:
            return "name_added"
    return None


# ── Inputs ────────────────────────────────────────────────────────────────────


def _answer(answers: Dict[str, Dict[str, Any]], key: str, now: datetime) -> Optional[Dict[str, Any]]:
    """The current answer when it can be used: shown, not expired and not 'not sure'."""
    row = answers.get(key)
    question = qn.question(key)
    if row is None or question is None or not truth.is_shown(question, answers) or truth.is_expired(row, now):
        return None
    if row["answer"].get("value") == qn.NOT_SURE:
        return None
    return row["answer"]


def _observed(observed: Dict[str, Dict[str, Dict[str, Any]]], key: str, now: datetime) -> Optional[str]:
    """present / gap across the verified domains' current observations, or None when not usable."""
    statuses = []
    for row in (observed.get(key) or {}).values():
        expires = row.get("expires_at")
        if expires is not None and truth._as_utc(expires) <= now:
            continue
        statuses.append(row.get("status"))
    if not statuses or any(s not in ("present", "gap") for s in statuses):
        return None
    return "gap" if "gap" in statuses else "present"


def _fact(key: str, label: str, source: Optional[str], value: Optional[str] = None, note: Optional[str] = None,
          ) -> Dict[str, Any]:
    state = "set" if source is not None else "missing"
    return {"key": key, "label": label, "state": state, "source": source, "value": value, "note": note}


def _yes_no(ctx, key: str, fact_key: str, label: str, now: datetime, *, no_is_a_fact: bool = False) -> Dict[str, Any]:
    """A yes/no answer as a fact. A 'no' is a statement only where it describes the organisation's practice;
    otherwise it stays a placeholder that records what the customer reported."""
    answer = _answer(ctx["answers"], key, now)
    value = answer.get("value") if answer else None
    if value == "yes" or (value == "no" and no_is_a_fact):
        return _fact(fact_key, label, "customer_attested", value)
    if value == "no":
        return _fact(fact_key, label, None, note="you reported this is not in place yet")
    return _fact(fact_key, label, None)


def _dpo(ctx, now: datetime) -> Dict[str, Any]:
    answer = _answer(ctx["answers"], "dpo.designated", now)
    if answer is None or answer.get("value") not in ("yes", "no"):
        return _fact("dpo_name", "name of your data protection officer", None)
    if answer["value"] == "no":
        return _fact("dpo_name", "name of your data protection officer", None, note="you reported none is named yet")
    name = clean_slot(answer.get("text"))
    if name is None:
        return _fact("dpo_name", "name of your data protection officer", None, note="no name recorded")
    return _fact("dpo_name", "name of your data protection officer", "customer_attested", name)


def build_inputs(kind: str, ctx: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """The deterministic inputs for one document. `ctx` holds the organisation's own data only:
    org_name, domains (verified), answers (current attestation rows) and observed (latest evidence status)."""
    if kind not in KINDS:
        raise ValueError("unknown document kind")
    now = now or datetime.now(timezone.utc)
    name = clean_slot(ctx.get("org_name"))
    sites = [clean_slot(d) for d in (ctx.get("domains") or [])]
    sites = [s for s in sites if s][:5]
    facts = [
        _fact("org_name", "name of your organisation", "organisation_profile" if name else None, name),
    ]
    if kind in ("privacy_policy", "cookie_notice"):
        facts.append(_fact("website", "your website address", "organisation_profile" if sites else None,
                           ", ".join(sites) or None))
    if kind in ("privacy_policy", "breach_response_plan", "retention_schedule"):
        facts.append(_dpo(ctx, now))
    if kind == "privacy_policy":
        facts.append(_yes_no(ctx, "transfers.outside_nigeria", "transfers_outside_nigeria",
                             "whether personal data is stored or sent outside Nigeria", now,
                             no_is_a_fact=True))
        facts.append(_yes_no(ctx, "rights.process", "rights_process",
                             "whether you have a process for access, correction, portability and erasure requests", now))
    if kind == "breach_response_plan":
        facts.append(_yes_no(ctx, "breach.notification_process", "notification_process",
                             "whether you have a process to notify the Commission within 72 hours", now))
        facts.append(_yes_no(ctx, "breach.incident_log", "incident_log", "whether you keep an incident log", now))
    if kind == "retention_schedule":
        facts.append(_yes_no(ctx, "rights.process", "rights_process",
                             "whether you have a process for access, correction, portability and erasure requests", now))
    if kind == "cookie_notice":
        for req, fact_key, label in (
                ("gaid.consent.accept_and_reject", "accept_and_reject", "whether your banner offers both accept and reject"),
                ("gaid.consent.purpose_and_withdrawal", "purpose_and_withdrawal",
                 "how a visitor changes or withdraws cookie consent")):
            status = _observed(ctx.get("observed") or {}, req, now)
            if status == "present":
                facts.append(_fact(fact_key, label, "externally_observed", status))
            else:
                note = "your last scan did not confirm it" if status == "gap" else None
                facts.append(_fact(fact_key, label, None, note=note))
    return {"kind": kind, "questionnaire_version": qn.QUESTIONNAIRE["version"], "facts": facts}


def inputs_hash(inputs: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _by_key(inputs: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {f["key"]: f for f in inputs["facts"]}


def _missing(label: str, note: Optional[str] = None) -> str:
    return f"[MISSING: {label}{' — ' + note if note else ''}]"


def placeholders_for(inputs: Dict[str, Any]) -> List[Dict[str, str]]:
    """Every placeholder the draft must show, computed from the inputs and not from any model output."""
    out = [{"key": f["key"], "text": _missing(f["label"], f.get("note"))} for f in inputs["facts"]
           if f["state"] == "missing"]
    for key, label in FIXED_GAPS[inputs["kind"]]:
        out.append({"key": key, "text": _missing(label)})
    return out


# Things no question collects. They are always placeholders, whatever the answers are.
FIXED_GAPS: Dict[str, List[Tuple[str, str]]] = {
    "privacy_policy": [
        ("controller_address", "your registered address"),
        ("dpo_contact", "contact details of your data protection officer (email or phone)"),
        ("data_categories", "the kinds of personal data you collect"),
        ("purposes_and_basis", "each purpose you use personal data for and the lawful basis for it"),
        ("retention", "how long you keep each kind of personal data"),
        ("request_contact", "where people send access, correction or erasure requests"),
    ],
    "cookie_notice": [
        ("cookie_list", "each cookie or tracker your site sets, its purpose and how long it lasts"),
        ("cookie_contact", "who to contact with questions about cookies"),
    ],
    "breach_response_plan": [
        ("response_lead", "name and contact details of the person who leads incident response"),
        ("escalation", "who you inform inside your organisation, in what order"),
        ("commission_channel", "how and where you notify the Commission"),
    ],
    "retention_schedule": [
        ("category_1", "data category"),
        ("category_2", "data category"),
        ("category_3", "data category"),
        ("retention_period", "retention period for each data category"),
        ("deletion_method", "how each data category is deleted"),
    ],
}


# ── Deterministic templates ──────────────────────────────────────────────────


def _gap(inputs: Dict[str, Any], key: str) -> str:
    return next(p["text"] for p in placeholders_for(inputs) if p["key"] == key)


def build_template(inputs: Dict[str, Any]) -> str:
    """The whole draft body, with `{{SLOT}}` tokens for set values and `[MISSING: ...]` for the rest."""
    facts = _by_key(inputs)
    kind = inputs["kind"]

    def val(key: str, slot: str) -> str:
        return slot if facts[key]["state"] == "set" else _gap(inputs, key)

    def fixed(key: str) -> str:
        return _gap(inputs, key)

    org = val("org_name", "{{ORG_NAME}}")
    site = val("website", "{{WEBSITE}}") if "website" in facts else ""
    lines: List[str] = []
    add = lines.append

    if kind == "privacy_policy":
        dpo = val("dpo_name", "{{DPO_NAME}}")
        add(f"# Privacy policy of {org}")
        add(f"This policy explains how {org} uses personal data collected through {site}.")
        add("## Who is responsible")
        add(f"{org} decides how personal data is used. Our address: {fixed('controller_address')}.")
        add("## Our data protection officer")
        add(f"Data protection officer: {dpo}. Contact: {fixed('dpo_contact')}.")
        add("## What we collect and why")
        add(f"We collect: {fixed('data_categories')}.")
        add(f"Purposes and lawful basis: {fixed('purposes_and_basis')}.")
        add("## How long we keep it")
        add(f"{fixed('retention')}.")
        add("## Sending data outside Nigeria")
        t = facts["transfers_outside_nigeria"]
        if t["state"] == "missing":
            add(f"{_gap(inputs, 'transfers_outside_nigeria')}.")
        elif t["value"] == "yes":
            add("Personal data may be stored or sent outside Nigeria, for example through cloud hosting.")
        else:
            add("We do not store or send personal data outside Nigeria.")
        add("## Your rights")
        r = facts["rights_process"]
        if r["state"] == "set" and r["value"] == "yes":
            add("You can ask to see, correct, move or erase your personal data. "
                f"Send your request to: {fixed('request_contact')}.")
        else:
            add(f"{_gap(inputs, 'rights_process')}. Send requests to: {fixed('request_contact')}.")
        add("You may also complain to the Nigeria Data Protection Commission.")
    elif kind == "cookie_notice":
        add(f"# Cookie notice of {org}")
        add(f"This notice explains the cookies and similar tools used on {site}.")
        add("## Cookies we use")
        add(f"{fixed('cookie_list')}.")
        add("## Your choice")
        both = facts["accept_and_reject"]
        if both["state"] == "set" and both["value"] == "present":
            add("When you first visit, a banner lets you accept or reject cookies that are not strictly necessary.")
        else:
            add(f"{_gap(inputs, 'accept_and_reject')}.")
        wd = facts["purpose_and_withdrawal"]
        if wd["state"] == "set" and wd["value"] == "present":
            add("You can change or withdraw your choice at any time using the cookie settings on our site.")
        else:
            add(f"{_gap(inputs, 'purpose_and_withdrawal')}.")
        add("## Questions")
        add(f"Contact: {fixed('cookie_contact')}.")
    elif kind == "breach_response_plan":
        dpo = val("dpo_name", "{{DPO_NAME}}")
        add(f"# Breach response plan of {org}")
        add("This plan sets out what we do when personal data is lost, stolen, exposed or changed without permission.")
        add("## Roles")
        add(f"Incident response lead: {fixed('response_lead')}.")
        add(f"Data protection officer: {dpo}.")
        add(f"Who we inform inside the organisation: {fixed('escalation')}.")
        add("## Steps")
        add("1. Detect and record. Write down what happened, when it was found and when we became aware of it.")
        add("2. Contain. Stop further loss or exposure, for example by removing access or taking a system offline.")
        add("3. Assess. Decide what personal data is involved, whose it is and what harm could follow.")
        n = facts["notification_process"]
        if n["state"] == "set" and n["value"] == "yes":
            add("4. Notify the Nigeria Data Protection Commission within 72 hours of becoming aware of a breach "
                f"likely to put people's rights at risk. Where to notify: {fixed('commission_channel')}.")
        else:
            add(f"4. Notify the Nigeria Data Protection Commission within 72 hours of becoming aware of a breach "
                f"likely to put people's rights at risk. {_gap(inputs, 'notification_process')}. "
                f"Where to notify: {fixed('commission_channel')}.")
        add("5. Tell the people affected without undue delay when the breach is likely to put them at high risk.")
        add("6. Review. Record what we learned and what we will change.")
        add("## Record keeping")
        i = facts["incident_log"]
        if i["state"] == "set" and i["value"] == "yes":
            add("Every incident is written in our incident log, including those we decide not to report.")
        else:
            add(f"{_gap(inputs, 'incident_log')}.")
    else:  # retention_schedule
        dpo = val("dpo_name", "{{DPO_NAME}}")
        add(f"# Retention schedule of {org}")
        add("This schedule lists how long we keep each kind of personal data and how we delete it.")
        add(f"Schedule owner: {dpo}.")
        add("| Data category | Retention period | Deletion method |")
        add("| --- | --- | --- |")
        for n in (1, 2, 3):
            add(f"| {fixed(f'category_{n}')} | {fixed('retention_period')} | {fixed('deletion_method')} |")
        add("## Requests to erase data")
        r = facts["rights_process"]
        if r["state"] == "set" and r["value"] == "yes":
            add("Requests to erase personal data follow our process for access, correction, portability and erasure requests.")
        else:
            add(f"{_gap(inputs, 'rights_process')}.")
    return "\n\n".join(lines)


SLOT_FOR = {"org_name": "{{ORG_NAME}}", "website": "{{WEBSITE}}", "dpo_name": "{{DPO_NAME}}"}


def fill_slots(text: str, inputs: Dict[str, Any]) -> str:
    """Put the organisation's own values in place of the tokens. Values were cleaned in `build_inputs`."""
    facts = _by_key(inputs)
    for key, token in SLOT_FOR.items():
        if key in facts and facts[key]["state"] == "set":
            text = text.replace(token, facts[key]["value"])
    return text


# ── Instructions for the model (fixed; no customer text) ─────────────────────

SYSTEM_PROMPT = (
    "You edit a draft of a data protection document for a Nigerian organisation. Reword the draft so it reads "
    "clearly in plain English, keeping the same sections, order of ideas and Markdown headings. Rules: keep every "
    "{{TOKEN}} and every [MISSING: ...] placeholder exactly as written, once each, unchanged. Do not add or "
    "change any fact, name, number, date, address, link or email. Do not add new sections or new commitments. "
    "Never say or imply that the organisation complies with, satisfies or is certified under any law, and never "
    "say the text is legally sufficient or adequate. Respond as JSON with one key, \"text\", holding the edited draft."
)


# ── Assembly ──────────────────────────────────────────────────────────────────


def reviewer_notes(inputs: Dict[str, Any]) -> str:
    rows = []
    for f in inputs["facts"]:
        if f["state"] == "set":
            rows.append(f"- {f['label']}: from {SOURCE_LABELS[f['source']]}")
        else:
            rows.append(f"- {f['label']}: not available" + (f" ({f['note']})" if f.get("note") else ""))
    return ("## Inputs behind this draft (for the reviewer; remove before publishing)\n\n"
            + "\n".join(rows)
            + "\n\nOnly the inputs above were used. Anything marked MISSING in square brackets is for you to fill in.")


def compose(body: str, inputs: Dict[str, Any], *, version: int, generated_at: datetime) -> str:
    """Full stored text: label on the first line, version and date, the body, reviewer notes, label again."""
    stamp = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
    head = f"{LABEL}\n\nVersion {version} · Generated {stamp} (UTC) · {TITLES[inputs['kind']]}"
    return f"{head}\n\n{body.strip()}\n\n---\n\n{reviewer_notes(inputs)}\n\n---\n\n{FOOTER}\n"


def final_problems(text: str, inputs: Dict[str, Any]) -> List[str]:
    """Checks on the finished text. Empty when it may be stored."""
    problems = []
    if not text.startswith(LABEL):
        problems.append("label_missing")
    for item in placeholders_for(inputs):
        if item["text"] not in text:
            problems.append(f"placeholder_dropped:{item['key']}")
    if SLOT.search(text):
        problems.append("slot_left")
    if banned_hits(text):
        problems.append("banned_phrase")
    return problems
