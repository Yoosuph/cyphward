"""Privacy stage (C2a) on the real test database, as the restricted app role.

Capability recorded at claim; old workers keep working; the observation is
fenced to the current attempt; evidence is externally observed and written in
the completion savepoint; coverage, grade and score never change; the newest
privacy result wins and a scan without the stage leaves the previous one.
"""
import asyncio
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import backend.app.api.scanner_jobs as sj
from backend.app.core import scan_admission as admission, scan_execution as ex
from backend.app.core.execution_fence import ClaimLost
from backend.app.main import app
from backend.app.workflows import inngest_workflow as wf
from backend.tests.test_compliance_postgres import _req, world  # noqa: F401 (fixture)
from backend.tests.test_scan_execution_postgres import (  # noqa: F401 (fixtures)
    _clean_declared_scope_scan, admission_db, disposable_postgres_url, execution_db, expire, no_external,
)

POLICY = "gaid.notice.privacy_policy"
API_KEY = "privacy-stage-scanner-key"


def _claim_headers(capabilities=None):
    headers = {"Authorization": f"Bearer {API_KEY}", "X-Scanner-Id": "w-privacy", "X-Timestamp": str(int(time.time())),
               "X-Scanner-Protocol": "2"}
    if capabilities:
        headers["X-Scanner-Capabilities"] = capabilities
    return headers


@pytest.fixture
def scanner_api(monkeypatch):
    monkeypatch.setattr(sj, "SCANNER_MODE", "remote")
    monkeypatch.setattr(sj, "SCANNER_API_KEY", API_KEY)
    monkeypatch.setattr(sj, "SCANNER_CLAIMS_ENABLED", True)
    return TestClient(app)


def _queued(conn, org, domain):
    return str(admission.admit_scan(org, domain, request_scope="privacy", request_key=str(uuid4())).scan["id"])


@pytest.mark.parametrize("capabilities,expected", [
    ("privacy_v1", {"status": "pending"}),
    (None, {"status": "skipped", "reason": "worker_without_privacy_capability"}),
    ("something_else", {"status": "skipped", "reason": "worker_without_privacy_capability"}),
])
def test_claim_records_whether_the_worker_can_run_privacy(execution_db, scanner_api, capabilities, expected):
    conn, org, domains = execution_db
    sid = _queued(conn, org, domains[0])
    r = scanner_api.post("/api/v1/scanner/claim", headers=_claim_headers(capabilities))
    assert r.status_code == 200 and r.json()["scan_id"] == sid
    privacy = conn.execute("SELECT stage_progress->'privacy' AS p FROM scans WHERE id = %s", (sid,)).fetchone()["p"]
    assert {k: privacy[k] for k in expected} == expected
    assert r.json()["limits"]["privacy_max_hosts"] == 5


def test_protocol_advertises_the_capability(scanner_api):
    r = scanner_api.get("/api/v1/scanner/protocol", headers=_claim_headers())
    assert r.json()["capabilities"] == ["privacy_v1"] and r.json()["version"] == 2


def _privacy_observation(apex, *, policy=True):
    page = ({"kind": "privacy_policy", "matched": True, "found_by": "link", "url": f"https://{apex}/privacy",
             "fingerprint": "f" * 64, "fixed_paths": {}} if policy else
            {"kind": "privacy_policy", "matched": False, "off_domain": False,
             "fixed_paths": {p: 404 for p in ("/privacy", "/privacy-policy", "/privacy-notice", "/data-protection")}})
    return {"privacy_observations": [{
        "hostname": apex, "catch_all": False, "pages": [page, {"kind": "cookie_notice", "matched": False, "fixed_paths": {}}],
        "first_response_cookies": [{"name": "__cf_bm", "category": "infrastructure", "vendor": None}],
        "trackers": [], "consent_manager": None, "policy_signals": None}],
        "attempted_hosts": [apex], "successful_hosts": [apex], "failed_hosts": {}}


def _complete_scan(execution_db, monkeypatch, privacy=None, domain_index=0):
    """A clean declared-scope scan, optionally with a privacy observation from the same attempt."""
    async def clean_checks(hostname, dns_item, http_item, is_apex=True):
        return []
    monkeypatch.setattr(wf, "run_security_checks", clean_checks)
    conn = execution_db[0]
    real_handoff = ex.handoff_to_core

    def handoff_with_privacy(worker):
        if privacy is not None:
            apex = conn.execute("SELECT d.domain FROM scans s JOIN domains d ON d.id = s.domain_id WHERE s.id = %s",
                                (worker.scan_id,)).fetchone()["domain"]
            ex.store_observation(worker, "privacy", privacy(apex))
        return real_handoff(worker)

    monkeypatch.setattr(ex, "handoff_to_core", handoff_with_privacy)
    core = _clean_declared_scope_scan(execution_db, domain_index)
    monkeypatch.setattr(ex, "handoff_to_core", real_handoff)
    result = asyncio.run(wf.finalize_scan(core.scan_id, core))
    assert result["status"] == "completed"
    return core.scan_id, result


def _privacy_rows(conn, scan_id):
    return {r["requirement_key"]: r for r in conn.execute(
        "SELECT * FROM compliance_evidence WHERE scan_id = %s AND source = 'externally_observed'", (scan_id,)).fetchall()}


def test_old_worker_scan_completes_with_no_privacy_rows(execution_db, monkeypatch):
    no_external(monkeypatch)
    scan_id, result = _complete_scan(execution_db, monkeypatch, privacy=None)
    assert _privacy_rows(execution_db[0], scan_id) == {}
    assert result["stage_progress"]["scoring"]["coverage"]["state"] == "complete"


def test_privacy_rows_are_externally_observed_and_never_change_coverage_or_score(execution_db, monkeypatch):
    no_external(monkeypatch)
    conn = execution_db[0]
    without_id, without = _complete_scan(execution_db, monkeypatch, privacy=None, domain_index=0)
    with_id, with_privacy = _complete_scan(execution_db, monkeypatch, privacy=_privacy_observation, domain_index=1)
    rows = _privacy_rows(conn, with_id)
    assert rows[POLICY]["status"] == "present" and rows[POLICY]["details"]["url"].endswith("/privacy")
    assert set(rows) == {POLICY, "gaid.notice.cookie_notice", "gaid.consent.no_trackers_before_consent",
                         "gaid.dpo.contact_published"}
    cov_a, cov_b = (r["stage_progress"]["scoring"]["coverage"] for r in (without, with_privacy))
    assert (cov_a["state"], cov_a["requested_checks"], cov_a["evaluated_checks"]) == \
           (cov_b["state"], cov_b["requested_checks"], cov_b["evaluated_checks"])
    snapshots = {r["scan_id"]: r for r in conn.execute(
        "SELECT scan_id::text, score, risk_points FROM score_snapshots WHERE scan_id::text = ANY(%s)",
        ([without_id, with_id],)).fetchall()}
    assert snapshots[without_id]["risk_points"] == snapshots[with_id]["risk_points"]


def test_a_stale_attempt_cannot_store_a_privacy_observation(execution_db):
    conn, org, domains = execution_db
    sid = _queued(conn, org, domains[0])
    worker = ex.claim_from_row(ex.claim_recon("w", "worker", 120, sid))
    expire(conn, worker)
    with pytest.raises(ClaimLost):
        ex.store_observation(worker, "privacy", _privacy_observation("x.example.test"))
    assert conn.execute("SELECT count(*) AS n FROM scan_results WHERE scan_id = %s AND stage = 'privacy'",
                        (sid,)).fetchone()["n"] == 0


def test_newest_privacy_result_wins_and_a_scan_without_it_leaves_it(world, monkeypatch):
    conn, org = world["conn"], world["org"]
    conn.execute("UPDATE organizations SET plan = 'growth' WHERE id = %s", (org,))
    conn.commit()
    client, headers = TestClient(app), world["member"](org)
    db = (conn, org, world["domains"])

    def policy_status():
        body = client.get("/api/v1/compliance/overview", headers=headers).json()
        return _req(body, POLICY)["domains"][0]

    _complete_scan(db, monkeypatch, privacy=_privacy_observation)
    assert policy_status()["status"] == "present"
    _complete_scan(db, monkeypatch, privacy=lambda apex: _privacy_observation(apex, policy=False))
    latest = policy_status()
    assert (latest["status"], latest["reason"], latest["source"]) == ("gap", "not_found_by_static_check",
                                                                      "externally_observed")
    _complete_scan(db, monkeypatch, privacy=None)  # an older worker ran the next scan
    assert policy_status()["status"] == "gap", "no new observation: the newest result still stands"
