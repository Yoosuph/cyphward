"""Identity of the sample-data demo organisation ("Fintech Org (SAMPLE DATA)").

backend/scripts/seed_fintech_demo.py writes it and removes it. Production metrics leave it out by these ids
(owner console overview). Nothing else in the app treats it specially: it is an ordinary organisation whose
domain is pending, so the app never scans it and never grades it at organisation level.
"""

import os
from uuid import UUID

DEMO_ORG_ID = "f1ac0000-0000-4000-8000-000000000001"
DEMO_USER_ID = "f1ac0000-0000-4000-8000-000000000002"

PUBLIC_DEMO_KEYS = ("DEMO_LOGIN_USER_ID", "DEMO_LOGIN_ORG_ID", "DEMO_LOGIN_EMAIL")


def public_demo_configured() -> bool:
    return any(os.getenv(key, "").strip() for key in PUBLIC_DEMO_KEYS)


def public_demo_target():
    """All identity pins are required. Partial/invalid configuration never falls back."""
    user, org, email = (os.getenv(key, "").strip() for key in PUBLIC_DEMO_KEYS)
    if not user or not org or not email or "@" not in email:
        return None
    try:
        return {"user_id": str(UUID(user)), "org_id": str(UUID(org)), "email": email.lower()}
    except ValueError:
        return None


def public_demo_session_valid(profile, org_id) -> bool:
    target = public_demo_target()
    return bool(os.getenv("DEMO_LOGIN_ENABLED", "").strip().lower() == "true" and target
                and str(profile.get("id")) == target["user_id"]
                and str(org_id) == target["org_id"]
                and str(profile.get("email", "")).lower() == target["email"]
                and bool(profile.get("email_verified_at"))
                and not profile.get("mfa_enrolled_at") and not profile.get("totp_enrolled_at"))
