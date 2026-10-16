"""Owner console API: sign-in, session and sign-out (admin.cyphward.com).

See backend/app/core/owner.py for the access model. Data views and actions
are added on this router in later stages; every one depends on
`require_owner` (reads) or `require_owner_mutation` (changes) and writes an
owner audit row.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend.app.core import owner as owner_mod
from backend.app.core import totp as totp_mod
from backend.app.core.database import execute_one
from backend.app.core.rate_limit import check_rate_limit
from backend.app.core.security import verify_password

router = APIRouter(prefix="/api/v1/owner", tags=["Owner console"])

_LOGIN_MAX = 5
_LOGIN_IP_MAX = 20
_LOGIN_WINDOW_SECONDS = 900
_GENERIC_FAILURE = "Sign-in failed."


class OwnerLoginBody(BaseModel):
    email: str = ""
    password: str = ""
    code: str = ""


@router.post("/session")
async def owner_sign_in(body: OwnerLoginBody, request: Request, response: Response) -> Dict[str, Any]:
    """Email + password + current authenticator code, all at once.

    Every failure (unknown account, wrong password, not an owner, no
    authenticator, wrong or replayed code, throttled) returns the same 401
    so nothing reveals which factor was wrong.
    """
    owner_mod.require_console_origin(request)
    email = (body.email or "").strip().lower()
    ip = owner_mod.client_ip(request) or "unknown"
    try:
        check_rate_limit(f"owner-login:{email}", _LOGIN_MAX, _LOGIN_WINDOW_SECONDS)
        check_rate_limit(f"owner-login-ip:{ip}", _LOGIN_IP_MAX, _LOGIN_WINDOW_SECONDS)
    except HTTPException:
        owner_mod.audit(request, "owner.sign_in", "throttled", email=email or None)
        raise HTTPException(status_code=401, detail=_GENERIC_FAILURE)

    def fail(reason: str, user_id: str | None = None) -> HTTPException:
        owner_mod.audit(request, "owner.sign_in", "denied", user_id=user_id, email=email or None,
                        metadata={"reason": reason})
        return HTTPException(status_code=401, detail=_GENERIC_FAILURE)

    user = execute_one("SELECT * FROM profiles WHERE email = %s", (email,)) if email else None
    if not user or not verify_password(user.get("password_hash"), body.password or ""):
        raise fail("credentials")
    uid = str(user["id"])
    if not owner_mod.is_owner(uid):
        raise fail("not_owner", uid)
    if not user.get("totp_secret_enc") or user.get("totp_enrolled_at") is None:
        raise fail("no_authenticator", uid)
    try:
        secret = totp_mod.decrypt_secret(user["totp_secret_enc"])
    except ValueError:
        raise fail("authenticator_unreadable", uid)
    step = totp_mod.matching_step(secret, body.code or "")
    if step is None:
        raise fail("code", uid)
    if not owner_mod.accept_totp_step(uid, step):
        raise fail("code_replayed", uid)

    session = owner_mod.start_session(request, response, uid)
    try:
        owner_mod.audit(request, "owner.sign_in", "success", user_id=uid, email=email,
                        session_id=session["session_id"])
    except HTTPException:
        execute_one("UPDATE owner_sessions SET revoked_at = now() WHERE id = %s RETURNING id",
                    (session["session_id"],))
        owner_mod.clear_cookie(response)
        raise
    return {"ok": True, "email": email, "expires_at": session["expires_at"].isoformat(),
            "idle_minutes": owner_mod.IDLE_MINUTES}


@router.get("/me")
async def owner_me(owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    return {"email": owner["email"], "expires_at": owner["expires_at"].isoformat(),
            "idle_minutes": owner_mod.IDLE_MINUTES}


@router.post("/logout")
async def owner_sign_out(request: Request, response: Response) -> Dict[str, Any]:
    """Always clears the cookie, with or without a live session."""
    revoked = owner_mod.revoke_session_by_token(request.cookies.get(owner_mod.COOKIE_NAME))
    owner_mod.clear_cookie(response)
    if revoked:
        owner_mod.audit(request, "owner.sign_out", "success", user_id=str(revoked["user_id"]),
                        session_id=str(revoked["id"]))
    return {"signed_out": True}
