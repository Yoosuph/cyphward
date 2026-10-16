"""Platform-owner console access (admin.cyphward.com).

One principal, the owner of the Cyphward platform, who can see every
customer's data. It is the most valuable account, so access is separate from
the customer app on every axis:

* Entry needs email + password + a fresh authenticator (TOTP) code in one
  request. Google sign-in, the emailed code and remembered browsers never
  count. Each TOTP step is accepted once (replay-safe).
* Owner status lives in `platform_owners`; the app role can only read it, so
  nobody becomes an owner through the API. It is checked on every request:
  removing the row ends access immediately.
* The session is an opaque random token in an httpOnly, host-only
  (`__Host-`) SameSite=Strict cookie; only its SHA-256 is stored. 30 minutes
  idle, 8 hours absolute, both enforced server-side.
* Owner endpoints accept only that cookie and refuse a bearer token; customer
  endpoints never read it. Mutations require the exact console Origin.
* Every attempt and action is written to `owner_audit` (no foreign keys, so
  customer deletion cannot erase it). If the audit write fails, the request
  fails without returning data.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, Response

from backend.app.core.config import CYPHWARD_ENV, OWNER_CONSOLE_ORIGINS
from backend.app.core.database import execute_one, execute_query

IDLE_MINUTES = 30
ABSOLUTE_HOURS = 8
SETUP_SESSION_MINUTES = 15
_SECURE = CYPHWARD_ENV == "production"
COOKIE_NAME = "__Host-cw_owner" if _SECURE else "cw_owner"

logger = logging.getLogger("cyphward.owner")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def client_ip(request: Request) -> Optional[str]:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return (forwarded or (request.client.host if request.client else "") or None)


def audit(request: Optional[Request], action: str, outcome: str, *,
          user_id: Optional[str] = None, email: Optional[str] = None,
          session_id: Optional[str] = None, target_type: Optional[str] = None,
          target_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
    """Durable owner audit row. Raises 503 when it cannot be written: callers
    must not return data or claim success without their audit record."""
    import json
    try:
        execute_query(
            "INSERT INTO owner_audit (actor_user_id, actor_email, session_id, action, outcome, "
            "target_type, target_id, ip, user_agent, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
            (user_id, (email or None), session_id, action, outcome, target_type, target_id,
             client_ip(request) if request else None,
             ((request.headers.get("user-agent") or "")[:200] or None) if request else None,
             json.dumps(metadata or {})),
        )
    except Exception:
        logger.exception("owner audit write failed for %s", action)
        raise HTTPException(status_code=503, detail="Owner console is temporarily unavailable.")


def is_owner(user_id: str) -> bool:
    return execute_one("SELECT user_id FROM platform_owners WHERE user_id = %s", (user_id,)) is not None


def accept_totp_step(user_id: str, step: int) -> bool:
    """Atomically record the TOTP step; False if this or a later step was already used."""
    row = execute_one(
        "UPDATE platform_owners SET last_totp_step = %s WHERE user_id = %s "
        "AND (last_totp_step IS NULL OR last_totp_step < %s) RETURNING user_id",
        (step, user_id, step),
    )
    return row is not None


def is_console_only(user_id: str) -> bool:
    """A dedicated admin login: never signs in to the customer app."""
    try:
        row = execute_one("SELECT console_only FROM platform_owners WHERE user_id = %s", (user_id,))
    except Exception:
        logger.warning("console-only check failed", exc_info=True)
        return False
    return bool(row and row.get("console_only"))


def setup_open(user_id: str) -> bool:
    """An operator-opened first sign-in that has not expired or completed."""
    row = execute_one(
        "SELECT user_id FROM owner_setups WHERE user_id = %s AND completed_at IS NULL AND expires_at > now()",
        (user_id,),
    )
    return row is not None


def start_session(request: Request, response: Response, user_id: str, purpose: str = "console") -> Dict[str, Any]:
    """Console session (8 h) or a setup-only session (15 min) for first sign-in."""
    token = secrets.token_urlsafe(32)
    lifetime = timedelta(hours=ABSOLUTE_HOURS) if purpose == "console" else timedelta(minutes=SETUP_SESSION_MINUTES)
    expires_at = datetime.now(timezone.utc) + lifetime
    row = execute_one(
        "INSERT INTO owner_sessions (user_id, token_hash, expires_at, user_agent, ip, purpose) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (user_id, _hash(token), expires_at,
         (request.headers.get("user-agent") or "")[:200] or None, client_ip(request), purpose),
    )
    response.set_cookie(COOKIE_NAME, token, max_age=int(lifetime.total_seconds()), path="/",
                        secure=_SECURE, httponly=True, samesite="strict")
    return {"session_id": str(row["id"]), "expires_at": expires_at}


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", secure=_SECURE, httponly=True, samesite="strict")


def revoke_session_by_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token or len(token) > 200:
        return None
    return execute_one(
        "UPDATE owner_sessions SET revoked_at = now() WHERE token_hash = %s AND revoked_at IS NULL "
        "RETURNING id, user_id",
        (_hash(token),),
    )


def revoke_all_sessions(user_id: str) -> None:
    """Credential/factor change: end every owner session for the user (best effort)."""
    try:
        execute_query("UPDATE owner_sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
                      (user_id,))
    except Exception:
        logger.warning("could not revoke owner sessions", exc_info=True)


def _session_for(request: Request, purpose: str) -> Dict[str, Any]:
    if request.headers.get("authorization"):
        raise HTTPException(status_code=401, detail="Owner console uses its own sign-in.")
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 200:
        raise HTTPException(status_code=401, detail="Owner sign-in required.")
    row = execute_one(
        "SELECT s.id, s.user_id, s.expires_at, s.last_seen_at, p.email "
        "FROM owner_sessions s JOIN platform_owners o ON o.user_id = s.user_id "
        "JOIN profiles p ON p.id = s.user_id "
        "WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.purpose = %s",
        (_hash(token), purpose),
    )
    return row


def require_setup_session(request: Request) -> Dict[str, Any]:
    """First sign-in only: the session can choose a password and enrol an authenticator, nothing else."""
    row = _session_for(request, "setup")
    if row is None:
        raise HTTPException(status_code=401, detail="Setup session expired — sign in again.")
    expires_at = row["expires_at"] if row["expires_at"].tzinfo else row["expires_at"].replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc) or not setup_open(str(row["user_id"])):
        raise HTTPException(status_code=401, detail="Setup session expired — sign in again.")
    return {"user_id": str(row["user_id"]), "email": row.get("email"), "session_id": str(row["id"])}


def require_owner(request: Request) -> Dict[str, Any]:
    """Owner session from the console cookie only; never a bearer token or a setup session."""
    row = _session_for(request, "console")
    now = datetime.now(timezone.utc)
    if row is None:
        raise HTTPException(status_code=401, detail="Owner sign-in required.")
    expires_at, last_seen = row["expires_at"], row["last_seen_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if expires_at <= now or now - last_seen > timedelta(minutes=IDLE_MINUTES):
        execute_query("UPDATE owner_sessions SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL",
                      (row["id"],))
        raise HTTPException(status_code=401, detail="Owner session expired — sign in again.")
    execute_query("UPDATE owner_sessions SET last_seen_at = now() WHERE id = %s", (row["id"],))
    return {"user_id": str(row["user_id"]), "email": row.get("email"), "session_id": str(row["id"]),
            "expires_at": expires_at}


def require_console_origin(request: Request) -> None:
    """CSRF guard for state-changing owner requests: exact console Origin only."""
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin not in OWNER_CONSOLE_ORIGINS:
        raise HTTPException(status_code=403, detail="Request must come from the owner console.")


def require_owner_mutation(request: Request,
                           owner: Dict[str, Any] = Depends(require_owner)) -> Dict[str, Any]:
    require_console_origin(request)
    return owner
