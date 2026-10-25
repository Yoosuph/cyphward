"""Public demo sign-in, gated by explicit server configuration.

An existing account requires pinned user/org/email identities and receives a
signed, view-only workspace scope that persists through refresh. Its normal
password, owner permissions and MFA policy are unaffected. The legacy synthetic
demo retains its password check when no public target is configured.
"""
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.app.core import owner as owner_mod
from backend.app.core.auth import log_audit
from backend.app.core.auth import get_current_org, get_current_user
from backend.app.core.database import execute_one, execute_query
from backend.app.core.demo_org import DEMO_ORG_ID, DEMO_USER_ID, public_demo_configured, public_demo_target
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
    if public_demo_configured():
        return flag and public_demo_target() is not None
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
    if user.get("session_demo_org_id") or str(user.get("id")) == DEMO_USER_ID:
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
    target = public_demo_target() if public_demo_configured() else None
    user_id = target["user_id"] if target else DEMO_USER_ID
    org_id = target["org_id"] if target else DEMO_ORG_ID
    email = target["email"] if target else DEMO_EMAIL
    user = execute_one("SELECT * FROM profiles WHERE id = %s AND email = %s", (user_id, email))
    if not user or (not target and not verify_password(user.get("password_hash"), os.environ["DEMO_LOGIN_PASSWORD"])):
        raise HTTPException(status_code=404, detail="Not found.")
    memberships = execute_query(
        "SELECT org_id, role FROM organization_members WHERE user_id = %s", (user_id,)) or []
    only = memberships[0] if len(memberships) == 1 else None
    # An explicitly pinned public account may retain ownership in the database:
    # its demo sessions carry a signed view-only scope, including after refresh.
    allowed_roles = ("member", "admin", "owner") if target else ("member", "admin")
    if only is None or str(only["org_id"]) != org_id or only["role"] not in allowed_roles:
        raise HTTPException(status_code=404, detail="Not found.")
    if user.get("mfa_enrolled_at") is not None or user.get("totp_enrolled_at") is not None:
        raise HTTPException(status_code=404, detail="Not found.")
    if target and not user.get("email_verified_at"):
        raise HTTPException(status_code=404, detail="Not found.")
    # A failed lookup refuses; owner_mod.is_console_only would treat an error as "not a console user".
    console = execute_query("SELECT console_only FROM platform_owners WHERE user_id = %s", (user_id,))
    if console is None or any(row.get("console_only") for row in console) or owner_mod.is_owner(user_id):
        raise HTTPException(status_code=404, detail="Not found.")
    log_audit(org_id, user_id, "auth.demo_login", "user", user_id, {"sample": not bool(target), "read_only": bool(target)})
    return issue_session(user, demo_org_id=org_id) if target else issue_session(user)


def limit_demo_ai(org: Dict[str, Any] = Depends(get_current_org)) -> None:
    """Router dependency for the AI endpoints: caps the demo account's calls. Every other account is unaffected."""
    user_id = str(org.get("current_user_id") or "")
    if org.get("demo_session") or user_id == DEMO_USER_ID:
        try:
            check_rate_limit(f"demo-ai:{user_id}", DEMO_AI_MAX_CALLS, DEMO_AI_WINDOW_SECONDS)
        except HTTPException as exc:
            if exc.status_code != 429:
                raise
            raise HTTPException(
                status_code=429,
                detail=(f"CyphBot's shared demo limit has been reached ({DEMO_AI_MAX_CALLS} requests per hour). "
                        "Please try again after the current window resets."),
                headers=exc.headers,
            ) from None
