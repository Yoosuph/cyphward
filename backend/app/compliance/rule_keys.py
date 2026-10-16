"""Stable rule keys for findings (compliance packet C0).

Findings are stored by display title (security checks) or Nuclei template id.
Compliance mapping must not depend on a display title, so every detector gets
a stable `rule_key` here. Existing findings are never renamed; the key is
derived on read from the stored category, evidence and title.

* Current security-check titles map exactly (`SECURITY_CHECK_RULES`). A test
  parses `backend/app/scanner/security_checks.py` and fails if any title it
  can emit has no rule key, so a new detector can't silently drop out of
  compliance mapping.
* Titles written by older checker versions (still present in stored
  findings) map through `LEGACY_TITLE_PATTERNS`.
* Nuclei findings map to `nuclei:<template_id>`.
* Anything else is unmapped (`None`) and never counts as compliance evidence.

`kind` decides how an open finding is read:
  issue          an open finding is a gap for the requirements that use it;
  informational  shown next to the requirement, never a gap on its own;
  positive       a positive observation; never a gap, and never enough on its
                 own to mark a requirement as having evidence.
`check` is the declared coverage check (risk/check_set.py) whose conclusive
evaluation is required before the rule's absence means anything, or None
when no declared check covers it (absence then proves nothing).
"""
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from backend.app.scanner.detectors import classify_detector

RULE_SET_VERSION = "cyphward-rules-v1"
KINDS = ("issue", "informational", "positive")
NUCLEI_PREFIX = "nuclei:"


@dataclass(frozen=True)
class Rule:
    key: str
    check: Optional[str]
    kind: str = "issue"


SECURITY_CHECK_RULES: Dict[str, Rule] = {
    # DNS & Email Security (apex)
    "Missing Email DMARC Authentication Policy": Rule("dns.dmarc.missing", "dns.dmarc"),
    "Permissive Email DMARC Policy (p=none)": Rule("dns.dmarc.policy_none", "dns.dmarc"),
    "Missing Sender Policy Framework (SPF) Record": Rule("dns.spf.missing", "dns.spf"),
    "SPF Record Configured with Softfail (~all)": Rule("dns.spf.softfail", "dns.spf"),
    # HTTP Headers
    "Strict-Transport-Security (HSTS) Header Missing": Rule("http.hsts.missing", "http.headers"),
    "Strict-Transport-Security Missing includeSubDomains": Rule("http.hsts.no_subdomains", "http.headers"),
    "Missing Content-Security-Policy (CSP) Header": Rule("http.csp.missing", "http.headers"),
    "Missing X-Frame-Options (Clickjacking Protection)": Rule("http.frame_options.missing", "http.headers"),
    "Missing X-Content-Type-Options: nosniff Header": Rule("http.content_type_options.missing", "http.headers"),
    # Information Disclosure
    "Server Software Version Disclosed in HTTP Header": Rule("http.server_version_disclosed", "http.headers"),
    "Technology Stack Disclosed via X-Powered-By Header": Rule("http.powered_by_disclosed", "http.headers"),
    # SSL/TLS
    "SSL/TLS Certificate Expired or Invalid": Rule("tls.certificate.invalid", "tls.certificate"),
    "SSL/TLS Certificate Expiring Soon": Rule("tls.certificate.expiring", "tls.certificate"),
    "Modern Cryptographic Protocols Active": Rule("tls.protocol.modern", None, "positive"),
    # Exposure (robots.txt is fetched outside the declared checks)
    "Robots.txt Discloses Sensitive Endpoint Paths": Rule("http.robots_paths_disclosed", None, "informational"),
}

# Older checker titles still present in stored findings (seen in production
# data on 2026-10-16). Matched in full, case-sensitively.
LEGACY_TITLE_PATTERNS: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"SSL/TLS Certificate Expiring within \d+ Days"), "tls.certificate.expiring"),
    (re.compile(r"Modern Cryptographic Protocols Active \(TLSv1\.[0-3]\)"), "tls.protocol.modern"),
)

RULES: Dict[str, Rule] = {rule.key: rule for rule in SECURITY_CHECK_RULES.values()}


def rule_key_for(category: Any, evidence: Any, title: Any) -> Optional[str]:
    """Stable rule key for a stored or new finding, or None when unmapped."""
    detector = classify_detector(category, evidence)
    if detector["name"] == "nuclei":
        template_id = (detector.get("template_id") or "").strip()
        return f"{NUCLEI_PREFIX}{template_id}" if template_id else None
    if detector["name"] != "security_checks":
        return None
    text = (title or "").strip()
    rule = SECURITY_CHECK_RULES.get(text)
    if rule:
        return rule.key
    for pattern, key in LEGACY_TITLE_PATTERNS:
        if pattern.fullmatch(text):
            return key
    return None


def rule_for(key: Optional[str]) -> Optional[Rule]:
    """Rule metadata for a key. Nuclei keys are issues with no declared check:
    a match is a gap, but no Nuclei result can show a clean outcome."""
    if not key:
        return None
    if key.startswith(NUCLEI_PREFIX):
        return Rule(key, None, "issue")
    return RULES.get(key)
