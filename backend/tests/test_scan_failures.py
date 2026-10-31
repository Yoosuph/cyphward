"""Plain scan-failure wording (admin phase 2, core/scan_failures.py), without a database.

Each known failure code maps to its reviewed sentence; an unknown or missing code maps to the generic one; raw
worker text classifies to the right code; and raw text never reaches a customer scan response (list, detail,
overview), while the owner console keeps it. The stored column is exercised in test_admin_phase2_postgres.py.
"""
import json
import uuid

import pytest

from backend.app.core import scan_failures as sf
from conftest import ALICE, ORG_A, DOM_A1

RAW = "Traceback: httpx.ConnectError [Errno 111] at 10.0.0.7:8443 SECRET-WORKER-TEXT"

BANNED = (
    "compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit",
    "compliance score", "fully meets", "meets the requirement", "is met", "adequate", "adequacy", "guarantee",
)


def test_every_code_has_a_plain_sentence():
    assert set(sf.CATEGORIES) == {"unreachable", "blocked", "timeout", "out_of_scope", "domain_unverified",
                                  "interrupted", "internal"}
    for code, sentence in sf.CATEGORIES.items():
        assert sf.failure_for(code) == {"code": code, "message": sentence}
        assert sentence.endswith(".") and len(sentence) < 140, code
        assert not any(p in sentence.lower() for p in BANNED), code
    assert sf.CATEGORIES["unreachable"] == "We could not reach the site."
    assert sf.CATEGORIES["blocked"] == "The site blocked our check."
    assert sf.CATEGORIES["timeout"] == "The check ran out of time."


@pytest.mark.parametrize("code", [None, "", "segfault", "UNREACHABLE", "x" * 50])
def test_unknown_or_missing_codes_get_the_generic_sentence(code):
    assert sf.failure_for(code) == {"code": "internal", "message": sf.CATEGORIES["internal"]}


@pytest.mark.parametrize("text, code", [
    ("discovery: [Errno -2] Name or service not known", "unreachable"),
    ("httpx.ConnectError: Connection refused", "unreachable"),
    ("httpx.ConnectError: [Errno 111]", "unreachable"),
    ("No usable HTTP response from any host", "unreachable"),
    ("dns: NXDOMAIN for example.test", "unreachable"),
    ("http: HTTP 403 Forbidden from origin", "blocked"),
    ("429 Too Many Requests", "blocked"),
    ("Blocked by WAF challenge", "blocked"),
    ("ports: stage deadline reached", "timeout"),
    ("asyncio.TimeoutError: timed out", "timeout"),
    ("recon budget exhausted", "timeout"),
    ("scope: host api.other.test is outside the authorized scope", "out_of_scope"),
    ("Domain example.test is not verified", "domain_unverified"),
    ("interrupted: legacy unleased scan cannot be resumed; run a new scan.", "interrupted"),
    ("KeyError: 'score'", "internal"),
    ("", "internal"),
    (None, "internal"),
])
def test_raw_text_classifies_to_a_known_code(text, code):
    assert sf.classify(text) == code


def test_the_interrupted_recovery_message_has_its_own_code():
    from backend.app.core.scan_recovery import INTERRUPTED_MESSAGE
    assert sf.classify(INTERRUPTED_MESSAGE) == "interrupted"


def test_customer_scan_drops_raw_text_and_adds_the_sentence():
    row = {"id": "s", "status": "failed", "error_message": RAW, "failure_code": "blocked", "claim_token": "tok",
           "stage_progress": {"error": RAW,
                              "http": {"status": "failed", "error": RAW},
                              "dns": {"status": "failed", "error": "1 of 2 targets could not be assessed."}}}
    out = sf.customer_scan(row)
    assert out["failure"] == {"code": "blocked", "message": "The site blocked our check."}
    assert "error_message" not in out and "claim_token" not in out and "failure_code" not in out
    assert "error" not in out["stage_progress"]
    assert out["stage_progress"]["http"]["error"] == sf.STAGE_NOTE_FALLBACK
    assert out["stage_progress"]["dns"]["error"] == "1 of 2 targets could not be assessed."
    assert "SECRET" not in json.dumps(out)
    assert row["error_message"] == RAW  # the stored row is not changed


def test_a_scan_failed_before_the_column_is_classified_from_its_text():
    out = sf.customer_scan({"status": "failed", "error_message": "Connection refused", "failure_code": None})
    assert out["failure"]["code"] == "unreachable"


def test_a_scan_that_did_not_fail_has_no_failure():
    assert sf.customer_scan({"status": "completed", "error_message": None})["failure"] is None


def test_host_reasons_keep_codes_and_reviewed_text_only():
    raw = [{"stage": "http", "raw_data": {"failed_hosts": {
        "a.test": "no_https_response", "b.test": "No HTTP response", "c.test": RAW,
        "d.test": "DNS queries failed or unknown: MX, TXT"},
        "http": [{"host": "c.test", "error": RAW}]}}]
    out = sf.customer_raw_results(raw)[0]["raw_data"]
    assert out["failed_hosts"] == {"a.test": "no_https_response", "b.test": "No HTTP response",
                                   "c.test": "check_failed", "d.test": "DNS queries failed or unknown: MX, TXT"}
    assert out["http"][0]["error"] == sf.STAGE_NOTE_FALLBACK
    assert "SECRET" not in json.dumps(out)


def test_raw_text_never_reaches_the_customer_api(client, store, auth_headers):
    scan_id = str(uuid.uuid4())
    store.scans.append({
        "id": scan_id, "org_id": ORG_A, "domain_id": DOM_A1, "domain": "acme.test", "status": "failed",
        "score": None, "current_stage": "http", "scan_type": "EXTERNAL_ASSESSMENT", "started_at": None,
        "completed_at": None, "created_at": "2026-10-30T00:00:00", "error_message": RAW, "failure_code": "unreachable",
        "claim_token": "claim-SECRET-token",
        "stage_progress": {"error": RAW, "http": {"status": "failed", "error": RAW}},
    })
    store.scan_results.append({"scan_id": scan_id, "stage": "http", "attempt_generation": 1,
                               "raw_data": {"failed_hosts": {"www.acme.test": RAW}, "error": RAW}})
    headers = auth_headers(ALICE, org=ORG_A)
    listing = client.get("/api/v1/scans", headers=headers)
    detail = client.get(f"/api/v1/scans/{scan_id}", headers=headers)
    overview = client.get("/api/v1/overview", headers=headers)
    for resp in (listing, detail, overview):
        assert resp.status_code == 200, resp.text
        assert "SECRET" not in resp.text and "Errno" not in resp.text and "error_message" not in resp.text
    mine = next(s for s in listing.json() if s["id"] == scan_id)
    assert mine["failure"] == {"code": "unreachable", "message": "We could not reach the site."}
    body = detail.json()
    assert body["scan"]["failure"]["message"] == "We could not reach the site."
    assert body["raw_results"][0]["raw_data"]["failed_hosts"] == {"www.acme.test": "check_failed"}


def test_fail_claim_stores_the_code(store):
    from conftest import prepare_execution_claim
    from backend.app.core import scan_execution
    scan_id = str(uuid.uuid4())
    store.scans.append({"id": scan_id, "org_id": ORG_A, "domain_id": DOM_A1, "status": "queued",
                        "stage_progress": {}, "current_stage": "queued", "created_at": "2026-10-30T00:00:00"})
    claim = prepare_execution_claim(store, scan_id, phase="local")
    scan_execution.fail_claim(claim, "ports: stage deadline reached")
    row = next(r for r in store.scans if r["id"] == scan_id)
    assert row["status"] == "failed" and row["failure_code"] == "timeout"
    assert row["error_message"] == "ports: stage deadline reached"
