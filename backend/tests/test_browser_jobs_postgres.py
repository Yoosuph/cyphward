"""Cookie-consent browser jobs (C2b) on the real test database, as the restricted app role.

The claim split in both directions, per-attempt fencing, strict result validation, evidence written
once under the existing consent keys as tool_observed, and the flag-off promise: with the feature off
the Compliance page reads exactly as it did before.
"""
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import backend.app.api.scanner_jobs as sj
from backend.app.compliance import browser_observation as bo
from backend.app.core import browser_jobs, config
from backend.app.main import app
from backend.tests.test_compliance_postgres import _req, world  # noqa: F401 (fixture)
from backend.tests.test_scan_execution_postgres import (  # noqa: F401 (fixtures)
    admission_db, disposable_postgres_url, execution_db, no_external,
)

KEY = "browser-worker-test-key"
SCANNER_KEY = "scanner-test-key-different"


_CLAIMED = {"domain": "acme.test"}  # the domain of the job most recently claimed, so results end where they started


def good_result(**over):
    body = {
        "version": 1, "final_url": f"https://{_CLAIMED['domain']}/", "browser_version": "Chromium 153.0",
        "cookies": [{"name": "_ga", "domain": "acme.test", "secure": True, "http_only": False,
                     "same_site": "lax", "lifetime": "over_1_year", "third_party": False},
                    {"name": "sid", "domain": "acme.test", "secure": True, "http_only": True,
                     "same_site": "lax", "lifetime": "session", "third_party": False}],
        "requests": {"total": 6, "first_party": 4, "third_party_hosts": [{"host": "www.google-analytics.com", "count": 2}]},
        "banner": {"detected": True, "in_first_view": True, "cms_marker": "onetrust",
                   "accept_control": True, "reject_control": "same_level"},
        "timings": {"navigation_ms": 900, "settle_ms": 2000, "total_ms": 3200},
    }
    body.update(over)
    return body


def headers(capabilities="privacy_browser", key=KEY, worker="vm-browser-1", protocol="1"):
    h = {"Authorization": f"Bearer {key}", "X-Scanner-Id": worker, "X-Timestamp": str(int(time.time())),
         "X-Browser-Protocol": protocol}
    if capabilities:
        h["X-Scanner-Capabilities"] = capabilities
    return h


def authority(job, **over):
    h = headers()
    h.update({"X-Claim-Generation": str(job["claim_generation"]), "X-Claim-Token": job["claim_token"]})
    h.update(over)
    return h


@pytest.fixture
def api(execution_db, disposable_postgres_url, monkeypatch):
    from contextlib import contextmanager
    import psycopg
    from psycopg.rows import dict_row

    @contextmanager
    def get_db():
        with psycopg.connect(disposable_postgres_url, row_factory=dict_row) as c:
            yield c

    monkeypatch.setattr(browser_jobs, "get_db", get_db)
    monkeypatch.setattr(config, "BROWSER_CONSENT_ENABLED", True)
    monkeypatch.setattr(config, "BROWSER_WORKER_API_KEY", KEY)
    monkeypatch.setattr(sj, "SCANNER_MODE", "remote")
    monkeypatch.setattr(sj, "SCANNER_API_KEY", SCANNER_KEY)
    monkeypatch.setattr(sj, "SCANNER_CLAIMS_ENABLED", True)
    client = TestClient(app)
    client.conn, client.org, client.domains = execution_db
    return client


def queue(api, index=0):
    job_id = browser_jobs.enqueue(api.org, api.domains[index], cooldown_hours=0)
    assert job_id
    return job_id


def claim(api):
    r = api.post("/api/v1/browser-worker/claim", headers=headers())
    assert r.status_code == 200, r.text
    _CLAIMED["domain"] = r.json()["target"]
    return r.json()


def rows(api, job_id=None):
    return api.conn.execute(
        "SELECT requirement_key, source, status, scan_id, details FROM compliance_evidence "
        "WHERE org_id = %s AND details->>'observation' = 'browser_consent_v1' ORDER BY requirement_key", (api.org,)).fetchall()


# ── off by default, authentication ────────────────────────────────────────
def test_everything_is_off_by_default(execution_db, monkeypatch):
    client = TestClient(app)
    assert config.BROWSER_CONSENT_ENABLED is False
    for path in ("/api/v1/browser-worker/protocol",):
        assert client.get(path, headers=headers()).status_code == 503
    assert client.post("/api/v1/browser-worker/claim", headers=headers()).status_code == 503
    assert browser_jobs.enqueue_after_scan(str(uuid4())) is None


def test_authentication_and_capability_are_all_required(api):
    url = "/api/v1/browser-worker/claim"
    assert api.post(url).status_code == 401
    assert api.post(url, headers=headers(key=SCANNER_KEY)).status_code == 401      # the scanner's key is not the browser's
    assert api.post(url, headers=headers(capabilities=None)).status_code == 403
    assert api.post(url, headers=headers(capabilities="privacy_v1")).status_code == 403  # scanner capability only
    assert api.post(url, headers=headers(protocol="2")).status_code == 426
    assert api.post(url, headers=headers(worker="local:x")).status_code == 400
    stale = headers()
    stale["X-Timestamp"] = str(int(time.time()) - 4000)
    assert api.post(url, headers=stale).status_code == 401
    assert api.post(url, headers=headers()).status_code == 204


# ── the claim split, both ways ────────────────────────────────────────────
def test_scanner_never_receives_a_browser_job_and_browser_worker_never_receives_a_scan(api):
    # A queued scan AND a queued browser job for the same org.
    from backend.app.core.scan_admission import admit_scan
    scan_id = str(admit_scan(api.org, api.domains[0], request_scope="split", request_key=str(uuid4())).scan["id"])
    job_id = queue(api, 1)

    # The browser worker gets only its own job and never touches the scan.
    job = claim(api)
    assert job["job_id"] == job_id and job["job_type"] == "cookie_consent_observation"
    assert api.post("/api/v1/browser-worker/claim", headers=headers()).status_code == 204
    assert api.conn.execute("SELECT status FROM scans WHERE id = %s", (scan_id,)).fetchone()["status"] == "queued"

    # A scanner that advertises the browser capability is turned away, and the scan stays queued.
    scanner_headers = {"Authorization": f"Bearer {SCANNER_KEY}", "X-Scanner-Id": "w1", "X-Timestamp": str(int(time.time())),
                       "X-Scanner-Protocol": "2"}
    r = api.post("/api/v1/scanner/claim", headers={**scanner_headers, "X-Scanner-Capabilities": "privacy_browser"})
    assert r.status_code == 204
    assert api.conn.execute("SELECT status FROM scans WHERE id = %s", (scan_id,)).fetchone()["status"] == "queued"

    # A normal scanner gets exactly the scan, never the browser job (already running here; queue another).
    r = api.post("/api/v1/scanner/claim", headers=scanner_headers)
    assert r.status_code == 200 and r.json()["scan_id"] == scan_id
    api.conn.execute("UPDATE privacy_browser_jobs SET status='completed', claimed_by=NULL, claim_token=NULL, lease_expires_at=NULL WHERE id=%s", (job_id,))
    api.conn.commit()
    queue(api, 1)
    assert api.post("/api/v1/scanner/claim", headers=scanner_headers).status_code == 204
    # The scanner's own client cannot request the capability even if an API advertises it.
    from scanner.client import WORKER_CAPABILITIES
    assert "privacy_browser" not in WORKER_CAPABILITIES


def test_scanner_and_browser_credentials_do_not_cross(api):
    queue(api)
    scanner_headers = {"Authorization": f"Bearer {KEY}", "X-Scanner-Id": "w1", "X-Timestamp": str(int(time.time())),
                       "X-Scanner-Protocol": "2"}
    assert api.post("/api/v1/scanner/claim", headers=scanner_headers).status_code == 401  # browser key on scanner API
    assert api.get("/api/v1/scanner/protocol", headers={**scanner_headers, "Authorization": f"Bearer {SCANNER_KEY}"}
                   ).json()["capabilities"] == ["privacy_v1"]  # scanner protocol is unchanged


# ── claim, lease, fencing ────────────────────────────────────────────────
def test_claim_payload_and_lease_expiry_fencing(api):
    job_id = queue(api)
    job = claim(api)
    domain = api.conn.execute("SELECT domain FROM domains WHERE id = %s", (api.domains[0],)).fetchone()["domain"]
    assert job["target"] == domain and job["scope"] == [domain] and job["url"] == f"https://{domain}/"
    assert job["limits"]["page_timeout_seconds"] == 45 and job["limits"]["max_requests"] == 150
    assert api.post(f"/api/v1/browser-worker/jobs/{job_id}/heartbeat", headers=authority(job)).status_code == 200

    api.conn.execute("UPDATE privacy_browser_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id=%s", (job_id,))
    api.conn.commit()
    # An expired lease cannot be revived by the old holder...
    assert api.post(f"/api/v1/browser-worker/jobs/{job_id}/heartbeat", headers=authority(job)).status_code == 409
    # ...and a replacement attempt supersedes it.
    new = claim(api)
    assert new["job_id"] == job_id and new["claim_generation"] == job["claim_generation"] + 1
    assert api.post(f"/api/v1/browser-worker/jobs/{job_id}/result", json=good_result(), headers=authority(job)).status_code == 409
    assert api.post(f"/api/v1/browser-worker/jobs/{job_id}/fail", json={"error": "late"}, headers=authority(job)).status_code == 409
    assert rows(api) == []


def test_wrong_token_wrong_worker_malformed_id(api):
    job_id = queue(api)
    job = claim(api)
    url = f"/api/v1/browser-worker/jobs/{job_id}/result"
    assert api.post(url, json=good_result(), headers=authority(job, **{"X-Claim-Token": "x" * 40})).status_code == 409
    other = authority(job)
    other["X-Scanner-Id"] = "someone-else"
    assert api.post(url, json=good_result(), headers=other).status_code == 409
    assert api.post("/api/v1/browser-worker/jobs/not-a-uuid/result", json=good_result(), headers=authority(job)).status_code == 404
    assert api.post(f"/api/v1/browser-worker/jobs/{uuid4()}/heartbeat", headers=authority(job)).status_code == 409
    assert rows(api) == []


def test_attempt_cap_fails_a_job_that_keeps_expiring(api, monkeypatch):
    monkeypatch.setattr(config, "BROWSER_MAX_ATTEMPTS", 2)
    job_id = queue(api)
    for _ in range(2):
        claim(api)
        api.conn.execute("UPDATE privacy_browser_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id=%s", (job_id,))
        api.conn.commit()
    assert api.post("/api/v1/browser-worker/claim", headers=headers()).status_code == 204
    row = api.conn.execute("SELECT status, error_message FROM privacy_browser_jobs WHERE id=%s", (job_id,)).fetchone()
    assert row["status"] == "failed" and "too many attempts" in row["error_message"]


def test_unverified_or_revoked_domains_are_never_claimed(api):
    job_id = queue(api)
    api.conn.execute("UPDATE domains SET revoked_at = now() WHERE id = %s", (api.domains[0],))
    api.conn.commit()
    assert api.post("/api/v1/browser-worker/claim", headers=headers()).status_code == 204
    assert api.conn.execute("SELECT status FROM privacy_browser_jobs WHERE id=%s", (job_id,)).fetchone()["status"] == "failed"
    api.conn.execute("UPDATE domains SET revoked_at = NULL WHERE id = %s", (api.domains[0],))
    api.conn.execute("UPDATE domains SET verification_status = 'pending' WHERE id = %s", (api.domains[1],))
    api.conn.commit()
    assert browser_jobs.enqueue(api.org, api.domains[1], cooldown_hours=0) is None


# ── results: validation, evidence, replay ────────────────────────────────
def test_valid_result_writes_tool_observed_evidence_once(api):
    job_id = queue(api)
    job = claim(api)
    r = api.post(f"/api/v1/browser-worker/jobs/{job_id}/result", json=good_result(), headers=authority(job))
    assert r.status_code == 202 and r.json()["evidence_rows"] == 3
    stored = rows(api)
    assert [x["requirement_key"] for x in stored] == sorted(bo.KEYS)
    assert {x["source"] for x in stored} == {"tool_observed"} and all(x["scan_id"] is None for x in stored)
    by = {x["requirement_key"]: x for x in stored}
    assert by[bo.BANNER_KEY]["status"] == "present" and by[bo.CHOICE_KEY]["status"] == "present"
    # _ga is a known analytics cookie set before any choice, so the browser reports a gap, in plain words.
    assert by[bo.TRACKERS_KEY]["status"] == "gap"
    assert by[bo.TRACKERS_KEY]["details"]["browser_label"].startswith("The browser observed 2 cookies set before any choice")
    job_row = api.conn.execute("SELECT status, result, claim_token FROM privacy_browser_jobs WHERE id=%s", (job_id,)).fetchone()
    assert job_row["status"] == "completed" and job_row["claim_token"] is None and job_row["result"]["banner"]["cms_marker"] == "onetrust"
    # Replay of the same result: refused, nothing duplicated.
    again = api.post(f"/api/v1/browser-worker/jobs/{job_id}/result", json=good_result(), headers=authority(job))
    assert again.status_code == 409 and len(rows(api)) == 3


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(extra_field=1),
    lambda b: b["cookies"][0].update(value="secret-cookie-value"),
    lambda b: b.update(cookies=b["cookies"] * 60),                                # > 100 cookies
    lambda b: b["cookies"][0].update(name="x" * 129),
    lambda b: b["cookies"][0].update(lifetime="forever"),
    lambda b: b.update(final_url="https://acme.test/?token=abc"),
    lambda b: b.update(final_url="javascript:alert(1)"),
    lambda b: b.update(final_url="ftp://acme.test/"),
    lambda b: b["requests"].update(total=1),                                       # counts exceed total
    lambda b: b["requests"].update(third_party_hosts=[{"host": "a.test", "count": 1}] * 2),
    lambda b: b["banner"].update(detected=False),                                  # controls without a banner
    lambda b: b["banner"].update(cms_marker="mystery"),
    lambda b: b["banner"].update(reject_control="yes"),
    lambda b: b["timings"].update(total_ms=-1),
    lambda b: b["timings"].update(navigation_ms=10 ** 9),
    lambda b: b.update(version=2),
    lambda b: b.update(browser_version="Chromium\n153"),
])
def test_invalid_results_are_refused_and_store_nothing(api, mutate):
    job_id = queue(api)
    job = claim(api)
    body = good_result()
    mutate(body)
    r = api.post(f"/api/v1/browser-worker/jobs/{job_id}/result", json=body, headers=authority(job))
    assert r.status_code == 422, r.text
    assert "secret-cookie-value" not in r.text
    assert rows(api) == []
    assert api.conn.execute("SELECT status FROM privacy_browser_jobs WHERE id=%s", (job_id,)).fetchone()["status"] == "running"


def test_oversized_and_non_json_results_are_refused(api):
    job_id = queue(api)
    job = claim(api)
    url = f"/api/v1/browser-worker/jobs/{job_id}/result"
    big = json.dumps(good_result(browser_version="x" * 70000))
    assert api.post(url, content=big, headers={**authority(job), "Content-Type": "application/json"}).status_code == 413
    assert api.post(url, content=b"{not json", headers={**authority(job), "Content-Type": "application/json"}).status_code == 422
    assert rows(api) == []


def test_fail_endpoint_and_retry_delay(api):
    job_id = queue(api)
    job = claim(api)
    r = api.post(f"/api/v1/browser-worker/jobs/{job_id}/fail", json={"error": "address refused", "reason": "refused_address"},
                 headers=authority(job))
    assert r.status_code == 200
    row = api.conn.execute("SELECT status, error_message FROM privacy_browser_jobs WHERE id=%s", (job_id,)).fetchone()
    assert row["status"] == "failed" and row["error_message"].startswith("refused_address")
    assert api.post(f"/api/v1/browser-worker/jobs/{job_id}/fail", json={"error": "again"}, headers=authority(job)).status_code == 409
    assert browser_jobs.enqueue(api.org, api.domains[0]) is None          # inside the retry delay
    assert api.post(f"/api/v1/browser-worker/jobs/{job_id}/fail", json={"error": ""}, headers=authority(job)).status_code in (409, 422)
    api.conn.execute("UPDATE privacy_browser_jobs SET requested_at = now() - interval '2 hours' WHERE id=%s", (job_id,))
    api.conn.commit()
    assert browser_jobs.enqueue(api.org, api.domains[0])


# ── queueing rules ───────────────────────────────────────────────────────
def test_one_active_job_per_domain_cooldown_and_tenant_check(api, world):
    first = browser_jobs.enqueue(api.org, api.domains[0])
    assert first and browser_jobs.enqueue(api.org, api.domains[0]) is None        # already queued
    other = world["other_org"]()
    # Another organisation can never queue a job for this organisation's domain.
    assert browser_jobs.enqueue(other, api.domains[0], cooldown_hours=0) is None
    count = api.conn.execute("SELECT count(*) AS n FROM privacy_browser_jobs WHERE domain_id=%s", (api.domains[0],)).fetchone()["n"]
    assert count == 1
    # The database itself refuses a cross-tenant row.
    import psycopg
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        api.conn.execute("INSERT INTO privacy_browser_jobs (org_id, domain_id) VALUES (%s, %s)", (other, api.domains[0]))
    api.conn.rollback()


def test_after_scan_hook_queues_only_for_completed_scans_and_only_when_on(api, monkeypatch):
    from backend.app.core.scan_admission import admit_scan
    scan_id = str(admit_scan(api.org, api.domains[0], request_scope="hook", request_key=str(uuid4())).scan["id"])
    assert browser_jobs.enqueue_after_scan(scan_id) is None                      # not completed yet
    api.conn.execute("UPDATE scans SET status='completed', completed_at=now() WHERE id=%s", (scan_id,))
    api.conn.commit()
    monkeypatch.setattr(config, "BROWSER_CONSENT_ENABLED", False)
    assert browser_jobs.enqueue_after_scan(scan_id) is None                      # flag off
    monkeypatch.setattr(config, "BROWSER_CONSENT_ENABLED", True)
    job_id = browser_jobs.enqueue_after_scan(scan_id)
    assert job_id and browser_jobs.enqueue_after_scan(scan_id) is None            # one job per scan
    assert api.conn.execute("SELECT scan_id FROM privacy_browser_jobs WHERE id=%s", (job_id,)).fetchone()["scan_id"]


def test_customer_endpoint_needs_admin_flag_and_a_verified_owned_domain(api, world):
    headers_owner = world["member"](api.org, "owner")
    headers_member = world["member"](api.org, "member")
    url = f"/api/v1/domains/{api.domains[0]}/consent-observation"
    assert api.post(url, headers=headers_member).status_code == 403
    r = api.post(url, headers=headers_owner)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert api.post(url, headers=headers_owner).status_code == 409
    assert api.post("/api/v1/domains/not-a-uuid/consent-observation", headers=headers_owner).status_code == 404
    assert api.post(f"/api/v1/domains/{uuid4()}/consent-observation", headers=headers_owner).status_code == 404
    other = world["other_org"]()
    foreign = api.conn.execute("SELECT id FROM domains WHERE org_id=%s", (other,)).fetchone()["id"]
    assert api.post(f"/api/v1/domains/{foreign}/consent-observation", headers=headers_owner).status_code == 404
    config.BROWSER_CONSENT_ENABLED = False
    try:
        assert api.post(url, headers=headers_owner).status_code == 404
    finally:
        config.BROWSER_CONSENT_ENABLED = True


# ── the Compliance page ─────────────────────────────────────────────────
def _growth(api):
    api.conn.execute("UPDATE organizations SET plan = 'growth' WHERE id = %s", (api.org,))
    api.conn.commit()


def _observe(api, index, **over):
    job_id = queue(api, index)
    job = claim(api)
    r = api.post(f"/api/v1/browser-worker/jobs/{job_id}/result", json=good_result(**over), headers=authority(job))
    assert r.status_code == 202, r.text


def _overview(api, world, headers_):
    return api.get("/api/v1/compliance/overview", headers=headers_).text


def test_flag_off_leaves_the_compliance_page_byte_identical(api, world, monkeypatch):
    headers_ = world["member"](api.org)
    _growth(api)
    monkeypatch.setattr(config, "BROWSER_CONSENT_ENABLED", False)
    before = _overview(api, world, headers_)
    # Browser rows exist in the table (for example from an earlier period with the flag on)...
    monkeypatch.setattr(config, "BROWSER_CONSENT_ENABLED", True)
    job_id = queue(api)
    job = claim(api)
    assert api.post(f"/api/v1/browser-worker/jobs/{job_id}/result", json=good_result(), headers=authority(job)).status_code == 202
    monkeypatch.setattr(config, "BROWSER_CONSENT_ENABLED", False)
    after = _overview(api, world, headers_)
    # ...but the page reads exactly as before, including the C1 note and the "Upcoming check" labels.
    assert after == before
    assert "Upcoming check" in after and "browser worker" not in after


def test_flag_on_shows_tool_observed_browser_evidence_with_plain_labels(api, world):
    headers_ = world["member"](api.org)
    _growth(api)
    _observe(api, 0)
    body = api.get("/api/v1/compliance/overview", headers=headers_).json()
    banner = _req(body, bo.BANNER_KEY)
    assert banner["source"] == "tool_observed" and banner["source_label"] == "Tool observed"
    assert banner["domains"][0]["status"] == "present"
    assert banner["domains"][0]["reason_text"].startswith("On a first visit the browser saw a consent banner")
    # One of two verified domains observed so far: the requirement as a whole is not stronger than that.
    assert banner["status"] == "not_assessed" and banner["domains"][1]["reason"] == "no_browser_observation"
    assert _req(body, bo.CHOICE_KEY)["domains"][0]["reason"] == "browser_accept_and_reject_same_level"
    trackers = _req(body, bo.TRACKERS_KEY)
    assert trackers["status"] == "gap" and trackers["source"] == "tool_observed"
    assert "2 cookies set before any choice was made" in trackers["domains"][0]["reason_text"]
    assert "browser worker" in body["note"]
    _observe(api, 1)  # the second domain, so every verified domain now has a browser observation
    body = api.get("/api/v1/compliance/overview", headers=headers_).json()
    assert _req(body, bo.BANNER_KEY)["status"] == "present" and _req(body, bo.BANNER_KEY)["status_label"] == "Evidence present"
    assert _req(body, bo.TRACKERS_KEY)["status"] == "gap"


def test_a_static_tracker_gap_still_stands_over_a_clean_browser_visit(api, world):
    headers_ = world["member"](api.org)
    _growth(api)
    job_id = queue(api)
    job = claim(api)
    clean = good_result(cookies=[], requests={"total": 3, "first_party": 3, "third_party_hosts": []})
    assert api.post(f"/api/v1/browser-worker/jobs/{job_id}/result", json=clean, headers=authority(job)).status_code == 202
    body = api.get("/api/v1/compliance/overview", headers=headers_).json()
    assert _req(body, bo.TRACKERS_KEY)["domains"][0]["reason"] == "browser_no_known_tracking"
    # A later static finding of a tracker cookie in the first response is a gap the browser cannot erase.
    api.conn.execute(
        "INSERT INTO compliance_evidence (org_id,domain_id,requirement_key,register_version,source,status,observed_at,expires_at,details) "
        "VALUES (%s,%s,%s,'v',%s,'gap',now() + interval '1 second',now() + interval '30 days',%s::jsonb)",
        (api.org, api.domains[0], bo.TRACKERS_KEY, "externally_observed", json.dumps({"reason": "tracker_before_consent"})))
    api.conn.commit()
    body = api.get("/api/v1/compliance/overview", headers=headers_).json()
    assert _req(body, bo.TRACKERS_KEY)["domains"][0]["reason"] == "tracker_before_consent"


# ── the real scan-completion hook ────────────────────────────────────────
def test_finishing_a_scan_queues_one_observation_only_when_the_feature_is_on(api, world, monkeypatch):
    from backend.tests.test_compliance_postgres import _finalize
    monkeypatch.setattr(config, "BROWSER_CONSENT_ENABLED", False)
    scan_off = _finalize(world, monkeypatch, domain_index=0)
    assert api.conn.execute("SELECT count(*) AS n FROM privacy_browser_jobs").fetchone()["n"] == 0
    monkeypatch.setattr(config, "BROWSER_CONSENT_ENABLED", True)
    scan_on = _finalize(world, monkeypatch, domain_index=1)
    jobs = api.conn.execute("SELECT domain_id, scan_id, status FROM privacy_browser_jobs").fetchall()
    assert [(str(j["domain_id"]), str(j["scan_id"]), j["status"]) for j in jobs] == [(api.domains[1], scan_on, "queued")]
    assert scan_off != scan_on


def test_a_failing_queue_never_changes_the_completed_scan(api, world, monkeypatch):
    import psycopg
    from backend.tests.test_compliance_postgres import _finalize

    def boom(scan_id):
        raise psycopg.OperationalError("queue unavailable")

    monkeypatch.setattr(browser_jobs, "enqueue_after_scan", boom)
    scan_id = _finalize(world, monkeypatch, domain_index=0)  # asserts status == completed
    assert api.conn.execute("SELECT status FROM scans WHERE id = %s", (scan_id,)).fetchone()["status"] == "completed"


# ── grants ───────────────────────────────────────────────────────────────
def test_api_roles_hold_nothing_on_the_jobs_table_and_the_app_role_only_its_minimal_grants(api):
    import os
    import pathlib
    import psycopg
    from psycopg.rows import dict_row
    sql = (pathlib.Path(__file__).resolve().parents[2] / "supabase/migrations/20261019300000_privacy_browser_jobs.sql").read_text()
    acl = ("SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE r.rolname END AS role, a.privilege_type AS priv "
           "FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a LEFT JOIN pg_roles r ON r.oid = a.grantee "
           "WHERE c.relnamespace = 'public'::regnamespace AND c.relname = 'privacy_browser_jobs'")
    with psycopg.connect(os.environ["CYPHWARD_TEST_DATABASE_ADMIN_URL"], row_factory=dict_row, autocommit=True) as conn:
        # What Supabase's default privileges would hand out, and more than the app role may keep.
        conn.execute("GRANT ALL ON privacy_browser_jobs TO anon, authenticated, PUBLIC, cyphward_app")
        assert any(r["role"] == "anon" and r["priv"] == "TRUNCATE" for r in conn.execute(acl).fetchall())
        conn.execute(sql)
        conn.execute(sql)  # idempotent
        rows = conn.execute(acl).fetchall()
        for role in ("anon", "authenticated", "PUBLIC"):
            assert [r for r in rows if r["role"] == role] == [], role
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                assert not conn.execute("SELECT has_table_privilege(%s, 'privacy_browser_jobs', %s) AS ok",
                                        (role.lower(), priv)).fetchone()["ok"], (role, priv)
        assert sorted(r["priv"] for r in rows if r["role"] == "cyphward_app") == ["INSERT", "SELECT", "UPDATE"]


# ── re-checks at completion, event loop, document inputs ─────────────────
def test_a_domain_revoked_mid_job_stores_nothing(api):
    job_id = queue(api)
    job = claim(api)
    api.conn.execute("UPDATE domains SET revoked_at = now() WHERE id = %s", (api.domains[0],))
    api.conn.commit()
    r = api.post(f"/api/v1/browser-worker/jobs/{job_id}/result", json=good_result(), headers=authority(job))
    assert r.status_code == 409 and rows(api) == []
    row = api.conn.execute("SELECT status, error_message FROM privacy_browser_jobs WHERE id=%s", (job_id,)).fetchone()
    assert row["status"] == "failed" and "no longer verified" in row["error_message"]
    api.conn.execute("UPDATE domains SET revoked_at = NULL WHERE id = %s", (api.domains[0],))
    api.conn.commit()


def test_an_unverified_domain_mid_job_stores_nothing(api):
    job_id = queue(api)
    job = claim(api)
    api.conn.execute("UPDATE domains SET verification_status = 'pending' WHERE id = %s", (api.domains[0],))
    api.conn.commit()
    assert api.post(f"/api/v1/browser-worker/jobs/{job_id}/result", json=good_result(), headers=authority(job)).status_code == 409
    assert rows(api) == []
    api.conn.execute("UPDATE domains SET verification_status = 'verified' WHERE id = %s", (api.domains[0],))
    api.conn.commit()


def test_a_final_url_outside_the_verified_domain_stores_nothing(api):
    job_id = queue(api)
    job = claim(api)
    domain = api.conn.execute("SELECT domain FROM domains WHERE id = %s", (api.domains[0],)).fetchone()["domain"]
    for bad in ("https://evil.example/", f"https://not{domain}/", f"https://{domain}.evil.example/"):
        r = api.post(f"/api/v1/browser-worker/jobs/{job_id}/result", json=good_result(final_url=bad), headers=authority(job))
        assert r.status_code == 409, bad
        assert rows(api) == []
        break  # the first refusal fails the job; the others are covered by the pure host check below
    from urllib.parse import urlsplit
    for bad in ("https://evil.example/", f"https://not{domain}/", f"https://{domain}.evil.example/"):
        host = urlsplit(bad).hostname
        assert not (host == domain or host.endswith("." + domain))


def test_completion_runs_off_the_event_loop(api, monkeypatch):
    import asyncio
    job_id = queue(api)
    job = claim(api)
    seen = {}
    real = browser_jobs.complete

    def spy(*a, **k):
        try:
            asyncio.get_running_loop()
            seen["on_loop"] = True
        except RuntimeError:
            seen["on_loop"] = False
        return real(*a, **k)

    monkeypatch.setattr(browser_jobs, "complete", spy)
    assert api.post(f"/api/v1/browser-worker/jobs/{job_id}/result", json=good_result(), headers=authority(job)).status_code == 202
    assert seen == {"on_loop": False}


def test_expired_browser_evidence_loses_its_sentence(api, world):
    headers_ = world["member"](api.org)
    _growth(api)
    _observe(api, 0)
    _observe(api, 1)
    import os
    import psycopg
    with psycopg.connect(os.environ["CYPHWARD_TEST_DATABASE_ADMIN_URL"], autocommit=True) as admin:  # the app role may not UPDATE evidence
        admin.execute("UPDATE compliance_evidence SET expires_at = now() - interval '1 day' WHERE details->>'observation' = 'browser_consent_v1'")
    text = api.get("/api/v1/compliance/overview", headers=headers_).text
    assert "the browser saw a consent banner" not in text and "The browser observed" not in text
    assert "evidence_expired" in text


def test_present_sentences_state_the_limit_of_one_visit(api, world):
    headers_ = world["member"](api.org)
    _growth(api)
    clean = {"cookies": [], "requests": {"total": 3, "first_party": 3, "third_party_hosts": []}}
    _observe(api, 0, **clean)
    _observe(api, 1, **clean)
    body = api.get("/api/v1/compliance/overview", headers=headers_).json()
    for key in bo.KEYS:
        view = _req(body, key)
        assert view["status"] == "present"
        assert "a page can behave differently for other visitors" in view["reason_text"], key
        assert all("a page can behave differently for other visitors" in d["reason_text"] for d in view["domains"]), key


def test_browser_rows_never_feed_document_inputs_or_the_static_previous_row(api, world):
    from backend.app.compliance import document_store
    _observe(api, 0)
    gathered = document_store.gather({"id": api.org, "name": "Org"})
    assert all(not rows_ for rows_ in gathered["observed"].values())
