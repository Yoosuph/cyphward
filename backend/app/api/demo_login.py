"""Demo sign-in for the sample organisation (see backend/scripts/seed_fintech_demo.py).

Off unless the server sets DEMO_LOGIN_ENABLED=true AND DEMO_LOGIN_PASSWORD. The browser sends no password:
the server checks the demo password from its environment against the demo owner's stored hash, then issues
the same session the password login issues. The demo owner must belong to the demo organisation and to no
other, and must not be a platform console user. When the flag is off the route answers 404, as if it did not exist.
"""
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from backend.app.core import owner as owner_mod
from backend.app.core.auth import log_audit
from backend.app.core.database import execute_one, execute_query
from backend.app.core.demo_org import DEMO_ORG_ID, DEMO_USER_ID
from backend.app.core.rate_limit import check_rate_limit
from backend.app.core.security import verify_password
from backend.app.core.sessions import issue_session

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

DEMO_EMAIL = "demo.owner@fintech-org.test"
DEMO_LOGIN_MAX_ATTEMPTS = 10
DEMO_LOGIN_WINDOW_SECONDS = 600


def is_enabled() -> bool:
    """Read at request time so the flag can be changed without code, and tests can toggle it."""
    flag = os.getenv("DEMO_LOGIN_ENABLED", "").strip().lower() == "true"
    return flag and bool(os.getenv("DEMO_LOGIN_PASSWORD", ""))


@router.get("/demo-login")
def demo_login_status() -> Dict[str, bool]:
    """Tells the sign-in page whether to show the demo button. Reveals nothing about the account."""
    return {"enabled": is_enabled()}


@router.post("/demo-login")
def demo_login() -> Dict[str, Any]:
    if not is_enabled():
        raise HTTPException(status_code=404, detail="Not found.")
    check_rate_limit("demo-login", DEMO_LOGIN_MAX_ATTEMPTS, DEMO_LOGIN_WINDOW_SECONDS)
    user = execute_one("SELECT * FROM profiles WHERE id = %s AND email = %s", (DEMO_USER_ID, DEMO_EMAIL))
    if not user or not verify_password(user.get("password_hash"), os.environ["DEMO_LOGIN_PASSWORD"]):
        raise HTTPException(status_code=404, detail="Not found.")
    memberships = [str(row["org_id"]) for row in execute_query(
        "SELECT org_id FROM organization_members WHERE user_id = %s", (DEMO_USER_ID,)) or []]
    if memberships != [DEMO_ORG_ID] or owner_mod.is_console_only(DEMO_USER_ID):
        raise HTTPException(status_code=404, detail="Not found.")
    log_audit(DEMO_ORG_ID, DEMO_USER_ID, "auth.demo_login", "user", DEMO_USER_ID, {"sample": True})
    return issue_session(user)
