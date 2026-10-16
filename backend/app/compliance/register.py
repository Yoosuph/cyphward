"""Legal requirements register: loaded from versioned JSON, validated once.

Requirement text lives only in `registers/<version>.json` so a reviewer can
correct it in one file. Validation runs at import, so an invalid register
stops the API from starting instead of rendering a wrong page.
"""
import json
import pathlib
from typing import Any, Dict, List, Optional

from backend.app.compliance.rule_keys import NUCLEI_PREFIX, RULES
from backend.app.risk.check_set import DECLARED_CHECKS

REGISTER_FILE = pathlib.Path(__file__).resolve().parent / "registers" / "ndpa_gaid_v1.json"

SOURCES = ("tool_observed", "externally_observed", "customer_attested", "practitioner_reviewed")
APPLIES_TO = ("all", "dcpmi", "uhl_ehl", "conditional")
REQUIRED = ("key", "group", "title", "clause", "clause_verified", "summary", "applies_to",
            "evidence_types", "freshness_days", "remediation_hint")
TOOL_TEXT = ("checks_performed", "not_checked")

DISCLAIMER = ("Readiness evidence, not legal advice or a compliance determination. Filing of Compliance "
              "Audit Returns for UHL/EHL organisations must go through a licensed DPCO.")


class RegisterError(ValueError):
    pass


def _fail(where: str, message: str) -> None:
    raise RegisterError(f"{where}: {message}")


def validate(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return the register when valid; raise RegisterError naming the first problem."""
    if not isinstance(data, dict) or not isinstance(data.get("version"), str) or not data["version"]:
        _fail("register", "missing version")
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        _fail("register", "missing groups")
    group_keys = [g.get("key") for g in groups if isinstance(g, dict)]
    if len(group_keys) != len(groups) or len(set(group_keys)) != len(group_keys) or \
            not all(isinstance(g.get("title"), str) and g["title"] for g in groups):
        _fail("register", "groups need a unique key and a title")

    requirements = data.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        _fail("register", "missing requirements")
    seen = set()
    for item in requirements:
        where = f"requirement {item.get('key') if isinstance(item, dict) else item!r}"
        if not isinstance(item, dict):
            _fail(where, "must be an object")
        for field in REQUIRED:
            if field not in item or item[field] in (None, "", []):
                _fail(where, f"missing {field}")
        if item["key"] in seen:
            _fail(where, "duplicate key")
        seen.add(item["key"])
        if item["group"] not in group_keys:
            _fail(where, f"unknown group {item['group']}")
        if item["applies_to"] not in APPLIES_TO:
            _fail(where, f"unknown applies_to {item['applies_to']}")
        if item["applies_to"] != "all" and not item.get("applicability_question"):
            _fail(where, "conditional requirements need an applicability_question")
        if not isinstance(item["clause_verified"], bool):
            _fail(where, "clause_verified must be true or false")
        if item["clause_verified"] and not item.get("clause_reviewed_by"):
            _fail(where, "a verified clause needs clause_reviewed_by")
        if not isinstance(item["freshness_days"], int) or not 1 <= item["freshness_days"] <= 400:
            _fail(where, "freshness_days must be 1-400")
        unknown = [e for e in item["evidence_types"] if e not in SOURCES]
        if unknown:
            _fail(where, f"unknown evidence types {unknown}")

        mapping = item.get("tool_mapping")
        if mapping is None:
            if "tool_observed" in item["evidence_types"]:
                _fail(where, "tool_observed evidence needs a tool_mapping")
            continue
        if "tool_observed" not in item["evidence_types"]:
            _fail(where, "a tool_mapping needs tool_observed evidence")
        for field in TOOL_TEXT:
            if not isinstance(item.get(field), str) or not item[field].strip():
                _fail(where, f"tool-backed requirements need {field}")
        if not isinstance(mapping, dict):
            _fail(where, "tool_mapping must be an object")
        if "scan_history" in mapping:
            history = mapping["scan_history"]
            if set(mapping) != {"scan_history"} or not isinstance(history, dict) or \
                    not isinstance(history.get("min_complete_scans"), int) or history["min_complete_scans"] < 1:
                _fail(where, "scan_history needs only min_complete_scans >= 1")
            continue
        if set(mapping) != {"checks", "rules"}:
            _fail(where, "tool_mapping needs exactly checks and rules")
        checks, rules = mapping["checks"], mapping["rules"]
        if not isinstance(checks, list) or not isinstance(rules, list) or not (checks or rules):
            _fail(where, "tool_mapping checks/rules must be lists, not both empty")
        bad_checks = [c for c in checks if c not in DECLARED_CHECKS]
        if bad_checks:
            _fail(where, f"unknown declared checks {bad_checks}")
        bad_rules = [r for r in rules if r != f"{NUCLEI_PREFIX}*" and r not in RULES]
        if bad_rules:
            _fail(where, f"unknown rule keys {bad_rules}")
    return data


def load(path: pathlib.Path = REGISTER_FILE) -> Dict[str, Any]:
    return validate(json.loads(path.read_text(encoding="utf-8")))


REGISTER: Dict[str, Any] = load()
_BY_KEY: Dict[str, Dict[str, Any]] = {r["key"]: r for r in REGISTER["requirements"]}


def requirement(key: str) -> Optional[Dict[str, Any]]:
    return _BY_KEY.get(key)


def requirements() -> List[Dict[str, Any]]:
    return list(REGISTER["requirements"])


def tool_requirements() -> List[Dict[str, Any]]:
    """Requirements whose evidence rows are written at scan finalisation."""
    return [r for r in REGISTER["requirements"]
            if isinstance(r.get("tool_mapping"), dict) and "checks" in r["tool_mapping"]]


def rule_matches(pattern: str, rule_key: str) -> bool:
    if pattern == f"{NUCLEI_PREFIX}*":
        return rule_key.startswith(NUCLEI_PREFIX)
    return pattern == rule_key
