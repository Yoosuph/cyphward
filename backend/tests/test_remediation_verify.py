"""
Remediation verification integrity (platform review P1):
the recheck must rerun the detector/rule that produced the finding, and
return "inconclusive" — never "verified" — when it cannot produce proof.

Run: uv run --with pytest ... python -m pytest backend/tests/test_remediation_verify.py -q
"""
from conftest import ORG_A, ALICE, FINDING_A1, FINDING_A2, SCAN_A1


def _seed_task(store, finding_id, task_id="task-1", status="ready_for_verification"):
    task = {
        "id": task_id, "org_id": ORG_A, "finding_id": finding_id,
        "title": "Verify the fix", "instructions": None, "assignee_id": None,
        "priority": "high", "due_date": None, "status": status,
        "created_by": ALICE, "verified_at": None,
        "created_at": "2026-09-01T00:00:00", "updated_at": "2026-09-01T00:00:00",
    }
    store.remediation_tasks.append(task)
    return task


def _seed_nuclei_finding(store, template_id="CVE-2024-1234"):
    row = {
        "id": "f5555555-0000-4000-8000-000000000005",
        "org_id": ORG_A, "scan_id": SCAN_A1, "asset_id": "a1",
        "title": "Reflected XSS (template)", "description": "nuclei matched",
        "severity": "high", "category": "Nuclei Scan", "status": "open",
        "evidence": {"template_id": template_id, "host": "www.acme.test"},
        "remediation": "patch it", "hostname": "www.acme.test",
        "first_seen_at": "2026-03-01T00:00:00", "last_seen_at": "2026-03-01T00:00:00",
        "resolved_at": None, "updated_at": "2026-03-01T00:00:00",
        "created_at": "2026-03-01T00:00:00",
    }
    store.findings.append(row)
    return row


def _seed_unknown_finding(store):
    row = {
        "id": "f6666666-0000-4000-8000-000000000006",
        "org_id": ORG_A, "scan_id": SCAN_A1, "asset_id": "a1",
        "title": "Oddball Issue", "description": "unknown detector",
        "severity": "medium", "category": "Supply Chain", "status": "open",
        "evidence": {}, "remediation": "investigate", "hostname": "www.acme.test",
        "first_seen_at": "2026-03-01T00:00:00", "last_seen_at": "2026-03-01T00:00:00",
        "resolved_at": None, "updated_at": "2026-03-01T00:00:00",
        "created_at": "2026-03-01T00:00:00",
    }
    store.findings.append(row)
    return row


def _mock_probes(monkeypatch, dns_ok=True, http_ok=True):
    async def fake_dns(hostname):
        return {
            "hostname": hostname,
            "primary_ip": "198.51.100.10" if dns_ok else None,
            "records": {"A": ["198.51.100.10"] if dns_ok else [],
                        "SPF": None, "DMARC": None},
            "has_spf": False, "has_dmarc": False,
        }

    async def fake_http(hostname, scope=None):
        return {
            "hostname": hostname,
            "http_status": 200 if http_ok else None,
            "error": None if http_ok else "connection refused",
            "scheme": "https" if http_ok else None,
            "security_headers": {}, "raw_headers": {}, "tls_info": {},
        }

    monkeypatch.setattr("backend.app.api.remediation.resolve_host_dns", fake_dns)
    monkeypatch.setattr("backend.app.api.remediation.probe_http_service", fake_http)


def test_shared_check_still_reproducing_reopens(client, auth_headers, store, monkeypatch):
    _seed_task(store, FINDING_A1)
    _mock_probes(monkeypatch)

    async def checks(hostname, dns_data, http_data, is_apex=True):
        return [{"title": "HSTS Missing"}]

    monkeypatch.setattr("backend.app.api.remediation.run_security_checks", checks)

    resp = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "reopened"
    assert store.remediation_tasks[0]["status"] == "reopened"
    finding = next(f for f in store.findings if f["id"] == FINDING_A1)
    assert finding["status"] == "open"


def test_shared_check_clean_recheck_verifies(client, auth_headers, store, monkeypatch):
    _seed_task(store, FINDING_A1)
    _mock_probes(monkeypatch)

    async def checks(hostname, dns_data, http_data, is_apex=True):
        return []

    monkeypatch.setattr("backend.app.api.remediation.run_security_checks", checks)

    resp = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "verified"
    assert store.remediation_tasks[0]["status"] == "verified"
    finding = next(f for f in store.findings if f["id"] == FINDING_A1)
    assert finding["status"] == "resolved"


def test_unreachable_host_is_inconclusive_not_verified(client, auth_headers, store, monkeypatch):
    """A dead probe must not turn an empty recheck into 'verified'."""
    _seed_task(store, FINDING_A1)
    _mock_probes(monkeypatch, http_ok=False)

    async def checks(hostname, dns_data, http_data, is_apex=True):
        return []

    monkeypatch.setattr("backend.app.api.remediation.run_security_checks", checks)

    resp = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "inconclusive"
    assert "HTTP probe" in data["message"]
    assert store.remediation_tasks[0]["status"] == "ready_for_verification"
    finding = next(f for f in store.findings if f["id"] == FINDING_A1)
    assert finding["status"] == "open"


def test_unresolvable_dns_is_inconclusive_for_dns_checks(client, auth_headers, store, monkeypatch):
    _seed_task(store, FINDING_A2)
    _mock_probes(monkeypatch, dns_ok=False, http_ok=True)

    async def checks(hostname, dns_data, http_data, is_apex=True):
        return []

    monkeypatch.setattr("backend.app.api.remediation.run_security_checks", checks)

    resp = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "inconclusive"
    assert "DNS" in data["message"]
    assert store.remediation_tasks[0]["status"] == "ready_for_verification"
    finding = next(f for f in store.findings if f["id"] == FINDING_A2)
    assert finding["status"] == "open"


def test_nuclei_finding_reruns_its_template_not_shared_checks(client, auth_headers, store, monkeypatch):
    _seed_nuclei_finding(store)
    _seed_task(store, "f5555555-0000-4000-8000-000000000005")
    _mock_probes(monkeypatch)

    async def shared_checks_must_not_run(*args, **kwargs):
        raise AssertionError("shared security checks must not decide a Nuclei finding")

    monkeypatch.setattr("backend.app.api.remediation.run_security_checks",
                        shared_checks_must_not_run)

    rerun_calls = []

    async def rerun(hostname, template_id, timeout=60):
        rerun_calls.append((hostname, template_id))
        return {"ok": True, "error": None, "findings": [
            {"evidence": {"template_id": template_id, "host": hostname}},
        ]}

    monkeypatch.setattr("backend.app.api.remediation.run_nuclei_template", rerun)

    resp = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert rerun_calls == [("www.acme.test", "CVE-2024-1234")]
    assert data["result"] == "reopened"
    assert store.remediation_tasks[0]["status"] == "reopened"


def test_nuclei_template_clean_verifies(client, auth_headers, store, monkeypatch):
    _seed_nuclei_finding(store)
    _seed_task(store, "f5555555-0000-4000-8000-000000000005")
    _mock_probes(monkeypatch)

    async def rerun(hostname, template_id, timeout=60):
        return {"ok": True, "error": None, "findings": []}

    monkeypatch.setattr("backend.app.api.remediation.run_nuclei_template", rerun)

    resp = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "verified"
    finding = next(f for f in store.findings
                   if f["id"] == "f5555555-0000-4000-8000-000000000005")
    assert finding["status"] == "resolved"


def test_nuclei_rerun_failure_is_inconclusive(client, auth_headers, store, monkeypatch):
    """Tool unavailable -> no proof -> finding stays open, task unchanged."""
    _seed_nuclei_finding(store)
    _seed_task(store, "f5555555-0000-4000-8000-000000000005")
    _mock_probes(monkeypatch)

    async def rerun(hostname, template_id, timeout=60):
        return {"ok": False, "findings": [], "error": "nuclei is not installed"}

    monkeypatch.setattr("backend.app.api.remediation.run_nuclei_template", rerun)

    resp = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "inconclusive"
    assert "nuclei is not installed" in data["message"]
    assert store.remediation_tasks[0]["status"] == "ready_for_verification"
    finding = next(f for f in store.findings
                   if f["id"] == "f5555555-0000-4000-8000-000000000005")
    assert finding["status"] == "open"


def test_nuclei_finding_unreachable_host_is_inconclusive(client, auth_headers, store, monkeypatch):
    _seed_nuclei_finding(store)
    _seed_task(store, "f5555555-0000-4000-8000-000000000005")
    _mock_probes(monkeypatch, http_ok=False)

    async def rerun_should_not_run(hostname, template_id, timeout=60):
        raise AssertionError("must not rerun against a dead host")

    monkeypatch.setattr("backend.app.api.remediation.run_nuclei_template",
                        rerun_should_not_run)

    resp = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    assert resp.json()["result"] == "inconclusive"
    assert store.remediation_tasks[0]["status"] == "ready_for_verification"


def test_unknown_detector_is_inconclusive(client, auth_headers, store, monkeypatch):
    _seed_unknown_finding(store)
    _seed_task(store, "f6666666-0000-4000-8000-000000000006")

    async def probes_must_not_run(hostname, **kwargs):
        raise AssertionError("unknown detector short-circuits before probing")

    monkeypatch.setattr("backend.app.api.remediation.resolve_host_dns", probes_must_not_run)
    monkeypatch.setattr("backend.app.api.remediation.probe_http_service", probes_must_not_run)

    resp = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "inconclusive"
    assert "fresh scan" in data["message"]
    assert store.remediation_tasks[0]["status"] == "ready_for_verification"
    finding = next(f for f in store.findings
                   if f["id"] == "f6666666-0000-4000-8000-000000000006")
    assert finding["status"] == "open"


def test_patch_cannot_mark_task_verified(client, auth_headers, store):
    _seed_task(store, FINDING_A1, status="in_progress")

    resp = client.patch(
        "/api/v1/remediation/task-1",
        json={"status": "verified"},
        headers=auth_headers(ALICE),
    )
    assert resp.status_code == 400
    assert "verify" in resp.json()["detail"]
    assert store.remediation_tasks[0]["status"] == "in_progress"


def test_create_task_from_finding(client, auth_headers, store):
    resp = client.post(
        "/api/v1/remediation",
        json={"finding_id": FINDING_A1, "title": "Enable HSTS everywhere",
              "priority": "high"},
        headers=auth_headers(ALICE),
    )
    assert resp.status_code == 201
    task = resp.json()["task"]
    assert task["status"] == "open"
    assert task["finding_id"] == FINDING_A1
    assert len(store.remediation_tasks) == 1


def test_verify_task_in_wrong_status_rejected(client, auth_headers, store):
    _seed_task(store, FINDING_A1, status="verified")

    resp = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert resp.status_code == 400
    assert "cannot be verified" in resp.json()["detail"]
