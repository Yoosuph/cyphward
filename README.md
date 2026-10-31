# Cyphward

Cyphward is an external security-posture platform for organisations in Nigeria and beyond. It discovers a
customer's public attack surface, scores it from 0 to 100, tracks findings through remediation, and produces
evidence for NDPA 2023 and GAID 2025 readiness (compliance evidence, not legal advice).

## What is in the product

- **Customer app** (`app.cyphward.com`): sign-up, verified domains, scans, findings and remediation tasks,
  a security score with history, reports and board summaries, a compliance readiness register with evidence
  packs and snapshots, evidence uploads, incidents, reviewer access for an outside practitioner, a
  newsletter sign-up page, billing and plans, and a Cyphbot assistant.
- **Owner console** (`admin.cyphward.com`): platform analytics, organisation and user management, plan and
  trial changes, suspension, member restore, audit logs, newsletter drafting and sending, and expandable logs.
  See [`docs/owner-console.md`](docs/owner-console.md).
- **Workers:** a scanner worker and a browser worker (consent observation) run outside the API and poll it over
  HTTPS with their own keys. Both currently run on AWS.
- **Newsletter:** sign-up with explicit consent, one branded confirmation email, one-click unsubscribe, and
  admin-approved issues sent through Brevo. Off unless `NEWSLETTER_ENABLED=true`. See [`docs/newsletter/README.md`](docs/newsletter/README.md).

## Architecture

| Part | Where it runs | Notes |
| --- | --- | --- |
| Frontend (customer app, owner console, public site) | Vercel | Vite · React 18 · TypeScript · Tailwind · react-router. `/api` requests are rewritten to the API. |
| API (`backend/app`) | Render (`cyphward-core`), with `api.cyphward.com` as the custom domain | FastAPI, uvicorn, Inngest endpoint at `/api/inngest` |
| Database | Supabase Postgres | Migrations in `supabase/migrations`; the app connects as a restricted role with row-level security |
| Scanner worker (`scanner/`) | AWS EC2 (af-south-1) | Outbound only. Claims scans from the API. Container limit 640 MB |
| Browser worker (`browser_worker/`) | AWS EC2 (af-south-1) | Outbound only. Headless Chromium with the sandbox on. Container limit 768 MB. Disabled unless `BROWSER_CONSENT_ENABLED=true` |
| Email | Brevo | Transactional mail from `info@cyphward.com`; newsletter from `news@cyphward.com` |
| Sign-in | Built into the API | Argon2 passwords, JWT access tokens with rotating refresh sessions, email codes, optional TOTP, optional Google sign-in |

Scheduled work runs in the API through Inngest: a daily scan job at 06:00 UTC and a compliance reminders job.

## Repository layout

```
backend/app/
  main.py            FastAPI app, routers, Inngest registration
  api/               REST routers (scans, domains, findings, compliance, owner, newsletter, ai, …)
  core/              config, database pool, auth and RBAC, suspension gate, rate limits, audit
  compliance/        NDPA/GAID register, attestations, evidence, reviewer access, documents
  packs/             branded evidence packs (HTML and PDF)
  snapshots/         frozen, hashed compliance snapshots
  scanner/           scan probes and the scanner-side scoring inputs used by the API
  risk/              0–100 scoring engine
  ai/                LLM providers, sanitiser, Cyphbot
  billing/           plans and subscription handling
  services/          transactional mail and notifications
  storage/           evidence file storage (private bucket)
  workflows/         Inngest scan pipeline and cron jobs
  db/                seed scripts
backend/tests/       pytest suite (unit tests plus PostgreSQL tests)
scanner/             scanner worker (container image, Dockerfile.scanner)
browser_worker/      browser worker (container image, Dockerfile.browser, deploy examples)
shared/              contracts shared by the worker and the API
frontend/src/        React app: pages, components, owner console (owner/), lib/
supabase/migrations/ ordered SQL migrations
docs/                runbooks and reviews (see below)
.github/workflows/   CI (ci.yml) and the scanner deploy (deploy-scanner.yml)
```

## Prerequisites

- Node 20 or newer, and npm
- Python 3.11 or newer, with [uv](https://docs.astral.sh/uv/)
- A Supabase project (Postgres)
- A Brevo account for email
- Inngest CLI for local scheduled and pipeline runs (`npm i -g inngest-cli`)
- For Postgres-backed tests: a local PostgreSQL 16 or newer

## Environment

Copy the examples and fill in real values. Never commit real values.

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp scanner/.env.example scanner/.env          # only when running the scanner locally
```

Required for the API:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres connection string for the restricted app role |
| `AUTH_JWT_SECRET` | HS256 signing secret for access tokens (required at runtime) |
| `FRONTEND_URL` | Public customer-app origin, used in links |
| `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME` | Transactional email |
| `SCANNER_API_KEY` | Shared secret the scanner worker uses to claim scans |
| `BROWSER_WORKER_API_KEY` | Shared secret the browser worker uses to claim jobs |

Feature flags (all default to off unless stated):

| Flag | What it turns on |
| --- | --- |
| `NEWSLETTER_ENABLED` | Newsletter sign-up, confirmation and sending. Needs the newsletter settings in the newsletter README. |
| `BROWSER_CONSENT_ENABLED` | Browser consent observations (the browser worker must also be running) |
| `DEMO_LOGIN_ENABLED` | The "Try the demo" sign-in button. Needs `DEMO_LOGIN_PASSWORD` |
| `EVIDENCE_UPLOADS_ENABLED` | Evidence file uploads to the private storage bucket |
| `COMPLIANCE_DOCS_MODEL` | Model-written wording for compliance drafts. Off by default and not set in production |

Optional: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (Google sign-in).

Generate a secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Database migrations

Apply every file in `supabase/migrations` in filename order. Each file sets its own lock and statement
timeouts, is idempotent, and is additive unless its header says otherwise.

```bash
supabase db push
```

Upgrading a database that already holds customer data? Read
[`docs/database-upgrade-runbook.md`](docs/database-upgrade-runbook.md) first. Some migrations need a backup and
a data decision beforehand, and migrations that change the scan failure column must be applied before the code
that writes it is deployed.

Optionally seed demo tenants:

```bash
python -m backend.app.db.seed_mvp
```

## Development

```bash
npm install                      # root convenience scripts
cd frontend && npm install && cd ..

npm run start                    # API on :8000, Inngest dev server, and Vite on :5173
```

Run the parts separately:

| Command | What it runs |
| --- | --- |
| `npm run server` | API with uvicorn (`backend.app.main:app`, port 8000, reload on) |
| `npm run inngest` | Inngest dev server pointed at `/api/inngest` |
| `npm run dev` | Vite dev server (port 5173) |
| `npm run build` | Frontend type-check and production build |
| `npm test` | Backend pytest suite (no database needed; Postgres tests skip) |

API documentation is served at `http://localhost:8000/docs`.

## Tests

```bash
npm test                                    # backend unit tests
cd frontend && npm run build                # type-check and build
cd frontend && npm run test:compliance-ui   # browser checks (also test:scans-ui, test:owner-logs, …)
```

Postgres tests need a database that the bootstrap script can create and reset. Point these at a throwaway
local cluster, never at production:

```bash
export CYPHWARD_TEST_DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1:55432/cyphward_test
export CYPHWARD_TEST_DATABASE_URL=postgresql://cyphward_app@127.0.0.1:55432/cyphward_test
python backend/scripts/bootstrap_test_database.py
python -m pytest backend/tests -q
```

CI (`.github/workflows/ci.yml`) runs the backend suite, a PostgreSQL job that runs the database-backed tests,
the frontend build, and builds the scanner and browser worker images. The browser UI suites are run locally
and are not part of CI yet.

## API conventions

- Authenticated requests send `Authorization: Bearer <access token>`.
- Customer requests that act on an organisation send `X-Organization-Id: <uuid or slug>`. The membership is
  checked on the server for every request, and a non-member gets `403`. There is no fallback organisation.
- Roles are `owner`, `admin` and `member`. Mutations need `admin` or `owner`; owner-only actions need `owner`.
- A suspended organisation can still sign in and read its data. Every write route is refused with
  `403` and the code `organization_suspended`. The rule is enforced by one shared check, and a test lists every
  write route and fails if one is neither gated nor on the reviewed allow-list.
- Owner console routes live under `/api/v1/owner/…` and need an owner session cookie plus the console origin.
  Every owner read and write is audited.
- Scan results shown to customers use reviewed wording for failures. Raw worker text is kept for the owner console only.
- Findings statuses: `open | acknowledged | in_progress | resolved`. Severities: `critical | high | medium | low | info`.

## Scanning and workflows

- Scans run only against **verified** domains. The backend resolves the scope; the worker re-checks it.
- The scan pipeline runs discovery, probes, nuclei templates, normalisation, scoring and notifications.
- Daily scans queue for verified domains at 06:00 UTC, and only domains without an active scan are queued.
- Compliance reminders run as an Inngest cron job.
- Do not run a scan while a release or migration is in progress.

## Documentation

| Document | Topic |
| --- | --- |
| [`docs/owner-console.md`](docs/owner-console.md) | Owner console access and dedicated admin login |
| [`docs/newsletter/README.md`](docs/newsletter/README.md) | Newsletter setup, GrokBot drafts, sending |
| [`docs/runbooks/browser-worker.md`](docs/runbooks/browser-worker.md) | Browser worker: build, run, firewall, verify |
| [`docs/database-upgrade-runbook.md`](docs/database-upgrade-runbook.md) | Upgrading a database that holds customer data |
| [`docs/compliance-build-plan-2026-10-16/`](docs/compliance-build-plan-2026-10-16/) | Compliance build plan, decisions and progress log |
| [`docs/admin-2026-10-29/`](docs/admin-2026-10-29/) | Owner console phase 1 audit and screens |

Older review and planning notes live under `docs/` and are kept for history; check the date in their folder name.

## Security notes

- Never commit `.env` files, keys or service-account JSON. Workers keep their keys in root-only files on their
  servers.
- Customer data is isolated per organisation in the API and by row-level security in the database.
- Report security issues privately to the maintainers before any public disclosure.
