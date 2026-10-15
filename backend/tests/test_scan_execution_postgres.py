"""Execution races on a synthetic, loopback-only cyphward_test database."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient

from backend.app.core import (
    database,
    scan_execution as ex,
    scan_admission as admission,
    cron_claim as cron,
)
from backend.app.core.execution_fence import ClaimLost, execution_scope
from backend.app.workflows import inngest_workflow as wf
from backend.app.core import scan_recovery
from backend.app.api import scanner_jobs as api, scans as scans_api
from backend.app.main import app
from backend.tests.test_scan_admission_postgres import (
    admission_db as admission_db,
    disposable_postgres_url as disposable_postgres_url,
)


@pytest.fixture
def execution_db(admission_db, disposable_postgres_url, monkeypatch):
    @contextmanager
    def get_db():
        with psycopg.connect(disposable_postgres_url, row_factory=dict_row) as conn:
            yield conn

    monkeypatch.setattr(ex, "get_db", get_db)
    monkeypatch.setattr(database, "get_db", get_db)
    yield admission_db


def queued(db):
    conn, org, domains = db
    result = admission.admit_scan(
        org, domains[0], request_scope="execution-test", request_key=str(uuid4())
    )
    return str(result.scan["id"])


def held(db, phase="worker"):
    sid = queued(db)
    row = ex.claim_recon(
        "same-worker" if phase == "worker" else "local:test", phase, 120, sid
    )
    return ex.claim_from_row(row)


def expire(conn, claim):
    conn.execute(
        "UPDATE scans SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
        (claim.scan_id,),
    )
    conn.commit()


def test_target_selection_is_persisted_only_for_current_producing_attempt(execution_db):
    from shared.scan_scope import select_targets
    conn, _, _ = execution_db
    old = held(execution_db)
    plan = select_targets("acme.test", ["acme.test"], ["a.acme.test"],
                          ["z.acme.test"], max_hosts=500, dns_max_hosts=2).payload()
    ex.store_observation(old, "discovery", {"target_selection": plan})
    expire(conn, old)
    new = ex.claim_from_row(ex.claim_recon("replacement", "worker", 120, old.scan_id))
    with pytest.raises(ClaimLost):
        ex.store_observation(old, "discovery", {"target_selection": {"stale": True}})
    current_plan = select_targets("acme.test", ["acme.test"], [], [],
                                  max_hosts=500, dns_max_hosts=2).payload()
    ex.store_observation(new, "discovery", {"target_selection": current_plan})
    core = ex.handoff_to_core(new)
    with execution_scope(core):
        assert wf._load_observations(old.scan_id) == {"discovery": {"target_selection": current_plan}}
    saved = conn.execute("SELECT attempt_generation,raw_data FROM scan_results WHERE scan_id=%s AND stage='discovery' ORDER BY attempt_generation", (old.scan_id,)).fetchall()
    assert [(r["attempt_generation"], r["raw_data"]["target_selection"]) for r in saved] == [
        (old.observation_generation, plan), (new.observation_generation, current_plan)]


def row(conn, scan_id):
    return conn.execute("SELECT * FROM scans WHERE id=%s", (scan_id,)).fetchone()


def race(*functions):
    barrier = Barrier(len(functions))

    def run(fn):
        barrier.wait(timeout=5)
        try:
            return fn()
        except ClaimLost:
            return "lost"

    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return list(pool.map(run, functions))


def cancel(scan_id):
    return database.execute_one(
        "UPDATE scans SET status='cancelled',completed_at=clock_timestamp(),claim_token=NULL,claimed_by=NULL,lease_expires_at=NULL,execution_phase=NULL,claim_generation=claim_generation+1 WHERE id=%s AND status IN ('queued','running') RETURNING id",
        (scan_id,),
    )


def finish(claim, org):
    return ex.finish_assessment(
        claim,
        org,
        {"score": 84, "subscores": [], "factors": [], "risk_points": 1},
        {"scoring": {"status": "completed", "score": 84}},
        {"score": 84},
        {
            "model": "test-v2",
            "scope": "organization",
            "title": "Synthetic completion",
            "body": "Test",
            "severity": "info",
        },
    )


def no_external(monkeypatch):
    async def discover(domain):
        return [], []

    monkeypatch.setattr(wf, "discover_subdomains_with_health", discover)
    monkeypatch.setattr(wf, "_tool_available", lambda _: False)
    monkeypatch.setattr(
        wf, "get_ai_provider", lambda: (_ for _ in ()).throw(RuntimeError("AI stubbed"))
    )


def test_atomic_claim_duplicate_delivery(execution_db):
    sid = queued(execution_db)
    rows = race(
        lambda: ex.claim_recon("same", "worker", 120, sid),
        lambda: ex.claim_recon("same", "worker", 120, sid),
    )
    assert sum(r is not None for r in rows) == 1
    assert row(execution_db[0], sid)["claim_generation"] == 1


def test_expiry_cannot_be_revived_and_same_scanner_reuse_is_fenced(execution_db):
    conn, _, _ = execution_db
    old = held(execution_db)
    ex.store_observation(old, "dns", {"old": True})
    expire(conn, old)
    with pytest.raises(ClaimLost):
        ex.renew_claim(old, 120)
    new = ex.claim_from_row(ex.claim_recon(old.owner, "worker", 120, old.scan_id))
    assert new.generation == old.generation + 1 and new.token != old.token
    for write in [
        lambda: ex.report_progress(old, "dns", {"status": "completed"}, 120),
        lambda: ex.store_observation(old, "dns", {"stale": True}),
        lambda: ex.handoff_to_core(old),
        lambda: ex.fail_claim(old, "stale"),
    ]:
        with pytest.raises(ClaimLost):
            write()
    ex.store_observation(new, "discovery", {"discovered_hosts": []})
    core = ex.handoff_to_core(new)
    with execution_scope(core):
        observations = wf._load_observations(core.scan_id)
    assert observations == {"discovery": {"discovered_hosts": []}}
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM scan_results WHERE scan_id=%s", (old.scan_id,)
        ).fetchone()["n"]
        == 2
    )


def test_expired_before_takeover_rejects_every_write(execution_db):
    conn, _, _ = execution_db
    claim = held(execution_db)
    expire(conn, claim)
    before = row(conn, claim.scan_id)["stage_progress"]
    for write in [
        lambda: ex.report_progress(claim, "dns", {"status": "running"}, 120),
        lambda: ex.store_observation(claim, "dns", {}),
        lambda: ex.fail_claim(claim, "expired"),
        lambda: ex.handoff_to_core(claim),
    ]:
        with pytest.raises(ClaimLost):
            write()
    assert row(conn, claim.scan_id)["stage_progress"] == before
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM scan_results WHERE scan_id=%s", (claim.scan_id,)
        ).fetchone()["n"]
        == 0
    )


def test_observation_replacement_rollback_preserves_previous_payload(
    execution_db, monkeypatch
):
    conn, _, _ = execution_db
    claim = held(execution_db)
    ex.store_observation(claim, "dns", {"value": "first"})
    original = ex.owned_transaction

    @contextmanager
    def interrupted(c):
        with original(c) as pair:
            yield pair
            raise RuntimeError("after-write interruption")

    monkeypatch.setattr(ex, "owned_transaction", interrupted)
    with pytest.raises(RuntimeError):
        ex.store_observation(claim, "dns", {"value": "second"})
    assert conn.execute(
        "SELECT raw_data FROM scan_results WHERE scan_id=%s", (claim.scan_id,)
    ).fetchone()["raw_data"] == {"value": "first"}


def test_concurrent_observation_retries_leave_one_payload(execution_db):
    conn, _, _ = execution_db
    claim = held(execution_db)
    race(
        lambda: ex.store_observation(claim, "dns", {"value": 1}),
        lambda: ex.store_observation(claim, "dns", {"value": 1}),
    )
    rows = conn.execute(
        "SELECT raw_data FROM scan_results WHERE scan_id=%s", (claim.scan_id,)
    ).fetchall()
    assert rows == [{"raw_data": {"value": 1}}]


def test_cancel_vs_observation_and_complete(execution_db):
    conn, _, _ = execution_db
    claim = held(execution_db)
    race(
        lambda: ex.store_observation(claim, "dns", {"before_cancel": True}),
        lambda: cancel(claim.scan_id),
    )
    assert row(conn, claim.scan_id)["status"] == "cancelled"
    before = conn.execute(
        "SELECT raw_data FROM scan_results WHERE scan_id=%s", (claim.scan_id,)
    ).fetchall()
    with pytest.raises(ClaimLost):
        ex.store_observation(claim, "dns", {"after_cancel": True})
    assert (
        conn.execute(
            "SELECT raw_data FROM scan_results WHERE scan_id=%s", (claim.scan_id,)
        ).fetchall()
        == before
    )
    with pytest.raises(ClaimLost):
        ex.handoff_to_core(claim)


def test_cancel_vs_handoff_never_resurrects(execution_db):
    conn, _, _ = execution_db
    claim = held(execution_db)
    race(lambda: ex.handoff_to_core(claim), lambda: cancel(claim.scan_id))
    assert row(conn, claim.scan_id)["status"] == "cancelled"
    with pytest.raises(ClaimLost):
        ex.fail_claim(claim, "late failure")


def test_core_takeover_fences_indirect_findings_assets_scores_and_progress(
    execution_db,
):
    conn, org, domains = execution_db
    worker = held(execution_db)
    core = ex.handoff_to_core(worker)
    with pytest.raises(ClaimLost):
        ex.store_observation(worker, "dns", {})
    expire(conn, core)
    assert ex.claim_recon(worker.owner, "worker", 120, worker.scan_id) is None
    latest = ex.claim_core_recovery()[0]
    assert (
        latest.generation > core.generation
        and latest.observation_generation == worker.generation
    )
    mutations = [
        lambda: database.execute_one(
            "INSERT INTO assets(org_id,domain_id,hostname) VALUES (%s,%s,'stale.example.test') RETURNING id",
            (org, domains[0]),
        ),
        lambda: database.execute_query(
            "INSERT INTO findings(org_id,title,description,severity,category) VALUES (%s,'stale','stale','low','test')",
            (org,),
        ),
        lambda: database.execute_many(
            "UPDATE scans SET stage_progress=%s::jsonb WHERE id=%s",
            [("{}", core.scan_id)],
        ),
        lambda: finish(core, org),
        lambda: ex.fail_claim(core, "stale"),
    ]
    with execution_scope(core):
        for mutate in mutations:
            with pytest.raises(ClaimLost):
                mutate()
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM assets WHERE org_id=%s", (org,)
        ).fetchone()["n"]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM findings WHERE org_id=%s", (org,)
        ).fetchone()["n"]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM score_snapshots WHERE scan_id=%s",
            (core.scan_id,),
        ).fetchone()["n"]
        == 0
    )
    ex.store_observation(latest, "security_checks", {"current": True})


def test_terminal_records_are_atomic_and_replay_cannot_duplicate(
    execution_db, monkeypatch
):
    conn, org, _ = execution_db
    core = ex.handoff_to_core(held(execution_db))
    original = ex.owned_transaction

    @contextmanager
    def interrupted(c):
        with original(c) as pair:
            yield pair
            raise RuntimeError("before terminal commit")

    monkeypatch.setattr(ex, "owned_transaction", interrupted)
    with pytest.raises(RuntimeError):
        finish(core, org)
    assert row(conn, core.scan_id)["status"] == "running"
    for table in ["score_snapshots", "notifications", "audit_log"]:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM " + table + " WHERE org_id=%s", (org,)
            ).fetchone()["n"]
            == 0
        )
    monkeypatch.setattr(ex, "owned_transaction", original)
    finish(core, org)
    with pytest.raises(ClaimLost):
        finish(core, org)
    assert row(conn, core.scan_id)["status"] == "completed"
    for table in ["score_snapshots", "notifications", "audit_log"]:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM " + table + " WHERE org_id=%s", (org,)
            ).fetchone()["n"]
            == 1
        )


def test_core_restart_reuses_recon_and_stale_attempt_cannot_finalize(
    execution_db, monkeypatch
):
    conn, _, _ = execution_db
    worker = held(execution_db)
    ex.store_observation(worker, "discovery", {"discovered_hosts": []})
    core = ex.handoff_to_core(worker)
    no_external(monkeypatch)
    original = wf._store_observation

    def interrupt(scan_id, stage, data):
        original(scan_id, stage, data)
        if stage == "security_checks":
            expire(conn, core)

    monkeypatch.setattr(wf, "_store_observation", interrupt)
    first = asyncio.run(wf.finalize_scan(core.scan_id, core))
    assert first["claim_lost"] and row(conn, core.scan_id)["status"] == "running"
    new = ex.claim_core_recovery()[0]
    monkeypatch.setattr(wf, "_store_observation", original)
    second = asyncio.run(wf.finalize_scan(core.scan_id, new))
    assert second["status"] == "completed"
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM score_snapshots WHERE scan_id=%s",
            (core.scan_id,),
        ).fetchone()["n"]
        == 1
    )


def test_duplicate_local_events_have_one_pipeline_and_snapshot(
    execution_db, monkeypatch
):
    conn, _, _ = execution_db
    sid = queued(execution_db)
    no_external(monkeypatch)
    monkeypatch.setattr(wf, "SCANNER_MODE", "local")
    calls = []

    async def discover(domain):
        calls.append(domain)
        await asyncio.sleep(0.05)
        return [], []

    monkeypatch.setattr(wf, "discover_subdomains_with_health", discover)

    async def run():
        return await asyncio.gather(
            wf.execute_scan_pipeline(sid), wf.execute_scan_pipeline(sid)
        )

    results = asyncio.run(run())
    assert len(calls) == 1 and sum(r.get("status") == "completed" for r in results) == 1
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM score_snapshots WHERE scan_id=%s", (sid,)
        ).fetchone()["n"]
        == 1
    )


def test_lost_local_dispatch_is_consumed_from_queue(execution_db, monkeypatch):
    conn, _, _ = execution_db
    sid = queued(execution_db)
    no_external(monkeypatch)
    monkeypatch.setattr(wf, "SCANNER_MODE", "local")
    monkeypatch.setattr(scan_recovery, "SCANNER_MODE", "local")

    async def run():
        stop = asyncio.Event()
        original = wf.finalize_scan

        async def finalized(s, c):
            result = await original(s, c)
            stop.set()
            return result

        monkeypatch.setattr(wf, "finalize_scan", finalized)
        await asyncio.wait_for(scan_recovery.recover_scan_queue(stop), timeout=5)

    asyncio.run(run())
    assert row(conn, sid)["status"] == "completed"


def test_heartbeat_revocation_cancels_external_work(execution_db):
    claim = held(execution_db, "local")
    stopped = []

    async def run():
        entered = asyncio.Event()

        async def work():
            entered.set()
            try:
                await asyncio.sleep(10)
            finally:
                stopped.append(True)

        task = asyncio.create_task(ex.run_owned(claim, work, 0.3))
        await entered.wait()
        await asyncio.to_thread(cancel, claim.scan_id)
        result = await asyncio.wait_for(task, timeout=3)
        assert result["cancelled"] is True

    asyncio.run(run())
    assert stopped == [True]


def test_stale_scheduler_cannot_complete_release_or_admit(execution_db):
    conn, org, domains = execution_db
    name = "test-" + str(uuid4())
    day = date(2026, 10, 13)
    old = cron.claim_cron_run(name, day, "same-process")
    conn.execute(
        "UPDATE cron_runs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE cron_name=%s",
        (name,),
    )
    conn.commit()
    new = cron.claim_cron_run(name, day, "same-process")
    assert new["claim_generation"] == old["claim_generation"] + 1
    assert not cron.complete_cron_run(name, day, old) and not cron.release_cron_run(
        name, day, old
    )
    with pytest.raises(ClaimLost):
        admission.admit_scan(
            org,
            domains[0],
            request_scope="scheduled:test",
            request_key="one",
            cron_authority=old,
        )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM scans WHERE org_id=%s", (org,)
        ).fetchone()["n"]
        == 0
    )
    assert cron.complete_cron_run(name, day, new) and not cron.release_cron_run(
        name, day, new
    )
    conn.execute("DELETE FROM cron_runs WHERE cron_name=%s", (name,))
    conn.commit()


def test_current_scan_detail_excludes_older_attempts(execution_db):
    conn, org, _ = execution_db
    claim = held(execution_db)
    conn.execute(
        "INSERT INTO scan_results(scan_id,stage,raw_data) VALUES (%s,'dns','{\"legacy\":true}')",
        (claim.scan_id,),
    )
    conn.commit()
    ex.store_observation(claim, "discovery", {"new": True})
    result = scans_api.get_scan_detail(claim.scan_id, org={"id": org})
    assert len(result["raw_results"]) == 1 and result["raw_results"][0]["raw_data"] == {
        "new": True
    }
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM scan_results WHERE scan_id=%s", (claim.scan_id,)
        ).fetchone()["n"]
        == 2
    )


def test_protocol_mismatch_does_not_allocate_and_missing_authority_does_not_write(
    execution_db, monkeypatch
):
    conn, _, _ = execution_db
    sid = queued(execution_db)
    monkeypatch.setattr(api, "SCANNER_MODE", "remote")
    monkeypatch.setattr(api, "SCANNER_API_KEY", "test-worker-key")
    import time

    headers = {
        "Authorization": "Bearer test-worker-key",
        "X-Scanner-Id": "same-worker",
        "X-Timestamp": str(int(time.time())),
    }
    client = TestClient(app)
    assert client.post("/api/v1/scanner/claim", headers=headers).status_code == 426
    assert row(conn, sid)["status"] == "queued"
    headers["X-Scanner-Protocol"] = "2"
    payload = client.post("/api/v1/scanner/claim", headers=headers).json()
    assert payload["version"] == 2 and payload["claim_generation"] == 1
    assert (
        client.post(
            f"/api/v1/scanner/jobs/{sid}/observations",
            headers=headers,
            json={"stage": "dns", "data": {}},
        ).status_code
        == 422
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM scan_results WHERE scan_id=%s", (sid,)
        ).fetchone()["n"]
        == 0
    )


def test_ai_deadline_does_not_strand_mandatory_completion(execution_db, monkeypatch):
    conn, _, _ = execution_db
    core = ex.handoff_to_core(held(execution_db))
    no_external(monkeypatch)

    class SlowAI:
        async def generate_executive_summary(self, *args):
            await asyncio.sleep(10)

    monkeypatch.setattr(wf, "get_ai_provider", lambda: SlowAI())
    monkeypatch.setattr(wf, "CORE_AI_TIMEOUT_SECONDS", 0.01)
    result = asyncio.run(wf.finalize_scan(core.scan_id, core))
    assert (
        result["status"] == "completed"
        and result["stage_progress"]["ai_analysis"]["status"] == "failed"
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM score_snapshots WHERE scan_id=%s",
            (core.scan_id,),
        ).fetchone()["n"]
        == 1
    )


def test_scan_replay_does_not_expose_worker_token(execution_db):
    from fastapi import BackgroundTasks

    conn, org, domains = execution_db
    request = admission.admit_scan(
        org, domains[0], request_scope="user:test", request_key="public-replay"
    )
    claim = ex.claim_from_row(
        ex.claim_recon("worker", "worker", 120, str(request.scan["id"]))
    )
    response = asyncio.run(
        scans_api.launch_scan(
            scans_api.LaunchScanRequest(domain_id=domains[0]),
            BackgroundTasks(),
            org={"id": org, "current_user_id": "test"},
            idempotency_key="public-replay",
        )
    )
    assert response["replayed"] is True and "claim_token" not in response["scan"]
    assert claim.token not in str(response)
    assert all(
        "claim_token" not in item for item in scans_api.list_scans(org={"id": org})
    )
    assert (
        "claim_token"
        not in scans_api.get_scan_detail(claim.scan_id, org={"id": org})["scan"]
    )


def test_unverified_queued_jobs_do_not_starve_local_recovery(execution_db, monkeypatch):
    conn, org, domains = execution_db
    for domain in domains:
        admission.admit_scan(
            org, domain, request_scope="starvation-test", request_key=str(uuid4())
        )
    conn.execute(
        "UPDATE domains SET verification_status='pending' WHERE org_id=%s", (org,)
    )
    third = str(uuid4())
    conn.execute(
        "INSERT INTO domains(id,org_id,domain,verification_status,verification_token) VALUES (%s,%s,'queue-recovery.example.test','verified','synthetic')",
        (third, org),
    )
    conn.commit()
    sid = str(
        admission.admit_scan(
            org, third, request_scope="starvation-test", request_key="verified"
        ).scan["id"]
    )
    no_external(monkeypatch)
    monkeypatch.setattr(wf, "SCANNER_MODE", "local")
    monkeypatch.setattr(scan_recovery, "SCANNER_MODE", "local")

    async def run():
        stop = asyncio.Event()
        original = wf.finalize_scan

        async def finalized(s, c):
            result = await original(s, c)
            stop.set()
            return result

        monkeypatch.setattr(wf, "finalize_scan", finalized)
        await asyncio.wait_for(scan_recovery.recover_scan_queue(stop), timeout=5)

    asyncio.run(run())
    assert row(conn, sid)["status"] == "completed"
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM scans WHERE org_id=%s AND status='queued'",
            (org,),
        ).fetchone()["n"]
        == 2
    )


def test_expired_attempt_cannot_overlap_a_transaction_already_holding_the_scan(
    execution_db,
):
    import time
    from threading import Event

    conn, _, _ = execution_db
    sid = queued(execution_db)
    claim = ex.claim_from_row(ex.claim_recon("worker", "worker", 1, sid))
    entered = Event()
    release = Event()

    def write_in_flight():
        with ex.owned_transaction(claim) as (cur, _):
            entered.set()
            assert release.wait(timeout=5)
            cur.execute(
                "INSERT INTO scan_results(scan_id,stage,raw_data,attempt_generation) VALUES (%s,%s,%s::jsonb,%s)",
                (sid, "dns", '{"first":true}', claim.observation_generation),
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(write_in_flight)
        assert entered.wait(timeout=3)
        try:
            time.sleep(1.1)
            assert ex.claim_recon("worker", "worker", 120, sid) is None
        finally:
            release.set()
        future.result(timeout=3)
    new = ex.claim_from_row(ex.claim_recon("worker", "worker", 120, sid))
    ex.store_observation(new, "dns", {"second": True})
    with pytest.raises(ClaimLost):
        ex.store_observation(claim, "dns", {"stale": True})
    rows = conn.execute(
        "SELECT attempt_generation,raw_data FROM scan_results WHERE scan_id=%s ORDER BY attempt_generation",
        (sid,),
    ).fetchall()
    assert rows == [
        {"attempt_generation": claim.generation, "raw_data": {"first": True}},
        {"attempt_generation": new.generation, "raw_data": {"second": True}},
    ]


def test_late_progress_is_monotonic_with_independent_connections(execution_db):
    conn, _, _ = execution_db
    claim = held(execution_db)
    race(
        lambda: ex.report_progress(claim, "dns", {"status": "running"}, 120),
        lambda: ex.report_progress(
            claim, "dns", {"status": "completed", "items": 3}, 120
        ),
    )
    assert row(conn, claim.scan_id)["stage_progress"]["dns"]["status"] == "completed"
    ex.report_progress(claim, "http", {"status": "running"}, 120)
    assert ex.report_progress(claim, "dns", {"status": "running"}, 120) == "completed"
    ex.report_progress(claim, "dns", {"status": "completed", "items": 3}, 120)
    final = row(conn, claim.scan_id)
    assert (
        final["current_stage"] == "http"
        and final["stage_progress"]["dns"]["status"] == "completed"
    )


def test_unassessed_completion_atomically_persists_null_score_and_coverage(execution_db, monkeypatch):
    conn, org, _ = execution_db
    worker = held(execution_db)
    ex.store_observation(worker, "discovery", {"target_selection": {
        "version": 1, "selected_hosts": [], "omitted_hosts": {},
    }})
    core = ex.handoff_to_core(worker)
    no_external(monkeypatch)
    result = asyncio.run(wf.finalize_scan(core.scan_id, core))
    assert result["status"] == "completed"
    assert result["score"] is None
    scan = row(conn, core.scan_id)
    snapshot = conn.execute("SELECT * FROM score_snapshots WHERE scan_id=%s", (core.scan_id,)).fetchone()
    assert scan["score"] is None and snapshot["score"] is None
    assert snapshot["model"] == "cyphward-risk-v3"
    assert snapshot["assessment_coverage"]["state"] == "unassessed"
    assert snapshot["assessment_coverage"]["evaluated_checks"] == 0
    assert scan["stage_progress"]["scoring"]["coverage"] == snapshot["assessment_coverage"]
    notifications = conn.execute("SELECT body FROM notifications WHERE org_id=%s AND type='scan_completed'", (org,)).fetchall()
    assert len(notifications) == 1
    assert "No score" in notifications[0]["body"]
    assert "None" not in notifications[0]["body"]
    assert "/100" not in notifications[0]["body"]
