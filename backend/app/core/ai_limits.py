"""Usage limits for every AI route (CyphBot, explain, remediate, executive summary).

Three controls, all stored in the shared ``rate_limits`` table so every replica sees them:

* Per-user and per-organisation hourly buckets, charged through ``check_rate_limit``.
  Defaults: 60 calls per user and 300 per organisation per hour, overridable with
  ``CYPHWARD_AI_USER_MAX_PER_HOUR`` and ``CYPHWARD_AI_ORG_MAX_PER_HOUR``.
* Upstream accounting: the organisation bucket is charged once when the request is
  admitted, and that unit pays for the request's first upstream provider attempt.
  Every further attempt (retries, a second provider, a follow-up model call) charges
  the organisation bucket again. So a request costs max(1, upstream attempts).
* At most ``AI_MAX_CONCURRENT_STREAMS`` open streaming responses per user, held as
  short-lived lease rows that expire on their own if a stream never finishes.

The shared demo account's stricter cap (``limit_demo_ai``) still applies first.
"""
from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException

from backend.app.core.auth import get_current_org
from backend.app.core.database import execute_one, execute_query
from backend.app.core.rate_limit import check_rate_limit

logger = logging.getLogger("cyphward.ai")

AI_WINDOW_SECONDS = 3600
DEFAULT_USER_MAX_PER_HOUR = 60
DEFAULT_ORG_MAX_PER_HOUR = 300
AI_MAX_CONCURRENT_STREAMS = 2
STREAM_LEASE_SECONDS = 300  # longer than any provider timeout chain; a stuck lease frees itself

USER_LIMIT_MESSAGE = "You have reached the hourly CyphBot request limit. Please try again after the current window resets."
ORG_LIMIT_MESSAGE = "Your organisation has reached its hourly CyphBot request limit. Please try again after the current window resets."
STREAM_LIMIT_MESSAGE = (f"You already have {AI_MAX_CONCURRENT_STREAMS} CyphBot answers in progress. "
                        "Wait for one to finish, then try again.")
ORG_BUDGET_EXHAUSTED_MESSAGE = ("Your organisation's hourly CyphBot allowance was used up while answering. "
                                "Please try again after the current window resets.")


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default
    return value if value > 0 else default


def user_limit() -> int:
    return _env_int("CYPHWARD_AI_USER_MAX_PER_HOUR", DEFAULT_USER_MAX_PER_HOUR)


def org_limit() -> int:
    return _env_int("CYPHWARD_AI_ORG_MAX_PER_HOUR", DEFAULT_ORG_MAX_PER_HOUR)


def org_bucket(org_id: str) -> str:
    return f"ai-org:{org_id}"


class _Budget:
    """Per-request upstream accounting; one prepaid attempt comes with admission."""

    def __init__(self, org_id: str):
        self.org_id = org_id
        self.prepaid = 1
        self.attempts = 0


_budget: ContextVar[Optional[_Budget]] = ContextVar("cyphward_ai_budget", default=None)


def _limited(exc: HTTPException, message: str) -> HTTPException:
    return HTTPException(status_code=429, detail=message, headers=exc.headers)


async def limit_ai(org: Dict[str, Any] = Depends(get_current_org)) -> None:
    """Router dependency for every AI route. Async on purpose: it runs in the
    request's own context, so the budget it sets reaches the endpoint and the
    streaming body (a sync dependency would set it on a threadpool copy)."""
    user_id = str(org.get("current_user_id") or "")
    org_id = str(org["id"])
    try:
        check_rate_limit(f"ai-user:{user_id}", user_limit(), AI_WINDOW_SECONDS)
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        raise _limited(exc, USER_LIMIT_MESSAGE) from None
    try:
        check_rate_limit(org_bucket(org_id), org_limit(), AI_WINDOW_SECONDS)
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        raise _limited(exc, ORG_LIMIT_MESSAGE) from None
    _budget.set(_Budget(org_id))


def charge_upstream_attempt() -> bool:
    """Call immediately before every upstream provider request, retries included.

    Returns False when the organisation's budget is exhausted; the caller must then
    skip the request. Never raises, because callers sit inside broad exception
    handlers and inside streams that can no longer send an HTTP error.
    Outside an AI route (no budget in context) nothing is charged.
    """
    budget = _budget.get()
    if budget is None:
        return True
    budget.attempts += 1
    if budget.prepaid > 0:
        budget.prepaid -= 1
        return True
    try:
        check_rate_limit(org_bucket(budget.org_id), org_limit(), AI_WINDOW_SECONDS)
        return True
    except HTTPException as exc:
        if exc.status_code == 429:
            logger.warning("ai org budget exhausted; upstream attempt skipped")
        return False
    except Exception:
        # Fail closed: an unrecorded attempt would escape the budget.
        logger.warning("ai org budget could not be recorded; upstream attempt skipped")
        return False


def acquire_stream_slot(user_id: str) -> tuple:
    """Claim one of the user's concurrent-stream leases or raise 429."""
    for slot in range(AI_MAX_CONCURRENT_STREAMS):
        key = f"ai-stream:{user_id}:{slot}"
        row = execute_one(
            """
            INSERT INTO rate_limits (bucket_key, window_start, count)
            VALUES (%s, now(), 1)
            ON CONFLICT (bucket_key) DO UPDATE SET window_start = now(), count = 1
            WHERE rate_limits.window_start < now() - make_interval(secs => %s)
            RETURNING bucket_key, window_start
            """,
            (key, float(STREAM_LEASE_SECONDS)),
        )
        if row:
            return (key, row.get("window_start"))
    raise HTTPException(status_code=429, detail=STREAM_LIMIT_MESSAGE,
                        headers={"Retry-After": "10"})


def release_stream_slot(lease: tuple) -> None:
    """Delete only this lease, never one another stream re-claimed after expiry."""
    key, started = lease
    try:
        execute_query("DELETE FROM rate_limits WHERE bucket_key = %s AND window_start = %s", (key, started))
    except Exception:
        logger.warning("ai stream lease could not be released; it expires on its own")
