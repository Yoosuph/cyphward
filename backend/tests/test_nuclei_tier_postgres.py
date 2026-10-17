"""Which Nuclei tier a claimed scan runs, on the real migrated database.

A domain gets a weekly run when none has been attempted for it in the last seven days; every other
scan is daily. The lookup is scoped by organisation and domain.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg.types.json

from backend.app.core import scan_admission as admission
from backend.app.core.nuclei_tier import choose_tier
from backend.tests.test_scan_execution_postgres import (  # noqa: F401 (fixtures)
    admission_db, disposable_postgres_url, execution_db,
)


def _scan(db, domain_index):
    conn, org, domains = db
    result = admission.admit_scan(org, domains[domain_index], request_scope="tier-test", request_key=str(uuid4()))
    return str(result.scan["id"])


def _observe(db, scan_id, tier, age_days=0):
    conn, _, _ = db
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    conn.execute(
        "INSERT INTO scan_results (scan_id, stage, raw_data, created_at) VALUES (%s, 'nuclei', %s, %s)",
        (scan_id, psycopg.types.json.Jsonb({"nuclei_findings": [], "tool_coverage": {"tier": tier}}), created))
    conn.commit()


def test_a_domain_with_no_weekly_run_gets_a_weekly_run(execution_db):
    _, org, domains = execution_db
    assert choose_tier(org, domains[0]) == "weekly"


def test_a_recent_weekly_run_makes_the_next_scan_daily(execution_db):
    _, org, domains = execution_db
    _observe(execution_db, _scan(execution_db, 0), "weekly", age_days=2)
    assert choose_tier(org, domains[0]) == "daily"


def test_a_weekly_run_older_than_seven_days_is_due_again(execution_db):
    _, org, domains = execution_db
    _observe(execution_db, _scan(execution_db, 0), "weekly", age_days=8)
    assert choose_tier(org, domains[0]) == "weekly"


def test_daily_runs_do_not_count_as_weekly(execution_db):
    _, org, domains = execution_db
    _observe(execution_db, _scan(execution_db, 0), "daily", age_days=1)
    assert choose_tier(org, domains[0]) == "weekly"


def test_another_domains_weekly_run_does_not_count(execution_db):
    _, org, domains = execution_db
    _observe(execution_db, _scan(execution_db, 1), "weekly", age_days=1)
    assert choose_tier(org, domains[0]) == "weekly"
    assert choose_tier(org, domains[1]) == "daily"


def test_the_lookup_is_scoped_to_the_organisation(execution_db):
    _, org, domains = execution_db
    _observe(execution_db, _scan(execution_db, 0), "weekly", age_days=1)
    assert choose_tier(str(uuid4()), domains[0]) == "weekly", "another organisation's id never sees this run"


# ── The claim carries the tier and the time it needs ───────────────────────

from backend.app.api import scanner_jobs as sj  # noqa: E402
from backend.tests.test_privacy_stage_postgres import _claim_headers, scanner_api  # noqa: E402,F401 (fixture)


def _finish(conn, scan_id):
    conn.execute("UPDATE scans SET status = 'completed', completed_at = now(), claimed_by = NULL, "
                 "claim_token = NULL, lease_expires_at = NULL, execution_phase = NULL WHERE id = %s", (scan_id,))
    conn.commit()


def test_the_first_claim_for_a_domain_is_weekly_with_the_longer_timeouts(execution_db, scanner_api):
    _scan(execution_db, 0)
    response = scanner_api.post("/api/v1/scanner/claim", headers=_claim_headers())
    assert response.status_code == 200
    job = response.json()
    assert job["nuclei_tier"] == "weekly"
    assert job["limits"]["stage_timeout_seconds"] >= 3600
    assert job["limits"]["recon_timeout_seconds"] >= 3600 + 900


def test_the_claim_after_a_weekly_run_is_daily_with_the_configured_timeouts(execution_db, scanner_api):
    conn, _, _ = execution_db
    first = _scan(execution_db, 0)
    assert scanner_api.post("/api/v1/scanner/claim", headers=_claim_headers()).json()["nuclei_tier"] == "weekly"
    _observe(execution_db, first, "weekly")
    _finish(conn, first)
    _scan(execution_db, 0)
    job = scanner_api.post("/api/v1/scanner/claim", headers=_claim_headers()).json()
    assert job["nuclei_tier"] == "daily"
    assert job["limits"]["stage_timeout_seconds"] == sj.SCANNER_STAGE_TIMEOUT_SECONDS
    assert job["limits"]["recon_timeout_seconds"] == sj.SCANNER_RECON_TIMEOUT_SECONDS


# ── Which open findings the worker is asked to re-verify ───────────────────

from backend.app.core.nuclei_tier import VERIFY_LIMIT, verification_targets  # noqa: E402


def _asset(db, domain_index, hostname):
    conn, org, domains = db
    row = conn.execute("INSERT INTO assets (org_id, domain_id, hostname, status, last_seen) "
                       "VALUES (%s, %s, %s, 'active', now()) RETURNING id", (org, domains[domain_index], hostname)).fetchone()
    conn.commit()
    return row["id"]


def _finding(db, asset_id, template_id, *, status="open", category="Nuclei Scan", title=None):
    conn, org, _ = db
    evidence = {"template_id": template_id} if template_id else {}
    conn.execute("INSERT INTO findings (org_id, asset_id, title, description, severity, category, evidence, "
                 "remediation, status) VALUES (%s, %s, %s, 'x', 'high', %s, %s, 'x', %s)",
                 (org, asset_id, title or f"Finding {template_id}", category, psycopg.types.json.Jsonb(evidence), status))
    conn.commit()


def test_open_nuclei_findings_of_the_domain_are_the_verification_targets(execution_db):
    _, org, domains = execution_db
    www = _asset(execution_db, 0, "www.acme.test")
    _finding(execution_db, www, "exposed-panel")
    _finding(execution_db, www, "git-config")
    assert verification_targets(org, domains[0]) == [
        {"host": "www.acme.test", "template_id": "exposed-panel"},
        {"host": "www.acme.test", "template_id": "git-config"},
    ]


def test_resolved_non_nuclei_and_template_less_findings_are_not_targets(execution_db):
    _, org, domains = execution_db
    www = _asset(execution_db, 0, "www.acme.test")
    _finding(execution_db, www, "fixed-already", status="resolved")
    _finding(execution_db, www, "x-frame", category="HTTP Headers")
    _finding(execution_db, www, None)
    assert verification_targets(org, domains[0]) == []


def test_targets_are_scoped_to_the_domain_and_the_organisation(execution_db):
    _, org, domains = execution_db
    _finding(execution_db, _asset(execution_db, 1, "www.other.test"), "exposed-panel")
    assert verification_targets(org, domains[0]) == []
    assert verification_targets(str(uuid4()), domains[1]) == []
    assert verification_targets(org, domains[1]) == [{"host": "www.other.test", "template_id": "exposed-panel"}]


def test_the_target_list_is_capped(execution_db):
    _, org, domains = execution_db
    www = _asset(execution_db, 0, "www.acme.test")
    for i in range(VERIFY_LIMIT + 5):
        _finding(execution_db, www, f"template-{i:03d}")
    assert len(verification_targets(org, domains[0])) == VERIFY_LIMIT


def test_the_claim_carries_the_open_findings_to_verify(execution_db, scanner_api):
    _finding(execution_db, _asset(execution_db, 0, "www.acme.test"), "exposed-panel")
    _scan(execution_db, 0)
    job = scanner_api.post("/api/v1/scanner/claim", headers=_claim_headers()).json()
    assert job["nuclei_verify"] == [{"host": "www.acme.test", "template_id": "exposed-panel"}]
