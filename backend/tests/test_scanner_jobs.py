"""
Scanner worker API tests (spec §14 — outbound-only job protocol).
Auth: Bearer SCANNER_API_KEY + X-Scanner-Id + X-Timestamp (±300s replay window).
Fail-closed: interface is 503 unless SCANNER_MODE=remote AND key configured.
"""
import time

import pytest

import backend.app.api.scanner_jobs as sj
import backend.app.workflows.inngest_workflow as wf
from conftest import DOM_A1, ORG_A

API_KEY = "test-scanner-key"
SCANNER_ID = "az-scanner-01"


def scanner_headers(key: str = API_KEY, scanner_id: str = SCANNER_ID, ts=None) -> dict:
    return {
        "Authorization": f"Bearer {key}",
        "X-Scanner-Id": scanner_id,
        "X-Timestamp": str(int(time.time()) if ts is None else ts),
    }


@pytest.fixture
def scanner_client(client, monkeypatch):
    monkeypatch.setattr(sj, "SCANNER_MODE", "remote")
    monkeypatch.setattr(sj, "SCANNER_API_KEY", API_KEY)
    return client


def test_interface_disabled_in_local_mode(scanner_client, monkeypatch):
    monkeypatch.setattr(sj, "SCANNER_MODE", "local")
    monkeypatch.setattr(sj, "SCANNER_API_KEY", API_KEY)
    r = scanner_client.post("/api/v1/scanner/claim", headers=scanner_headers())
    assert r.status_code == 503


def test_interface_disabled_without_api_key(scanner_client, monkeypatch):
    monkeypatch.setattr(sj, "SCANNER_API_KEY", "")
    r = scanner_client.post("/api/v1/scanner/claim", headers=scanner_headers(key="anything"))
    assert r.status_code == 503


def test_missing_bearer_is_401(scanner_client):
    r = scanner_client.post(
        "/api/v1/scanner/claim",
        headers={"X-Scanner-Id": SCANNER_ID, "X-Timestamp": str(int(time.time()))},
    )
    assert r.status_code == 401


def test_wrong_bearer_is_401(scanner_client):
    r = scanner_client.post("/api/v1/scanner/claim", headers=scanner_headers(key="wrong-key"))
    assert r.status_code == 401


def test_missing_scanner_id_is_400(scanner_client):
    h = scanner_headers()
    del h["X-Scanner-Id"]
    r = scanner_client.post("/api/v1/scanner/claim", headers=h)
    assert r.status_code == 400


def test_stale_timestamp_is_401(scanner_client):
    r = scanner_client.post("/api/v1/scanner/claim", headers=scanner_headers(ts=int(time.time()) - 3600))
    assert r.status_code == 401


def test_claim_empty_queue_returns_204(scanner_client, store):
    store.scans = [s for s in store.scans if s["status"] != "queued"]
    r = scanner_client.post("/api/v1/scanner/claim", headers=scanner_headers())
    assert r.status_code == 204


def test_claim_returns_job_payload(scanner_client, store):
    store.scans.append({
        "id": "52222222-0000-4000-8000-000000000002",
        "org_id": ORG_A, "domain_id": DOM_A1, "domain": "acme.test",
        "status": "queued", "score": None, "current_stage": "queued",
        "stage_progress": {}, "scan_type": "EXTERNAL_ASSESSMENT",
        "started_at": None, "completed_at": None, "created_at": "2026-09-01T00:00:00",
        "claimed_by": None, "lease_expires_at": None,
    })
    r = scanner_client.post("/api/v1/scanner/claim", headers=scanner_headers())
    assert r.status_code == 200
    job = r.json()
    assert job["version"] == 1
    assert job["target"] == "acme.test"
    assert job["scope"] == ["acme.test"]
    assert job["organization_id"] == ORG_A
    assert job["limits"]["max_hosts"] >= 1
    assert job["limits"]["max_ports"] >= 1
    assert job["lease_expires_at"]


def test_progress_requires_held_lease(scanner_client):
    # Seeded scan is 'completed' — no running lease for this scanner.
    r = scanner_client.post(
        "/api/v1/scanner/jobs/51111111-0000-4000-8000-000000000001/progress",
        headers=scanner_headers(),
        json={"stage": "dns", "status": "running", "items": 3},
    )
    assert r.status_code == 409


def test_progress_on_held_job_heartbeats(scanner_client, store):
    store.scans[0]["status"] = "running"
    store.scans[0]["claimed_by"] = SCANNER_ID
    r = scanner_client.post(
        "/api/v1/scanner/jobs/51111111-0000-4000-8000-000000000001/progress",
        headers=scanner_headers(),
        json={"stage": "ports", "status": "completed", "items": 4, "duration_ms": 1200},
    )
    assert r.status_code == 200
    assert r.json()["stage"] == "ports"


def test_progress_rejects_unknown_stage(scanner_client, store):
    store.scans[0]["status"] = "running"
    store.scans[0]["claimed_by"] = SCANNER_ID
    r = scanner_client.post(
        "/api/v1/scanner/jobs/51111111-0000-4000-8000-000000000001/progress",
        headers=scanner_headers(),
        json={"stage": "risk_decisions", "status": "running"},
    )
    assert r.status_code == 422


def test_observations_reject_non_recon_stage(scanner_client, store):
    store.scans[0]["status"] = "running"
    store.scans[0]["claimed_by"] = SCANNER_ID
    r = scanner_client.post(
        "/api/v1/scanner/jobs/51111111-0000-4000-8000-000000000001/observations",
        headers=scanner_headers(),
        json={"stage": "scoring", "data": {"score": 1}},
    )
    assert r.status_code == 422


def test_observations_accept_recon_stage(scanner_client, store):
    store.scans[0]["status"] = "running"
    store.scans[0]["claimed_by"] = SCANNER_ID
    r = scanner_client.post(
        "/api/v1/scanner/jobs/51111111-0000-4000-8000-000000000001/observations",
        headers=scanner_headers(),
        json={"stage": "dns", "data": {"dns_records": [{"hostname": "www.acme.test"}]}},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "stage": "dns"}


def test_complete_releases_lease_and_finalizes(scanner_client, store, monkeypatch):
    store.scans[0]["status"] = "running"
    store.scans[0]["claimed_by"] = SCANNER_ID
    finalized = {}

    async def fake_finalize(scan_id):
        finalized["scan_id"] = scan_id

    monkeypatch.setattr(wf, "finalize_scan", fake_finalize)
    r = scanner_client.post(
        "/api/v1/scanner/jobs/51111111-0000-4000-8000-000000000001/complete",
        headers=scanner_headers(),
        json={"stats": {"discovered": 5}},
    )
    assert r.status_code == 202
    assert r.json()["status"] == "finalizing"
    assert finalized.get("scan_id") == "51111111-0000-4000-8000-000000000001"


def test_fail_marks_scan_failed(scanner_client, store):
    store.scans[0]["status"] = "running"
    store.scans[0]["claimed_by"] = SCANNER_ID
    r = scanner_client.post(
        "/api/v1/scanner/jobs/51111111-0000-4000-8000-000000000001/fail",
        headers=scanner_headers(),
        json={"stage": "discovery", "error": "provider unreachable"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
