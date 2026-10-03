import os
from pathlib import Path
from typing import Dict, Tuple
from dotenv import load_dotenv

# Load .env from backend directory or project root
# layout: backend/app/core/config.py -> parents[2]=backend, parents[3]=repo root
backend_env = Path(__file__).resolve().parents[2] / ".env"
root_env = Path(__file__).resolve().parents[3] / ".env"

if backend_env.exists():
    load_dotenv(dotenv_path=backend_env)
elif root_env.exists():
    load_dotenv(dotenv_path=root_env)
else:
    load_dotenv()

# Secrets are environment-only — never hardcode credentials in source.
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Cyphward Auth — our own JWT sessions (Supabase Auth is not used).
AUTH_JWT_SECRET = os.getenv("AUTH_JWT_SECRET", "")
# Access tokens are short-lived: get_current_user checks session revocation on
# every request, and the frontend refreshes before expiry (30s slack), so a
# short window only limits stolen-token use when no logout happened (review P1).
ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "1800"))
REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", "2592000"))
# Where password-reset / OAuth links send the browser back to.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

# Google OAuth (sign-in with Google) — optional until configured.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback"
)

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "https://cyphward.com",
    "https://www.cyphward.com",
    "https://cyphward.vercel.app",
    "https://app.cyphward.com",
    "https://auth.cyphward.com",
]

# AI Intelligence Layer Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Inngest (cloud) — event key sends events, signing key verifies callbacks.
INNGEST_EVENT_KEY = os.getenv("INNGEST_EVENT_KEY", "")
INNGEST_SIGNING_KEY = os.getenv("INNGEST_SIGNING_KEY", "")

# In-process daily scan scheduler (06:00 UTC sweep). Disable only if an
# external trigger (e.g. the Inngest cron) is actually registered instead.
SCHEDULER_ENABLED = os.getenv("CYPHWARD_SCHEDULER_ENABLED", "true").lower() in ("true", "1", "yes")

# Scanner worker integration (spec §14/§29)
# SCANNER_MODE: "local"  -> recon runs in-process (dev fallback, default)
#               "remote" -> recon is claimed by the Azure scanner worker
SCANNER_MODE = os.getenv("SCANNER_MODE", "local").strip().lower()
SCANNER_API_KEY = os.getenv("SCANNER_API_KEY", "")
# Shared secret is enforced only when SCANNER_MODE=remote; never run remote unarmed.
SCANNER_LEASE_SECONDS = int(os.getenv("SCANNER_LEASE_SECONDS", "3600"))
SCANNER_MAX_HOSTS = int(os.getenv("SCANNER_MAX_HOSTS", "500"))
SCANNER_MAX_PORTS = int(os.getenv("SCANNER_MAX_PORTS", "100"))
SCANNER_STAGE_TIMEOUT_SECONDS = int(os.getenv("SCANNER_STAGE_TIMEOUT_SECONDS", "300"))
SCANNER_NUCLEI_CONCURRENCY = int(os.getenv("SCANNER_NUCLEI_CONCURRENCY", "1"))
SCANNER_NUCLEI_MAX_HOSTS = int(os.getenv("SCANNER_NUCLEI_MAX_HOSTS", "50"))

# Brevo (Sendinblue) Transactional Mailing Service
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_SMTP_SERVER = os.getenv("BREVO_SMTP_SERVER", "smtp-relay.brevo.com")
BREVO_SMTP_PORT = int(os.getenv("BREVO_SMTP_PORT", "587"))
BREVO_SMTP_LOGIN = os.getenv("BREVO_SMTP_LOGIN", "")
BREVO_SMTP_PASSWORD = os.getenv("BREVO_SMTP_PASSWORD", "") or BREVO_API_KEY

# Central sender identities for outgoing mail — every address below is a
# verified Brevo sender (DKIM + DMARC aligned). Call sites pick an email
# kind; never hardcode a "From" address outside this map.
#   system   → authentication & account email (verification, reset, welcome)
#   alerts   → automated security events (critical/reopened findings)
#   reports  → scan & executive report delivery
#   support  → human support replies (reply-enabled)
#   security → vulnerability disclosure & security contact
#   general  → business and general inquiries
EMAIL_SENDERS: Dict[str, Tuple[str, str]] = {
    "system": ("Cyphward", "no-reply@cyphward.com"),
    "alerts": ("Cyphward Alerts", "alerts@cyphward.com"),
    "reports": ("Cyphward Reports", "reports@cyphward.com"),
    "support": ("Cyphward Support", "support@cyphward.com"),
    "security": ("Cyphward Security", "security@cyphward.com"),
    "general": ("Cyphward", "info@cyphward.com"),
}
DEFAULT_EMAIL_SENDER_KIND = "system"
