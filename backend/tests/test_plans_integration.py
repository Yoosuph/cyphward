"""Real-Postgres plan-entitlement tests (review P1 — plan enforcement).

Proves against production Postgres, as the least-privileged app role:
- the repaired plan values satisfy the server allowlist CHECK constraint;
- the quota usage queries (monthly scans/reports, domains, members) run;
- an invalid plan is rejected by the CHECK constraint at insert time.

Enable with: CYPHWARD_PLANS_INTEGRATION=1 (+ DATABASE_URL and
CYPHWARD_APP_DATABASE_URL).
"""
import os

import psycopg
import psycopg.rows
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CYPHWARD_PLANS_INTEGRATION") != "1",
    reason="set CYPHWARD_PLANS_INTEGRATION=1 (plus DATABASE_URL) to run against real Postgres",
)


def test_plan_values_satisfy_allowlist():
    with psycopg.connect(os.environ["DATABASE_URL"],
                         row_factory=psycopg.rows.dict_row) as conn:
        bad = conn.execute(
            "SELECT count(*) AS n FROM organizations "
            "WHERE plan NOT IN ('growth', 'scale', 'sovereign')"
        ).fetchone()["n"]
        assert bad == 0
        assert conn.execute(
            "SELECT count(*) AS n FROM pg_constraint "
            "WHERE conname = 'organizations_plan_check'"
        ).fetchone()["n"] == 1
        default = conn.execute(
            "SELECT column_default AS d FROM information_schema.columns "
            "WHERE table_name = 'organizations' AND column_name = 'plan'"
        ).fetchone()["d"]
        assert "scale" in default


def test_quota_usage_queries_run_as_app_role():
    with psycopg.connect(os.environ["CYPHWARD_APP_DATABASE_URL"],
                         row_factory=psycopg.rows.dict_row) as app:
        org = app.execute("SELECT id FROM organizations LIMIT 1").fetchone()["id"]
        for label, sql, params in [
            ("scans", "SELECT count(*) AS n FROM scans WHERE org_id = %s "
                       "AND created_at >= date_trunc('month', now())", (org,)),
            ("reports", "SELECT count(*) AS n FROM reports WHERE org_id = %s "
                         "AND created_at >= date_trunc('month', now())", (org,)),
            ("domains", "SELECT count(*) AS n FROM domains WHERE org_id = %s", (org,)),
            ("members", "SELECT count(*) AS n FROM organization_members WHERE org_id = %s",
             (org,)),
        ]:
            n = app.execute(sql, params).fetchone()["n"]
            assert isinstance(n, int), label


def test_invalid_plan_rejected_by_check_constraint():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.transaction():
            with pytest.raises(psycopg.errors.CheckViolation):
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO organizations (name, slug, plan) "
                        "VALUES ('constraint-probe', 'constraint-probe', 'Platinum')"
                    )
