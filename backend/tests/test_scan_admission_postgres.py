"""Admission races against an explicitly isolated, migrated PostgreSQL DB.

Run with CYPHWARD_TEST_DATABASE_URL pointing to a disposable local database
named `cyphward_test`. This module never falls back to DATABASE_URL or .env.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
import pytest

import backend.app.api.billing as billing
import backend.app.core.scan_admission as scan_admission


@pytest.fixture(scope="session")
def disposable_postgres_url():
    url = os.environ.get("CYPHWARD_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set CYPHWARD_TEST_DATABASE_URL to a disposable local PostgreSQL database named cyphward_test")
    info = conninfo_to_dict(url)
    host = info.get("host", "")
    if info.get("dbname") != "cyphward_test" or host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Refusing PostgreSQL integration tests outside the local cyphward_test database")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT current_database() AS db, host(inet_server_addr()) AS server_addr, "
            "to_regclass('public.scan_launch_requests') IS NOT NULL AS migrated"
        ).fetchone()
    if row["db"] != "cyphward_test" or row["server_addr"] not in {"127.0.0.1", "::1"} or not row["migrated"]:
        pytest.fail("Disposable database identity or scan-admission migration check failed")
    return url


@pytest.fixture
def admission_db(disposable_postgres_url, monkeypatch):
    @contextmanager
    def get_db():
        conn = psycopg.connect(disposable_postgres_url, row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(scan_admission, "get_db", get_db)
    monkeypatch.setattr(billing, "get_db", get_db)
    conn = psycopg.connect(disposable_postgres_url, row_factory=dict_row)
    org_id = str(uuid4())
    domain_ids = [str(uuid4()), str(uuid4())]
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO organizations (id, name, slug, sector, plan) VALUES (%s, %s, %s, %s, %s)",
                (org_id, "Admission Race Test", f"admission-{org_id}", "Technology", "starter"),
            )
            for index, domain_id in enumerate(domain_ids):
                conn.execute(
                    "INSERT INTO domains (id, org_id, domain, verification_status, verification_token, created_at) "
                    "VALUES (%s, %s, %s, 'verified', %s, %s)",
                    (domain_id, org_id, f"{index}-{org_id}.example.test", f"token-{domain_id}",
                     datetime(2026, 1, 1 + index, tzinfo=timezone.utc)),
                )
        yield conn, org_id, domain_ids
    finally:
        conn.rollback()
        conn.execute("DELETE FROM organizations WHERE id = %s", (org_id,))
        conn.commit()
        conn.close()


def _race(call_a, call_b):
    barrier = Barrier(3)

    def run(call):
        barrier.wait(timeout=10)
        return call()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run, call_a)
        second = executor.submit(run, call_b)
        barrier.wait(timeout=10)
        return first.result(timeout=20), second.result(timeout=20)


def _counts(conn, org_id):
    scan_count = conn.execute("SELECT count(*) AS n FROM scans WHERE org_id = %s", (org_id,)).fetchone()["n"]
    key_count = conn.execute("SELECT count(*) AS n FROM scan_launch_requests WHERE org_id = %s", (org_id,)).fetchone()["n"]
    return scan_count, key_count


def test_same_key_race_commits_one_scan_and_replays(admission_db):
    conn, org_id, domains = admission_db
    scope = f"user:{uuid4()}"
    calls = [lambda: scan_admission.admit_scan(org_id, domains[0], request_scope=scope, request_key="same-key") for _ in range(2)]
    first, second = _race(*calls)
    assert {first.outcome, second.outcome} == {"created", "replayed"}
    assert first.scan["id"] == second.scan["id"]
    assert _counts(conn, org_id) == (1, 1)


def test_distinct_keys_cannot_start_overlapping_jobs(admission_db):
    conn, org_id, domains = admission_db
    scope = f"user:{uuid4()}"
    first, second = _race(
        lambda: scan_admission.admit_scan(org_id, domains[0], request_scope=scope, request_key="intent-a"),
        lambda: scan_admission.admit_scan(org_id, domains[0], request_scope=scope, request_key="intent-b"),
    )
    assert {first.outcome, second.outcome} == {"created", "active"}
    assert _counts(conn, org_id) == (1, 1)


def test_quota_race_across_distinct_domains_admits_only_last_allowance(admission_db):
    conn, org_id, domains = admission_db
    with conn.transaction():
        conn.execute(
            "INSERT INTO scans (org_id, domain_id, status, created_at) "
            "SELECT %s, %s, 'completed', clock_timestamp() FROM generate_series(1, 29)",
            (org_id, domains[0]),
        )
    scope = f"user:{uuid4()}"
    first, second = _race(
        lambda: scan_admission.admit_scan(org_id, domains[0], request_scope=scope, request_key="last-a"),
        lambda: scan_admission.admit_scan(org_id, domains[1], request_scope=scope, request_key="last-b"),
    )
    assert {first.outcome, second.outcome} == {"created", "quota"}
    assert _counts(conn, org_id) == (30, 1)


def test_same_key_payload_mismatch_conflicts_without_mutation(admission_db):
    conn, org_id, domains = admission_db
    scope = f"user:{uuid4()}"
    created = scan_admission.admit_scan(org_id, domains[0], request_scope=scope, request_key="fingerprint")
    with pytest.raises(scan_admission.AdmissionConflict) as error:
        scan_admission.admit_scan(org_id, domains[1], request_scope=scope, request_key="fingerprint")
    assert error.value.code == "idempotency_key_reused"
    assert _counts(conn, org_id) == (1, 1)
    assert str(created.scan["domain_id"]) == domains[0]


def test_terminal_replay_survives_exhausted_quota(admission_db):
    conn, org_id, domains = admission_db
    scope = f"user:{uuid4()}"
    first = scan_admission.admit_scan(org_id, domains[0], request_scope=scope, request_key="terminal-replay")
    with conn.transaction():
        conn.execute("UPDATE scans SET status = 'completed' WHERE id = %s", (first.scan["id"],))
        conn.execute(
            "INSERT INTO scans (org_id, domain_id, status, created_at) "
            "SELECT %s, %s, 'completed', clock_timestamp() FROM generate_series(1, 29)",
            (org_id, domains[1]),
        )
    replay = scan_admission.admit_scan(org_id, domains[0], request_scope=scope, request_key="terminal-replay")
    assert replay.outcome == "replayed"
    assert replay.scan["id"] == first.scan["id"]
    assert replay.scan["status"] == "completed"
    assert _counts(conn, org_id) == (30, 1)


def test_scheduler_uses_same_active_domain_guard_as_manual(admission_db):
    conn, org_id, domains = admission_db
    manual = scan_admission.admit_scan(org_id, domains[0], request_scope=f"user:{uuid4()}", request_key="manual")
    scheduled = scan_admission.admit_scan(
        org_id, domains[0], request_scope="scheduled:2026-10-13",
        request_key=f"domain:{domains[0]}",
    )
    assert manual.outcome == "created"
    assert scheduled.outcome == "active"
    assert _counts(conn, org_id) == (1, 1)


def test_scheduler_retry_after_completion_replays_original_for_same_utc_day(admission_db):
    conn, org_id, domains = admission_db
    scope = "scheduled:2026-10-13"
    key = f"domain:{domains[0]}"
    first = scan_admission.admit_scan(org_id, domains[0], request_scope=scope, request_key=key)
    with conn.transaction():
        conn.execute("UPDATE scans SET status = 'completed' WHERE id = %s", (first.scan["id"],))
    retry = scan_admission.admit_scan(org_id, domains[0], request_scope=scope, request_key=key)
    assert retry.outcome == "replayed"
    assert retry.scan["id"] == first.scan["id"]
    assert _counts(conn, org_id) == (1, 1)


def test_omitted_selector_replay_stays_bound_to_original_domain(admission_db):
    conn, org_id, domains = admission_db
    scope = f"user:{uuid4()}"
    first = scan_admission.admit_scan(org_id, None, request_scope=scope, request_key="default-domain")
    assert str(first.scan["domain_id"]) == domains[0]
    with conn.transaction():
        conn.execute("UPDATE domains SET created_at = %s WHERE id = %s",
                     (datetime(2025, 1, 1, tzinfo=timezone.utc), domains[1]))
    replay = scan_admission.admit_scan(org_id, None, request_scope=scope, request_key="default-domain")
    assert replay.outcome == "replayed"
    assert str(replay.scan["domain_id"]) == domains[0]


def test_same_raw_key_isolated_by_tenant(admission_db):
    conn, org_id, domains = admission_db
    other_org = str(uuid4())
    other_domain = str(uuid4())
    with conn.transaction():
        conn.execute(
            "INSERT INTO organizations (id, name, slug, sector, plan) VALUES (%s, %s, %s, %s, %s)",
            (other_org, "Second Admission Race Test", f"admission-{other_org}", "Technology", "starter"),
        )
        conn.execute(
            "INSERT INTO domains (id, org_id, domain, verification_status, verification_token) "
            "VALUES (%s, %s, %s, 'verified', %s)",
            (other_domain, other_org, f"{other_org}.example.test", f"token-{other_domain}"),
        )
    scope = f"user:{uuid4()}"
    try:
        first = scan_admission.admit_scan(org_id, domains[0], request_scope=scope, request_key="same-raw-key")
        second = scan_admission.admit_scan(other_org, other_domain, request_scope=scope, request_key="same-raw-key")
        assert first.outcome == second.outcome == "created"
        assert first.scan["id"] != second.scan["id"]
    finally:
        conn.rollback()
        conn.execute("DELETE FROM organizations WHERE id = %s", (other_org,))
        conn.commit()


def test_active_subscription_entitlement_overrides_org_plan(admission_db):
    conn, org_id, domains = admission_db
    with conn.transaction():
        conn.execute("UPDATE organizations SET plan = 'starter' WHERE id = %s", (org_id,))
        conn.execute(
            "INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, current_period_end) "
            "VALUES (%s, 'growth', 'active', 'manual', now(), now() + interval '30 days')",
            (org_id,),
        )
        conn.execute(
            "INSERT INTO scans (org_id, domain_id, status, created_at) "
            "SELECT %s, %s, 'completed', clock_timestamp() FROM generate_series(1, 30)",
            (org_id, domains[0]),
        )
    result = scan_admission.admit_scan(org_id, domains[1], request_scope=f"user:{uuid4()}", request_key="active-growth")
    assert result.outcome == "created"


def test_expired_subscription_falls_back_to_starter_quota(admission_db):
    conn, org_id, domains = admission_db
    with conn.transaction():
        conn.execute(
            "INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, current_period_end) "
            "VALUES (%s, 'growth', 'active', 'manual', now() - interval '60 days', now() - interval '30 days')",
            (org_id,),
        )
        conn.execute(
            "INSERT INTO scans (org_id, domain_id, status, created_at) "
            "SELECT %s, %s, 'completed', clock_timestamp() FROM generate_series(1, 30)",
            (org_id, domains[0]),
        )
    result = scan_admission.admit_scan(org_id, domains[1], request_scope=f"user:{uuid4()}", request_key="expired-growth")
    assert result.outcome == "quota"
    assert result.limit == 30


def test_first_subscription_write_serializes_with_admission(admission_db):
    conn, org_id, domains = admission_db
    with conn.transaction():
        conn.execute(
            "INSERT INTO scans (org_id, domain_id, status, created_at) "
            "SELECT %s, %s, 'completed', clock_timestamp() FROM generate_series(1, 30)",
            (org_id, domains[0]),
        )
    barrier = Barrier(3)
    with ThreadPoolExecutor(max_workers=2) as executor:
        launch = executor.submit(lambda: (barrier.wait(timeout=10), scan_admission.admit_scan(
            org_id, domains[1], request_scope=f"user:{uuid4()}", request_key="subscription-race"))[1])
        change = executor.submit(lambda: (barrier.wait(timeout=10), billing._save_subscription_plan(org_id, "growth"))[1])
        barrier.wait(timeout=10)
        admitted, subscription = launch.result(timeout=20), change.result(timeout=20)
    current = conn.execute("SELECT plan, status FROM subscriptions WHERE org_id = %s", (org_id,)).fetchone()
    assert subscription["plan"] == current["plan"] == "growth"
    assert current["status"] == "active"
    assert admitted.outcome in {"created", "quota"}
    scans, keys = _counts(conn, org_id)
    assert scans == (31 if admitted.outcome == "created" else 30)
    assert keys == (1 if admitted.outcome == "created" else 0)


def test_failure_after_scan_insert_rolls_back_scan_and_key(admission_db, disposable_postgres_url, monkeypatch):
    conn, org_id, domains = admission_db

    class CursorProxy:
        def __init__(self, cursor):
            self.cursor = cursor

        def __enter__(self):
            self.cursor.__enter__()
            return self

        def __exit__(self, *args):
            return self.cursor.__exit__(*args)

        def execute(self, sql, params=()):
            if sql.lstrip().startswith("INSERT INTO scan_launch_requests"):
                raise RuntimeError("injected key-write failure")
            self.cursor.execute(sql, params)
            return self

        def fetchone(self):
            return self.cursor.fetchone()

    class ConnectionProxy:
        def __init__(self, connection):
            self.connection = connection

        def transaction(self):
            return self.connection.transaction()

        def cursor(self):
            return CursorProxy(self.connection.cursor())

    @contextmanager
    def failing_get_db():
        connection = psycopg.connect(disposable_postgres_url, row_factory=dict_row)
        try:
            yield ConnectionProxy(connection)
        finally:
            connection.close()

    monkeypatch.setattr(scan_admission, "get_db", failing_get_db)
    with pytest.raises(RuntimeError, match="injected key-write failure"):
        scan_admission.admit_scan(org_id, domains[0], request_scope=f"user:{uuid4()}", request_key="rollback-probe")
    assert _counts(conn, org_id) == (0, 0)


def test_utc_quota_boundary_does_not_follow_session_timezone(disposable_postgres_url):
    utc = datetime(2026, 10, 1, 0, 15, tzinfo=timezone.utc)
    with psycopg.connect(disposable_postgres_url, row_factory=dict_row) as conn:
        conn.execute("SET TIME ZONE 'Pacific/Honolulu'")
        row = conn.execute(
            "SELECT (date_trunc('month', %s::timestamptz AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') AS period_start",
            (utc,),
        ).fetchone()
    assert row["period_start"] == datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
