"""Plain scan-failure wording (admin phase 2, docs/admin-phase2-2026-10-31/README.md).

When a scan fails, the customer and the owner console show one reviewed sentence chosen by a stored failure code
(`scans.failure_code`). The raw worker error text (`scans.error_message`, the stage `error` notes and per-host
failure reasons) stays in the database for the owner console and never reaches a customer response.

* `classify(text)` picks the code when a scan is marked failed (core/scan_execution.fail_claim, used by the worker's
  fail call and the local pipeline; core/scan_recovery stores 'interrupted'). A scan failed before the column
  existed has no stored code, so its stored text is classified when it is read.
* `failure_for(code)` maps a code to its sentence; an unknown or missing code maps to the generic sentence.
* `customer_scan(row)` and `customer_raw_results(rows)` are the only way a scan row leaves a customer endpoint.

The sentences use plain English and no claim wording (test_scan_failures.py).
"""
import copy
import re
from typing import Any, Dict, Iterable, List, Optional

GENERIC = "internal"

# code -> reviewed sentence. Keep the codes stable: they are stored and the frontend may key on them.
CATEGORIES: Dict[str, str] = {
    "unreachable": "We could not reach the site.",
    "blocked": "The site blocked our check.",
    "timeout": "The check ran out of time.",
    "out_of_scope": "The site is outside the verified domain, so we did not check it.",
    "domain_unverified": "The domain is no longer verified, so the check stopped.",
    "interrupted": "The check was interrupted before it finished. You can run it again.",
    GENERIC: ("Something went wrong on our side. The failure is recorded for our team, and you can run the "
              "scan again."),
}

# Ordered: the first matching rule wins. Patterns are matched against the lower-cased raw text.
_RULES = (
    ("out_of_scope", r"\bscope\b|outside (the )?(authori[sz]ed|verified)|off[-_ ]scope|not in scope"),
    ("domain_unverified", r"not verified|verification (failed|expired|revoked)|unverified"),
    ("blocked", r"\b(403|429)\b|forbidden|blocked|rate[- ]?limit|too many requests|captcha|access denied|\bwaf\b"),
    ("timeout", r"time[sd]? ?out|timed out|deadline|budget exhausted|took too long|stage_deadline"),
    ("interrupted", r"interrupted|cannot be resumed|lease (lost|expired)"),
    ("unreachable", r"could not resolve|name or service not known|nxdomain|no (public )?dns|getaddrinfo|"
                    r"connecterror|connect error|errno (111|-2|-3|-5|101|113)|"
                    r"connection (refused|reset|error|failed)|unreachable|no route to host|no (usable )?http|"
                    r"no https response|network (error|is unreachable)|ssl|certificate verify|"
                    r"no hosts? (found|discovered|resolved)|no live hosts?"),
)
_COMPILED = tuple((code, re.compile(pattern)) for code, pattern in _RULES)


def classify(text: Optional[str]) -> str:
    """The failure code for a raw error text. Text that matches no rule is the generic code."""
    lowered = (text or "").lower()
    for code, pattern in _COMPILED:
        if pattern.search(lowered):
            return code
    return GENERIC


def failure_for(code: Optional[str]) -> Dict[str, str]:
    """{"code", "message"}: the reviewed sentence for a stored code; unknown or missing codes are generic."""
    known = code if code in CATEGORIES else GENERIC
    return {"code": known, "message": CATEGORIES[known]}


def code_for_row(row: Dict[str, Any]) -> Optional[str]:
    """The code for a failed scan row: the stored one, else (scans failed before the column) classified text."""
    if (row.get("status") or "") != "failed":
        return None
    return row.get("failure_code") or classify(row.get("error_message"))


# ── Customer serialization ─────────────────────────────────────────────────
# Stage notes and per-host reasons the backend itself writes. Anything else is worker text and is replaced.
STAGE_NOTE_FALLBACK = "This check did not finish."
_REVIEWED_NOTES = (
    re.compile(r"\d+ of \d+ targets could not be assessed\."),
    re.compile(r"Security checks failed on \d+ of \d+ hosts\."),
    re.compile(r"AI analysis exceeded its deadline\."),
)
# Per-host reason codes the scans page explains (frontend/src/pages/Scans.tsx omissionReason).
HOST_REASON_CODES = frozenset({
    "stage_host_cap", "tool_unavailable", "no_public_dns_address", "no_usable_http_response", "no_https_response",
    "outside_authorised_scope", "recon_budget_exhausted", "recon_stage_deadline", "third_party_service",
    "check_failed",
})
HOST_REASON_FALLBACK = "check_failed"
_REVIEWED_HOST_REASONS = (
    re.compile(r"No HTTP response"),
    re.compile(r"DNS queries failed or unknown: [A-Za-z0-9_., ]{1,200}"),
)
_PRIVATE_SCAN_KEYS = ("claim_token", "error_message", "failure_code")


def _reviewed(text: Any, patterns) -> bool:
    return isinstance(text, str) and any(p.fullmatch(text) for p in patterns)


def _scrub_errors(value: Any) -> Any:
    """Replace every `error` string that is not reviewed backend wording, and every unreviewed host reason."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "error" and isinstance(item, str):
                out[key] = item if _reviewed(item, _REVIEWED_NOTES) else STAGE_NOTE_FALLBACK
            elif key == "failed_hosts" and isinstance(item, dict):
                out[key] = {host: (reason if (isinstance(reason, str) and (reason in HOST_REASON_CODES
                                              or _reviewed(reason, _REVIEWED_HOST_REASONS)))
                                   else HOST_REASON_FALLBACK)
                            for host, reason in item.items()}
            else:
                out[key] = _scrub_errors(item)
        return out
    if isinstance(value, list):
        return [_scrub_errors(item) for item in value]
    return value


def customer_stage_progress(progress: Any) -> Any:
    if not isinstance(progress, dict):
        return progress
    cleaned = {k: v for k, v in progress.items() if k != "error"}  # the top-level copy of the raw failure
    return _scrub_errors(copy.deepcopy(cleaned))


def customer_scan(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A scan row as a customer may see it: no raw failure text, no execution token, plus `failure`."""
    if row is None:
        return None
    code = code_for_row(row)
    out = {k: v for k, v in row.items() if k not in _PRIVATE_SCAN_KEYS}
    if "stage_progress" in out:
        out["stage_progress"] = customer_stage_progress(out["stage_progress"])
    out["failure"] = failure_for(code) if code else None
    return out


def customer_raw_results(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{**r, "raw_data": _scrub_errors(r.get("raw_data"))} for r in rows or []]
