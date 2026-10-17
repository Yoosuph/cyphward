"""Declared-scope copy: a score is only ever described as valid within the declared scope.

Covers the executive email (mailer), the LLM summary gate (llm_provider) and the
report summary keys (api/reports). Nothing here sends mail or calls a real LLM.
"""
import asyncio
import json

import pytest

from backend.app.ai.llm_provider import CloudLLMProvider
from backend.app.api import reports as reports_api
from backend.app.snapshots import builder as snapshot_builder
from backend.app.risk.check_set import NUCLEI_LINE
from backend.app.services.mailer import generate_executive_report_html

from conftest import ALICE, DOM_A1, ORG_A

COVERAGE_LABEL = "example.com: all declared checks complete on 3 hosts"
DOMAIN_LINE = "example.com: complete · other.ng: not scanned"
GRADED_SCOPE = "Within declared scope"
NO_COMPLETE_CLAIM = "does not establish complete coverage"


def _graded_html(**overrides):
    kwargs = dict(
        org_name="Acme Traders", domain="example.com", score=82, grade="B",
        posture_label="Good", assets_count=3, critical_count=0, high_count=1, medium_count=2,
        scope_label=GRADED_SCOPE, coverage_label=COVERAGE_LABEL,
        domain_line=DOMAIN_LINE, nuclei_line=NUCLEI_LINE,
    )
    kwargs.update(overrides)
    return generate_executive_report_html(**kwargs)


# --- Executive email ----------------------------------------------------------

def test_graded_complete_email_states_declared_scope_and_lines():
    html = _graded_html()
    assert "within declared scope" in html
    assert COVERAGE_LABEL in html
    assert DOMAIN_LINE in html
    assert NUCLEI_LINE in html
    assert "not a statement about security beyond the declared checks" in html
    assert NO_COMPLETE_CLAIM not in html


def test_ungraded_email_keeps_coverage_wording_and_shows_domain_line():
    html = generate_executive_report_html(
        org_name="Acme Traders", domain="example.com", score=74, grade=None,
        posture_label="Partial assessment", assets_count=3, critical_count=1,
        high_count=0, medium_count=0,
        coverage_label="example.com: 4 of 5 declared checks conclusive",
        domain_line=DOMAIN_LINE, nuclei_line=NUCLEI_LINE,
    )
    assert NO_COMPLETE_CLAIM in html
    assert DOMAIN_LINE in html
    assert "within declared scope" not in html


def test_not_assessed_email_keeps_insufficient_evidence_wording():
    html = generate_executive_report_html(
        org_name="Acme Traders", domain="example.com", score=None, grade=None,
        posture_label="", domain_line=DOMAIN_LINE,
    )
    assert "does not yet have sufficient evaluated evidence" in html
    assert "missing evidence is not proof of security" in html
    assert "Insufficient assessment evidence" in html
    assert DOMAIN_LINE in html
    assert "within declared scope" not in html


def test_scope_block_absent_when_no_scope_lines_given():
    html = generate_executive_report_html(
        org_name="Acme Traders", domain="example.com", score=82, grade="B",
        posture_label="Good",
    )
    assert "Known-CVE templates" not in html
    assert "within declared scope" not in html
    assert NO_COMPLETE_CLAIM in html  # legacy graded wording without a scope label


def test_new_scope_text_is_html_escaped():
    hostile_domain_line = "shop.example.com: <b>complete</b> & <script>x</script>"
    html = _graded_html(domain_line=hostile_domain_line,
                        coverage_label="<i>example.com</i>: all declared checks complete on 1 host")
    assert "&lt;b&gt;complete&lt;/b&gt;" in html
    assert "&amp; &lt;script&gt;x&lt;/script&gt;" in html
    assert "&lt;i&gt;example.com&lt;/i&gt;" in html
    assert "<b>complete</b>" not in html
    assert "<script>x</script>" not in html


# --- LLM summary gate ---------------------------------------------------------

SCOPE_SENTENCE = "covers only the declared checks"


def _score_data(**overrides):
    data = {
        "score": 82,
        "grade": "B",
        "posture_label": "Good",
        "scope_label": GRADED_SCOPE,
        "domain_coverage": [{"domain": "example.com", "state": "complete"}],
        "domain_coverage_line": "example.com: complete",
        "assessment": {"coverage": {
            "state": "complete", "label": COVERAGE_LABEL,
            "nuclei": {"label": NUCLEI_LINE},
        }},
    }
    data.update(overrides)
    return data


@pytest.fixture
def llm_calls(monkeypatch):
    """A provider with keys set and _call_llm replaced by a recorder (no network)."""
    calls = []

    async def fake_call_llm(self, system_prompt, user_prompt):
        calls.append((system_prompt, user_prompt))
        return {"executive_headline": "LLM headline", "board_summary": "LLM summary"}

    monkeypatch.setattr(CloudLLMProvider, "_call_llm", fake_call_llm)
    provider = CloudLLMProvider()
    provider.gemini_key = "test-gemini-key"
    provider.openai_key = None
    return provider, calls


def _summarise(provider, score_data):
    return asyncio.run(provider.generate_executive_summary("Acme Traders", score_data, []))


def test_llm_gate_graded_complete_uses_model_with_scope_prompts(llm_calls):
    provider, calls = llm_calls
    result = _summarise(provider, _score_data())

    assert len(calls) == 1
    system_prompt, user_prompt = calls[0]
    assert SCOPE_SENTENCE in system_prompt
    assert "known-CVE templates" in system_prompt
    assert GRADED_SCOPE in user_prompt
    assert COVERAGE_LABEL in user_prompt
    assert "example.com: complete" in user_prompt
    assert NUCLEI_LINE in user_prompt
    assert result == {"executive_headline": "LLM headline", "board_summary": "LLM summary"}


def test_llm_gate_ungraded_complete_uses_heuristic(llm_calls):
    provider, calls = llm_calls
    result = _summarise(provider, _score_data(grade=None, scope_label=None))

    assert calls == []
    assert "executive_headline" in result
    assert result["score"] == 82


def test_llm_gate_grade_none_with_scope_still_uses_heuristic(llm_calls):
    provider, calls = llm_calls
    _summarise(provider, _score_data(grade=None))
    assert calls == []


def test_llm_gate_partial_coverage_uses_heuristic(llm_calls):
    provider, calls = llm_calls
    partial = _score_data(scope_label=None, assessment={"coverage": {
        "state": "partial", "label": "example.com: 4 of 5 declared checks conclusive",
        "nuclei": {"label": NUCLEI_LINE},
    }})
    result = _summarise(provider, partial)

    assert calls == []
    assert "executive_headline" in result


def test_llm_gate_partial_with_scope_label_still_uses_heuristic(llm_calls):
    provider, calls = llm_calls
    _summarise(provider, _score_data(assessment={"coverage": {"state": "partial"}}))
    assert calls == []


# --- Report summary keys ------------------------------------------------------

def _fake_scoring(version):
    coverage = {"version": version, "state": "complete", "label": COVERAGE_LABEL,
                "nuclei": {"label": NUCLEI_LINE}}
    return {
        "score": 82, "grade": "B", "posture_label": "Good", "assessed": True,
        "model": "test-model", "scope": {"domains": 1},
        "assessment": {"completed_at": "2026-10-01T00:00:00", "coverage": coverage},
        "scope_label": GRADED_SCOPE,
        "domain_coverage": [{"domain": "example.com", "state": "complete"},
                            {"domain": "other.ng", "state": "not_scanned"}],
        "domain_coverage_line": DOMAIN_LINE,
    }


def _create_report(monkeypatch, client, auth_headers, store, scoring):
    captured = {}
    real_render = reports_api.generate_executive_report_html

    def capturing_render(**kwargs):
        captured.update(kwargs)
        return real_render(**kwargs)

    monkeypatch.setattr(snapshot_builder, "compute_risk_score", lambda findings, assessment=None: scoring)
    monkeypatch.setattr(reports_api, "generate_executive_report_html", capturing_render)
    resp = client.post("/api/v1/reports", json={"domain_id": DOM_A1},
                       headers=auth_headers(ALICE, email="alice@acme.test", org=ORG_A))
    assert resp.status_code == 201
    return json.loads(store.reports[-1]["summary"]), captured


def test_report_summary_carries_declared_scope_keys(monkeypatch, client, auth_headers, store):
    summary, captured = _create_report(monkeypatch, client, auth_headers, store, _fake_scoring(2))

    assert summary["scope_label"] == GRADED_SCOPE
    assert summary["coverage_label"] == COVERAGE_LABEL
    assert summary["domain_coverage_line"] == DOMAIN_LINE
    assert summary["domain_coverage"] == [{"domain": "example.com", "state": "complete"},
                                          {"domain": "other.ng", "state": "not_scanned"}]
    assert summary["nuclei_line"] == NUCLEI_LINE
    assert captured["scope_label"] == GRADED_SCOPE
    assert captured["coverage_label"] == COVERAGE_LABEL
    assert captured["domain_line"] == DOMAIN_LINE
    assert captured["nuclei_line"] == NUCLEI_LINE


def test_report_summary_without_v2_coverage_has_no_nuclei_line(monkeypatch, client, auth_headers, store):
    scoring = _fake_scoring(1)
    scoring.pop("scope_label")
    scoring.pop("domain_coverage_line")
    scoring.pop("domain_coverage")
    summary, _ = _create_report(monkeypatch, client, auth_headers, store, scoring)

    assert summary["scope_label"] is None
    assert summary["domain_coverage"] == []
    assert summary["domain_coverage_line"] == ""
    assert summary["nuclei_line"] is None
