"""
Regression tests: trustworthy findings — the baseline diff must never treat
"not evaluated" as "clear" (review item "P1 — trustworthy findings").

Rules under test:
- A finding auto-resolves only when its detector completed for that exact
  host during this scan (per-host security-check success; nuclei attempted
  hosts with the nuclei stage completed).
- A detector that failed/skipped/wasn't attempted leaves findings open and
  records them as not evaluated (counted in the result, audit and notify).
- Finding identity is detector + rule/template id, not the mutable title:
  unknown detectors never auto-resolve, and normalize keeps same-titled
  findings from different detectors.
"""
import asyncio

import backend.app.workflows.inngest_workflow as wf
from conftest import DOM_A1, FINDING_A1, FINDING_A2, ORG_A, SCAN_A1
from shared.contracts import empty_stage_progress

NEW_SCAN = "51111111-0000-4000-8000-000000000099"
NUC_FINDING = "f6666666-0000-4000-8000-000000000006"
UNK_FINDING = "f5555555-0000-4000-8000-000000000005"

HOST = "www.acme.test"


def _add_scan(store, scan_id=NEW_SCAN):
    store.scans.append({
        "id": scan_id,
        "org_id": ORG_A,
        "domain_id": DOM_A1,
        "domain": "acme.test",
        "status": "queued",
        "current_stage": "queued",
        "stage_progress": empty_stage_progress(),
        "scan_type": "EXTERNAL_ASSESSMENT",
        "score": None,
        "started_at": None,
        "completed_at": None,
        "created_at": "2026-10-03T00:00:00",
        "claimed_by": None,
        "lease_expires_at": None,
        "error_message": None,
    })
    row = next(x for x in store.scans if x["id"] == scan_id)
    return scan_id, row


def _find(store, finding_id):
    return next(f for f in store.findings if f["id"] == finding_id)


def _obs(nuclei_findings=None, attempted_hosts=None):
    return {
        "discovery": {"discovered_hosts": [HOST]},
        "dns": {"dns_records": [
            {"hostname": HOST, "primary_ip": "198.51.100.10", "records": {}},
        ]},
        "http": {"http_probes": [
            {"hostname": HOST, "http_status": 200, "tls_info": {}},
        ]},
        "nuclei": {
            "nuclei_findings": nuclei_findings or [],
            "attempted_hosts": attempted_hosts if attempted_hosts is not None else [],
        },
    }


def _seed_nuclei_finding(store):
    store.findings.append({
        "id": NUC_FINDING, "org_id": ORG_A, "scan_id": SCAN_A1, "asset_id": "a1",
        "title": "Exposed Admin Panel", "description": "Nuclei found an exposed panel.",
        "severity": "high", "category": "Nuclei Scan", "status": "open",
        "evidence": {"template_id": "exposed-panel", "host": HOST},
        "remediation": "Restrict panel access.",
        "hostname": HOST, "resolved_at": None,
    })


def _seed_unknown_finding(store):
    store.findings.append({
        "id": UNK_FINDING, "org_id": ORG_A, "scan_id": SCAN_A1, "asset_id": "a1",
        "title": "Old Compliance Gap", "description": "Legacy check.",
        "severity": "low", "category": "Legacy Compliance", "status": "open",
        "evidence": {},
        "remediation": "Review manually.",
        "hostname": HOST, "resolved_at": None,
    })


def _finalize(store, monkeypatch, obs, sec_ok=True, nuclei_status="skipped"):
    sid, row = _add_scan(store)
    row["stage_progress"]["nuclei"] = {
        "status": nuclei_status, "items": 0, "duration_ms": 0,
    }
    monkeypatch.setattr(wf, "_load_observations", lambda scan_id: obs)

    async def fake_sec(*args, **kwargs):
        if not sec_ok:
            raise RuntimeError("checker exploded")
        return []

    monkeypatch.setattr(wf, "run_security_checks", fake_sec)

    def _no_ai():
        raise RuntimeError("no AI provider in tests")

    monkeypatch.setattr(wf, "get_ai_provider", _no_ai)
    return sid, asyncio.run(wf.finalize_scan(sid))


# ---------------------------------------------------------------------------
# coverage → resolution
# ---------------------------------------------------------------------------
def test_resolves_when_detector_covered_and_title_absent(store, monkeypatch):
    sid, result = _finalize(store, monkeypatch, _obs())

    assert result["status"] == "completed"
    assert result["resolved_findings"] == 1, "unobserved HSTS finding on a covered host resolves"
    assert result["not_evaluated_findings"] == 0
    assert _find(store, FINDING_A1)["status"] == "resolved"
    # different asset outside the scan scope is untouched
    assert _find(store, FINDING_A2)["status"] == "open"


def test_failed_security_check_keeps_finding_open_as_not_evaluated(store, monkeypatch):
    sid, result = _finalize(store, monkeypatch, _obs(), sec_ok=False)

    assert result["status"] == "completed", "a failed detector must not fail the scan"
    assert result["resolved_findings"] == 0
    assert result["not_evaluated_findings"] == 1, "failed detector = not evaluated, never clear"
    assert _find(store, FINDING_A1)["status"] == "open"

    bodies = [str(n) for n in store.notifications]
    assert any("not evaluated" in b for b in bodies), "notify must surface not-evaluated count"

    # The completed scan and its snapshot must retain ALL organization risk,
    # including an unchecked finding and another asset outside this scan.
    from backend.app.api.overview import get_overview
    overview = get_overview(store.organizations[ORG_A])
    completed = next(row for row in store.scans if row["id"] == sid)
    snapshot = store.snapshots[-1]
    assert completed["score"] == overview["score"] == snapshot["score"]
    assert completed["score"] < 100
    assert snapshot["scope"] == "organization"
    assert snapshot["domain_id"] is None
    assert snapshot["risk_points"] == overview["risk_points"]


def test_nuclei_attempted_host_resolves_finding(store, monkeypatch):
    _seed_nuclei_finding(store)
    sid, result = _finalize(
        store, monkeypatch, _obs(attempted_hosts=[HOST]), nuclei_status="completed",
    )

    assert result["resolved_findings"] == 2, "both covered detectors resolve their findings"
    assert result["not_evaluated_findings"] == 0
    assert _find(store, FINDING_A1)["status"] == "resolved"
    assert _find(store, NUC_FINDING)["status"] == "resolved"


def test_nuclei_not_attempted_keeps_finding_open(store, monkeypatch):
    _seed_nuclei_finding(store)
    sid, result = _finalize(
        store, monkeypatch, _obs(attempted_hosts=["other.test"]), nuclei_status="completed",
    )

    assert _find(store, NUC_FINDING)["status"] == "open", "nuclei never attempted this host"
    assert result["not_evaluated_findings"] == 1
    # the security-check finding on the same host still resolves (its detector ran)
    assert _find(store, FINDING_A1)["status"] == "resolved"
    assert result["resolved_findings"] == 1


def test_failed_nuclei_stage_keeps_findings_open(store, monkeypatch):
    _seed_nuclei_finding(store)
    sid, result = _finalize(
        store, monkeypatch, _obs(attempted_hosts=[HOST]), nuclei_status="failed",
    )

    assert _find(store, NUC_FINDING)["status"] == "open"
    assert result["not_evaluated_findings"] == 1


def test_unknown_detector_never_auto_resolves(store, monkeypatch):
    _seed_unknown_finding(store)
    sid, result = _finalize(
        store, monkeypatch, _obs(attempted_hosts=[HOST]), nuclei_status="completed",
    )

    unk = _find(store, UNK_FINDING)
    assert unk["status"] == "open", "an unknown detector can never prove absence"
    assert result["not_evaluated_findings"] == 1
    assert result["resolved_findings"] == 1, "known detectors on the same asset still resolve"


# ---------------------------------------------------------------------------
# detector identity (not mutable titles)
# ---------------------------------------------------------------------------
def test_normalizer_keeps_same_title_from_different_detectors():
    from backend.app.scanner.normalizer import normalize_findings

    raw = [
        {"title": "Exposed Admin Panel", "severity": "high",
         "category": "Nuclei Scan", "evidence": {"template_id": "exposed-panel"}},
        {"title": "Exposed Admin Panel", "severity": "medium",
         "category": "Exposure", "evidence": {}},
    ]
    out = normalize_findings(raw, asset_id="asset-1", org_id="org-1", scan_id="scan-1")

    assert len(out) == 2, "same title, different detectors = two findings"
    cats = sorted(f["category"] for f in out)
    assert cats == ["Exposure", "Nuclei Scan"]


def test_normalizer_dedupes_nuclei_template_across_titles():
    from backend.app.scanner.normalizer import normalize_findings

    raw = [
        {"title": "Panel Detected", "severity": "high",
         "category": "Nuclei Scan", "evidence": {"template_id": "exposed-panel"}},
        {"title": "Panel Detected (duplicate)", "severity": "high",
         "category": "Nuclei Scan", "evidence": {"template_id": "exposed-panel"}},
    ]
    out = normalize_findings(raw, asset_id="asset-1", org_id="org-1", scan_id="scan-1")

    assert len(out) == 1, "one template id = one finding regardless of display title"


def test_existing_title_identity_survives_for_static_check_titles():
    """Stored findings keyed by (detector, static title) still match observed ones."""
    from backend.app.scanner.detectors import detector_key

    stored = detector_key("HTTP Headers", {"header": "missing"}, "HSTS Missing")
    observed = detector_key("HTTP Headers", {}, "HSTS Missing")
    assert stored == observed == "security_checks:HSTS Missing"
    assert detector_key("Nuclei Scan", {"template_id": "x"}, "Any Title") == "nuclei:x"
