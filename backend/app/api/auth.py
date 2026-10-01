"""
Cyphward Auth lifecycle endpoints (our own auth — no Supabase Auth).

Credentials & sessions:
POST /api/v1/auth/register        create account (argon2id), returns session tokens
POST /api/v1/auth/login           email + password -> session tokens
POST /api/v1/auth/refresh         rotate refresh token
POST /api/v1/auth/logout          revoke a refresh token
POST /api/v1/auth/forgot-password Brevo password-reset link (30-min single-use token)
POST /api/v1/auth/reset-password  consume the link, set new password, revoke sessions
GET  /api/v1/auth/bootstrap       profile + memberships + domains (drives onboarding)

Email verification (Brevo 6-digit OTP, SHA-256 hashed, 10-min TTL, 5 attempts,
60s resend cooldown):
POST /api/v1/auth/otp/send
POST /api/v1/auth/otp/verify
GET  /api/v1/auth/verification

POST /api/v1/auth/welcome         welcome email (recipient from verified claims)
"""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from backend.app.core.auth import execute_query_memberships, get_current_user, log_audit
from backend.app.core.config import FRONTEND_URL, REFRESH_TOKEN_TTL_SECONDS
from backend.app.core.database import execute_one, execute_query
from backend.app.core.security import hash_password, new_opaque_token, hash_opaque_token, verify_password
from backend.app.core.sessions import (
    issue_session,
    public_user,
    revoke_all_sessions,
    revoke_session,
    rotate_refresh_token,
)
from backend.app.services.mailer import (
    generate_otp_email_html,
    generate_otp_email_text,
    generate_password_reset_email_html,
    generate_password_reset_email_text,
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

# Password reset policy
_RESET_TTL_MINUTES = 30
_RESET_COOLDOWN_SECONDS = 60
_reset_cooldown: Dict[str, float] = {}

# Login throttle (in-process, mirrors the OTP cooldown style)
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300
_login_attempts: Dict[str, list] = {}


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


# ---------------------------------------------------------------------------
# Credentials & sessions (our own auth)
# ---------------------------------------------------------------------------

class RegisterBody(BaseModel):
    email: str
    password: str
    full_name: str = ""


class LoginBody(BaseModel):
    email: str
    password: str


class RefreshBody(BaseModel):
    refresh_token: str


class ForgotPasswordBody(BaseModel):
    email: str


class ResetPasswordBody(BaseModel):
    token: str
    password: str


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _check_password_policy(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if len(password) > 128:
        raise HTTPException(status_code=400, detail="Password must be at most 128 characters.")


def _login_throttled(email: str) -> bool:
    now = time.time()
    window = [t for t in _login_attempts.get(email, []) if now - t < _LOGIN_WINDOW_SECONDS]
    _login_attempts[email] = window
    return len(window) >= _LOGIN_MAX_ATTEMPTS


def _record_login_attempt(email: str) -> None:
    _login_attempts.setdefault(email, []).append(time.time())


@router.post("/register")
async def register(body: RegisterBody) -> Dict[str, Any]:
    """Create an account with a password and return a session (logged in immediately)."""
    email = _normalize_email(body.email)
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    _check_password_policy(body.password)

    password_hash = hash_password(body.password)
    name = (body.full_name or "").strip() or email.split("@")[0]

    # An invited-but-not-registered profile (created by members.py) is adopted
    # by email so its id — and every membership FK pointing at it — stays intact.
    existing = execute_one("SELECT * FROM profiles WHERE email = %s", (email,))
    if existing:
        if existing.get("password_hash"):
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists. Try signing in.",
            )
        user = execute_one(
            """
            UPDATE profiles
            SET password_hash = %s,
                full_name = CASE WHEN %s = '' THEN full_name ELSE %s END,
                provider = CASE WHEN provider = 'google' THEN 'both' ELSE provider END,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (password_hash, name, name, existing["id"]),
        )
    else:
        user = execute_one(
            """
            INSERT INTO profiles (id, email, full_name, role, password_hash, provider)
            VALUES (gen_random_uuid(), %s, %s, 'Member', %s, 'email')
            RETURNING *
            """,
            (email, name, password_hash),
        )
    if not user:
        raise HTTPException(status_code=500, detail="Could not create the account.")

    log_audit(None, str(user["id"]), "auth.register", "user", str(user["id"]))
    return issue_session(user)


@router.post("/login")
async def login(body: LoginBody) -> Dict[str, Any]:
    """Verify email + password and return session tokens."""
    email = _normalize_email(body.email)
    if not email or _login_throttled(email):
        if email:
            _record_login_attempt(email)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user = execute_one("SELECT * FROM profiles WHERE email = %s", (email,))
    if not user or not verify_password(user.get("password_hash"), body.password):
        _record_login_attempt(email)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    _login_attempts.pop(email, None)
    log_audit(None, str(user["id"]), "auth.login", "user", str(user["id"]))
    return issue_session(user)


@router.post("/refresh")
async def refresh(body: RefreshBody) -> Dict[str, Any]:
    """Rotate a refresh token into a fresh token pair."""
    tokens = rotate_refresh_token(body.refresh_token)
    if not tokens:
        raise HTTPException(status_code=401, detail="Session expired — sign in again.")
    return tokens


@router.post("/logout")
async def logout(body: RefreshBody) -> Dict[str, Any]:
    """Revoke the given refresh token (works even with an expired access token)."""
    revoke_session(body.refresh_token)
    return {"ok": True}


@router.post("/forgot-password")
async def forgot_password(
    background_tasks: BackgroundTasks, body: ForgotPasswordBody
) -> Dict[str, Any]:
    """Queue a Brevo password-reset link. Always responds generically (no account enumeration)."""
    email = _normalize_email(body.email)
    now = time.time()
    if email and now - _reset_cooldown.get(email, 0) < _RESET_COOLDOWN_SECONDS:
        return {"ok": True}

    user = execute_one("SELECT * FROM profiles WHERE email = %s", (email,)) if email else None
    if user is None:
        return {"ok": True}

    _reset_cooldown[email] = now
    token = new_opaque_token()
    execute_query("DELETE FROM password_reset_tokens WHERE user_id = %s", (str(user["id"]),))
    execute_one(
        """
        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
        VALUES (%s, %s, now() + make_interval(mins => %s))
        RETURNING id
        """,
        (str(user["id"]), hash_opaque_token(token), _RESET_TTL_MINUTES),
    )

    name = (user.get("full_name") or email.split("@")[0]).strip()
    reset_url = f"{FRONTEND_URL}/reset-password?token={token}"
    background_tasks.add_task(
        send_email_async,
        email,
        "Reset your Cyphward password",
        generate_password_reset_email_html(name, reset_url, _RESET_TTL_MINUTES),
        generate_password_reset_email_text(name, reset_url, _RESET_TTL_MINUTES),
        recipient_name=name,
    )
    log_audit(None, str(user["id"]), "auth.reset_requested", "user", str(user["id"]))
    return {"ok": True}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordBody) -> Dict[str, Any]:
    """Consume a single-use reset link, set the new password, revoke all sessions."""
    _check_password_policy(body.password)
    token_hash = hash_opaque_token(body.token.strip())
    row = execute_one(
        """
        SELECT id, user_id, expires_at FROM password_reset_tokens
        WHERE token_hash = %s AND used_at IS NULL
        ORDER BY created_at DESC LIMIT 1
        """,
        (token_hash,),
    )
    if row is None:
        raise HTTPException(status_code=400, detail="This link is invalid or has expired — request a new one.")

    expires_at = row.get("expires_at")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            raise HTTPException(status_code=400, detail="This link is invalid or has expired — request a new one.")

    password_hash = hash_password(body.password)
    execute_one(
        "UPDATE profiles SET password_hash = %s, updated_at = now() WHERE id = %s RETURNING id",
        (password_hash, row["user_id"]),
    )
    execute_query("UPDATE password_reset_tokens SET used_at = now() WHERE id = %s", (row["id"],))
    execute_query("DELETE FROM password_reset_tokens WHERE user_id = %s", (row["user_id"],))
    revoke_all_sessions(row["user_id"])
    log_audit(None, str(row["user_id"]), "auth.password_reset", "user", str(row["user_id"]))
    return {"ok": True}


@router.get("/bootstrap")
async def bootstrap(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Everything the frontend needs after sign-in: profile, email verification
    state, memberships, and each org's domains (replaces the old direct
    Supabase PostgREST reads).
    """
    memberships = execute_query_memberships(user["id"])
    result_memberships = []
    for org in memberships:
        domains = (
            execute_query(
                "SELECT * FROM domains WHERE org_id = %s ORDER BY created_at ASC",
                (org["id"],),
            )
            or []
        )
        result_memberships.append({"org": org, "role": org.get("membership_role") or "member", "domains": domains})

    return {
        "user": public_user(user),
        "email_verified": bool(user.get("email_verified_at")),
        "memberships": result_memberships,
    }
