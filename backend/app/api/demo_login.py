"""Demo sign-in for the sample organisation (see backend/scripts/seed_fintech_demo.py).

Off unless the server sets DEMO_LOGIN_ENABLED=true AND DEMO_LOGIN_PASSWORD. The browser sends no password:
the server checks the demo password from its environment against the demo owner's stored hash, then issues
the same session the password login issues. The demo owner must belong to the demo organisation and to no
other, and must not be a platform console user. When the flag is off the route answers 404, as if it did not exist.
"""
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.app.core import owner as owner_mod
from backend.app.core.auth import log_audit
from backend.app.core.auth import get_current_org, get_current_user
from backend.app.core.database import execute_one, execute_query
from backend.app.core.demo_org import DEMO_ORG_ID, DEMO_USER_ID
from backend.app.core.rate_limit import check_rate_limit
from backend.app.core.security import verify_password
from backend.app.core.sessions import issue_session

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

DEMO_EMAIL = "demo.owner@fintech-org.test"
DEMO_LOGIN_MAX_ATTEMPTS = 10  # per client address, so one visitor cannot lock out the others
DEMO_LOGIN_GLOBAL_MAX = 300  # ceiling across all clients per hour, whatever the addresses claim
DEMO_LOGIN_WINDOW_SECONDS = 600
DEMO_AI_MAX_CALLS = 30  # per hour for the demo account, which bounds model spend
DEMO_AI_WINDOW_SECONDS = 3600


def is_enabled() -> bool:
    """Read at request time so the flag can be changed without code, and tests can toggle it."""
    flag = os.getenv("DEMO_LOGIN_ENABLED", "").strip().lower() == "true"
    return flag and bool(os.getenv("DEMO_LOGIN_PASSWORD", ""))


def _client_address(request: Request) -> str:
    """The hop the proxy adds: the last X-Forwarded-For entry. The leftmost value is set by the client."""
    joined = ",".join(request.headers.getlist("x-forwarded-for"))
    hops = [hop.strip() for hop in joined.split(",") if hop.strip()]
    if hops:
        return hops[-1]
    return request.client.host if request.client else "unknown"


def refuse_demo_account(user: Dict[str, Any] = Depends(get_current_user)) -> None:
    """Account-level changes (second factors, organisations, invites, domains, scans, profile) are closed to the
    shared demo account. Document-level and organisation-level edits inside the demo stay open."""
    if str(user.get("id")) == DEMO_USER_ID:
        raise HTTPException(status_code=403, detail="This change is not available on the sample account.")


@router.get("/demo-login")
def demo_login_status() -> Dict[str, bool]:
    """Tells the sign-in page whether to show the demo button. Reveals nothing about the account."""
    return {"enabled": is_enabled()}


@router.post("/demo-login")
def demo_login(request: Request) -> Dict[str, Any]:
    if not is_enabled():
        raise HTTPException(status_code=404, detail="Not found.")
    check_rate_limit(f"demo-login:{_client_address(request)}", DEMO_LOGIN_MAX_ATTEMPTS, DEMO_LOGIN_WINDOW_SECONDS)
    check_rate_limit("demo-login:all", DEMO_LOGIN_GLOBAL_MAX, 3600)
    user = execute_one("SELECT * FROM profiles WHERE id = %s AND email = %s", (DEMO_USER_ID, DEMO_EMAIL))
    if not user or not verify_password(user.get("password_hash"), os.environ["DEMO_LOGIN_PASSWORD"]):
        raise HTTPException(status_code=404, detail="Not found.")
    memberships = execute_query(
        "SELECT org_id, role FROM organization_members WHERE user_id = %s", (DEMO_USER_ID,)) or []
    only = memberships[0] if len(memberships) == 1 else None
    # Member or admin of the demo organisation only: never owner, and no second factor enrolled.
    if only is None or str(only["org_id"]) != DEMO_ORG_ID or only["role"] not in ("member", "admin"):
        raise HTTPException(status_code=404, detail="Not found.")
    if user.get("mfa_enrolled_at") is not None or user.get("totp_enrolled_at") is not None:
        raise HTTPException(status_code=404, detail="Not found.")
    # A failed lookup refuses; owner_mod.is_console_only would treat an error as "not a console user".
    console = execute_query("SELECT console_only FROM platform_owners WHERE user_id = %s", (DEMO_USER_ID,))
    if console is None or any(row.get("console_only") for row in console) or owner_mod.is_owner(DEMO_USER_ID):
        raise HTTPException(status_code=404, detail="Not found.")
    log_audit(DEMO_ORG_ID, DEMO_USER_ID, "auth.demo_login", "user", DEMO_USER_ID, {"sample": True})
    return issue_session(user)


def limit_demo_ai(org: Dict[str, Any] = Depends(get_current_org)) -> None:
    """Router dependency for the AI endpoints: caps the demo account's calls. Every other account is unaffected."""
    if str(org.get("current_user_id") or "") == DEMO_USER_ID:
        try:
            check_rate_limit(f"demo-ai:{DEMO_USER_ID}", DEMO_AI_MAX_CALLS, DEMO_AI_WINDOW_SECONDS)
        except HTTPException as exc:
            if exc.status_code != 429:
                raise
            raise HTTPException(
                status_code=429,
                detail=(f"CyphBot's shared demo limit has been reached ({DEMO_AI_MAX_CALLS} requests per hour). "
                        "Please try again after the current window resets."),
                headers=exc.headers,
            ) from None
