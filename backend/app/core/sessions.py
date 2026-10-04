"""
Auth session storage for Cyphward Auth — refresh tokens and Google exchange codes.

Opaque tokens are stored only as SHA-256 hashes; refresh tokens rotate on
every use and can be revoked (logout, password reset).
"""
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
        "mfa_enrolled": profile.get("mfa_enrolled_at") is not None,
        "provider": profile.get("provider") or "email",
    }


def token_response(
    profile: Dict[str, Any], refresh_token: str, session_id: Optional[str] = None
) -> Dict[str, Any]:
    return {
        "access_token": issue_access_token(profile, session_id),
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "user": public_user(profile),
    }


def _create_session_row(
    user_id: str, refresh_token: str, otc: Optional[str] = None
) -> str:
    if otc:
        row = execute_one(
            """
            INSERT INTO auth_sessions (user_id, refresh_token_hash, otc_hash, otc_expires_at, expires_at)
            VALUES (%s, %s, %s, now() + interval '5 minutes', now() + make_interval(secs => %s))
            RETURNING id
            """,
            (user_id, hash_opaque_token(refresh_token), hash_opaque_token(otc), REFRESH_TOKEN_TTL_SECONDS),
        )
    else:
        row = execute_one(
            """
            INSERT INTO auth_sessions (user_id, refresh_token_hash, expires_at)
            VALUES (%s, %s, now() + make_interval(secs => %s))
            RETURNING id
            """,
            (user_id, hash_opaque_token(refresh_token), REFRESH_TOKEN_TTL_SECONDS),
        )
    return str(row["id"]) if row else ""


def issue_session(profile: Dict[str, Any], otc: Optional[str] = None) -> Dict[str, Any]:
    """Create a session row and return access + refresh tokens for the caller."""
    refresh_token = new_opaque_token()
    session_id = _create_session_row(str(profile["id"]), refresh_token, otc)
    return token_response(profile, refresh_token, session_id)


def rotate_refresh_token(old_refresh_token: str) -> Optional[Dict[str, Any]]:
    """Validate + rotate a refresh token; returns new tokens or None if invalid.

    The write is a conditional compare-and-set (old hash + not revoked + not
    expired in the same statement), so a replayed or concurrently-rotated
    token loses the race and gets nothing — single-use is enforced by the
    database, not by read-then-write timing (review P1).
    """
    old_hash = hash_opaque_token(old_refresh_token)
    session = execute_one(
        "SELECT id, user_id FROM auth_sessions WHERE refresh_token_hash = %s",
        (old_hash,),
    )
    if not session:
        return None
    profile = execute_one("SELECT * FROM profiles WHERE id = %s", (session["user_id"],))
    if not profile:
        return None
    new_refresh = new_opaque_token()
    rotated = execute_one(
        """
        UPDATE auth_sessions
        SET refresh_token_hash = %s, last_used_at = now()
        WHERE id = %s AND refresh_token_hash = %s
          AND revoked_at IS NULL AND expires_at > now()
        RETURNING id
        """,
        (hash_opaque_token(new_refresh), session["id"], old_hash),
    )
    if not rotated:
        return None  # already rotated / revoked / expired by someone else
    return token_response(profile, new_refresh, str(session["id"]))


def consume_otc(otc: str) -> Optional[Dict[str, Any]]:
    """Single-use Google exchange code -> session tokens (refresh rotated)."""
    otc_hash = hash_opaque_token(otc)
    session = execute_one(
        "SELECT id, user_id FROM auth_sessions WHERE otc_hash = %s AND revoked_at IS NULL",
        (otc_hash,),
    )
    if not session:
        return None
    profile = execute_one("SELECT * FROM profiles WHERE id = %s", (session["user_id"],))
    if not profile:
        return None
    new_refresh = new_opaque_token()
    consumed = execute_one(
        """
        UPDATE auth_sessions
        SET otc_hash = NULL, otc_expires_at = NULL,
            refresh_token_hash = %s, last_used_at = now()
        WHERE id = %s AND otc_hash = %s
          AND revoked_at IS NULL AND otc_expires_at > now()
        RETURNING id
        """,
        (hash_opaque_token(new_refresh), session["id"], otc_hash),
    )
    if not consumed:
        return None  # already consumed / revoked / expired by someone else
    return token_response(profile, new_refresh, str(session["id"]))


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
