# CYPHWARD — Sovereign Attack Surface Management

External security posture platform: continuous attack-surface discovery, security
scoring (0–100), findings lifecycle, remediation tasks, and executive reports.

- **Frontend:** Vite · React 18 · TypeScript · Tailwind · react-router
- **Backend:** FastAPI (Python) · PostgreSQL (Supabase) · built-in auth · Inngest workflows
- **Auth:** Our own backend accounts — argon2 passwords, JWT access tokens with
  rotating refresh sessions, email verification & password reset sent through
  Brevo, optional Google sign-in (server-side OAuth flow). Org membership is
  verified server-side via `X-Organization-Id` (fail-closed, no fallback org),
  roles `owner | admin | member`.

## Repository layout

```
backend/app/
  main.py           # FastAPI app, routers, Inngest serve (/api/inngest)
  api/              # REST routers (domains, findings, scans, assets, AI, …)
  core/             # config, database, auth (JWT + RBAC + audit)
  risk/             # 0-100 security scoring engine
  scanner/          # DNS/HTTP/TLS probes, normalizer, nuclei runner
  ai/               # LLM providers + privacy sanitizer
  services/         # notifications, transactional email
  workflows/        # Inngest scan pipeline + daily scan cron
  db/               # seed scripts
backend/tests/      # pytest suite (no DB required — in-memory fake)
frontend/src/       # React app (pages, components, lib/api, lib/auth, lib/session)
supabase/migrations # SQL schema
```

## Prerequisites

- Node 18+
- Python 3.11+ with [uv](https://docs.astral.sh/uv/) (used to run the server)
- A Supabase project (Postgres only — auth is built into the backend)
- Brevo account for outbound email (verification codes, password resets)
- Inngest CLI (`npm i -g inngest-cli`) for local workflow execution

## Environment

Copy the examples and fill in real values:

```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

Required:

| Variable | Where | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `.env` / `backend/.env` | Postgres connection string |
| `AUTH_JWT_SECRET` | `.env` | HS256 secret for signing/verifying access tokens (**required at runtime**) |
| `FRONTEND_URL` | `.env` | Public frontend origin (password-reset links) |
| `BREVO_*` | `.env` | Brevo SMTP/API credentials — all product email |

Optional:

| Variable | Where | Purpose |
| --- | --- | --- |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | `.env` | Google sign-in (OAuth 2.0 client) |

Generate the JWT secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Database migrations

Apply migrations in order (Supabase CLI or SQL editor):

```bash
supabase db push
# or apply supabase/migrations/*.sql manually, ending with:
# 20261001120000_own_auth.sql
```

> Upgrading a database that already holds customer data? Read
> `docs/database-upgrade-runbook.md` first — one migration drops legacy
> tables and needs a backup + data decision beforehand.

Optionally seed demo tenants:

```bash
python -m backend.app.db.seed_mvp
```

## Development

```bash
npm install          # root convenience scripts
cd frontend && npm install

npm run start        # API (:8000) + Inngest dev + Vite dev (:5173)
```

Individually:

| Command | What it runs |
| --- | --- |
| `npm run server` | FastAPI via uvicorn (`backend.app.main:app`, :8000) |
| `npm run inngest` | Inngest dev server, signed to `/api/inngest` |
| `npm run dev` | Vite dev server (:5173) |
| `npm test` | Backend pytest suite |
| `npm run build` | Frontend type-check + production build |

API docs: `http://localhost:8000/docs`

## Tests & CI

```bash
npm test             # backend: auth chain, RBAC, cross-tenant, units
cd frontend && npm run build   # tsc + vite
```

The backend suite runs offline: `backend/tests/conftest.py` seeds an in-memory
tenant store and patches `get_db`, so tests exercise the **real** JWT →
membership → RBAC path with no Postgres. GitHub Actions (`.github/workflows/ci.yml`)
runs both jobs on every push/PR.

## API conventions

- All authenticated requests: `Authorization: Bearer <access token>`
- Tenant selection: `X-Organization-Id: <org uuid or slug>` — verified against
  `organization_members`; requests for a non-member org return `403`.
- No API keys. Mutations require `admin`/`owner`; owner-only actions require
  `owner`.
- Findings statuses: `open | acknowledged | in_progress | resolved`
  (severities lowercase: `critical | high | medium | low | info`).

## Scanning & workflows

- Scans may only target **verified** domains; the backend resolves scope.
- The Inngest pipeline (`backend/app/workflows/inngest_workflow.py`) runs
  discovery → probes → nuclei → normalize/upsert → score → notify.
- A daily cron (`0 6 * * *`) queues scans for verified domains without an
  active scan.

## Out of scope (intentionally removed)

Compliance modules, Academy, Detect/alerts, Copilot, threat ticker, SAML SSO,
API-key auth, and analytics — see git history if needed.
