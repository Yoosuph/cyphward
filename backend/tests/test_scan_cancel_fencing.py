"""
Regression tests: a cancelled scan must never be resurrected, continued or
finalized (review item "P1 — trustworthy scan history").

Covers:
- cancel-before-dispatch  (recon entry CAS refuses a cancelled row)
- cancel-during-scan      (stage-boundary checks stop the pipeline promptly;
                           stage writes are fenced at the SQL level)
- cancel-during-finalize  (entry CAS, mid-finalize boundary, completion CAS)
- cancel endpoint         (conditional transition, idempotent 400s)
"""
import asyncio

import pytest

import backend.app.workflows.inngest_workflow as wf
from conftest import ALICE, DOM_A1, ORG_A, SCAN_A1
from shared.contracts import empty_stage_progress

NEW_SCAN = "51111111-0000-4000-8000-000000000099"


def _add_scan(store, status="queued", scan_id=NEW_SCAN):
    store.scans.append({
        "id": scan_id,
        "org_id": ORG_A,
        "domain_id": DOM_A1,
        "domain": "acme.test",
        "status": status,
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
    return scan_id


def _row(store, scan_id):
    return next(x for x in store.scans if x["id"] == scan_id)


# ---------------------------------------------------------------------------
# cancel-before-dispatch
# ---------------------------------------------------------------------------
def test_cancelled_scan_never_resurrected_by_dispatch(store, monkeypatch):
    sid = _add_scan(store, status="cancelled")
    ran = []

    async def discover(domain):
        ran.append(domain)
        return []

    monkeypatch.setattr(wf, "discover_subdomains", discover)

    result = asyncio.run(wf.execute_recon_local(sid))

    assert result == {"scan_id": sid, "cancelled": True}
    assert ran == [], "discovery must not run for a cancelled scan"
    row = _row(store, sid)
    assert row["status"] == "cancelled"
    assert row["current_stage"] == "queued", "entry CAS must not have set running/discovery"


def test_finalize_refuses_cancelled_scan(store, monkeypatch):
    sid = _add_scan(store, status="cancelled")
    sec_calls = []

    async def fake_sec(*args, **kwargs):
        sec_calls.append(1)
        return []

    monkeypatch.setattr(wf, "run_security_checks", fake_sec)

    result = asyncio.run(wf.finalize_scan(sid))

    assert result["status"] == "cancelled"
    assert sec_calls == [], "security checks must not run for a cancelled scan"
    assert _row(store, sid)["status"] == "cancelled"


def test_pipeline_skips_finalize_when_cancelled_before_dispatch(store, monkeypatch):
    sid = _add_scan(store, status="cancelled")
    fin_calls = []

    async def fake_fin(scan_id):
        fin_calls.append(scan_id)
        return {}

    monkeypatch.setattr(wf, "finalize_scan", fake_fin)

    result = asyncio.run(wf.execute_scan_pipeline(sid))

    assert result.get("cancelled") is True
    assert fin_calls == []


# ---------------------------------------------------------------------------
# cancel-during-scan
# ---------------------------------------------------------------------------
def test_cancel_during_scan_stops_before_next_stage(store, monkeypatch):
    sid = _add_scan(store, status="queued")
    dns_calls = []

    async def discover(domain):
        # user cancels while discovery is in flight
        _row(store, sid)["status"] = "cancelled"
        return ["www.acme.test", "mail.acme.test"]

    async def resolve(host):
        dns_calls.append(host)
        return {"hostname": host, "primary_ip": "198.51.100.10", "records": {}}

    monkeypatch.setattr(wf, "discover_subdomains", discover)
    monkeypatch.setattr(wf, "resolve_host_dns", resolve)

    result = asyncio.run(wf.execute_recon_local(sid))

    assert result.get("cancelled") is True
    assert dns_calls == [], "DNS stage must not start after cancellation"
    row = _row(store, sid)
    assert row["status"] == "cancelled"
    assert row["current_stage"] == "discovery", "fenced progress write must not advance the stage"


def test_pipeline_skips_finalize_when_cancelled_during_recon(store, monkeypatch):
    sid = _add_scan(store, status="queued")
    fin_calls = []

    async def discover(domain):
        _row(store, sid)["status"] = "cancelled"
        return ["www.acme.test"]

    async def fake_fin(scan_id):
        fin_calls.append(scan_id)
        return {}

    monkeypatch.setattr(wf, "discover_subdomains", discover)
    monkeypatch.setattr(wf, "finalize_scan", fake_fin)

    result = asyncio.run(wf.execute_scan_pipeline(sid))

    assert result.get("cancelled") is True
    assert fin_calls == []
    assert _row(store, sid)["status"] == "cancelled"


def test_recon_error_after_cancel_keeps_cancelled_status(store, monkeypatch):
    sid = _add_scan(store, status="queued")

    async def discover(domain):
        _row(store, sid)["status"] = "cancelled"
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(wf, "discover_subdomains", discover)

    with pytest.raises(RuntimeError):
        asyncio.run(wf.execute_recon_local(sid))

    row = _row(store, sid)
    assert row["status"] == "cancelled", "failure write must not clobber a cancelled scan"
    assert row["error_message"] is None


def test_progress_write_is_fenced_after_cancel(store):
    sid = _add_scan(store, status="cancelled")
    row = _row(store, sid)
    before_progress = row["stage_progress"]

    wf._save_progress(sid, {"dns": {"status": "running"}}, "dns")

    assert row["current_stage"] == "queued"
    assert row["stage_progress"] == before_progress


# ---------------------------------------------------------------------------
# cancel-during-finalize
# ---------------------------------------------------------------------------
def test_cancel_during_security_checks_stops_before_findings_writes(store, monkeypatch):
    sid = _add_scan(store, status="queued")
    sec_calls = []
    norm_calls = []

    def observations_with_host(scan_id, *args, **kwargs):
        # recon evidence from a pre-cancel remote/local run
        return {
            "discovery": {"discovered_hosts": ["www.acme.test"]},
            "dns": {"dns_records": [
                {"hostname": "www.acme.test", "primary_ip": "198.51.100.10", "records": {}},
            ]},
            "http": {"http_probes": []},
            "nuclei": {"nuclei_findings": []},
        }

    async def fake_sec(*args, **kwargs):
        # cancel lands while security checks are in flight
        _row(store, sid)["status"] = "cancelled"
        sec_calls.append(1)
        return []

    def fake_norm(*args, **kwargs):
        norm_calls.append(1)
        return []

    monkeypatch.setattr(wf, "_load_observations", observations_with_host)
    monkeypatch.setattr(wf, "run_security_checks", fake_sec)
    monkeypatch.setattr(wf, "normalize_findings", fake_norm)

    result = asyncio.run(wf.finalize_scan(sid))

    assert result["status"] == "cancelled"
    assert sec_calls == [1], "security checks should have started before the cancel"
    assert norm_calls == [], "normalization/baseline diff must not run after cancel"
    assert _row(store, sid)["status"] == "cancelled"


def test_cancel_at_completion_refuses_score_and_snapshot(store, monkeypatch):
    sid = _add_scan(store, status="queued")
    snapshots_before = len(store.snapshots)
    notifications_before = len(store.notifications)

    def cancel_then_score(findings, assessment=None):
        # cancel lands after the last boundary check, at the scoring step
        _row(store, sid)["status"] = "cancelled"
        return {
            "score": 88, "grade": "B", "posture_label": "Good",
            "status_color": "ok", "assessed": True, "max_score": 100,
            "subscores": [], "factors": [],
        }

    monkeypatch.setattr(wf, "compute_risk_score", cancel_then_score)

    result = asyncio.run(wf.finalize_scan(sid))

    assert result["status"] == "cancelled"
    row = _row(store, sid)
    assert row["status"] == "cancelled", "completion CAS must not overwrite cancel"
    assert row["score"] is None, "cancelled scan must never be scored"
    assert len(store.snapshots) == snapshots_before, "no score snapshot for a cancelled scan"
    assert len(store.notifications) == notifications_before, "no completion notification"


# ---------------------------------------------------------------------------
# cancel endpoint (conditional transition)
# ---------------------------------------------------------------------------
def test_cancel_endpoint_transitions_once_then_400s(client, store, auth_headers):
    sid = _add_scan(store, status="queued")
    headers = auth_headers(ALICE, org=ORG_A)

    first = client.post(f"/api/v1/scans/{sid}/cancel", headers=headers)
    assert first.status_code == 200
    assert _row(store, sid)["status"] == "cancelled"

    second = client.post(f"/api/v1/scans/{sid}/cancel", headers=headers)
    assert second.status_code == 400
    assert "already cancelled" in second.json()["detail"]


def test_cancel_endpoint_refuses_completed_scan(client, store, auth_headers):
    headers = auth_headers(ALICE, org=ORG_A)
    resp = client.post(f"/api/v1/scans/{SCAN_A1}/cancel", headers=headers)
    assert resp.status_code == 400
    assert "already completed" in resp.json()["detail"]
    assert _row(store, SCAN_A1)["status"] == "completed"
