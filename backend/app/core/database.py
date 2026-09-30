import logging
import atexit
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from backend.app.core.config import DATABASE_URL

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
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set. Configure it in backend/.env or the process environment."
            )
        try:
            from psycopg_pool import ConnectionPool
            _pool = ConnectionPool(
                DATABASE_URL,
                min_size=1,
                max_size=20,
                timeout=5.0,
                max_idle=30.0,
                reconnect_timeout=3.0,
                check=ConnectionPool.check_connection,
                open=False,
                kwargs={"row_factory": dict_row, "prepare_threshold": None}
            )
            _pool.open()
            logger.info("Cyphward PostgreSQL connection pool established successfully (size=20).")
        except Exception as e:
            logger.warning(f"Connection pool init failed: {e}. Falling back to unpooled connections.")
            _pool = None
    return _pool


@contextmanager
def get_db():
    """Yields a database connection from the pool, or creates a direct connection as fallback."""
    pool = get_pool()
    if pool:
        try:
            conn = pool.getconn(timeout=5.0)
        except Exception as e:
            logger.warning(f"Pool getconn failed ({e}). Using direct ephemeral connection.")
            conn = None

        if conn is not None:
            try:
                yield conn
            finally:
                try:
                    pool.putconn(conn)
                except Exception:
                    pass
            return

    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=6)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


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
