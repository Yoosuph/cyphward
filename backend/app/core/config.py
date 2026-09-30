import os
from pathlib import Path
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

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
# HS256 secret used to verify Supabase Auth access tokens (JWT) in the API.
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "https://cyphward.com",
    "https://www.cyphward.com",
    "https://cyphward.vercel.app",
]

# AI Intelligence Layer Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Inngest (cloud) — event key sends events, signing key verifies callbacks.
INNGEST_EVENT_KEY = os.getenv("INNGEST_EVENT_KEY", "")
INNGEST_SIGNING_KEY = os.getenv("INNGEST_SIGNING_KEY", "")

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
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "Cyphward Security")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "")
