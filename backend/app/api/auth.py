"""
Cyphward Auth lifecycle endpoints (greetings, welcome mail, email OTP).

POST /api/v1/auth/welcome
    Queues a welcome email to the account's own address (recipient always
    derived server-side from verified claims).

POST /api/v1/auth/otp/send
POST /api/v1/auth/otp/verify
GET  /api/v1/auth/verification
    Brevo-delivered 6-digit email verification. Supabase auth stays silent
    (mailer_autoconfirm); verification is owned by this backend. Codes are
    stored as SHA-256 hashes only, expire after 10 minutes, and allow 5
    attempts with a 60s resend cooldown.
"""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from backend.app.core.auth import get_current_user, log_audit
from backend.app.core.database import execute_one, execute_query
from backend.app.services.mailer import (
    generate_otp_email_html,
    generate_otp_email_text,
    generate_welcome_email_html,
    generate_welcome_email_text,
    send_email_async,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

# One welcome mail per account per hour (signup trigger + login retry can race).
_WELCOME_COOLDOWN_SECONDS = 3600
_last_sent: Dict[str, float] = {}

# Email OTP policy
_OTP_TTL_SECONDS = 600
_OTP_RESEND_SECONDS = 60
_OTP_MAX_ATTEMPTS = 5


def _prune(now: float) -> None:
    expired = [uid for uid, ts in _last_sent.items() if now - ts >= _WELCOME_COOLDOWN_SECONDS]
    for uid in expired:
        _last_sent.pop(uid, None)


def _hash_code(email: str, code: str) -> str:
    """One-way hash binding the code to the account (never store plaintext)."""
    return hashlib.sha256(f"{email}:{code}".encode("utf-8")).hexdigest()


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


class OtpVerifyBody(BaseModel):
    code: str


@router.post("/otp/send")
async def send_verification_otp(
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Queue a 6-digit verification code to the JWT-verified account email (Brevo)."""
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Account has no email address on file.")
    if user.get("email_verified_at"):
        return {"sent": False, "reason": "already_verified"}

    latest = execute_one(
        "SELECT created_at FROM email_otps WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
        (user["id"],),
    )
    if latest is not None and latest.get("created_at") is not None:
        created = latest["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - created).total_seconds()
        if elapsed < _OTP_RESEND_SECONDS:
            raise HTTPException(
                status_code=429,
                detail=f"Resend available in {int(_OTP_RESEND_SECONDS - elapsed) + 1}s.",
            )

    code = f"{secrets.randbelow(1_000_000):06d}"
    execute_query("DELETE FROM email_otps WHERE user_id = %s", (user["id"],))
    execute_query(
        """
        INSERT INTO email_otps (user_id, code_hash, expires_at)
        VALUES (%s, %s, now() + make_interval(secs => %s))
        """,
        (user["id"], _hash_code(email, code), _OTP_TTL_SECONDS),
    )

    name = (user.get("full_name") or email.split("@")[0]).strip()
    background_tasks.add_task(
        send_email_async,
        email,
        "Your Cyphward verification code",
        generate_otp_email_html(name, code),
        generate_otp_email_text(name, code),
        recipient_name=name,
    )
    log_audit(None, str(user["id"]), "auth.otp_sent", "user", str(user["id"]))
    return {"sent": True, "expires_in": _OTP_TTL_SECONDS, "resend_after": _OTP_RESEND_SECONDS}


@router.post("/otp/verify")
async def verify_verification_otp(
    body: OtpVerifyBody,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Validate the 6-digit code and mark the account's email as verified."""
    code = body.code.strip()
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="Enter the 6-digit code.")

    email = (user.get("email") or "").strip().lower()
    row = execute_one(
        """
        SELECT id, code_hash, attempts, expires_at
        FROM email_otps WHERE user_id = %s
        ORDER BY created_at DESC LIMIT 1
        """,
        (user["id"],),
    )
    if row is None:
        raise HTTPException(status_code=400, detail="No active code — request a new one.")

    remaining = _OTP_MAX_ATTEMPTS - int(row.get("attempts") or 0)
    if remaining <= 0:
        execute_query("DELETE FROM email_otps WHERE user_id = %s", (user["id"],))
        raise HTTPException(status_code=429, detail="Too many attempts — request a new code.")

    expires_at = row.get("expires_at")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            execute_query("DELETE FROM email_otps WHERE user_id = %s", (user["id"],))
            raise HTTPException(status_code=400, detail="That code has expired — request a new one.")

    execute_query("UPDATE email_otps SET attempts = attempts + 1 WHERE id = %s", (row["id"],))

    if not hmac.compare_digest(str(row.get("code_hash") or ""), _hash_code(email, code)):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid code — {remaining - 1} attempt(s) left.",
        )

    execute_query(
        "UPDATE profiles SET email_verified_at = now(), updated_at = now() WHERE id = %s",
        (user["id"],),
    )
    execute_query("DELETE FROM email_otps WHERE user_id = %s", (user["id"],))
    log_audit(None, str(user["id"]), "auth.email_verified", "user", str(user["id"]))
    return {"verified": True}


@router.get("/verification")
async def get_verification_status(
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Whether the account's email has been verified (drives onboarding routing)."""
    return {
        "email": (user.get("email") or "").strip().lower(),
        "verified": bool(user.get("email_verified_at")),
    }
