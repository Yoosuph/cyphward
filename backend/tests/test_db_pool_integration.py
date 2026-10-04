"""Opt-in production-like pool integration test (review P1 — processing and
database capacity: "Add production-like Postgres integration tests").

Runs ONLY when CYPHWARD_DB_INTEGRATION=1 so CI (fake DB) and routine test
runs never touch a real database:

    CYPHWARD_DB_INTEGRATION=1 uv run --with-requirements requirements.txt \
        python -m pytest backend/tests/test_db_pool_integration.py -q
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CYPHWARD_DB_INTEGRATION") != "1",
    reason="set CYPHWARD_DB_INTEGRATION=1 to run against a real Postgres",
)


def test_pool_checkout_query_and_return():
    import backend.app.core.database as database

    with database.get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            assert cur.fetchone() == {"ok": 1}
        conn.commit()

    pool = database.get_pool()
    stats = pool.get_stats()
    assert stats["pool_max"] <= database.DB_POOL_MAX
    assert stats["requests_waiting"] == 0  # no caller stuck waiting afterwards
    assert stats["pool_available"] == stats["pool_size"]  # connection returned


def test_pool_is_single_and_bounded():
    import backend.app.core.database as database

    a = database.get_pool()
    b = database.get_pool()
    assert a is b  # one pool per process
    assert a.max_size <= database.DB_POOL_MAX
