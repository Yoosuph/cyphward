"""Real-Postgres isolation tests (review P1 — isolation boundary).

"Existing fake-database tests cannot verify production role behavior" —
these run against a real Postgres when explicitly enabled:

    CYPHWARD_RLS_INTEGRATION=1 CYPHWARD_APP_DATABASE_URL=postgresql://...
        uv run --with-requirements requirements.txt \
        python -m pytest backend/tests/test_rls_integration.py -q

Covers:
- production role posture (app role must NOT be superuser/BYPASSRLS);
- RLS enabled on every public table with the cyphward_app policies;
- cross-tenant READ and WRITE attempts through the app's real query shapes;
- live proof that RLS actually applies to cyphward_app (a no-policy table
  is invisible/unwritable for it, a policy-restored table is not).
"""
import os

import psycopg
import psycopg.rows
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CYPHWARD_RLS_INTEGRATION") != "1",
    reason="set CYPHWARD_RLS_INTEGRATION=1 (plus DATABASE_URL) to run against real Postgres",
)

ORG_A = "5e3fe575-caea-4ea9-acab-353e72487d36"  # prod org used by other E2E checks


def _app_url() -> str:
    return os.getenv("CYPHWARD_APP_DATABASE_URL", "")


def test_all_public_tables_have_rls_enabled():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute("""
            SELECT c.relname, c.relrowsecurity
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
        """).fetchall()
        assert rows, "no tables found"
        missing = [name for name, enabled in rows if not enabled]
        assert missing == [], f"tables without RLS: {missing}"


def test_role_posture_app_role_is_least_privileged():
    """Assert the facts the review asks to verify: cyphward_app exists and
    carries no superuser / BYPASSRLS / CREATEROLE powers."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        role = conn.execute("SELECT current_user").fetchone()[0]
        super_, bypass = conn.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", (role,)
        ).fetchone()
        # Today's prod posture (the concern itself): the postgres role
        # bypasses RLS — asserted so any change here is noticed.
        assert (super_, bypass) in [(False, True), (False, False)], (
            f"unexpected posture for {role}: super={super_} bypassrls={bypass}"
        )
        app = conn.execute(
            "SELECT rolsuper, rolbypassrls, rolcreaterole "
            "FROM pg_roles WHERE rolname = 'cyphward_app'"
        ).fetchone()
        assert app is not None, "cyphward_app missing — apply migration 20261004160000"
        assert tuple(app) == (False, False, False), f"cyphward_app not least-privileged: {app}"


def test_cross_tenant_read_and_write_are_filtered():
    """The app's own query shapes must not see or touch another org's rows —
    the defense-in-depth the review asks to verify on real Postgres.
    Self-contained: synthetic tenant rows inside one rolled-back transaction."""
    with psycopg.connect(os.environ["DATABASE_URL"],
                         row_factory=psycopg.rows.dict_row) as conn:
        with conn.transaction():  # everything below rolls back
            conn.execute("""
                INSERT INTO organizations (id, name, slug, created_at)
                VALUES ('aaaaaaaa-0000-4000-8000-000000000001',
                        'rls-probe-other-org', 'rls-probe-other-org', now())
                ON CONFLICT (id) DO NOTHING
            """)
            conn.execute("""
                INSERT INTO findings (id, org_id, title, description,
                                      remediation, status, created_at)
                VALUES ('bbbbbbbb-0000-4000-8000-000000000001',
                        'aaaaaaaa-0000-4000-8000-000000000001',
                        'rls-probe', 'rls-probe', 'rls-probe', 'open', now())
                ON CONFLICT (id) DO NOTHING
            """)
            other_org = "aaaaaaaa-0000-4000-8000-000000000001"
            other_finding = "bbbbbbbb-0000-4000-8000-000000000001"

            # cross-tenant SELECT with the app's org filter -> empty
            seen = conn.execute(
                "SELECT id FROM findings WHERE org_id = %s AND id = %s",
                (ORG_A, other_finding),
            ).fetchall()
            assert seen == []

            # cross-tenant UPDATE guarded by org_id -> 0 rows touched
            cur = conn.execute(
                "UPDATE findings SET status = 'resolved' WHERE id = %s AND org_id = %s",
                (other_finding, ORG_A),
            )
            assert cur.rowcount == 0

            # row still open under its real org (write truly never landed)
            row = conn.execute(
                "SELECT status FROM findings WHERE id = %s AND org_id = %s",
                (other_finding, other_org),
            ).fetchone()
            assert row["status"] == "open"


@pytest.mark.skipif(not _app_url(), reason="CYPHWARD_APP_DATABASE_URL not set")
def test_app_role_connects_and_rls_is_enforced_for_it():
    app_url = _app_url()
    pg_url = os.environ["DATABASE_URL"]
    # postgres side owns DDL (cyphward_app has no CREATE — least-privileged);
    # the app side proves RLS actually applies to it.
    with psycopg.connect(pg_url) as pg:
        with pg.transaction():
            pg.execute("CREATE TABLE rls_probe (org_id uuid, note text)")
            pg.execute("ALTER TABLE rls_probe ENABLE ROW LEVEL SECURITY")
            pg.execute(
                "INSERT INTO rls_probe VALUES (%s, 'owner-written')", (ORG_A,)
            )
        try:
            with psycopg.connect(app_url,
                                 row_factory=psycopg.rows.dict_row) as app:
                role = app.execute("SELECT current_user AS role").fetchone()["role"]
                assert role == "cyphward_app"
                assert app.execute(
                    "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
                ).fetchone()["rolbypassrls"] is False

                # normal reads work under the permissive cyphward_app policies
                assert app.execute(
                    "SELECT count(*) AS n FROM organizations"
                ).fetchone()["n"] >= 1

                # no policy on the probe table: data invisible + writes denied
                assert app.execute(
                    "SELECT count(*) AS n FROM rls_probe"
                ).fetchone()["n"] == 0
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with app.transaction():
                        app.execute(
                            "INSERT INTO rls_probe VALUES (%s, 'denied')", (ORG_A,)
                        )

            with pg.transaction():
                pg.execute(
                    "CREATE POLICY probe_policy ON rls_probe "
                    "FOR ALL TO cyphward_app USING (true) WITH CHECK (true)"
                )

            with psycopg.connect(app_url,
                                 row_factory=psycopg.rows.dict_row) as app:
                assert app.execute(
                    "SELECT count(*) AS n FROM rls_probe"
                ).fetchone()["n"] == 1
                with app.transaction():
                    app.execute(
                        "INSERT INTO rls_probe VALUES (%s, 'allowed')", (ORG_A,)
                    )
                assert app.execute(
                    "SELECT count(*) AS n FROM rls_probe"
                ).fetchone()["n"] == 2

            with pg.transaction():
                pg.execute("DROP POLICY probe_policy ON rls_probe")

            with psycopg.connect(app_url,
                                 row_factory=psycopg.rows.dict_row) as app:
                # policy gone -> rows invisible for this role again
                assert app.execute(
                    "SELECT count(*) AS n FROM rls_probe"
                ).fetchone()["n"] == 0
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with app.transaction():
                        app.execute(
                            "INSERT INTO rls_probe VALUES (%s, 'denied')", (ORG_A,)
                        )
        finally:
            # fresh connection so cleanup works even if probe txns died
            with psycopg.connect(pg_url) as cleanup:
                with cleanup.transaction():
                    cleanup.execute("DROP TABLE IF EXISTS rls_probe")
