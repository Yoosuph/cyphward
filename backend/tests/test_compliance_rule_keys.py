"""Every detector must have a stable rule key (compliance packet C0).

The security-check titles are read from the checker's source, so adding a
detector without a rule key fails here instead of silently dropping out of
compliance mapping.
"""
import ast
import pathlib

import pytest

from backend.app.compliance import rule_keys
from backend.app.compliance.rule_keys import (
    KINDS, LEGACY_TITLE_PATTERNS, NUCLEI_PREFIX, SECURITY_CHECK_RULES, rule_for, rule_key_for,
)
from backend.app.risk.check_set import DECLARED_CHECKS
from backend.app.scanner.detectors import SHARED_CHECK_CATEGORIES

CHECKER = pathlib.Path(__file__).resolve().parents[1] / "app" / "scanner" / "security_checks.py"


def _emitted_titles():
    """(title, category) for every finding dict literal the checker can emit."""
    tree = ast.parse(CHECKER.read_text())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        fields = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
        if "title" not in fields or "severity" not in fields:
            continue
        title, category = fields["title"], fields.get("category")
        assert isinstance(title, ast.Constant), (
            f"security_checks.py line {node.lineno}: finding titles must be static strings so they "
            "can carry a stable rule key")
        found.append((title.value, category.value if isinstance(category, ast.Constant) else None))
    return found


def test_the_checker_source_is_parsed():
    assert len(_emitted_titles()) >= 15


def test_every_security_check_title_has_a_rule_key():
    missing = [(t, c) for t, c in _emitted_titles() if rule_key_for(c, {}, t) is None]
    assert not missing, f"add these titles to rule_keys.SECURITY_CHECK_RULES: {missing}"


def test_every_emitted_title_is_in_the_exact_table_with_its_category():
    for title, category in _emitted_titles():
        assert title in SECURITY_CHECK_RULES, title
        assert category in SHARED_CHECK_CATEGORIES, (title, category)


def test_rule_keys_are_unique_and_well_formed():
    keys = [r.key for r in SECURITY_CHECK_RULES.values()]
    assert len(keys) == len(set(keys))
    for rule in SECURITY_CHECK_RULES.values():
        assert rule.kind in KINDS
        assert rule.check is None or rule.check in DECLARED_CHECKS, rule
        assert not rule.key.startswith(NUCLEI_PREFIX)
        assert rule_for(rule.key) == rule


def test_titles_from_older_checkers_still_map():
    # Titles present in stored production findings on 2026-10-16.
    assert rule_key_for("SSL/TLS", {}, "SSL/TLS Certificate Expiring within 21 Days") == "tls.certificate.expiring"
    assert rule_key_for("SSL/TLS", {}, "SSL/TLS Certificate Expiring within 22 Days") == "tls.certificate.expiring"
    assert rule_key_for("SSL/TLS", {}, "Modern Cryptographic Protocols Active (TLSv1.3)") == "tls.protocol.modern"
    for _, key in LEGACY_TITLE_PATTERNS:
        assert key in rule_keys.RULES


def test_nuclei_findings_key_on_template_id():
    assert rule_key_for("Nuclei Scan", {"template_id": "CVE-2024-1234"}, "Some CVE") == "nuclei:CVE-2024-1234"
    assert rule_key_for("HTTP Headers", {"template_id": "exposed-panel"}, "Missing X") == "nuclei:exposed-panel"
    assert rule_key_for("Nuclei Scan", {}, "No template") is None
    nuclei = rule_for("nuclei:CVE-2024-1234")
    assert nuclei.kind == "issue" and nuclei.check is None, "no Nuclei result can show a clean outcome"


@pytest.mark.parametrize("category,title", [
    ("Security Configuration", "rls-probe"),           # stray non-detector row seen in production
    ("Unknown Category", "Missing Content-Security-Policy (CSP) Header"),
    ("HTTP Headers", "Missing Content-Security-Policy (CSP) Header — renamed"),
    (None, None),
])
def test_unknown_findings_are_unmapped(category, title):
    assert rule_key_for(category, {}, title) is None
    assert rule_for(None) is None and rule_for("no.such.rule") is None


def test_positive_and_informational_rules_are_never_issues():
    assert rule_for("tls.protocol.modern").kind == "positive"
    assert rule_for("http.robots_paths_disclosed").kind == "informational"
