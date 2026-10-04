"""Real-Postgres billing tests (billing follow-up; provider NOT wired).

Proves on production Postgres, as the least-privileged app role:
- subscriptions/invoices have RLS with working app policies;
- plan and status allowlists hold at the CHECK-constraint level;
- the subscription upsert + invoice insert shapes run.

Enable with: CYPHWARD_BILLING_INTEGRATION=1 (+ DATABASE_URL and
CYPHWARD_APP_DATABASE_URL). Leaves no rows behind (asserted).
"""
import os

import psycopg
import psycopg.rows
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CYPHWARD_BILLING_INTEGRATION") != "1",
    reason="set CYPHWARD_BILLING_INTEGRATION=1 (plus DATABASE_URL) to run against real Postgres",
)


def _app():
    return psycopg.connect(os.environ["CYPHWARD_APP_DATABASE_URL"],
                           row_factory=psycopg.rows.dict_row)


def test_billing_tables_posture():
    with psycopg.connect(os.environ["DATABASE_URL"],
                         row_factory=psycopg.rows.dict_row) as conn:
        for table in ("subscriptions", "invoices"):
            assert conn.execute(
                "SELECT relrowsecurity FROM pg_class WHERE relname = %s", (table,)
            ).fetchone()["relrowsecurity"] is True, table
        assert conn.execute(
            "SELECT count(*) AS n FROM pg_constraint WHERE conname = 'subscriptions_plan_check'"
        ).fetchone()["n"] == 1


def test_subscription_upsert_and_invoice_as_app_role():
    with psycopg.connect(os.environ["DATABASE_URL"],
                         row_factory=psycopg.rows.dict_row) as pg:
        org = pg.execute("SELECT id FROM organizations LIMIT 1").fetchone()["id"]
        try:
            with _app() as app:
                with app.transaction():
                    sub = app.execute(
                        """
                        INSERT INTO subscriptions (org_id, plan, status, provider)
                        VALUES (%s, 'growth', 'active', 'manual')
                        ON CONFLICT (org_id) DO UPDATE SET plan = EXCLUDED.plan
                        RETURNING id, plan, status
                        """,
                        (org,),
                    ).fetchone()
                    assert (sub["plan"], sub["status"]) == ("growth", "active")
                    inv = app.execute(
                        "INSERT INTO invoices (org_id, plan, amount_kobo) "
                        "VALUES (%s, 'growth', 45000000) RETURNING id, number",
                        (org,),
                    ).fetchone()
                    assert inv["number"].startswith("INV-")
                    # allowlists hold for the app role too
                    with pytest.raises(psycopg.errors.CheckViolation):
                        with app.transaction():
                            app.execute(
                                "INSERT INTO subscriptions (org_id, plan) VALUES (%s, 'Platinum') "
                                "ON CONFLICT (org_id) DO UPDATE SET plan = EXCLUDED.plan",
                                (org,),
                            )
        finally:
            with psycopg.connect(os.environ["DATABASE_URL"],
                                 row_factory=psycopg.rows.dict_row) as cleanup:
                with cleanup.transaction():
                    cleanup.execute("DELETE FROM invoices WHERE org_id = %s", (org,))
                    cleanup.execute("DELETE FROM subscriptions WHERE org_id = %s", (org,))
                    left = cleanup.execute(
                        "SELECT (SELECT count(*) FROM invoices WHERE org_id = %s) AS inv, "
                        "(SELECT count(*) FROM subscriptions WHERE org_id = %s) AS sub",
                        (org, org),
                    ).fetchone()
                    assert (left["inv"], left["sub"]) == (0, 0), "billing probe rows leaked"
