"""Regressions for saturation, organization scope, and comparable history."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.risk.engine import compute_risk_score, finding_pillar, SCORE_MODEL
from conftest import ALICE, ORG_A, ORG_B

ASSESSMENT = {"scan_id": "latest", "status": "completed", "model": SCORE_MODEL}


def finding(severity="high", category="HTTP Headers", **kwargs):
    return {"title": "Example", "severity": severity, "category": category, "status": "open", **kwargs}


def score(findings):
    return compute_risk_score(findings, assessment=ASSESSMENT)


def test_resolving_findings_above_old_pillar_cap_improves_score():
    values = [score([finding() for _ in range(n)])["score"] for n in (8, 7, 6, 5, 4)]
    assert all(a < b for a, b in zip(values, values[1:]))
    assert values == [38.5, 41.7, 45.5, 50.0, 55.6]


def test_critical_nuclei_findings_cannot_hide_in_exposure_cap():
    one = score([finding("critical", "Nuclei Scan")])
    many = score([finding("critical", "Nuclei Scan") for _ in range(20)])
    assert one["score"] == 62.5
    assert many["score"] == 7.7
    assert many["grade"] == "F"
    assert many["risk_points"] == 1200


@pytest.mark.parametrize("evidence,expected", [
    ({"type": "http", "tags": ["sqli", "cve"]}, "Web & Apps"),
    ({"type": "ssl"}, "Encryption"),
    ({"type": "http", "tags": "tls,misconfig"}, "Encryption"),
    ({"type": "dns"}, "Network & DNS"),
    ({"type": "tcp"}, "Network & DNS"),
    ({"type": "http", "tags": ["exposure"]}, "Exposure"),
    ({}, "Web & Apps"),
])
def test_nuclei_category_uses_existing_evidence(evidence, expected):
    original = finding(category="Nuclei Scan", evidence=evidence)
    assert finding_pillar(original) == expected
    assert original["category"] == "Nuclei Scan"  # detector identity is preserved


def test_overall_risk_does_not_depend_on_category_or_query_order():
    findings = [finding(), finding("low"), finding("critical")]
    assert score(findings) == score(list(reversed(findings)))
    assert score(findings)["score"] == score([{**f, "category": "Exposure"} for f in findings])["score"]


def test_resolved_and_informational_findings_do_not_add_risk():
    findings = [finding(status="resolved"), finding("info")]
    assert score(findings)["score"] == 100
    assert score(findings)["risk_points"] == 0


def test_factors_keep_actual_finding_provenance():
    result = score([finding(scan_id="older-domain-scan", last_seen_at="2026-10-01T00:00:00Z")])
    assert result["factors"][0]["scan_id"] == "older-domain-scan"
    assert result["factors"][0]["assessed_at"] == "2026-10-01T00:00:00Z"


def test_seven_day_change_excludes_recent_legacy_domain_and_other_tenant_scores(client, store, auth_headers):
    now = datetime.now(timezone.utc)
    def snapshot(days, value, **extra):
        return {"org_id": ORG_A, "score": value, "created_at": (now - timedelta(days=days)).isoformat(),
                "model": SCORE_MODEL, "scope": "organization", **extra}
    store.snapshots = [
        snapshot(9, 20), snapshot(8, 40),  # most recent eligible baseline
        snapshot(7.5, 90, model="cyphward-risk-v1"),
        snapshot(7.4, 90, scope="domain"),
        snapshot(7.3, 90, org_id=ORG_B),
        snapshot(1, 99),  # too recent to represent seven days ago
    ]
    overview = client.get("/api/v1/overview", headers=auth_headers(ALICE)).json()
    dashboard = client.get("/api/v1/dashboard/security-score", headers=auth_headers(ALICE)).json()
    assert overview["trend"] == round(overview["score"] - 40, 1)
    assert dashboard["previous_score"] == 40
    assert dashboard["change"] == overview["trend"]
    assert dashboard["score"] == overview["score"]


def test_new_model_has_no_trend_until_comparable_history_exists(client, store, auth_headers):
    response = client.get("/api/v1/overview", headers=auth_headers(ALICE))
    assert response.status_code == 200
    assert response.json()["trend"] is None
    assert response.json()["trend_baseline_at"] is None


def test_resolving_finding_updates_live_score_without_another_scan(client, store, auth_headers):
    before = client.get("/api/v1/overview", headers=auth_headers(ALICE)).json()
    for row in store.findings:
        if row["org_id"] == ORG_A:
            row["status"] = "resolved"
    after = client.get("/api/v1/overview", headers=auth_headers(ALICE)).json()
    assert after["score"] > before["score"]
    assert after["score"] == 100
    assert after["counts"]["total_findings"] == 0
    assert after["assessment"]["scan_id"] == before["assessment"]["scan_id"]
