"""Remembered browsers for the sign-in step-up code.

Owners, admins and opted-in users confirm sign-in with a 6-digit code. After a
correct code with "remember this browser" ticked, the browser receives an
httpOnly cookie holding a random token; only its SHA-256 is stored. For 30
days (absolute, never extended) a fresh primary sign-in from that browser,
password or Google, skips the second factor. The cookie alone never signs
anyone in: it is only consulted after the first factor succeeded, and only for
the user that factor proved.

Anything unexpected (no table yet, a database error, an expired or foreign
token) means "not trusted", so the code is asked for as before.
"""
import hashlib
import logging
import secrets
from typing import Optional

from fastapi import Request, Response

from backend.app.core.config import CYPHWARD_ENV
from backend.app.core.database import execute_one, execute_query

TRUST_DAYS = 30
_SECURE = CYPHWARD_ENV == "production"
# __Host- pins the cookie to this exact host (Secure, Path=/, no Domain), so no
# cyphward.com subdomain (some are run by third parties) can plant or shadow it.
COOKIE_NAME = "__Host-cw_trusted_browser" if _SECURE else "cw_trusted_browser"

logger = logging.getLogger("cyphward.trusted_browsers")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_trusted(request: Optional[Request], user_id: str) -> bool:
    """True only for an unexpired remembered-browser token belonging to user_id."""
    token = request.cookies.get(COOKIE_NAME) if request is not None else None
    if not token or len(token) > 200:
        return False
    try:
        row = execute_one(
            "SELECT id FROM trusted_browsers WHERE token_hash = %s AND user_id = %s AND expires_at > now()",
            (_hash(token), user_id),
        )
        if row is None:
            return False
        execute_query("UPDATE trusted_browsers SET last_used_at = now() WHERE id = %s", (row["id"],))
        return True
    except Exception:  # fail closed: ask for the code
        logger.warning("trusted browser lookup failed; asking for the code", exc_info=True)
        return False


def remember(response: Response, user_id: str, user_agent: Optional[str]) -> bool:
    """Store a new remembered browser and set its cookie. False if it could not be stored."""
    token = secrets.token_urlsafe(32)
    try:
        execute_query(
            "INSERT INTO trusted_browsers (user_id, token_hash, user_agent, expires_at) "
            "VALUES (%s, %s, %s, now() + make_interval(days => %s))",
            (user_id, _hash(token), (user_agent or "")[:200] or None, TRUST_DAYS),
        )
    except Exception:
        logger.warning("could not remember browser", exc_info=True)
        return False
    response.set_cookie(
        COOKIE_NAME, token, max_age=TRUST_DAYS * 86400, path="/",
        secure=_SECURE, httponly=True, samesite="strict",
    )
    return True


def forget_all(user_id: str) -> None:
    """Forget every remembered browser for the user (credential or MFA change)."""
    try:
        execute_query("DELETE FROM trusted_browsers WHERE user_id = %s", (user_id,))
    except Exception:
        logger.warning("could not forget remembered browsers", exc_info=True)


def count(user_id: str) -> int:
    try:
        row = execute_one(
            "SELECT count(*) AS n FROM trusted_browsers WHERE user_id = %s AND expires_at > now()",
            (user_id,),
        )
        return int((row or {}).get("n") or 0)
    except Exception:
        return 0
