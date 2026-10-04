"""Synchronous psycopg access with a single bounded pool.

Capacity contract (review P1 — processing and database capacity):
- exactly ONE pool per process, capped at DB_POOL_MAX connections;
- pool checkout waits up to DB_POOL_TIMEOUT_SECONDS and then raises
  psycopg_pool.PoolTimeout (mapped to HTTP 503 by the app) — there is no
  direct-connection fallback anywhere: opening unpooled connections under
  load amplifies saturation instead of applying backpressure;
- pool construction is fail-fast and retried on the next call — a transient
  failure never degrades into per-query unlimited connects.

The queries themselves are synchronous and run on the event loop; adopting
a consistently async driver across routes and workflows is the tracked
follow-up to move this work fully off the loop.
"""
import logging
import atexit
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from backend.app.core.config import (
    DATABASE_URL,
    DB_POOL_MIN,
    DB_POOL_MAX,
    DB_POOL_TIMEOUT_SECONDS,
)

logger = logging.getLogger("cyphward.db")

_pool = None


def _cleanup_pool():
    global _pool
    if _pool is not None:
        try:
            _pool.close(timeout=1.0)
        except Exception:
            pass
        _pool = None


atexit.register(_cleanup_pool)


def get_pool():
    """Return the process-wide pool, constructing it on first use.

    Construction failures propagate (and leave _pool unset) so the next call
    retries — fail fast instead of silently falling back to unlimited
    direct connections.
    """
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set. Configure it in backend/.env or the process environment."
            )
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            DATABASE_URL,
            min_size=DB_POOL_MIN,
            max_size=DB_POOL_MAX,
            timeout=DB_POOL_TIMEOUT_SECONDS,
            max_idle=30.0,
            reconnect_timeout=3.0,
            check=ConnectionPool.check_connection,
            open=False,
            kwargs={"row_factory": dict_row, "prepare_threshold": None}
        )
        pool.open()
        _pool = pool
        logger.info(
            "Cyphward PostgreSQL connection pool established (min=%s max=%s timeout=%ss).",
            DB_POOL_MIN, DB_POOL_MAX, DB_POOL_TIMEOUT_SECONDS,
        )
    return _pool


@contextmanager
def get_db():
    """Yields a pooled connection; returns it on exit.

    Saturation behavior: waits up to DB_POOL_TIMEOUT_SECONDS for a free
    connection, then raises psycopg_pool.PoolTimeout. Never opens a
    connection outside the pool (no unpooled fallback).
    """
    pool = get_pool()  # construction errors propagate; no direct-connect path
    conn = pool.getconn(timeout=DB_POOL_TIMEOUT_SECONDS)
    try:
        yield conn
    finally:
        pool.putconn(conn)


def _run_query(sql: str, params: tuple, *, fetch_all: bool, fetch_one: bool):
    """Internal query executor with one retry on transient connection errors."""
    attempts = 0
    while True:
        attempts += 1
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    if fetch_all:
                        res = cur.fetchall() if cur.description else None
                    elif fetch_one:
                        res = cur.fetchone() if cur.description else None
                    else:
                        res = None
                conn.commit()
                return res
        except psycopg.OperationalError as e:
            if attempts >= 2:
                logger.error(f"Query failed after retry: {e}")
                raise
            logger.warning(f"Transient OperationalError (attempt {attempts}), retrying: {e}")


def execute_query(sql: str, params: tuple = ()):
    """Execute a query and return all matching rows as dictionaries."""
    return _run_query(sql, params, fetch_all=True, fetch_one=False)


def execute_one(sql: str, params: tuple = ()):
    """Execute a query and return a single row as a dictionary."""
    return _run_query(sql, params, fetch_all=False, fetch_one=True)


def execute_many(sql: str, params_seq: list):
    """Execute a batch parameterized query efficiently across multiple parameter tuples."""
    if not params_seq:
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, params_seq)
        conn.commit()
