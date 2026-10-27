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

# "production" only on deployed services. Anything else, with a non-loopback
# DATABASE_URL, refuses scheduler/recovery work (core/runtime_guard.py).
CYPHWARD_ENV = os.getenv("CYPHWARD_ENV", "development").strip().lower()

# Cyphward Auth — our own JWT sessions (Supabase Auth is not used).
AUTH_JWT_SECRET = os.getenv("AUTH_JWT_SECRET", "")
# Access tokens are short-lived: get_current_user checks session revocation on
# every request, and the frontend refreshes before expiry (30s slack), so a
# short window only limits stolen-token use when no logout happened (review P1).
ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "1800"))
REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", "2592000"))
# Database pool capacity — set from the Postgres connection budget and the
# expected number of app replicas. A saturated pool makes callers WAIT (then
# 503); it never opens connections outside the pool (review P1 — processing
# and database capacity).
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "20"))
DB_POOL_TIMEOUT_SECONDS = float(os.getenv("DB_POOL_TIMEOUT_SECONDS", "5.0"))
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

# Owner console (admin.cyphward.com). Mutations must come from one of these
# exact origins; dev origins are only accepted outside production.
OWNER_CONSOLE_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.getenv("OWNER_CONSOLE_ORIGINS", "https://admin.cyphward.com").split(",")
    if o.strip()
]
if CYPHWARD_ENV != "production":
    OWNER_CONSOLE_ORIGINS += ["http://127.0.0.1:5181", "http://localhost:5181",
                              "http://127.0.0.1:5173", "http://localhost:5173", "http://testserver"]

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
EXECUTION_RECOVERY_ENABLED = os.getenv("CYPHWARD_EXECUTION_RECOVERY_ENABLED", "true").lower() in ("true", "1", "yes")

# Scanner worker integration (spec §14/§29)
# SCANNER_MODE: "local"  -> recon runs in-process (dev fallback, default)
#               "remote" -> recon is claimed by the Azure scanner worker
SCANNER_MODE = os.getenv("SCANNER_MODE", "local").strip().lower()
SCANNER_CLAIMS_ENABLED = os.getenv("SCANNER_CLAIMS_ENABLED", "true").lower() in ("true", "1", "yes")
SCANNER_API_KEY = os.getenv("SCANNER_API_KEY", "")
# Shared secret is enforced only when SCANNER_MODE=remote; never run remote unarmed.
SCANNER_LEASE_SECONDS = int(os.getenv("SCANNER_LEASE_SECONDS", "3600"))
SCANNER_MAX_HOSTS = int(os.getenv("SCANNER_MAX_HOSTS", "500"))
SCANNER_DNS_MAX_HOSTS = int(os.getenv("SCANNER_DNS_MAX_HOSTS", "40"))
SCANNER_MAX_PORTS = int(os.getenv("SCANNER_MAX_PORTS", "100"))
SCANNER_STAGE_TIMEOUT_SECONDS = int(os.getenv("SCANNER_STAGE_TIMEOUT_SECONDS", "300"))
SCANNER_RECON_TIMEOUT_SECONDS = int(os.getenv("SCANNER_RECON_TIMEOUT_SECONDS", "900"))
SCANNER_TLS_MAX_HOSTS = int(os.getenv("SCANNER_TLS_MAX_HOSTS", "25"))
CORE_AI_TIMEOUT_SECONDS = max(1, int(os.getenv("CORE_AI_TIMEOUT_SECONDS", "120")))
SCANNER_NUCLEI_CONCURRENCY = int(os.getenv("SCANNER_NUCLEI_CONCURRENCY", "1"))
SCANNER_NUCLEI_MAX_HOSTS = int(os.getenv("SCANNER_NUCLEI_MAX_HOSTS", "50"))

# Cookie-consent browser observation (packet C2b). OFF by default: with the flag off the browser
# endpoints answer 503/204, no job is queued and the Compliance page reads exactly as before.
# The separate browser worker has its own key; the scanner key cannot authenticate to it.
BROWSER_CONSENT_ENABLED = os.getenv("BROWSER_CONSENT_ENABLED", "false").lower() in ("true", "1", "yes")
BROWSER_WORKER_API_KEY = os.getenv("BROWSER_WORKER_API_KEY", "")
if BROWSER_WORKER_API_KEY and BROWSER_WORKER_API_KEY == SCANNER_API_KEY:
    # One key for both workers would let either claim the other's work. Refuse to start.
    raise RuntimeError("BROWSER_WORKER_API_KEY must differ from SCANNER_API_KEY.")
# Optional allowlist of worker ids (X-Scanner-Id). The id is chosen by the caller, so the limits below never
# depend on it: they are global.
BROWSER_WORKER_IDS = [w.strip() for w in os.getenv("BROWSER_WORKER_IDS", "").split(",") if w.strip()]
BROWSER_MAX_RUNNING_JOBS = max(1, int(os.getenv("BROWSER_MAX_RUNNING_JOBS", "1")))
BROWSER_CLAIM_MIN_INTERVAL_SECONDS = float(os.getenv("BROWSER_CLAIM_MIN_INTERVAL_SECONDS", "2"))
BROWSER_LEASE_SECONDS = int(os.getenv("BROWSER_LEASE_SECONDS", "180"))
BROWSER_MAX_ATTEMPTS = int(os.getenv("BROWSER_MAX_ATTEMPTS", "3"))
BROWSER_JOB_COOLDOWN_HOURS = int(os.getenv("BROWSER_JOB_COOLDOWN_HOURS", "20"))

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
# Inbox for the public contact form. The address shown on the site is
# info@cyphward.com; delivery goes here so a person reads it.
CONTACT_INBOX = os.getenv("CONTACT_INBOX", "cyphward@gmail.com")

# Newsletter (docs/newsletter/README.md). Off by default: with the flag off every
# /api/v1/newsletter endpoint returns 404. Turning it on without the list id, the
# postal line, the token secret or a Brevo API key also leaves it off (fails closed).
# The newsletter sender is passed to the mailer explicitly; it is not an
# EMAIL_SENDERS kind, so transactional mail can never pick it by accident.
NEWSLETTER_ENABLED = os.getenv("NEWSLETTER_ENABLED", "false").strip().lower() in ("true", "1", "yes")
NEWSLETTER_SENDER: Tuple[str, str] = ("Cyphward News", "news@cyphward.com")
# Only GrokBot holds this key; it can create drafts and nothing else.
NEWSLETTER_DRAFT_API_KEY = os.getenv("NEWSLETTER_DRAFT_API_KEY", "")
# Keys the derived unsubscribe tokens (so issues can carry a per-subscriber link). At least 32 characters.
NEWSLETTER_TOKEN_SECRET = os.getenv("NEWSLETTER_TOKEN_SECRET", "")
# The Brevo contact list that holds confirmed subscribers only. Never list 2 (the mailer's transactional fallback).
NEWSLETTER_BREVO_LIST_ID = os.getenv("NEWSLETTER_BREVO_LIST_ID", "").strip()
# The Brevo contact attribute (type text) that carries each subscriber's unsubscribe token into campaigns.
NEWSLETTER_BREVO_UNSUB_ATTRIBUTE = os.getenv("NEWSLETTER_BREVO_UNSUB_ATTRIBUTE", "CW_UNSUB_TOKEN").strip()
# The sender's postal/contact line printed at the foot of every newsletter email.
NEWSLETTER_POSTAL_LINE = os.getenv("NEWSLETTER_POSTAL_LINE", "").strip()
# Public site that serves /newsletter/* pages and proxies /api/* to this API.
NEWSLETTER_PUBLIC_BASE_URL = os.getenv("NEWSLETTER_PUBLIC_BASE_URL", "https://cyphward.com").strip().rstrip("/")
