"""Numeric scores need evaluation evidence, not just a completed job."""
import asyncio

import pytest

from backend.app.risk.coverage import assessment_coverage
from backend.app.risk.engine import compute_risk_score, SCORE_MODEL
from backend.app.ai.heuristic_provider import HeuristicAIProvider


def assessment(state="partial", evaluated=1):
    return {"scan_id": "new-scan", "status": "completed", "model": SCORE_MODEL,
            "coverage": {"version": 1, "state": state, "evaluated_checks": evaluated}}


@pytest.mark.parametrize("data", [
    {"scan_id": "legacy", "status": "completed"},
    assessment("unassessed", 0), assessment("partial", 0), assessment("unknown", 4),
    {**assessment(), "status": "failed"},
])
def test_legacy_failed_or_zero_evaluated_assessment_has_no_score(data):
    result = compute_risk_score([], assessment=data)
    assert result["score"] is None
    assert result["grade"] is None
    assert not result["assessed"]
    assert result["subscores"] == []
    assert not any(factor["type"] == "positive" for factor in result["factors"])
    assert result["assessment"]["scan_id"] == data["scan_id"]


def test_partial_no_findings_is_not_a_clean_100():
    result = compute_risk_score([], assessment=assessment())
    assert result["score"] is None
    assert result["posture_label"] == "Partial assessment"
    assert result["risk_points"] == 0


def test_partial_known_risk_has_no_grade_or_unchecked_category_health():
    result = compute_risk_score([{"title": "Known issue", "severity": "high", "status": "open"}], assessment=assessment())
    assert result["score"] == 83.3
    assert result["risk_points"] == 20
    assert result["grade"] is None
    assert result["status_color"] == "warn"
    assert result["subscores"] == []
    assert result["posture_label"] == "Partial assessment"


def test_no_evidence_preserves_known_findings_without_a_numeric_score():
    result = compute_risk_score([{"title": "Existing risk", "severity": "critical"}], assessment=assessment("unassessed", 0))
    assert result["score"] is None
    assert result["counts"]["critical"] == 1
    assert result["risk_points"] == 60
    assert result["factors"][0]["label"] == "Existing risk"


def test_inventory_or_process_success_does_not_make_evaluated_security_checks():
    observations = {"dns": {"dns_records": [{"hostname": "acme.test", "primary_ip": "8.8.8.8", "records": {}}]},
                    "nuclei": {"successful_hosts": ["acme.test"], "nuclei_findings": []}}
    assert assessment_coverage("acme.test", observations, {"acme.test"})["evaluated_checks"] == 0


def test_failed_checker_or_blocked_redirect_cannot_supply_header_evidence():
    observations = {"http": {"http_probes": [{"hostname": "acme.test", "http_status": 200}]}}
    assert assessment_coverage("acme.test", observations, set())["evaluated_checks"] == 0
    observations["http"]["http_probes"][0]["error"] = "redirect blocked"
    assert assessment_coverage("acme.test", observations, {"acme.test"})["evaluated_checks"] == 0


def test_evaluated_header_group_yields_partial_scope_not_complete():
    observations = {"http": {"http_probes": [{"hostname": "acme.test", "http_status": 200}]}}
    result = assessment_coverage("acme.test", observations, {"acme.test"})
    assert result["state"] == "partial"
    assert result["evaluated_checks"] == 1
    assert result["requested_checks"] is None


def test_ai_summary_does_not_invent_strengths_or_missing_first_scan():
    provider = HeuristicAIProvider()
    score = compute_risk_score([], assessment=assessment())
    summary = asyncio.run(provider.generate_executive_summary("Acme", score, []))
    assert summary["score"] is None
    assert summary["key_strengths"] == []
    assert summary["critical_action_items"] == []
    assert "insufficient evaluated evidence" in summary["board_summary"]
    assert "not completed" not in summary["board_summary"]
    assert "TLS 1.3" not in summary["board_summary"]
