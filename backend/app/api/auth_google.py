"""
Google sign-in — OAuth 2.0 authorization-code flow owned by this backend.

GET  /api/v1/auth/google             -> redirect to Google's consent screen
GET  /api/v1/auth/google/callback    -> exchange code, load/create profile, issue session
POST /api/v1/auth/exchange           -> frontend consumes the single-use redirect code
GET  /api/v1/auth/google/client-id   -> public client id for One Tap (no secrets)
POST /api/v1/auth/google/one-tap     -> verify a One Tap ID token, issue session

No Supabase Auth involved. State is a short-lived signed JWT (CSRF protection).
"""
import secrets
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
import jwt as pyjwt
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from backend.app.core.auth import log_audit
from backend.app.core.config import (
    AUTH_JWT_SECRET,
    FRONTEND_URL,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
)
from backend.app.core.database import execute_one
from backend.app.core.security import new_opaque_token
from backend.app.core.sessions import consume_otc, issue_session

google_router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_STATE_TTL_SECONDS = 600


def _make_state() -> str:
    now = int(time.time())
    return pyjwt.encode(
        {
            "purpose": "google_oauth",
            "nonce": secrets.token_urlsafe(16),
            "iat": now,
            "exp": now + _STATE_TTL_SECONDS,
        },
        AUTH_JWT_SECRET,
        algorithm="HS256",
    )


def _check_state(state: str) -> bool:
    try:
        claims = pyjwt.decode(
            state, AUTH_JWT_SECRET, algorithms=["HS256"], options={"require": ["exp"]}
        )
        return claims.get("purpose") == "google_oauth"
    except pyjwt.PyJWTError:
        return False


def _login_error_url(reason: str) -> str:
    return f"{FRONTEND_URL}/login?error={reason}"


class ExchangeBody(BaseModel):
    otc: str


class OneTapBody(BaseModel):
    credential: str


_jwks_client: Optional[pyjwt.PyJWKClient] = None


def _jwks() -> pyjwt.PyJWKClient:
    """Cached Google JWKS client (signing keys rotate rarely)."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = pyjwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")
    return _jwks_client


def _verify_one_tap_credential(credential: str) -> Dict[str, Any]:
    """Verify a Google Identity Services ID token (One Tap) and return its claims."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured yet.")
    # Parse the header before touching the network so a malformed token
    # (or an offline test run) never triggers a JWKS fetch.
    try:
        header = pyjwt.get_unverified_header(credential)
    except Exception:
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified.")
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified.")
    try:
        key = _jwks().get_signing_key_from_jwt(credential).key
        claims = pyjwt.decode(
            credential,
            key,
            algorithms=["RS256"],
            audience=GOOGLE_CLIENT_ID,
            options={"require": ["exp", "iat", "email"]},
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified.")
    if not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="That Google account's email address is not verified.")
    return claims


def _upsert_google_profile(email: str, name: str) -> Optional[Dict[str, Any]]:
    """Load-or-create the local profile for a verified Google account."""
    existing = execute_one("SELECT * FROM profiles WHERE email = %s", (email,))
    if existing:
        return execute_one(
            """
            UPDATE profiles
            SET full_name = CASE WHEN full_name IS NULL OR full_name = '' THEN %s ELSE full_name END,
                email_verified_at = COALESCE(email_verified_at, now()),
                provider = CASE WHEN provider = 'email' THEN 'both' ELSE provider END,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (name, existing["id"]),
        )
    return execute_one(
        """
        INSERT INTO profiles (id, email, full_name, role, provider, email_verified_at)
        VALUES (gen_random_uuid(), %s, %s, 'Member', 'google', now())
        RETURNING *
        """,
        (email, name),
    )


@google_router.get("/google")
async def google_start() -> RedirectResponse:
    """Send the browser to Google's consent screen."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not AUTH_JWT_SECRET:
        # Browsers only hit this route — bounce back with a friendly error
        # instead of a raw JSON 400.
        return RedirectResponse(_login_error_url("google_not_configured"))
    params = urlencode(
        {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "select_account",
            "state": _make_state(),
        }
    )
    return RedirectResponse(f"{_GOOGLE_AUTH_URL}?{params}")


@google_router.get("/google/callback")
async def google_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    """Finish the Google flow and hand the frontend a single-use exchange code."""
    if error or not code or not state or not _check_state(state):
        return RedirectResponse(_login_error_url("oauth_failed"))

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")
            if not access_token:
                return RedirectResponse(_login_error_url("oauth_failed"))

            userinfo_resp = await client.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            info: Dict[str, Any] = userinfo_resp.json()
    except Exception:
        return RedirectResponse(_login_error_url("oauth_failed"))

    email = (info.get("email") or "").strip().lower()
    if not email or not info.get("email_verified"):
        return RedirectResponse(_login_error_url("email_unverified"))
    name = (info.get("name") or "").strip() or email.split("@")[0]

    user = _upsert_google_profile(email, name)
    if not user:
        return RedirectResponse(_login_error_url("oauth_failed"))

    # Single-use exchange code; the frontend trades it for real session tokens.
    otc = new_opaque_token()
    issue_session(user, otc=otc)
    log_audit(None, str(user["id"]), "auth.google_signin", "user", str(user["id"]))
    return RedirectResponse(f"{FRONTEND_URL}/auth/callback?otc={otc}")


@google_router.get("/google/client-id")
async def google_client_id() -> Dict[str, Any]:
    """Public Google OAuth client id for Identity Services (One Tap)."""
    return {"client_id": GOOGLE_CLIENT_ID or None}


@google_router.post("/google/one-tap")
async def google_one_tap(body: OneTapBody) -> Dict[str, Any]:
    """Verify a One Tap ID token and start a session in one round trip."""
    claims = _verify_one_tap_credential(body.credential.strip())
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified.")
    name = (claims.get("name") or "").strip() or email.split("@")[0]
    user = _upsert_google_profile(email, name)
    if not user:
        raise HTTPException(status_code=500, detail="Could not create your account. Please try again.")
    tokens = issue_session(user)
    log_audit(None, str(user["id"]), "auth.google_onetap", "user", str(user["id"]))
    return tokens


@google_router.post("/exchange")
async def google_exchange(body: ExchangeBody) -> Dict[str, Any]:
    """Consume the single-use code from the OAuth redirect and return session tokens."""
    tokens = consume_otc(body.otc.strip())
    if not tokens:
        raise HTTPException(status_code=401, detail="This sign-in link is invalid or has expired.")
    return tokens
