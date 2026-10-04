"""Bounded database pool behavior (review P1 — processing and database capacity).

The defect: when pool checkout failed, get_db opened a direct unpooled
connection — under saturation that amplified load instead of applying
backpressure, and pool-init failure silently degraded to per-query unlimited
connects. These tests pin the fix: one bounded pool, wait-then-503, and no
path that connects outside the pool.
"""
import inspect

import psycopg_pool
import pytest

import backend.app.core.database as database


class _FakePool:
    def __init__(self, conn=object()):
        self.conn = conn
        self.got = 0
        self.returned = []
        self.getconn_timeout = None

    def getconn(self, timeout=None):
        self.got += 1
        self.getconn_timeout = timeout
        return self.conn

    def putconn(self, conn):
        self.returned.append(conn)

    def raise_timeout(self, timeout=None):
        raise psycopg_pool.PoolTimeout(f"no free connections (timeout={timeout})")


class _TimeoutPool(_FakePool):
    def getconn(self, timeout=None):
        self.got += 1
        self.getconn_timeout = timeout
        raise psycopg_pool.PoolTimeout(f"no free connections (timeout={timeout})")


def test_get_db_yields_pooled_connection_and_returns_it(monkeypatch):
    pool = _FakePool()
    monkeypatch.setattr(database, "get_pool", lambda: pool)

    with database.get_db() as conn:
        assert conn is pool.conn

    assert pool.got == 1
    assert pool.returned == [pool.conn]
    assert pool.getconn_timeout == database.DB_POOL_TIMEOUT_SECONDS


def test_saturated_pool_raises_pool_timeout_and_never_connects(monkeypatch):
    """Saturation must wait then raise — never open a direct connection."""
    pool = _TimeoutPool()
    monkeypatch.setattr(database, "get_pool", lambda: pool)

    def boom(*args, **kwargs):
        raise AssertionError("direct psycopg.connect fallback used under saturation")

    monkeypatch.setattr(database.psycopg, "connect", boom)

    with pytest.raises(psycopg_pool.PoolTimeout):
        with database.get_db():
            pass

    assert pool.got == 1
    assert pool.returned == []


def test_pool_construction_failure_leaves_pool_unset_and_retries(monkeypatch):
    """Init errors propagate (fail fast) and are retried next call — the old
    code swallowed them and fell back to unlimited direct connections."""
    monkeypatch.setattr(database, "DATABASE_URL", "postgresql://probe/db")
    monkeypatch.setattr(database, "_pool", None)

    calls = {"n": 0}
    built = []

    class _BoomThenOk:
        def __init__(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("pg is down")
            built.append(kwargs)

        def open(self):
            pass

        @staticmethod
        def check_connection(*args, **kwargs):
            return None

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", _BoomThenOk)

    with pytest.raises(RuntimeError, match="pg is down"):
        database.get_pool()
    assert database._pool is None  # nothing cached from the failed attempt

    pool = database.get_pool()  # retry succeeds
    assert database._pool is pool
    assert built[0]["max_size"] == database.DB_POOL_MAX
    assert built[0]["min_size"] == database.DB_POOL_MIN
    assert built[0]["timeout"] == database.DB_POOL_TIMEOUT_SECONDS


def test_get_db_has_no_direct_connection_path():
    """Static regression guard: the unpooled fallback code must not exist."""
    src = inspect.getsource(database.get_db)
    assert "psycopg.connect" not in src
    assert "PoolTimeout" in src or "getconn" in src


def test_pool_limits_come_from_config(monkeypatch):
    import importlib

    monkeypatch.setenv("DB_POOL_MAX", "7")
    monkeypatch.setenv("DB_POOL_MIN", "2")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "1.5")
    import backend.app.core.config as config

    importlib.reload(config)
    try:
        assert config.DB_POOL_MAX == 7
        assert config.DB_POOL_MIN == 2
        assert config.DB_POOL_TIMEOUT_SECONDS == 1.5
    finally:
        monkeypatch.undo()  # drop the env overrides before restoring modules
        importlib.reload(config)
        importlib.reload(database)


def test_pool_timeout_handler_returns_503_with_retry_after():
    import asyncio
    import json

    from starlette.requests import Request

    import backend.app.main as main_mod

    req = Request({"type": "http", "method": "GET", "path": "/api/v1/members",
                   "headers": [], "query_string": b""})
    resp = asyncio.run(
        main_mod.database_busy_handler(req, psycopg_pool.PoolTimeout("no free connections"))
    )

    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "5"
    body = json.loads(resp.body)
    assert body["status"] == 503
    assert "database capacity" in body["detail"]
