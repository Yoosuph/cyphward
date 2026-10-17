"""Guided questionnaire (packet C3a): loaded from versioned JSON, validated once.

Each question names the register requirements it evidences and, for the
applicability questions, the conditional requirements it can exclude. The
validator runs at import, so an invalid questionnaire stops the API from
starting instead of recording answers against the wrong requirement.
"""
import json
import pathlib
import re
from typing import Any, Dict, List, Optional

from backend.app.compliance.register import REGISTER

QUESTIONNAIRE_FILE = pathlib.Path(__file__).resolve().parent / "questionnaires" / "ndpa_gaid_v1.json"

TYPES = ("yes_no", "choice", "date")
EVIDENCE_STATUSES = ("present", "gap", "not_applicable")
KEY_PATTERN = re.compile(r"^[a-z_]+(\.[a-z_]+)*$")
GROUP_KEYS = {g["key"] for g in REGISTER["groups"]}
REQUIREMENTS = {r["key"]: r for r in REGISTER["requirements"]}
NOT_SURE = "not_sure"


class QuestionnaireError(ValueError):
    pass


def _fail(where: str, message: str) -> None:
    raise QuestionnaireError(f"{where}: {message}")


def _values(question: Dict[str, Any]) -> List[str]:
    """Answer values a question accepts. `not_sure` is always allowed (decision D13)."""
    if question["type"] == "yes_no":
        values = ["yes", "no"] + (["not_applicable"] if question.get("allow_not_applicable") else [])
    elif question["type"] == "choice":
        values = list(question["options"])
    else:
        values = ["date"]
    return values + [NOT_SURE]


def validate(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return the questionnaire when valid; raise QuestionnaireError naming the first problem."""
    if not isinstance(data, dict) or not isinstance(data.get("version"), str) or not data["version"]:
        _fail("questionnaire", "missing version")
    if data.get("register_version") != REGISTER["version"]:
        _fail("questionnaire", f"register_version must be {REGISTER['version']}")
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        _fail("questionnaire", "missing questions")

    by_key: Dict[str, Dict[str, Any]] = {}
    applicability_targets: Dict[str, List[str]] = {}
    evidenced: Dict[str, List[str]] = {}
    for question in questions:
        key = question.get("key") if isinstance(question, dict) else None
        where = f"question {key!r}"
        if not isinstance(question, dict):
            _fail(where, "must be an object")
        if not isinstance(key, str) or len(key) > 80 or not KEY_PATTERN.match(key):
            _fail(where, "key must be lowercase dotted words")
        if key in by_key:
            _fail(where, "duplicate key")
        if question.get("group") not in GROUP_KEYS:
            _fail(where, f"unknown group {question.get('group')!r}")
        if not isinstance(question.get("prompt"), str) or not question["prompt"].strip():
            _fail(where, "missing prompt")
        if question.get("type") not in TYPES:
            _fail(where, f"type must be one of {list(TYPES)}")
        if question["type"] == "choice":
            options = question.get("options")
            if not isinstance(options, list) or not options or not all(isinstance(o, str) and o for o in options) \
                    or len(set(options)) != len(options) or NOT_SURE in options:
                _fail(where, "choice needs unique, non-empty options (not_sure is implicit)")
        if question["type"] == "date" and question.get("date_label") is None:
            _fail(where, "date questions need a date_label")
        if question.get("allow_not_applicable") and question["type"] != "yes_no":
            _fail(where, "allow_not_applicable applies to yes_no questions only")
        if question.get("allows_text") and (not isinstance(question.get("text_max"), int)
                                            or not 1 <= question["text_max"] <= 500):
            _fail(where, "allows_text needs text_max between 1 and 500")
        if "expiry_days_from_date" in question:
            days = question["expiry_days_from_date"]
            if question["type"] != "date" or not isinstance(days, int) or not 1 <= days <= 730:
                _fail(where, "expiry_days_from_date needs a date question and 1-730 days")

        # Only requirements that take customer answers can be evidenced by a question.
        evidences = question.get("evidences")
        if not isinstance(evidences, list):
            _fail(where, "evidences must be a list")
        for requirement_key in evidences:
            requirement = REQUIREMENTS.get(requirement_key)
            if requirement is None:
                _fail(where, f"unknown requirement {requirement_key!r}")
            if "customer_attested" not in requirement["evidence_types"]:
                _fail(where, f"{requirement_key} does not take customer answers")
            if requirement["group"] != question["group"]:
                _fail(where, f"{requirement_key} belongs to group {requirement['group']}")
        evidence_on = question.get("evidence_on", {})
        if evidences:
            if not isinstance(evidence_on, dict) or not evidence_on:
                _fail(where, "evidencing questions need evidence_on")
            allowed = set(_values(question)) - {NOT_SURE}
            for value, status in evidence_on.items():
                if value not in allowed or status not in EVIDENCE_STATUSES:
                    _fail(where, f"evidence_on {value!r}: {status!r} is not allowed")
                if status == "not_applicable" and not question.get("allow_not_applicable"):
                    _fail(where, "not_applicable evidence needs allow_not_applicable")
            if question["type"] == "yes_no" and not {"yes", "no"} <= set(evidence_on):
                _fail(where, "yes_no evidence_on must cover yes and no")
            if question["type"] == "date" and "date" not in evidence_on:
                _fail(where, "date evidence_on must cover date")
        elif evidence_on:
            _fail(where, "evidence_on without evidences")

        applicability = question.get("applicability", [])
        if not isinstance(applicability, list):
            _fail(where, "applicability must be a list")
        for rule in applicability:
            target = rule.get("target") if isinstance(rule, dict) else None
            requirement = REQUIREMENTS.get(target)
            if requirement is None:
                _fail(where, f"unknown applicability target {target!r}")
            if requirement.get("applicability_question") != key:
                _fail(where, f"{target} is not decided by this question")
            if rule.get("when") not in _values(question) or rule.get("when") == NOT_SURE:
                _fail(where, f"applicability when {rule.get('when')!r} is not an answer")
            applicability_targets.setdefault(target, []).append(key)
        if not evidences and not applicability:
            _fail(where, "a question must evidence a requirement or decide applicability")

        show_if = question.get("show_if")
        if show_if is not None:
            prerequisite = by_key.get(show_if.get("question") if isinstance(show_if, dict) else None)
            if prerequisite is None:
                _fail(where, "show_if must name an earlier question")
            if show_if.get("value") not in _values(prerequisite) or show_if.get("value") == NOT_SURE:
                _fail(where, "show_if value is not an answer to that question")

        for requirement_key in evidences:
            evidenced.setdefault(requirement_key, []).append(key)
        by_key[key] = question

    # Coverage in both directions: every customer-answered requirement has a question,
    # and every applicability question targets only the conditional requirements it decides.
    for requirement in REGISTER["requirements"]:
        if "customer_attested" in requirement["evidence_types"] and requirement["key"] not in evidenced:
            _fail(f"requirement {requirement['key']}", "takes customer answers but no question asks for them")
        if requirement.get("applicability_question") and requirement["key"] not in applicability_targets:
            _fail(f"requirement {requirement['key']}", "is conditional but no question decides it")
    return data


def load(path: pathlib.Path = QUESTIONNAIRE_FILE) -> Dict[str, Any]:
    return validate(json.loads(path.read_text(encoding="utf-8")))


QUESTIONNAIRE: Dict[str, Any] = load()
QUESTIONS: List[Dict[str, Any]] = list(QUESTIONNAIRE["questions"])
BY_KEY: Dict[str, Dict[str, Any]] = {q["key"]: q for q in QUESTIONS}


def question(key: str) -> Optional[Dict[str, Any]]:
    return BY_KEY.get(key)


def values_for(item: Dict[str, Any]) -> List[str]:
    return _values(item)


def questions_evidencing(requirement_key: str) -> List[Dict[str, Any]]:
    return [q for q in QUESTIONS if requirement_key in q.get("evidences", [])]


def applicability_for(requirement_key: str) -> List[Dict[str, Any]]:
    """Each rule that can exclude this requirement: {question, when}."""
    rules = []
    for q in QUESTIONS:
        for rule in q.get("applicability", []):
            if rule["target"] == requirement_key:
                rules.append({"question": q, "when": rule["when"]})
    return rules
