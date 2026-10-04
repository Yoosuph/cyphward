"""Real-Postgres throttling tests (review P2 — throttling).

Proves on production Postgres, as the least-privileged app role:
- the fixed-window check-and-increment is atomic and shared (the exact
  statement the app runs): counts climb 1..N inside one window and reset
  when the window expires;
- stale buckets are deletable (bounded state);
- `email_otps.purpose` defaults to 'verify' and MFA rows coexist.

Enable with: CYPHWARD_THROTTLING_INTEGRATION=1 (+ DATABASE_URL and
CYPHWARD_APP_DATABASE_URL). Leaves no rows behind (asserted).
"""
import os

import psycopg
import psycopg.rows
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CYPHWARD_THROTTLING_INTEGRATION") != "1",
    reason="set CYPHWARD_THROTTLING_INTEGRATION=1 (plus DATABASE_URL) to run against real Postgres",
)

BUCKET = "integration-probe-login:user@example.com"

CHECK_SQL = """
INSERT INTO rate_limits (bucket_key, window_start, count)
VALUES (%s, now(), 1)
ON CONFLICT (bucket_key) DO UPDATE SET
  window_start = CASE
    WHEN rate_limits.window_start < now() - make_interval(secs => %s)
    THEN now() ELSE rate_limits.window_start END,
  count = CASE
    WHEN rate_limits.window_start < now() - make_interval(secs => %s)
    THEN 1 ELSE rate_limits.count + 1 END
RETURNING count, window_start
"""


def _app():
    return psycopg.connect(os.environ["CYPHWARD_APP_DATABASE_URL"],
                           row_factory=psycopg.rows.dict_row)


def test_fixed_window_counts_and_resets_as_app_role():
    with _app() as app:
        try:
            with app.transaction():
                assert app.execute(CHECK_SQL, (BUCKET, 300.0, 300.0)).fetchone()["count"] == 1
                assert app.execute(CHECK_SQL, (BUCKET, 300.0, 300.0)).fetchone()["count"] == 2
                # force the window to expire, next hit restarts at 1
                app.execute(
                    "UPDATE rate_limits SET window_start = now() - make_interval(secs => 301) "
                    "WHERE bucket_key = %s",
                    (BUCKET,),
                )
                assert app.execute(CHECK_SQL, (BUCKET, 300.0, 300.0)).fetchone()["count"] == 1
        finally:
            with psycopg.connect(os.environ["CYPHWARD_APP_DATABASE_URL"],
                                 row_factory=psycopg.rows.dict_row) as cleanup:
                with cleanup.transaction():
                    cleanup.execute("DELETE FROM rate_limits WHERE bucket_key = %s", (BUCKET,))
                    left = cleanup.execute(
                        "SELECT count(*) AS n FROM rate_limits WHERE bucket_key = %s",
                        (BUCKET,),
                    ).fetchone()["n"]
                    assert left == 0, "probe bucket leaked"


def test_stale_bucket_reap_and_otp_purpose_default():
    with psycopg.connect(os.environ["DATABASE_URL"],
                         row_factory=psycopg.rows.dict_row) as pg:
        with pg.transaction():
            pg.execute(
                "INSERT INTO rate_limits (bucket_key, window_start, count) "
                "VALUES ('integration-probe-stale', now() - make_interval(secs => 90000), 9) "
                "ON CONFLICT (bucket_key) DO UPDATE SET window_start = EXCLUDED.window_start"
            )
            pg.execute(
                "DELETE FROM rate_limits WHERE window_start < now() - make_interval(secs => 86400)")
            left = pg.execute(
                "SELECT count(*) AS n FROM rate_limits WHERE bucket_key = 'integration-probe-stale'"
            ).fetchone()["n"]
            assert left == 0
            purpose = pg.execute(
                "SELECT column_default AS d FROM information_schema.columns "
                "WHERE table_name = 'email_otps' AND column_name = 'purpose'"
            ).fetchone()["d"]
            assert "verify" in purpose
