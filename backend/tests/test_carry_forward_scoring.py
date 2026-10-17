"""Carry-forward scoring: a failed, partial or timed-out stage never removes an open finding.

Risk points come from open findings. A finding auto-resolves only when its detector completed
for that host in this scan, so a stage that failed, timed out or answered partially must leave
its findings open. These tests check that end to end through finalize_scan, including the
score the organisation would show afterwards.
"""
import pytest

import backend.app.core.scan_execution as scan_execution
import backend.app.risk.engine as engine
from backend.tests.conftest import FINDING_A1, ORG_A
from backend.tests.test_baseline_coverage import (
    NUC_FINDING, _finalize, _find, _obs, _seed_nuclei_finding, HOST,
)

APEX = "acme.test"
APEX_ASSET = "a0"
DMARC_FINDING = "f7777777-0000-4000-8000-000000000007"


@pytest.fixture(autouse=True)
def _isolated(store, monkeypatch):
    """Drop the HSTS finding, whose detector legitimately completes and resolves in every default scan,
    and skip the compliance-evidence write (not part of scoring) that the fake store cannot run."""
    removed = [f for f in store.findings if f["id"] == FINDING_A1]
    store.findings[:] = [f for f in store.findings if f["id"] != FINDING_A1]
    monkeypatch.setattr(scan_execution, "_insert_compliance_evidence", lambda *a, **k: None)
    return removed


def _open_risk_points(store):
    return sum(engine.RISK_WEIGHTS.get((f.get("severity") or "medium").lower(), 5)
               for f in store.findings
               if f["org_id"] == ORG_A and f.get("status") != "resolved")


def _apex_dns_partial(obs):
    """Apex DNS answered everything except DMARC, so the DMARC finding cannot be re-evaluated."""
    obs["dns"]["dns_records"].append({
        "hostname": APEX, "primary_ip": "198.51.100.11", "records": {
            "query_coverage": {"version": 1, "queries": {
                "A": {"status": "answered", "name": APEX, "record_type": "A"},
                "TXT": {"status": "answered", "name": APEX, "record_type": "TXT"},
                # DMARC query never completed: no status for it.
            }},
        },
    })
    return obs


def _seed_apex_dmarc(store):
    store.assets.append({"id": APEX_ASSET, "org_id": ORG_A, "hostname": APEX})
    store.findings.append({
        "id": DMARC_FINDING, "org_id": ORG_A, "scan_id": "51111111-0000-4000-8000-000000000001",
        "asset_id": APEX_ASSET, "title": "Permissive Email DMARC Policy (p=none)",
        "description": "DMARC is set to monitor only.", "severity": "high",
        "category": "DNS & Email Security", "status": "open", "evidence": {},
        "remediation": "Move DMARC to quarantine or reject.", "hostname": APEX,
        "resolved_at": None,
    })


def test_partial_dns_keeps_the_dmarc_finding_open(store, monkeypatch):
    _seed_apex_dmarc(store)
    before = _open_risk_points(store)
    _, result = _finalize(store, monkeypatch, _apex_dns_partial(_obs()))

    assert _find(store, DMARC_FINDING)["status"] == "open"
    assert result["not_evaluated_findings"] >= 1, "a DMARC query that never completed is not a clean result"
    assert _open_risk_points(store) >= before


def test_partial_dns_does_not_lower_the_organisation_score(store, monkeypatch):
    _seed_apex_dmarc(store)
    before = _open_risk_points(store)
    _finalize(store, monkeypatch, _apex_dns_partial(_obs()))
    snapshot = store.snapshots[-1]
    assert snapshot["scope"] == "organization"
    assert snapshot["risk_points"] >= before


def test_failed_nuclei_stage_keeps_every_template_finding_and_its_points(store, monkeypatch):
    _seed_nuclei_finding(store)
    before = _open_risk_points(store)
    _finalize(store, monkeypatch, _obs(attempted_hosts=[HOST]), nuclei_status="failed")

    assert _find(store, NUC_FINDING)["status"] == "open"
    assert _open_risk_points(store) >= before
    assert store.snapshots[-1]["risk_points"] >= before


def test_timed_out_nuclei_stage_keeps_its_findings_open(store, monkeypatch):
    _seed_nuclei_finding(store)
    _finalize(store, monkeypatch, _obs(attempted_hosts=[HOST]), nuclei_status="timeout")
    assert _find(store, NUC_FINDING)["status"] == "open"


def test_unreachable_http_stage_keeps_header_findings_and_points(store, monkeypatch, _isolated):
    store.findings.extend(_isolated)  # the HSTS finding is the one an unreachable HTTP stage must protect
    before = _open_risk_points(store)
    obs = _obs()
    obs["http"]["http_probes"][0]["http_status"] = None
    _finalize(store, monkeypatch, obs)

    assert _find(store, "f1111111-0000-4000-8000-000000000001")["status"] == "open"
    assert store.snapshots[-1]["risk_points"] >= before


def test_failed_security_checks_do_not_lower_the_score(store, monkeypatch):
    before = _open_risk_points(store)
    _finalize(store, monkeypatch, _obs(), sec_ok=False)
    assert store.snapshots[-1]["risk_points"] >= before


def test_control_complete_dmarc_answer_resolves_the_same_finding(store, monkeypatch):
    """Positive control: the same setup resolves once DMARC is actually answered, so the partial-DNS result above is the cause."""
    _seed_apex_dmarc(store)
    obs = _apex_dns_partial(_obs())
    obs["dns"]["dns_records"][-1]["records"]["query_coverage"]["queries"]["DMARC"] = {
        "status": "answered", "name": f"_dmarc.{APEX}", "record_type": "TXT",
    }
    _finalize(store, monkeypatch, obs)
    assert _find(store, DMARC_FINDING)["status"] == "resolved"
