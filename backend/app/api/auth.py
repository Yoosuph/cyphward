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

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from backend.app.core.auth import execute_query_memberships, get_current_user, log_audit
from backend.app.core.config import AUTH_JWT_SECRET, FRONTEND_URL, REFRESH_TOKEN_TTL_SECONDS
from backend.app.core.database import execute_one, execute_query
from backend.app.core.rate_limit import check_rate_limit, reset_bucket
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
    generate_password_changed_alert_html,
    generate_password_changed_alert_text,
    generate_password_reset_email_html,
    generate_password_reset_email_text,
    generate_welcome_email_html,
    generate_welcome_email_text,
    send_email_async,
    send_email_sync,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

# Shared fixed-window budgets (Postgres-backed, review P2 — throttling).
# Login throttle: 5 attempts per 5 minutes per email (fail-closed 401).
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300
# Password-reset request: 1 per minute per email (generic ok on exceed).
_RESET_MAX_SENDS = 1
_RESET_WINDOW_SECONDS = 60
# Welcome mail: 1 per hour per account.
_WELCOME_MAX_SENDS = 1
_WELCOME_WINDOW_SECONDS = 3600
# Admin login step-up (MFA): code resend 1/min, 3 per 10 min; 5 verify tries.
_MFA_SEND_WINDOW_SECONDS = 60
_MFA_SEND_MAX = 3
_MFA_SEND_BUDGET_SECONDS = 600
_MFA_VERIFY_MAX_ATTEMPTS = 5
_MFA_TOKEN_MINUTES = 10
# Welcome is a signup gift, not a login ritual: only accounts younger than this
# may ever receive one (existing accounts are rejected outright).
_WELCOME_MAX_ACCOUNT_AGE_SECONDS = 86400

# Email OTP policy
_OTP_TTL_SECONDS = 600
_OTP_RESEND_SECONDS = 60
_OTP_MAX_ATTEMPTS = 5

# Password reset policy
_RESET_TTL_MINUTES = 30


def _hash_code(email: str, code: str) -> str:
    """One-way hash binding the code to the account (never store plaintext)."""
    return hashlib.sha256(f"{email}:{code}".encode("utf-8")).hexdigest()


def _account_is_new(user: Dict[str, Any]) -> bool:
    """True only for accounts created within the welcome window.

    Fails safe: an unreadable/missing created_at is treated as "existing" so
    the endpoint can never spam an account we cannot prove is brand new.
    """
    created = user.get("created_at")
    if isinstance(created, str):
        try:
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            return False
    if not isinstance(created, datetime):
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created).total_seconds()
    return age <= _WELCOME_MAX_ACCOUNT_AGE_SECONDS


@router.post("/welcome")
async def send_welcome_email(
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Account has no email address on file.")

    now = time.time()
    try:
        check_rate_limit(f"welcome:{user['id']}", _WELCOME_MAX_SENDS, _WELCOME_WINDOW_SECONDS)
    except HTTPException:
        return {"sent": False, "reason": "recently_sent"}

    # Persistent dedupe: one welcome per account, ever (survives restarts).
    prior = execute_one(
        "SELECT id FROM audit_log WHERE user_id = %s AND action = 'welcome.sent' LIMIT 1",
        (str(user["id"]),),
    )
    if prior:
        return {"sent": False, "reason": "already_sent"}

    # Welcome belongs to signup, not sign-in: existing accounts never get one.
    if not _account_is_new(user):
        return {"sent": False, "reason": "existing_account"}

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
    log_audit(None, str(user["id"]), "welcome.sent", "user", str(user["id"]))
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
        "SELECT created_at FROM email_otps WHERE user_id = %s AND purpose = 'verify' "
        "ORDER BY created_at DESC LIMIT 1",
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
    execute_query("DELETE FROM email_otps WHERE user_id = %s AND purpose = 'verify'", (user["id"],))
    execute_query(
        """
        INSERT INTO email_otps (user_id, code_hash, expires_at, purpose)
        VALUES (%s, %s, now() + make_interval(secs => %s), 'verify')
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
        FROM email_otps WHERE user_id = %s AND purpose = 'verify'
        ORDER BY created_at DESC LIMIT 1
        """,
        (user["id"],),
    )
    if row is None:
        raise HTTPException(status_code=400, detail="No active code — request a new one.")

    remaining = _OTP_MAX_ATTEMPTS - int(row.get("attempts") or 0)
    if remaining <= 0:
        execute_query("DELETE FROM email_otps WHERE user_id = %s AND purpose = 'verify'", (user["id"],))
        raise HTTPException(status_code=429, detail="Too many attempts — request a new code.")

    expires_at = row.get("expires_at")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            execute_query("DELETE FROM email_otps WHERE user_id = %s AND purpose = 'verify'", (user["id"],))
            raise HTTPException(status_code=400, detail="That code has expired — request a new one.")

    # Conditional attempt consume: the budget check and the increment are one
    # statement, so concurrent verifies can't both slip past the limit.
    bumped = execute_one(
        "UPDATE email_otps SET attempts = attempts + 1 WHERE id = %s AND attempts < %s RETURNING attempts",
        (row["id"], _OTP_MAX_ATTEMPTS),
    )
    if not bumped:
        execute_query("DELETE FROM email_otps WHERE user_id = %s AND purpose = 'verify'", (user["id"],))
        raise HTTPException(status_code=429, detail="Too many attempts — request a new code.")
    attempts_now = int(bumped.get("attempts") or _OTP_MAX_ATTEMPTS)
    left = max(_OTP_MAX_ATTEMPTS - attempts_now, 0)

    if not hmac.compare_digest(str(row.get("code_hash") or ""), _hash_code(email, code)):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid code — {left} attempt(s) left.",
        )

    execute_query(
        "UPDATE profiles SET email_verified_at = now(), updated_at = now() WHERE id = %s",
        (user["id"],),
    )
    execute_query("DELETE FROM email_otps WHERE user_id = %s AND purpose = 'verify'", (user["id"],))
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


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if len(local) <= 1:
        masked = "*"
    else:
        masked = local[0] + "***"
    return f"{masked}@{domain}"


def _issue_mfa_token(user_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": str(user_id), "purpose": "mfa",
         "iat": now, "exp": now + _MFA_TOKEN_MINUTES * 60},
        AUTH_JWT_SECRET,
        algorithm="HS256",
    )


def _verify_mfa_token(token: str) -> str:
    if not AUTH_JWT_SECRET:
        raise HTTPException(status_code=401, detail="Authentication is not configured on the server.")
    try:
        claims = jwt.decode(token, AUTH_JWT_SECRET, algorithms=["HS256"],
                            options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Sign-in step expired — start again.")
    if claims.get("purpose") != "mfa" or not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Sign-in step expired — start again.")
    return str(claims["sub"])


def _user_is_admin(user_id: str) -> bool:
    row = execute_one(
        "SELECT 1 FROM organization_members WHERE user_id = %s AND role IN ('owner', 'admin') LIMIT 1",
        (user_id,),
    )
    return row is not None


def _send_mfa_code(user: Dict[str, Any]) -> None:
    """Create a fresh login step-up code and email it (purpose='mfa')."""
    email = (user.get("email") or "").strip().lower()
    code = f"{secrets.randbelow(1_000_000):06d}"
    execute_query("DELETE FROM email_otps WHERE user_id = %s AND purpose = 'mfa'", (user["id"],))
    execute_query(
        """
        INSERT INTO email_otps (user_id, code_hash, expires_at, purpose)
        VALUES (%s, %s, now() + make_interval(secs => %s), 'mfa')
        """,
        (user["id"], _hash_code(email, code), _OTP_TTL_SECONDS),
    )
    name = (user.get("full_name") or email.split("@")[0]).strip()
    send_email_sync(
        email,
        "Your Cyphward sign-in code",
        generate_otp_email_html(name, code),
        generate_otp_email_text(name, code),
        recipient_name=name,
    )


@router.post("/register")
async def register(body: RegisterBody) -> Dict[str, Any]:
    """Create an account with a password and return a session (logged in immediately)."""
    email = _normalize_email(body.email)
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    _check_password_policy(body.password)

    password_hash = hash_password(body.password)
    name = (body.full_name or "").strip() or email.split("@")[0]

    # Never adopt an existing profile from public registration. The old
    # adopt-by-email path let a registrant take over any passwordless
    # (Google or invited) profile — and every organization membership
    # attached to it — without proving control of that account (review P0-1).
    # Ownership stays where it can be proven: signing in with the original
    # provider, or setting a password through the emailed reset link.
    existing = execute_one("SELECT * FROM profiles WHERE email = %s", (email,))
    if existing:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Sign in instead, or reset your password.",
        )

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
    """Verify email + password. Owners/admins must also complete an email
    step-up code (MFA) before a session is issued; everyone else signs in
    directly. Throttling is fail-closed 401 (no existence oracle)."""
    email = _normalize_email(body.email)
    if not email:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    try:
        check_rate_limit(f"login:{email}", _LOGIN_MAX_ATTEMPTS, _LOGIN_WINDOW_SECONDS)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user = execute_one("SELECT * FROM profiles WHERE email = %s", (email,))
    if not user or not verify_password(user.get("password_hash"), body.password):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    reset_bucket(f"login:{email}")
    log_audit(None, str(user["id"]), "auth.login", "user", str(user["id"]))

    if _user_is_admin(str(user["id"])) or user.get("mfa_enrolled_at") is not None:
        check_rate_limit(f"mfa:{user['id']}", _MFA_SEND_MAX, _MFA_SEND_BUDGET_SECONDS)
        _send_mfa_code(user)
        return {
            "mfa_required": True,
            "mfa_token": _issue_mfa_token(str(user["id"])),
            "email_hint": _mask_email(email),
        }
    return issue_session(user)


class MfaBody(BaseModel):
    mfa_token: str
    code: str = ""


@router.post("/mfa/send")
async def resend_mfa_code(body: MfaBody) -> Dict[str, Any]:
    """Resend the admin login step-up code (1/min; the token proves a fresh
    password login, so this cannot be used to spam arbitrary addresses)."""
    user_id = _verify_mfa_token(body.mfa_token)
    user = execute_one("SELECT * FROM profiles WHERE id = %s", (user_id,))
    if not user:
        raise HTTPException(status_code=401, detail="Sign-in step expired — start again.")
    latest = execute_one(
        "SELECT created_at FROM email_otps WHERE user_id = %s AND purpose = 'mfa' "
        "ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    if latest is not None and latest.get("created_at") is not None:
        created = latest["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - created).total_seconds() < _MFA_SEND_WINDOW_SECONDS:
            raise HTTPException(status_code=429, detail="A code was just sent — check your inbox.")
    try:
        check_rate_limit(f"mfa-send:{user_id}", 1, _MFA_SEND_WINDOW_SECONDS)
    except HTTPException:
        raise HTTPException(status_code=429, detail="A code was just sent — check your inbox.")
    _send_mfa_code(user)
    return {"sent": True}


@router.post("/mfa/verify")
async def verify_mfa_code(body: MfaBody) -> Dict[str, Any]:
    """Consume the admin login step-up code and issue the session."""
    code = (body.code or "").strip()
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="Enter the 6-digit code.")
    user_id = _verify_mfa_token(body.mfa_token)
    user = execute_one("SELECT * FROM profiles WHERE id = %s", (user_id,))
    if not user:
        raise HTTPException(status_code=401, detail="Sign-in step expired — start again.")
    _consume_mfa_code(user_id, (user.get("email") or "").strip().lower(), code)
    reset_bucket(f"mfa-verify:{user_id}")
    log_audit(None, str(user["id"]), "auth.mfa_verified", "user", str(user["id"]))
    return issue_session(user)


def _consume_mfa_code(user_id: str, email: str, code: str) -> None:
    """Validate and single-use consume a purpose='mfa' code (shared by the
    login step-up and the disable-confirm flows — neither trusts the other
    purpose's rows). Raises 400/401/429; returns None on success."""
    try:
        check_rate_limit(f"mfa-verify:{user_id}", _MFA_VERIFY_MAX_ATTEMPTS, _LOGIN_WINDOW_SECONDS)
    except HTTPException:
        raise HTTPException(status_code=429, detail="Too many attempts — start sign-in again.")
    row = execute_one(
        """
        SELECT id, code_hash, attempts, expires_at FROM email_otps
        WHERE user_id = %s AND purpose = 'mfa'
        ORDER BY created_at DESC LIMIT 1
        """,
        (user_id,),
    )
    if row is None:
        raise HTTPException(status_code=400, detail="No active code — request a new one.")
    if int(row.get("attempts") or 0) >= _MFA_VERIFY_MAX_ATTEMPTS:
        execute_query("DELETE FROM email_otps WHERE user_id = %s AND purpose = 'mfa'", (user_id,))
        raise HTTPException(status_code=429, detail="Too many attempts — start sign-in again.")
    expires_at = row.get("expires_at")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            execute_query("DELETE FROM email_otps WHERE user_id = %s AND purpose = 'mfa'", (user_id,))
            raise HTTPException(status_code=400, detail="That code has expired — request a new one.")
    bumped = execute_one(
        "UPDATE email_otps SET attempts = attempts + 1 WHERE id = %s AND attempts < %s RETURNING attempts",
        (row["id"], _MFA_VERIFY_MAX_ATTEMPTS),
    )
    if not bumped:
        execute_query("DELETE FROM email_otps WHERE user_id = %s AND purpose = 'mfa'", (user_id,))
        raise HTTPException(status_code=429, detail="Too many attempts — start sign-in again.")
    if not hmac.compare_digest(str(row.get("code_hash") or ""), _hash_code(email, code)):
        raise HTTPException(status_code=401, detail="Invalid code.")
    execute_query("DELETE FROM email_otps WHERE user_id = %s AND purpose = 'mfa'", (user_id,))


@router.get("/mfa/status")
async def mfa_status(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Drive the Settings MFA panel: enrolled, admin-mandated, email verified."""
    return {
        "enrolled": user.get("mfa_enrolled_at") is not None,
        "admin_required": _user_is_admin(str(user["id"])),
        "email_verified": user.get("email_verified_at") is not None,
    }


@router.post("/mfa/enroll")
async def enroll_mfa(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Opt into the login step-up code. Requires a verified email — the
    code has to reach the account, or the next login locks the user out."""
    if not user.get("email_verified_at"):
        raise HTTPException(
            status_code=403,
            detail="Verify your email address first — the sign-in code has to reach you.",
        )
    execute_one(
        "UPDATE profiles SET mfa_enrolled_at = now(), updated_at = now() WHERE id = %s RETURNING id",
        (user["id"],),
    )
    log_audit(None, str(user["id"]), "auth.mfa_enrolled", "user", str(user["id"]))
    return {"enrolled": True}


@router.post("/mfa/disable/request")
async def request_mfa_disable(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Mail a confirmation code for turning the step-up off. Disabling
    needs inbox access — a stolen session alone cannot switch MFA off."""
    try:
        check_rate_limit(f"mfa-disable:{user['id']}", 1, _MFA_SEND_WINDOW_SECONDS)
    except HTTPException:
        raise HTTPException(status_code=429, detail="A code was just sent — check your inbox.")
    _send_mfa_code(user)
    return {"sent": True}


class MfaDisableBody(BaseModel):
    code: str = ""


class DeleteAccountBody(BaseModel):
    email: str = ""
    password: str = ""


@router.post("/account/delete")
async def delete_own_account(
    body: DeleteAccountBody,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Self-service account deletion (data-rights follow-up).

    Typed-email confirmation plus the password when one is set (Google-only
    accounts rely on the session + typed email). Sole owners are blocked
    until ownership is transferred or the workspace is closed — otherwise
    the org would be orphaned. Profile DELETE cascades sessions, tokens,
    OTPs, memberships and staff grants; references (invites, reports,
    remediation) null out; a NULL-user tombstone keeps the deletion itself
    on record.
    """
    email = (body.email or "").strip().lower()
    if email != (user.get("email") or "").strip().lower():
        raise HTTPException(status_code=400, detail="Type your account email to confirm deletion.")
    if user.get("password_hash"):
        if not body.password or not verify_password(user.get("password_hash"), body.password):
            raise HTTPException(status_code=401, detail="Password is incorrect.")
    sole_owned = execute_query(
        """
        SELECT o.id, o.name, o.slug FROM organization_members m
        JOIN organizations o ON o.id = m.org_id
        WHERE m.user_id = %s AND m.role = 'owner'
          AND (SELECT count(*) FROM organization_members
               WHERE org_id = m.org_id AND role = 'owner') = 1
        """,
        (user["id"],),
    )
    if sole_owned:
        names = ", ".join(sorted({(r.get("name") or r.get("slug") or "?") for r in sole_owned}))
        raise HTTPException(
            status_code=409,
            detail=f"Transfer ownership or close these workspaces first: {names}.",
        )
    log_audit(None, None, "account.deleted", "user", str(user["id"]),
              {"email": email})
    deleted = execute_one("DELETE FROM profiles WHERE id = %s RETURNING id", (user["id"],))
    if not deleted:
        raise HTTPException(status_code=404, detail="Account not found.")
    return {"deleted": True}


@router.post("/mfa/disable/confirm")
async def confirm_mfa_disable(
    body: MfaDisableBody,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Consume the disable code and switch the step-up off (no session issued)."""
    code = (body.code or "").strip()
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="Enter the 6-digit code.")
    _consume_mfa_code(str(user["id"]), (user.get("email") or "").strip().lower(), code)
    execute_one(
        "UPDATE profiles SET mfa_enrolled_at = NULL, updated_at = now() WHERE id = %s RETURNING id",
        (user["id"],),
    )
    log_audit(None, str(user["id"]), "auth.mfa_disabled", "user", str(user["id"]))
    return {"disabled": True}


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
    if email:
        try:
            check_rate_limit(f"reset:{email}", _RESET_MAX_SENDS, _RESET_WINDOW_SECONDS)
        except HTTPException:
            return {"ok": True}

    user = execute_one("SELECT * FROM profiles WHERE email = %s", (email,)) if email else None
    if user is None:
        return {"ok": True}

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
async def reset_password(background_tasks: BackgroundTasks, body: ResetPasswordBody) -> Dict[str, Any]:
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

    # Claim the token first with a conditional write — a replayed link loses
    # the compare-and-set and is rejected even under concurrent use.
    consumed = execute_one(
        """
        UPDATE password_reset_tokens SET used_at = now()
        WHERE id = %s AND used_at IS NULL AND expires_at > now()
        RETURNING id
        """,
        (row["id"],),
    )
    if not consumed:
        raise HTTPException(status_code=400, detail="This link is invalid or has expired — request a new one.")

    password_hash = hash_password(body.password)
    execute_one(
        "UPDATE profiles SET password_hash = %s, updated_at = now() WHERE id = %s RETURNING id",
        (password_hash, row["user_id"]),
    )
    execute_query("DELETE FROM password_reset_tokens WHERE user_id = %s", (row["user_id"],))
    revoke_all_sessions(row["user_id"])
    log_audit(None, str(row["user_id"]), "auth.password_reset", "user", str(row["user_id"]))
    # Credential-recovery alert (review P2): the account owner is told the
    # password changed, even if the reset was legitimate.
    changed = execute_one(
        "SELECT * FROM profiles WHERE id = %s", (row["user_id"],)
    )
    if changed and changed.get("email"):
        name = (changed.get("full_name") or changed["email"].split("@")[0]).strip()
        background_tasks.add_task(
            send_email_async,
            changed["email"],
            "Your Cyphward password was changed",
            generate_password_changed_alert_html(name),
            generate_password_changed_alert_text(name),
            recipient_name=name,
        )
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
