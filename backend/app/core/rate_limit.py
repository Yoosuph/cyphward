"""Shared Postgres-backed rate limiting (review P2 — throttling).

Replaces the process-memory dicts (login attempts, reset cooldowns,
welcome cooldowns) that were invisible across replicas, lost on restart,
and grew without bound. Each check is ONE atomic statement — safe across
replicas — and stale buckets are reaped probabilistically on each call so
state stays bounded without a janitor process.
"""
import random
from typing import Optional

from fastapi import HTTPException

from backend.app.core.database import execute_one, execute_query

# Probabilistic stale-bucket reap on each check (1%).
_REAP_PROBABILITY = 0.01
_REAP_MAX_AGE_SECONDS = 86400


def check_rate_limit(bucket: str, max_attempts: int, window_seconds: int) -> int:
    """Atomically consume one attempt from a fixed window.

    Returns the new in-window count. Raises 429 with a Retry-After hint
    when the bucket is exhausted. `bucket` should encode the scope, e.g.
    "login:<email>" or "reset:<email>".
    """
    row = execute_one(
        """
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
        """,
        (bucket, float(window_seconds), float(window_seconds)),
    )
    if random.random() < _REAP_PROBABILITY:
        try:
            execute_query(
                "DELETE FROM rate_limits WHERE window_start < now() - make_interval(secs => %s)",
                (float(_REAP_MAX_AGE_SECONDS),),
            )
        except Exception:
            pass  # cleanup must never break the request path
    count = (row or {}).get("count", 0)
    if count > max_attempts:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts — please wait before trying again.",
            headers={"Retry-After": str(window_seconds)},
        )
    return count


def reset_bucket(bucket: str) -> None:
    """Clear a bucket (e.g. successful login resets the login throttle)."""
    try:
        execute_query("DELETE FROM rate_limits WHERE bucket_key = %s", (bucket,))
    except Exception:
        pass
