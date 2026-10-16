# Cyphward Compliance — agent build plan

**Prepared:** 16 October 2026 · **Baseline:** `main` at `8f174a1` (PR #18 merged)
**Location:** `docs/compliance-build-plan-2026-10-16/README.md` (this file). Progress: `PROGRESS.md`; packet plans: `C1-plan.md`.
**Goal:** Turn Cyphward's scan results plus collected customer evidence into an **NDPA 2023 / GAID 2025 readiness evidence workflow**, without a legal practitioner on staff.

---

## 0. The one rule that governs everything

Cyphward **collects, labels and organises evidence**. It **never issues a legal verdict**.

- Never output "compliant", "non-compliant", "certified", "satisfies NDPA", "passes audit" or any equivalent, in UI, reports, emails, AI output or API field names.
- Every piece of evidence carries its **source label**: `tool_observed`, `externally_observed`, `customer_attested`, `practitioner_reviewed`.
- Missing or unassessed evidence is shown as **Not assessed** or **Gap**, never as satisfied. This is the same principle as Packet 03 coverage.
- The headline metric is **Readiness coverage %**: applicable requirements with current evidence divided by applicable requirements. It is never a "compliance score".
- Every report and page carries a short disclaimer: *"Readiness evidence, not legal advice or a compliance determination. Filing of Compliance Audit Returns for UHL/EHL organisations must go through a licensed DPCO."*
- Extend `backend/tests/test_compliance_claims.py` so the banned-phrase check covers every new page, report, email and AI path.

---

## 1. What already exists (build on it, don't duplicate)

| Existing piece | Reuse for compliance |
|---|---|
| Findings + detectors (`backend/app/scanner/security_checks.py`, `detectors.py`) | Map findings to NDPA s.39 controls |
| Packet 03 coverage v2 (`backend/app/risk/check_set.py`, `coverage.py`) | Decide evidence present vs not assessed per control |
| Daily scheduler + scan history | Evidence of s.39(2) *periodic risk assessment / regular testing* |
| Remediation tasks (assignee, due date, rechecks) | Gaps become tasks, using the existing system |
| `audit_log`, notifications, Brevo mailer | Audit every evidence change, remind owners about expiry |
| RBAC (owner/admin/member), tenant isolation, RLS, `cyphward_app` role | Same boundaries apply to all compliance data |
| Plans (`backend/app/core/plans.py`: starter/growth) | Gate compliance features (decision D1) |
| `/comply` route (currently redirects to `/overview`) | Becomes the Compliance page |
| Owner console (`admin.cyphward.com`) | Later: staff view of register versions, not customer data |
| Release runbook (`docs/agent-build-plan-2026-10-13/02-release-runbook.md`) | Mandatory for any worker/scanner change (C2) |

**Not yet available:** private file storage (no upload support exists), immutable assessment snapshots (Packet 04), stable rule IDs on findings (findings are currently keyed by `title`).

---

## 2. Legal requirements register (data, versioned)

Create `backend/app/compliance/registers/ndpa_gaid_v1.json`, loaded and validated at startup. Do **not** put requirement text in the database or code. A reviewer must be able to correct it in one file.

Each entry:

```json
{
  "key": "ndpa.s39.encryption_in_transit",
  "title": "Personal data protected in transit",
  "clause": "NDPA 2023 s.39(2)",
  "clause_verified": false,
  "summary": "Plain-English description, no legal conclusion",
  "applies_to": "all | dcpmi | uhl_ehl | conditional",
  "applicability_question": "optional attestation key that decides applicability",
  "evidence_types": ["tool_observed", "customer_attested"],
  "tool_mapping": ["tls.certificate", "http.headers:hsts"],
  "freshness_days": 30,
  "remediation_hint": "short, actionable"
}
```

**Initial requirement set (v1).** The clause references come from secondary legal summaries. Every entry ships with `clause_verified: false` until the founder or a DPCO checks it against the official NDPA and GAID texts. The UI shows unverified clause references as "reference pending review".

| Group | Requirements | Clause (verify) | Evidence source |
|---|---|---|---|
| Security measures | Encryption in transit; secure/available systems (headers, exposed services, known CVEs); email anti-spoofing (SPF/DMARC); periodic risk assessment; regular testing of measures | NDPA s.39(1)–(2) | tool_observed (existing scanner + scan history) |
| Notices | Privacy policy published; cookie notice published | GAID Art. 7 | externally_observed (C2) |
| Cookie consent | Banner visible without scrolling; accept **and** reject options; no non-essential cookies/trackers before consent; purpose and withdrawal disclosed | GAID Art. 19 | externally_observed (C2) |
| DPO | DPO designated; DPO contact published; DPO reports to management; six-monthly DPO compliance report | GAID Arts. 11–13, NDPA s.32 | externally_observed + customer_attested |
| Registration / CAR | Major-importance status and tier (UHL/EHL/OHL); registration done; annual CAR filed through a DPCO (UHL/EHL, by 31 March) | GAID Arts. 8–10 | customer_attested |
| Breach | Breach response plan exists; 72-hour notification process; incident log | NDPA s.40, GAID | customer_attested + incident log (C3) |
| DPIA | DPIA done for high-risk processing | GAID Art. 28 | customer_attested |
| Lawful basis / consent | Lawful basis documented per processing purpose; consent records kept | NDPA s.24–25, GAID Arts. 17–18 | customer_attested |
| Data subject rights | Process for access, correction, portability, erasure requests | NDPA Part VI, GAID Arts. 7, 38 | customer_attested |
| Cross-border transfer | Transfers identified with a recognised basis | NDPA Part VIII, GAID Art. 45 | customer_attested |
| Training | Internal privacy/security training in place | GAID Art. 7 | customer_attested (later: Academy completion records) |

---

## 3. Data model (one new migration per packet, additive only)

**`compliance_evidence`** (C1)
`id, org_id, domain_id NULL, requirement_key, register_version, source (enum of the four labels), status (present | gap | not_assessed | not_applicable), observed_at, expires_at, scan_id NULL, finding_ids uuid[], details jsonb, created_by NULL, created_at`
- Tool-derived rows are written inside the Core finalisation transaction under the existing claim fence (Packet 02). Never written outside it.
- Append-only. The current state is the latest row per (org, requirement, domain). History stays intact.

**`compliance_attestations`** (C3)
`id, org_id, question_key, answer jsonb, owner_user_id, attested_by, attested_at, expires_at, evidence_link text NULL, notes, superseded_by NULL`

**`compliance_incidents`** (C3)
`id, org_id, title, detected_at, became_aware_at, notified_commission_at NULL, notified_subjects_at NULL, severity, status, notes, created_by`
- 72-hour deadline = `became_aware_at + 72h`. Show the countdown and overdue state.

All tables: RLS policy for `cyphward_app`, tenant-scoped indexes, grants verified through the restricted role, `audit_log` entry on every write.

**Status derivation is computed on read** from register + latest evidence/attestations (`backend/app/compliance/status.py`). Report immutability comes in C4 through Packet 04 snapshots, not by freezing these tables.

---

## 4. Packets

Each packet: own branch `codex/compliance-cN`, real tests, PROGRESS entry, one merge at a time, verify the deploy before the next merge. Same rules as Packets 01–03.

### C0 — Baseline and decisions (half a day)
1. Record HEAD, migration count, backend/frontend test baseline.
2. Confirm founder decisions D1–D4 (section 6). Proceed with the recommended defaults if not answered.
3. Add a stable `rule_key` for every existing detector (a mapping file `backend/app/compliance/rule_keys.py`, title → key). Add a test that **every detector title has a rule key**, so a new detector can't silently drop out of compliance mapping. Do not rename existing findings.

### C1 — Register, s.39 mapping, Compliance page (API + frontend only, no worker change)
- Register loader + JSON schema validation + test that every `tool_mapping` key exists in the declared check set / rule keys.
- `backend/app/compliance/mapping.py`: from the latest assessment per verified domain:
  - Coverage v2 says the check was evaluated and there is no open finding → `present` (tool_observed).
  - Open finding mapped to the requirement → `gap`, linked to `finding_ids`.
  - Check missing/unassessed or legacy coverage → `not_assessed`. **Never `present`.**
  - "Periodic risk assessment / regular testing": `present` only if at least one **complete** scan per verified domain within `freshness_days`. Show the count and dates.
- Write evidence rows in the fenced Core finalisation transaction. Add a backfill-free read path: domains without a v2 assessment show `not_assessed`.
- API: `GET /api/v1/compliance/overview` (readiness %, per-group status, gaps), `GET /api/v1/compliance/requirements/{key}` (evidence history). Member-readable, tenant-scoped.
- Frontend: replace the `/comply` redirect with a **Compliance** page: readiness coverage %, requirement groups, status chips with source labels, "reference pending review" for unverified clauses, gaps linking to existing Findings/Remediation. Desktop/390px/320px.
- Gap → "Create task" uses the existing remediation task API.
- Plan gating per D1.
- **Tests:** mapping truth table (evaluated clean / open finding / not assessed / legacy / stale scan); tenant isolation; RBAC; banned-phrase test over the page and API copy; PostgreSQL test that evidence is written under the fence and a stale finaliser writes nothing.
- **Release:** migration first, then API, then frontend. No scanner deploy.

### C2 — External privacy checks (worker change, use the release runbook)
Split in two so the cheap part ships first.

**C2a — static checks (no browser):**
- On the apex homepage and in-scope web hosts: discover the privacy policy (footer/nav links matching privacy/policy/data-protection, plus `/privacy`, `/privacy-policy`), cookie notice, DPO/contact email in policy text, `security.txt`.
- First-response checks: `Set-Cookie` headers on the first unauthenticated GET; known tracker scripts in the HTML (Google Analytics/GTM, Meta Pixel, Hotjar, TikTok, etc.) plus whether a known consent-manager script is present.
- Policy content signals (heuristic, labelled as such): mentions of lawful basis, data subject rights, DPO contact, NDPA. Output is "mentioned / not found", **never** "adequate".
- New recon stage `privacy` added to `shared/contracts.py` with an explicit **capability flag**. API must accept old workers without it (privacy requirements become `not_assessed`). Respect existing scope rules, the IP guard, redirect handling and rate limits; only verified domains.
- Persist as observations with a versioned contract (`privacy_observations` v1), same attempt identity as other stages.

**C2b — browser consent test (only after measuring memory):**
- Headless Chromium: load the homepage with no interaction, then record cookies set, third-party requests, whether a banner is visible in the initial viewport, and whether accept **and** reject controls exist. Optionally click reject and verify no non-essential cookies are set afterwards.
- The VPS worker has a 640 MiB limit. Measure peak memory first. If it doesn't fit beside the scanners, run it as a separate small worker process/service with its own claim of the `privacy_browser` stage. Report numbers before choosing.

- **Tests:** fixture sites (static HTML fixtures served locally): no policy, policy present, tracker before consent, consent manager present, cookie set on first response, off-scope redirect, private IP. No live third-party sites in tests.
- **Release:** full runbook (pause claims → drain → deploy API first → worker → resume). Core/API before worker.

### C3 — Attestations, owners, expiry, breach log (API + frontend)
- Short guided questionnaire grouped like the register (~20 questions max for v1). Each answer has owner, date, expiry (default 12 months), optional evidence **link**. File uploads wait for D2.
- Applicability questions first (e.g. "Are you registered as a data controller of major importance? Which tier?"), so `not_applicable` requirements drop out of the readiness denominator with a recorded reason.
- Expiry reminders via existing notifications/email (owner + admins), 30 and 7 days before.
- Breach incident log with the 72-hour countdown, overdue badge and a plain checklist (not legal advice).
- Owners/admins edit; members view. Every change audited.
- **Tests:** expiry turns evidence stale; not_applicable excluded from denominator with reason; attestation never shown as tool_observed; cross-tenant ID rejection; countdown/overdue edge cases across timezones (store UTC, display Africa/Lagos for Nigerian orgs).

### Packet 04 — Assessment/report snapshots (already planned; prerequisite for C4)
Include compliance state in the snapshot contract: register version, evidence rows (with sources and timestamps), attestations, readiness %.

### C4 — Evidence pack + DPO six-monthly security section
- **NDPA readiness evidence pack** (HTML + PDF export), generated from a Packet 04 snapshot: scope, dates, register version, per-requirement status with source labels and evidence references, prioritised gaps, unverified-clause markers, disclaimer. Immutable once issued; later scans don't change it.
- **DPO report section** (GAID Art. 13): a six-monthly export of the data-security part — scans run, coverage, findings opened/resolved, incidents logged, notices/consent observations. Remind DPO/owner every six months.
- Format designed so a DPCO can use it as CAR supporting evidence. Do not claim it *is* a CAR.
- **Tests:** snapshot immutability after new scans/attestations; banned phrases; cross-tenant; report with all `not_assessed` renders honestly.

### C5 — AI-drafted documents (after C3)
- Drafts generated from attestations + observations: privacy policy, cookie notice, breach response plan, retention schedule.
- Every draft: labelled **"Draft — not legal advice"**, version, generated date, requires owner/admin approval; approval recorded as `customer_attested` with approver and date.
- Grounded only in the org's own answers/observations. If an input is missing, the draft leaves a visible placeholder instead of inventing facts. Use the existing privacy sanitizer; no raw evidence sent beyond what's needed.
- Tests: no banned phrases; missing inputs produce placeholders; approval workflow and audit.

### C6 — Later, demand-gated
- **DPCO reviewer seat:** customer-granted, time-limited, scoped access for a licensed DPCO who can mark requirements `practitioner_reviewed` and set `clause_verified`. Separate from platform staff authority; fully audited.
- **Academy hook:** training-completion records become evidence for the training requirement.

---

## 5. Validation rules (same as Packets 01–03)

- Fresh owned loopback `cyphward_test` DB, restricted `cyphward_app` role, bootstrap script only. Never `.env`/production URLs (`CYPHWARD_ENV` guard must stay intact).
- Stub scanning, browser, AI and email. Fixture websites only.
- Run: full backend suite, PostgreSQL modules, frontend build, browser suites at desktop/390/320, `git diff --check`. Report real pass/skip counts.
- One PR per packet; merge one at a time; check `/health` and the relevant page after each deploy. Worker changes follow the release runbook.

---

## 6. Founder decisions (agent proposes default, founder confirms)

| # | Decision | Recommended default |
|---|---|---|
| D1 | Plan gating | Growth gets full Compliance; Starter sees readiness % and the security group, others locked with upgrade prompt |
| D2 | File uploads | Defer; links only in C3. Later: private storage bucket, tenant-scoped signed URLs, size/type limits, retention policy |
| D3 | Cookie browser test location | Measure first; separate small worker if > ~200 MiB peak |
| D4 | Clause verification | Founder or partner DPCO reviews the register before C4 reports go to customers; until then UI marks references "pending review" |

---

## 7. Completion report per packet

Packet + revision; changed behaviour; files/migrations; tests with actual counts and skips; compatibility (old workers, legacy scans); limitations; deployment state (planned / implemented / validated / review-ready / released / production-verified); next packet's prerequisites. Update `PROGRESS.md`.
