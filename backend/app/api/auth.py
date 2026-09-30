"""
Cyphward Auth lifecycle endpoints (greetings & welcome mail).

POST /api/v1/auth/welcome
    Verifies the caller's Supabase JWT (real auth chain: JWT -> profile upsert),
    then queues a welcome email to the account's own address. The recipient is
    always derived server-side from verified claims — never trusted from the
    client — so this endpoint cannot be used to mail arbitrary addresses.
"""
import time
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from backend.app.core.auth import get_current_user
from backend.app.services.mailer import (
    generate_welcome_email_html,
    generate_welcome_email_text,
    send_email_async,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

# One welcome mail per account per hour (signup trigger + login retry can race).
_WELCOME_COOLDOWN_SECONDS = 3600
_last_sent: Dict[str, float] = {}


def _prune(now: float) -> None:
    expired = [uid for uid, ts in _last_sent.items() if now - ts >= _WELCOME_COOLDOWN_SECONDS]
    for uid in expired:
        _last_sent.pop(uid, None)


@router.post("/welcome")
async def send_welcome_email(
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Account has no email address on file.")

    now = time.time()
    _prune(now)
    last = _last_sent.get(user["id"])
    if last is not None and now - last < _WELCOME_COOLDOWN_SECONDS:
        return {"sent": False, "reason": "recently_sent"}

    _last_sent[user["id"]] = now

    name = (user.get("full_name") or email.split("@")[0]).strip()
    first_name = name.split(" ")[0]
    background_tasks.add_task(
        send_email_async,
        email,
        f"Welcome to Cyphward, {first_name}",
        generate_welcome_email_html(name, email),
        generate_welcome_email_text(name, email),
        recipient_name=name,
    )
    return {"sent": True}
