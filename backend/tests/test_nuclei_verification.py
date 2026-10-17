"""Verified resolution of Nuclei findings.

A scan run proves matches and process completion, never that one template was clear. A finding resolves
only when the worker reran its exact template on that host and Nuclei left a receipt (a non-match record)
for a template that sends a single request. Nuclei prints one record per template run, for the last
request, so a multi-request template can never be proven this way.
"""
import asyncio
import json
import textwrap

import pytest

import backend.app.core.scan_execution as scan_execution
from backend.app.scanner import nuclei_runner
from backend.tests.conftest import FINDING_A1, ORG_A
from backend.tests.test_baseline_coverage import (
    HOST, NUC_FINDING, _find, _finalize, _obs, _seed_nuclei_finding,
)

TEMPLATE = "exposed-panel"


def _receipt(template=TEMPLATE, host=HOST, status=False):
    return json.dumps({"template-id": template, "host": host, "matcher-status": status, "info": {}}) + "\n"


# ── Receipts ────────────────────────────────────────────────────────────────


def test_only_non_match_records_for_this_template_and_host_count():
    out = (_receipt() + _receipt(template="other") + _receipt(host="evil.example")
           + _receipt(status=True) + "not json\n" + json.dumps({"template-id": TEMPLATE, "host": HOST}) + "\n").encode()
    assert nuclei_runner.count_receipts(out, HOST, TEMPLATE) == 1
    assert nuclei_runner.count_receipts(b"", HOST, TEMPLATE) == 0


def test_host_comparison_ignores_case_and_a_trailing_dot():
    assert nuclei_runner.count_receipts(_receipt(host="WWW.Acme.Test.").encode(), HOST, TEMPLATE) == 1


# ── Counting a template's requests from the pinned set ─────────────────────


@pytest.fixture
def templates(tmp_path, monkeypatch):
    http = tmp_path / "http" / "misc"
    http.mkdir(parents=True)

    def write(name, body):
        (http / f"{name}.yaml").write_text(textwrap.dedent(body))

    write("one", """
        id: one-request
        info: {name: One, severity: high}
        http:
          - method: GET
            path: ["{{BaseURL}}/a"]
    """)
    write("two", """
        id: two-requests
        info: {name: Two, severity: high}
        http:
          - method: GET
            path: ["{{BaseURL}}/a", "{{BaseURL}}/b"]
    """)
    write("payload", """
        id: payload-template
        info: {name: Payload, severity: high}
        http:
          - method: GET
            path: ["{{BaseURL}}/{{p}}"]
            payloads: {p: [a, b]}
    """)
    write("dns", """
        id: dns-template
        info: {name: Dns, severity: high}
        dns:
          - name: "{{FQDN}}"
            type: TXT
    """)
    monkeypatch.setattr(nuclei_runner, "TEMPLATES_DIR", tmp_path)
    nuclei_runner._template_index.cache_clear()
    yield
    nuclei_runner._template_index.cache_clear()


def test_request_counts(templates):
    count = nuclei_runner.template_request_count
    assert count("one-request") == 1
    assert count("two-requests") == 2
    assert count("payload-template") is None, "a variable number of requests cannot be counted"
    assert count("dns-template") is None, "only HTTP templates are countable"
    assert count("not-in-the-set") is None


# ── The exact-template rerun ────────────────────────────────────────────────


class _Process:
    def __init__(self, stdout, code=0):
        self.stdout, self.returncode = stdout, code

    async def communicate(self):
        return self.stdout, b""

    async def wait(self):
        return self.returncode


def _rerun(monkeypatch, stdout, expected):
    async def spawn(*args, **kwargs):
        return _Process(stdout)

    monkeypatch.setattr(nuclei_runner.ip_guard, "resolve_connect_ip", lambda host: "93.184.216.34")
    monkeypatch.setattr(nuclei_runner.shutil, "which", lambda name: "/usr/bin/nuclei")
    monkeypatch.setattr(nuclei_runner.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(nuclei_runner, "template_request_count", lambda template_id: expected)
    return asyncio.run(nuclei_runner.run_nuclei_template(HOST, TEMPLATE))


def test_a_single_request_template_with_a_receipt_is_proven_clean(monkeypatch):
    result = _rerun(monkeypatch, _receipt().encode(), expected=1)
    assert result["proven_clean"] is True and result["receipts"] == 1


def test_no_receipt_is_not_proof(monkeypatch):
    assert _rerun(monkeypatch, b"", expected=1)["proven_clean"] is False


def test_a_multi_request_template_is_never_proven(monkeypatch):
    assert _rerun(monkeypatch, _receipt().encode(), expected=2)["proven_clean"] is False


def test_an_uncountable_template_is_never_proven(monkeypatch):
    assert _rerun(monkeypatch, _receipt().encode(), expected=None)["proven_clean"] is False


def test_a_match_means_the_finding_still_reproduces(monkeypatch):
    match = json.dumps({"template-id": TEMPLATE, "host": HOST, "info": {"name": "Exposed", "severity": "high"},
                        "matched-at": f"https://{HOST}/"}) + "\n"
    result = _rerun(monkeypatch, match.encode(), expected=1)
    assert result["ok"] is True and result["proven_clean"] is False


def test_the_rerun_asks_nuclei_for_receipts(monkeypatch):
    captured = []

    async def spawn(*args, **kwargs):
        captured.append(list(args))
        return _Process(b"")

    monkeypatch.setattr(nuclei_runner.ip_guard, "resolve_connect_ip", lambda host: "93.184.216.34")
    monkeypatch.setattr(nuclei_runner.shutil, "which", lambda name: "/usr/bin/nuclei")
    monkeypatch.setattr(nuclei_runner.asyncio, "create_subprocess_exec", spawn)
    asyncio.run(nuclei_runner.run_nuclei_template(HOST, TEMPLATE))
    assert "-matcher-status" in captured[0]


# ── The worker verifies each open finding ──────────────────────────────────


def test_verify_open_findings_reports_what_is_proven_and_why_the_rest_is_not(monkeypatch):
    results = {
        "a": {"ok": False, "proven_clean": True, "receipts": 1, "expected_receipts": 1},
        "b": {"ok": True, "proven_clean": False},
        "c": {"ok": False, "proven_clean": False, "receipts": 1, "expected_receipts": 2},
        "d": {"ok": False, "error": "rerun timed out"},
        "e": {"ok": False, "proven_clean": False, "receipts": 0, "expected_receipts": 1},
    }

    async def fake(host, template_id, timeout=60):
        return results[template_id]

    monkeypatch.setattr(nuclei_runner, "run_nuclei_template", fake)
    out = asyncio.run(nuclei_runner.verify_open_findings([{"host": HOST, "template_id": t} for t in results]))
    assert [c["template_id"] for c in out["clean"]] == ["a"]
    reasons = {u["template_id"]: u["reason"] for u in out["unverified"]}
    assert reasons == {"b": "still_reproduces", "c": "template_not_provable",
                       "d": "no_receipt_or_rerun_failed", "e": "no_receipt_or_rerun_failed"}


def test_verify_open_findings_stops_when_the_stage_has_no_time_left(monkeypatch):
    from shared.scan_budget import ReconBudget
    calls = []

    async def fake(host, template_id, timeout=60):
        calls.append(template_id)
        return {"ok": False, "proven_clean": True, "receipts": 1, "expected_receipts": 1}

    monkeypatch.setattr(nuclei_runner, "run_nuclei_template", fake)

    async def run():
        return await ReconBudget(1000, 5).run(
            lambda: nuclei_runner.verify_open_findings([{"host": HOST, "template_id": "a"}]))

    out = asyncio.run(run())
    assert calls == [] and out["unverified"][0]["reason"] == "no_time_left"


# ── Core resolves only what the worker proved ──────────────────────────────


@pytest.fixture(autouse=True)
def _isolated(store, monkeypatch):
    store.findings[:] = [f for f in store.findings if f["id"] != FINDING_A1]
    monkeypatch.setattr(scan_execution, "_insert_compliance_evidence", lambda *a, **k: None)


def _with_verification(verification):
    obs = _obs(attempted_hosts=[HOST])
    if verification is not None:
        obs["nuclei"]["verification"] = verification
    return obs


def test_a_verified_clean_receipt_resolves_the_nuclei_finding(store, monkeypatch):
    _seed_nuclei_finding(store)
    _finalize(store, monkeypatch, _with_verification({"clean": [{"host": HOST, "template_id": TEMPLATE}]}),
              nuclei_status="completed")
    assert _find(store, NUC_FINDING)["status"] == "resolved"


def test_the_match_is_case_insensitive_on_the_host(store, monkeypatch):
    _seed_nuclei_finding(store)
    _finalize(store, monkeypatch, _with_verification({"clean": [{"host": HOST.upper(), "template_id": TEMPLATE}]}),
              nuclei_status="completed")
    assert _find(store, NUC_FINDING)["status"] == "resolved"


@pytest.mark.parametrize("verification", [
    None,
    {"clean": []},
    {"clean": [], "unverified": [{"host": HOST, "template_id": TEMPLATE, "reason": "template_not_provable"}]},
    {"clean": [{"host": "other.acme.test", "template_id": TEMPLATE}]},
    {"clean": [{"host": HOST, "template_id": "another-template"}]},
    {"clean": ["not a dict", 7]},
], ids=["no-verification", "nothing-proven", "unverified-listed", "other-host", "other-template", "garbage"])
def test_anything_less_leaves_the_finding_open(store, monkeypatch, verification):
    _seed_nuclei_finding(store)
    _finalize(store, monkeypatch, _with_verification(verification), nuclei_status="completed")
    assert _find(store, NUC_FINDING)["status"] == "open"


def test_a_failed_nuclei_stage_with_no_receipt_never_resolves(store, monkeypatch):
    _seed_nuclei_finding(store)
    _finalize(store, monkeypatch, _with_verification(None), nuclei_status="failed")
    assert _find(store, NUC_FINDING)["status"] == "open"
