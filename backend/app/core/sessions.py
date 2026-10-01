"""
Auth session storage for Cyphward Auth — refresh tokens and Google exchange codes.

Opaque tokens are stored only as SHA-256 hashes; refresh tokens rotate on
every use and can be revoked (logout, password reset).
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.app.core.auth import issue_access_token
from backend.app.core.config import ACCESS_TOKEN_TTL_SECONDS, REFRESH_TOKEN_TTL_SECONDS
from backend.app.core.database import execute_one, execute_query
from backend.app.core.security import hash_opaque_token, new_opaque_token


def public_user(profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(profile["id"]),
        "email": (profile.get("email") or "").strip().lower(),
        "full_name": profile.get("full_name") or "",
        "email_verified_at": profile.get("email_verified_at"),
        "provider": profile.get("provider") or "email",
    }


def token_response(profile: Dict[str, Any], refresh_token: str) -> Dict[str, Any]:
    return {
        "access_token": issue_access_token(profile),
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "user": public_user(profile),
    }


def _create_session_row(
    user_id: str, refresh_token: str, otc: Optional[str] = None
) -> None:
    if otc:
        execute_one(
            """
            INSERT INTO auth_sessions (user_id, refresh_token_hash, otc_hash, otc_expires_at, expires_at)
            VALUES (%s, %s, %s, now() + interval '5 minutes', now() + make_interval(secs => %s))
            RETURNING id
            """,
            (user_id, hash_opaque_token(refresh_token), hash_opaque_token(otc), REFRESH_TOKEN_TTL_SECONDS),
        )
    else:
        execute_one(
            """
            INSERT INTO auth_sessions (user_id, refresh_token_hash, expires_at)
            VALUES (%s, %s, now() + make_interval(secs => %s))
            RETURNING id
            """,
            (user_id, hash_opaque_token(refresh_token), REFRESH_TOKEN_TTL_SECONDS),
        )


def issue_session(profile: Dict[str, Any], otc: Optional[str] = None) -> Dict[str, Any]:
    """Create a session row and return access + refresh tokens for the caller."""
    refresh_token = new_opaque_token()
    _create_session_row(str(profile["id"]), refresh_token, otc)
    return token_response(profile, refresh_token)


def _not_expired(ts: Any) -> bool:
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < ts


def rotate_refresh_token(old_refresh_token: str) -> Optional[Dict[str, Any]]:
    """Validate + rotate a refresh token; returns new tokens or None if invalid."""
    session = execute_one(
        "SELECT * FROM auth_sessions WHERE refresh_token_hash = %s",
        (hash_opaque_token(old_refresh_token),),
    )
    if not session or session.get("revoked_at") is not None or not _not_expired(session.get("expires_at")):
        return None
    profile = execute_one("SELECT * FROM profiles WHERE id = %s", (session["user_id"],))
    if not profile:
        return None
    new_refresh = new_opaque_token()
    execute_query(
        "UPDATE auth_sessions SET refresh_token_hash = %s, last_used_at = now() WHERE id = %s",
        (hash_opaque_token(new_refresh), session["id"]),
    )
    return token_response(profile, new_refresh)


def consume_otc(otc: str) -> Optional[Dict[str, Any]]:
    """Single-use Google exchange code -> session tokens (refresh rotated)."""
    session = execute_one(
        "SELECT * FROM auth_sessions WHERE otc_hash = %s AND revoked_at IS NULL",
        (hash_opaque_token(otc),),
    )
    if not session or not _not_expired(session.get("otc_expires_at")):
        return None
    profile = execute_one("SELECT * FROM profiles WHERE id = %s", (session["user_id"],))
    if not profile:
        return None
    new_refresh = new_opaque_token()
    execute_query(
        "UPDATE auth_sessions SET otc_hash = NULL, otc_expires_at = NULL, "
        "refresh_token_hash = %s, last_used_at = now() WHERE id = %s",
        (hash_opaque_token(new_refresh), session["id"]),
    )
    return token_response(profile, new_refresh)


def revoke_session(refresh_token: str) -> None:
    execute_query(
        "UPDATE auth_sessions SET revoked_at = now() "
        "WHERE refresh_token_hash = %s AND revoked_at IS NULL",
        (hash_opaque_token(refresh_token),),
    )


def revoke_all_sessions(user_id: str) -> None:
    execute_query(
        "UPDATE auth_sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
        (str(user_id),),
    )
