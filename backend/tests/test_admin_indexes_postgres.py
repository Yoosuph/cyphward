"""Admin phase 2 indexes (supabase/migrations/20261031100000_admin_indexes.sql) against the local PostgreSQL.

Loads a 50,000-row fixture (scans, findings, customer audit rows and owner audit rows, spread over two years,
plus 2,000 organisations, 5,000 people and 20,000 sessions) inside one transaction, runs ANALYZE, and checks with
EXPLAIN that the owner console's top analytics and list queries use an index. The statements are captured from the
real code paths (owner_analytics, owner_lists, owner_views), not copied, so a change to a query is checked too.
Planner settings are left at their defaults. Everything is rolled back at the end.

Run with CYPHWARD_TEST_DATABASE_ADMIN_URL pointing at the local cyphward_test database.
"""
import json
import os
from typing import Any, Dict, List, Tuple

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

ROWS = 50_000
MIGRATION_INDEXES = {
    "idx_organizations_created", "idx_profiles_created", "idx_organization_members_org", "idx_owner_audit_target",
    "idx_auth_sessions_user_created", "idx_findings_created", "idx_audit_log_created", "idx_audit_log_user_created",
    "idx_scans_created", "idx_scans_org_created",
}


@pytest.fixture(scope="module")
def admin_url():
    url = os.environ.get("CYPHWARD_TEST_DATABASE_ADMIN_URL")
    if not url:
        pytest.skip("Set CYPHWARD_TEST_DATABASE_ADMIN_URL (local cyphward_test)")
    info = conninfo_to_dict(url)
    if info.get("dbname") != "cyphward_test" or info.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Refusing the index check outside the local cyphward_test database")
    return url


@pytest.fixture(scope="module")
def loaded(admin_url):
    """One connection holding the 50,000-row fixture in an open transaction; rolled back afterwards."""
    conn = psycopg.connect(admin_url, row_factory=dict_row)
    try:
        conn.execute("SET LOCAL statement_timeout = '120s'")
        conn.execute("""
            CREATE TEMP TABLE fx_org ON COMMIT DROP AS
            SELECT gen_random_uuid() AS id, g AS n FROM generate_series(1, 2000) g;
            INSERT INTO organizations (id, name, slug, plan, created_at)
              SELECT id, 'Fixture org ' || n, 'fx-org-' || n || '-' || left(id::text, 8),
                     CASE WHEN n % 2 = 0 THEN 'growth' ELSE 'starter' END,
                     now() - (n % 730) * interval '1 day' FROM fx_org;
            CREATE TEMP TABLE fx_dom ON COMMIT DROP AS SELECT gen_random_uuid() AS id, id AS org_id, n FROM fx_org;
            INSERT INTO domains (id, org_id, domain, verification_token, verification_status)
              SELECT id, org_id, 'fx-' || n || '.test', 'tok', 'verified' FROM fx_dom;
            CREATE TEMP TABLE fx_user ON COMMIT DROP AS
            SELECT gen_random_uuid() AS id, g AS n FROM generate_series(1, 5000) g;
            INSERT INTO profiles (id, email, full_name, created_at)
              SELECT id, 'fx-' || n || '-' || left(id::text, 8) || '@fixture.test', 'Fixture person',
                     now() - (n % 730) * interval '1 day' FROM fx_user;
            INSERT INTO organization_members (user_id, org_id, role)
              SELECT u.id, o.id, CASE WHEN u.n <= 2000 THEN 'owner' ELSE 'member' END
              FROM fx_user u JOIN fx_org o ON o.n = 1 + (u.n - 1) % 2000;
        """)
        conn.execute("""
            INSERT INTO scans (org_id, domain_id, status, scan_type, created_at)
              SELECT d.org_id, d.id, (ARRAY['completed','failed','cancelled'])[1 + g % 3], 'EXTERNAL_ASSESSMENT',
                     now() - (g % 730) * interval '1 day' - (g % 1440) * interval '1 minute'
              FROM generate_series(1, {rows}) g JOIN fx_dom d ON d.n = 1 + g % 2000;
            INSERT INTO findings (org_id, title, description, remediation, severity, status, created_at)
              SELECT o.id, 'Fixture finding', 'd', 'r', (ARRAY['critical','high','medium','low','info'])[1 + g % 5],
                     'open', now() - (g % 730) * interval '1 day'
              FROM generate_series(1, {rows}) g JOIN fx_org o ON o.n = 1 + g % 2000;
            INSERT INTO audit_log (org_id, user_id, action, resource_type, metadata, created_at)
              SELECT o.id, u.id, 'fixture.action', 'fixture', '{}'::jsonb, now() - (g % 730) * interval '1 day'
              FROM generate_series(1, {rows}) g JOIN fx_org o ON o.n = 1 + g % 2000
              JOIN fx_user u ON u.n = 1 + g % 5000;
            INSERT INTO owner_audit (actor_email, action, outcome, target_type, target_id, metadata, created_at)
              SELECT 'owner@fixture.test', 'owner.view.organization', 'success', 'organization', o.id::text,
                     '{}'::jsonb, now() - (g % 730) * interval '1 day'
              FROM generate_series(1, {rows}) g JOIN fx_org o ON o.n = 1 + g % 2000;
            INSERT INTO auth_sessions (user_id, refresh_token_hash, created_at, expires_at)
              SELECT u.id, 'fx-' || g, now() - (g % 730) * interval '1 day', now() + interval '1 day'
              FROM generate_series(1, 20000) g JOIN fx_user u ON u.n = 1 + g % 5000;
        """.replace("{rows}", str(ROWS)))
        for table in ("organizations", "domains", "profiles", "organization_members", "scans", "findings",
                      "audit_log", "owner_audit", "auth_sessions", "subscriptions", "organization_suspensions"):
            conn.execute(f"ANALYZE {table}")
        sample = conn.execute("SELECT id FROM fx_org WHERE n = 7").fetchone()["id"]
        yield conn, str(sample)
    finally:
        conn.rollback()
        conn.close()


def _plan(conn, sql: str, params: Any) -> Dict[str, Any]:
    row = conn.execute("EXPLAIN (FORMAT JSON) " + sql, params).fetchone()
    return list(row.values())[0][0]["Plan"]


def _nodes(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = [plan]
    for child in plan.get("Plans", []):
        out.extend(_nodes(child))
    return out


def _indexes(plan) -> set:
    return {n["Index Name"] for n in _nodes(plan) if "Index Name" in n}


def _seq_scans(plan) -> set:
    return {n.get("Relation Name") for n in _nodes(plan) if n["Node Type"] == "Seq Scan"}


def _capture_bounded(monkeypatch, call) -> List[Tuple[str, Any]]:
    from backend.app.core import owner as owner_mod, owner_reads
    captured: List[Tuple[str, Any]] = []
    monkeypatch.setattr(owner_mod, "audit", lambda *a, **k: None)

    def fake(statements):
        captured.extend(statements)
        return [[] for _ in statements]

    monkeypatch.setattr(owner_reads, "bounded_read", fake)
    call()
    return captured


def _capture_rows(monkeypatch, call, org_id=None) -> List[Tuple[str, Any]]:
    from backend.app.api import owner_views
    captured: List[Tuple[str, Any]] = []
    monkeypatch.setattr(owner_views, "_view", lambda *a, **k: None)
    monkeypatch.setattr(owner_views, "_rows", lambda sql, params=None: captured.append((sql, params)) or [])
    monkeypatch.setattr(owner_views, "execute_one", lambda sql, params=None: (
        {"id": org_id, "name": "x"} if "FROM organizations" in sql else None))
    call()
    return captured


OWNER = {"user_id": "u", "email": "owner@fixture.test", "session_id": "s"}


def test_the_migration_created_every_index(loaded):
    conn, _ = loaded
    names = {r["indexname"] for r in conn.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'").fetchall()}
    assert MIGRATION_INDEXES <= names, MIGRATION_INDEXES - names


def test_analytics_timeseries_uses_indexes(loaded, monkeypatch):
    from backend.app.api import owner_analytics
    conn, _ = loaded
    scans_sql, findings_sql = _capture_bounded(monkeypatch, lambda: owner_analytics.timeseries(None, "30", OWNER))
    scans_plan, findings_plan = _plan(conn, *scans_sql), _plan(conn, *findings_sql)
    assert "scans" not in _seq_scans(scans_plan), json.dumps(scans_plan)[:2000]
    assert _indexes(scans_plan) & {"idx_scans_status_created", "idx_scans_created"}
    assert "findings" not in _seq_scans(findings_plan), json.dumps(findings_plan)[:2000]
    assert "idx_findings_created" in _indexes(findings_plan)


def test_analytics_summary_scan_counts_use_an_index(loaded, monkeypatch):
    from backend.app.api import owner_analytics
    conn, _ = loaded
    statements = _capture_bounded(monkeypatch, lambda: owner_analytics.summary(None, "7", OWNER))
    scans_sql = next(s for s in statements if "FROM scans" in s[0])
    plan = _plan(conn, *scans_sql)
    assert "scans" not in _seq_scans(plan) and _indexes(plan) & {"idx_scans_status_created", "idx_scans_created"}


def test_organizations_list_uses_the_member_and_last_scan_indexes(loaded):
    from backend.app.core import owner_lists
    conn, _ = loaded
    rows_sql, _total = owner_lists.organizations("", "", "", "", "created", "desc", 50, 0)
    plan = _plan(conn, *rows_sql)
    used = _indexes(plan)
    assert "idx_scans_org_created" in used, used
    assert "idx_organization_members_org" in used, used
    assert "scans" not in _seq_scans(plan) and "organization_members" not in _seq_scans(plan)


def test_users_list_last_sign_in_uses_the_session_index(loaded):
    from backend.app.core import owner_lists
    conn, _ = loaded
    rows_sql, _total = owner_lists.users("", "", "", "created", "desc", 50, 0)
    plan = _plan(conn, *rows_sql)
    assert "auth_sessions" not in _seq_scans(plan), _indexes(plan)
    assert _indexes(plan) & {"idx_auth_sessions_user_created", "auth_sessions_user_idx"}


def test_owner_logs_and_organization_detail_use_indexes(loaded, monkeypatch):
    from backend.app.api import owner_views
    conn, org_id = loaded
    logs = _capture_rows(monkeypatch, lambda: owner_views.logs(None, "customer", "", 100, 0, OWNER))
    plan = _plan(conn, *logs[0])
    assert "idx_audit_log_created" in _indexes(plan) and "audit_log" not in _seq_scans(plan)

    owner_logs = _capture_rows(monkeypatch, lambda: owner_views.logs(None, "owner", "", 100, 0, OWNER))
    plan = _plan(conn, *owner_logs[0])
    assert "owner_audit" not in _seq_scans(plan), _indexes(plan)

    detail = _capture_rows(monkeypatch, lambda: owner_views.organization_detail(org_id, None, OWNER), org_id)
    by_table = {}
    for sql, params in detail:
        plan = _plan(conn, sql, params)
        for marker in ("FROM scans s", "FROM owner_audit a", "FROM owner_audit\n", "FROM audit_log a",
                       "FROM organization_members m"):
            if marker in sql:
                by_table[marker] = plan
    # 25 scans per organisation here, so either per-organisation scans index is a fine plan; never a full scan.
    assert _indexes(by_table["FROM scans s"]) & {"idx_scans_org_created", "idx_scans_org"}
    assert "scans" not in _seq_scans(by_table["FROM scans s"])
    assert "idx_owner_audit_target" in _indexes(by_table["FROM owner_audit a"])
    assert "idx_owner_audit_target" in _indexes(by_table["FROM owner_audit\n"])
    assert "idx_audit_org" in _indexes(by_table["FROM audit_log a"])
    assert "idx_organization_members_org" in _indexes(by_table["FROM organization_members m"])
