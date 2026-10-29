"""Bounded reads for the owner console's analytics, lists and exports (docs/admin-2026-10-29).

* Every statement runs inside one short transaction with `SET LOCAL statement_timeout = '5s'`. A query that runs
  longer is cancelled by PostgreSQL and the request answers 503 with reviewed wording; it is never retried.
* The pooled connection is held only while the statements run. Rows are fetched into memory (lists are capped at
  100 rows, exports at 10,000) and the connection goes back to the pool before anything is formatted or sent.
* List page sizes above PAGE_MAX are capped, not refused; a size below 1 is refused by the endpoint (422).
"""
import csv
import io
import logging
from typing import Any, Dict, List, Sequence, Tuple

import psycopg
from fastapi import HTTPException

from backend.app.core import database

logger = logging.getLogger("cyphward.owner")

STATEMENT_TIMEOUT = "5s"
PAGE_MAX = 100
EXPORT_MAX = 10_000
SLOW_READ_DETAIL = "This view took too long to load. Narrow the filters or try again in a moment."
READ_FAILED_DETAIL = "Owner console is temporarily unavailable."

Statement = Tuple[str, Any]


def page_size(limit: int) -> int:
    """Sizes above the cap are capped (the endpoint's Query(ge=1) refuses anything below 1)."""
    return max(1, min(int(limit), PAGE_MAX))


def bounded_read(statements: Sequence[Statement]) -> List[List[Dict[str, Any]]]:
    """Run read-only statements in one transaction under a 5 s statement timeout; return each one's rows."""
    results: List[List[Dict[str, Any]]] = []
    try:
        with database.get_db() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
                    for sql, params in statements:
                        cur.execute(sql, params)
                        results.append(list(cur.fetchall()) if cur.description else [])
    except psycopg.errors.QueryCanceled:
        logger.warning("owner read cancelled by the statement timeout")
        raise HTTPException(status_code=503, detail=SLOW_READ_DETAIL)
    except HTTPException:
        raise
    except Exception:
        logger.exception("owner read failed")
        raise HTTPException(status_code=503, detail=READ_FAILED_DETAIL)
    return results


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: Any) -> str:
    """A spreadsheet-safe cell: values a spreadsheet would run as a formula are prefixed with a quote."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value)
    if text.startswith(_FORMULA_START):
        return "'" + text
    return text


def to_csv(columns: Sequence[Tuple[str, str]], rows: Sequence[Dict[str, Any]]) -> str:
    """columns: (key, header) pairs. Formatting happens after the database connection is released."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([header for _, header in columns])
    for row in rows:
        writer.writerow([csv_cell(row.get(key)) for key, _ in columns])
    return out.getvalue()
