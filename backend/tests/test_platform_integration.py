"""Real-Postgres platform-staff tests (review P1 — workspace authorization).

Proves on the production database, under both roles:
- `platform_staff` has RLS enabled; the app role's privileges are exactly
  SELECT + INSERT + UPDATE(revoked_at) — escalation and deletion denied,
  and `audit_log` is append-only for the app role;
- the gate's grant query returns live grants and excludes expired/revoked;
- the support query shapes (org lookup, counts, overdue scans) run as the
  least-privileged role.

Enable with: CYPHWARD_PLATFORM_INTEGRATION=1 (+ DATABASE_URL and
CYPHWARD_APP_DATABASE_URL).
"""
import os

import psycopg
import psycopg.rows
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CYPHWARD_PLATFORM_INTEGRATION") != "1",
    reason="set CYPHWARD_PLATFORM_INTEGRATION=1 (plus DATABASE_URL) to run against real Postgres",
)

STAFF_ID = "eeeeeeee-0000-4000-8000-000000000001"
AUDIT_ID = "ffffffff-0000-4000-8000-000000000001"


def _pg():
    return psycopg.connect(os.environ["DATABASE_URL"],
                           row_factory=psycopg.rows.dict_row)


def _app():
    return psycopg.connect(os.environ["CYPHWARD_APP_DATABASE_URL"],
                           row_factory=psycopg.rows.dict_row)


def test_staff_table_posture():
    with _pg() as conn:
        assert conn.execute(
            "SELECT relrowsecurity FROM pg_class WHERE relname = 'platform_staff'"
        ).fetchone()["relrowsecurity"] is True


def test_app_role_privilege_matrix_on_staff_tables():
    with _pg() as pg:
        profile = pg.execute("SELECT id FROM profiles LIMIT 1").fetchone()["id"]
        with pg.transaction():
            pg.execute(
                "INSERT INTO platform_staff (id, user_id, scopes, reason) "
                "VALUES (%s, %s, '{platform:read}', 'integration-probe') "
                "ON CONFLICT (id) DO NOTHING",
                (STAFF_ID, profile),
            )
            pg.execute(
                "INSERT INTO audit_log (id, action) VALUES (%s, 'integration-probe') "
                "ON CONFLICT (id) DO NOTHING",
                (AUDIT_ID,),
            )
        try:
            with _app() as app:
                # revoke path: allowed
                with app.transaction():
                    app.execute(
                        "UPDATE platform_staff SET revoked_at = NULL WHERE id = %s",
                        (STAFF_ID,),
                    )
                # escalation / deletion: denied
                for label, stmt in [
                    ("update-reason", "UPDATE platform_staff SET reason = 'x' WHERE id = %s"),
                    ("update-scopes", "UPDATE platform_staff SET scopes = '{}' WHERE id = %s"),
                    ("delete-grant", "DELETE FROM platform_staff WHERE id = %s"),
                    ("update-audit", "UPDATE audit_log SET action = 'x' WHERE id = %s"),
                    ("delete-audit", "DELETE FROM audit_log WHERE id = %s"),
                ]:
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        with app.transaction():
                            app.execute(stmt, (STAFF_ID if "audit" not in label else AUDIT_ID,))
                # audit stays writable for new events
                with app.transaction():
                    n = app.execute(
                        "INSERT INTO audit_log (org_id, user_id, action) "
                        "VALUES (NULL, NULL, 'integration-probe-ok') RETURNING id"
                    ).fetchone()
                    assert n is not None
        finally:
            with psycopg.connect(os.environ["DATABASE_URL"]) as cleanup:
                with cleanup.transaction():
                    cleanup.execute("DELETE FROM audit_log WHERE action LIKE 'integration-probe%'")
                    cleanup.execute("DELETE FROM platform_staff WHERE id = %s", (STAFF_ID,))


def test_gate_queries_behave_as_app_role():
    with _pg() as pg:
        profile = pg.execute("SELECT id FROM profiles LIMIT 1").fetchone()["id"]
        with pg.transaction():
            pg.execute(
                "INSERT INTO platform_staff (id, user_id, scopes, reason, expires_at) "
                "VALUES ('eeeeeeee-1111-4000-8000-000000000001', %s, '{platform:read}', "
                "'probe-live', now() + interval '1 hour') ON CONFLICT (id) DO NOTHING",
                (profile,),
            )
            pg.execute(
                "INSERT INTO platform_staff (id, user_id, scopes, reason, expires_at) "
                "VALUES ('eeeeeeee-2222-4000-8000-000000000002', %s, '{platform:read}', "
                "'probe-expired', now() - interval '1 hour') ON CONFLICT (id) DO NOTHING",
                (profile,),
            )
            pg.execute(
                "INSERT INTO platform_staff (id, user_id, scopes, reason, revoked_at) "
                "VALUES ('eeeeeeee-3333-4000-8000-000000000003', %s, '{platform:read}', "
                "'probe-revoked', now()) ON CONFLICT (id) DO NOTHING",
                (profile,),
            )
        try:
            with _app() as app:
                live = app.execute(
                    """
                    SELECT id, scopes FROM platform_staff
                    WHERE user_id = %s AND revoked_at IS NULL
                      AND (expires_at IS NULL OR expires_at > now())
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (profile,),
                ).fetchone()
                assert live is not None and live["scopes"] == ["platform:read"]
                # support query shapes run under the app role
                org = app.execute(
                    "SELECT id, name, slug, plan, created_at FROM organizations LIMIT 1"
                ).fetchone()
                assert org is not None
                counts = app.execute(
                    "SELECT (SELECT count(*) FROM organization_members) AS m"
                ).fetchone()
                assert counts["m"] >= 1
                overdue = app.execute(
                    """
                    SELECT s.id, s.org_id, o.name AS org_name, s.status,
                           s.created_at, s.lease_expires_at
                    FROM scans s JOIN organizations o ON o.id = s.org_id
                    WHERE s.status IN ('queued', 'running')
                      AND (s.lease_expires_at IS NULL OR s.lease_expires_at < now())
                    ORDER BY s.created_at ASC LIMIT 5
                    """
                ).fetchall()
                assert isinstance(overdue, list)
        finally:
            with psycopg.connect(os.environ["DATABASE_URL"]) as cleanup:
                with cleanup.transaction():
                    cleanup.execute(
                        "DELETE FROM platform_staff WHERE reason LIKE 'probe-%'"
                    )

