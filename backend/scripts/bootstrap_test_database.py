"""Bootstrap only an explicitly selected, empty, loopback cyphward_test DB.

No .env loading and no fallback to DATABASE_URL. Historical/destructive
migrations are permitted here only because an empty owned test DB is required.
"""

import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict


def main() -> None:
    admin_url = os.environ.get("CYPHWARD_TEST_DATABASE_ADMIN_URL", "")
    app_url = os.environ.get("CYPHWARD_TEST_DATABASE_URL", "")
    if not admin_url or not app_url:
        raise RuntimeError(
            "Explicit test administrator and application URLs are required"
        )
    admin = conninfo_to_dict(admin_url)
    application = conninfo_to_dict(app_url)
    for info in (admin, application):
        if info.get("dbname") != "cyphward_test" or info.get("host") not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise RuntimeError("Refusing any destination except loopback cyphward_test")
    if (admin.get("host"), admin.get("port", "5432")) != (
        application.get("host"),
        application.get("port", "5432"),
    ) or application.get("user") != "cyphward_app":
        raise RuntimeError(
            "Test URLs must identify the same server and restricted application role"
        )
    with psycopg.connect(admin_url) as conn:
        identity = conn.execute(
            "SELECT current_database(),host(inet_server_addr())"
        ).fetchone()
        if identity[0] != "cyphward_test" or identity[1] not in {"127.0.0.1", "::1"}:
            raise RuntimeError("Test server identity failed")
        if conn.execute(
            "SELECT 1 FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN ('r','p','v','m') LIMIT 1"
        ).fetchone():
            raise RuntimeError(
                "Refusing migration bootstrap of a nonempty application schema"
            )
        for role in ["anon", "authenticated", "service_role"]:
            if not conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
            ).fetchone():
                conn.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
        conn.execute("CREATE SCHEMA auth")
        conn.execute(
            "CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT NULL::uuid $$"
        )
        conn.commit()
        files = sorted(
            (Path(__file__).resolve().parents[2] / "supabase/migrations").glob("*.sql")
        )
        for file in files:
            conn.execute(file.read_text())
            conn.commit()
        if application.get("password"):
            conn.execute(
                sql.SQL("ALTER ROLE cyphward_app PASSWORD {}").format(
                    sql.Literal(application["password"])
                )
            )
            conn.commit()
    with psycopg.connect(app_url) as conn:
        role = conn.execute(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        if role != (False, False):
            raise RuntimeError("Restricted test role must not bypass permissions/RLS")
    print(
        f"Applied {len(files)} migrations to an empty owned test database; restricted role verified."
    )


if __name__ == "__main__":
    main()
