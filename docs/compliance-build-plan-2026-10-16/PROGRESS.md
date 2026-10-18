# Compliance build progress

Keep implementation, validation and deployment states separate. Never record credentials, customer evidence or personal data here.

## C0 — baseline, decisions, rule keys (16 October 2026)

**State:** implemented and validated locally; review-ready on `codex/compliance-c0`. Not released.

### Baseline

- `main` at `1aaca20` (PR #20, owner console actions, merged and deployed). The plan's own baseline was `8f174a1`. PRs #19 and #20 since then touch only the owner console, the shared scan-cancel SQL and owner tests.
- Migrations: **29**.
- Fresh owned PostgreSQL 18.6 cluster bound to `127.0.0.1:55439`, database `cyphward_test`, built only by `backend/scripts/bootstrap_test_database.py` (29 migrations, restricted `cyphward_app` verified). No `.env`, production URL or restored snapshot was used.
- PostgreSQL modules (admission, execution, owner views, owner actions): **51 passed**.
- Full backend suite with the test database: **611 passed, 16 skipped**. Without a test database: **560 passed, 67 skipped**.
- Frontend `npm run build`: passed. `git diff --check`: passed.

### Founder decisions — proposed defaults

The founder delegated approval to the agent on 16 October 2026 ("approve on your own"). These defaults apply until the founder overrides them.

| # | Decision | Default adopted | Notes |
|---|---|---|---|
| D1 | Plan gating | **Growth:** full Compliance page. **Starter:** readiness % and the Security measures group; the other groups are listed but locked, with an upgrade prompt. | Gating applies to reads only. Evidence rows are written for every plan so an upgrade shows history immediately. |
| D2 | File uploads | **Deferred.** C3 accepts evidence links only. | Later: private bucket, tenant-scoped signed URLs, size and type limits, retention policy. |
| D3 | Cookie browser test location | **Measure first** in C2b. Use a separate small worker if peak memory exceeds about 200 MiB. | The VPS worker has a 640 MiB limit. |
| D4 | Clause verification | **Every register entry ships `clause_verified: false`.** The UI shows "reference pending review". The founder or a partner DPCO reviews the register before any C4 pack goes to a customer. | Corrections are one-file edits to the register JSON plus a version bump. |

Three further defaults surfaced while planning C1. They follow section 0 of the plan and are recorded so they can be challenged:

| # | Decision | Default adopted |
|---|---|---|
| D5 | Readiness figure (revised by the founder, 16 Oct) | No bare percentage. Shown as **"N of 29 have evidence · M awaiting input or upcoming checks"**, where N = present + gap (current evidence either way) and present, gaps, not assessed and awaiting input are each counted. |
| D6 | Tool evidence and applicability | Tool evidence never produces `not_applicable`. A check omitted for a known reason (for example, no web service) yields `not_assessed` with that reason. Only an answered applicability question (C3) can remove a requirement from the denominator. |
| D7 | Requirements without an evidence source yet | Notices, consent, DPO, registration, breach, DPIA, lawful basis, rights, transfers and training stay in the denominator as `not_assessed` ("evidence collection not available yet") until C2/C3 builds their source. They read **"Awaiting your input"** (customer answer) or **"Upcoming check"** (C2 check), never "Not assessed", which is reserved for a check that could have run but did not finish (founder, 16 Oct). |

### Rule keys

- `backend/app/compliance/rule_keys.py`: a stable key for each of the 15 security-check titles, patterns for 2 legacy titles still stored in production (`…Expiring within N Days`, `Modern Cryptographic Protocols Active (TLSv1.3)`), and `nuclei:<template_id>` for Nuclei. Anything else is unmapped. No stored finding is renamed.
- Each rule has a `kind`:
  - `issue`: an open finding is a gap;
  - `informational`: robots.txt paths;
  - `positive`: modern TLS protocol, which is never a gap and never evidence on its own.
- Each rule also names the declared coverage check whose conclusive evaluation it needs. Nuclei has none, so no Nuclei result can show a clean outcome.
- `backend/tests/test_compliance_rule_keys.py` (11 tests) parses `security_checks.py` and fails if any title it can emit lacks a key. A temporary new detector title made the test fail, as intended; the checker was restored unchanged.
- Production data note: one stored finding titled `rls-probe` (category Security Configuration) is not a detector output. It stays unmapped, and was left untouched.

Next: C1, as planned in `C1-plan.md`.

## C1 — register, s.39 mapping, Compliance page (16 October 2026)

**State:** implemented and validated locally; review-ready on `codex/compliance-c1` (stacked on C0). **Not released.** No production migration has been applied.

### Changed behaviour

- **Register** `ndpa_gaid_v1.json`:
  - 29 requirements in 11 groups, all `clause_verified: false`;
  - clause references are only those in the plan (no new legal references were introduced);
  - every tool-backed entry states what was checked and what was not;
  - validated at startup by `compliance/register.py`, so an invalid register stops the API.
- **Evidence written at finalisation:** five tool-backed requirements get one append-only `compliance_evidence` row each, for the **scanned** domain. The rows are computed before the completion transaction and inserted inside the held claim under a SAVEPOINT:
  - if the computation or the insert fails, no rows are written;
  - the scan still completes, and the `scan.completed` audit records `compliance_evidence: "error"`;
  - on success, the audit records the row count.
- **Status is derived on read:**
  - any currently open mapped issue finding (status other than `resolved`) is a live gap, whatever the stored row says;
  - `present` needs a current, unexpired row that recorded conclusive declared checks;
  - legacy/missing coverage, missing checks, omitted-only checks, expired evidence and gaps whose findings were since resolved all read `not_assessed`;
  - Nuclei can only be a gap;
  - the two scan-history requirements need a complete-coverage scan for every verified domain within the window.
- **API:** `GET /api/v1/compliance/overview` and `GET /api/v1/compliance/requirements/{key}`.
  - Any member can read them, scoped by `get_current_org`.
  - Starter gets readiness plus the security group; other groups are locked and the detail endpoint returns 403 for them (D1).
  - Every response carries the plan's disclaimer word for word.
- **Page:** `/comply` (Compliance in the sidebar and mobile menu) replaces the old redirect. It shows:
  - the readiness coverage % with present / gap / not-assessed counts;
  - status chips with source labels, or "No evidence yet";
  - "reference pending review" on unverified clauses;
  - checked / not-checked lines, per-domain detail, open ports and complete-scan counts;
  - gap findings with "Create task", which uses the existing remediation API and shows an existing task instead of duplicating it.
- **Readiness** reads "N of 29 have evidence · M awaiting input or upcoming checks" with present / gap / not assessed / awaiting counts; no percentage. 22 requirements await input or upcoming checks; Nuclei can never be present, so at most 6 can be present in C1.

### Files and migration

- **Backend:** `compliance/{register,mapping,status,scan_evidence}.py`, `compliance/registers/ndpa_gaid_v1.json`, `api/compliance.py`, plus small changes to `core/scan_execution.py` (`finish_assessment(..., compliance_evidence=)`), `workflows/inngest_workflow.py` and `main.py`.
- **Migration** `20261017090000_compliance_evidence.sql` (additive): the table, a latest-row index, a unique `(scan_id, requirement_key)` for replay, RLS policy for `cyphward_app`, and append-only grants (SELECT, INSERT). `scan_id ON DELETE SET NULL` keeps history.
- **Frontend:** `pages/Compliance.tsx`, `lib/api.ts`, `App.tsx`, `Sidebar.tsx`, `MobileMenuSheet.tsx`, `lib/routePrefetch.ts`, and the browser suite `scripts/check-compliance-page.mjs` (`npm run test:compliance-ui`).
- **CI:** `test_compliance_postgres.py` is added to the PostgreSQL job.

### Validation (fresh owned loopback PostgreSQL 18.6 on 127.0.0.1:55439, bootstrap script only, 30 migrations, restricted `cyphward_app`)

- PostgreSQL modules: **62 passed**, including **11 new compliance cases**:
  - evidence written inside the completion;
  - a stale claim writes nothing (no evidence, no snapshot);
  - replay can't duplicate;
  - a mapping exception and an invalid insert each leave the scan completed with zero evidence;
  - UPDATE/DELETE are refused for the app role;
  - an HSTS finding and an apex DMARC finding become gaps linked to the real finding rows;
  - a reopened finding turns stored `present` into a live gap;
  - scan history needs every verified domain;
  - member read, tenant isolation (including 403 for a foreign `X-Organization-Id`) and Starter gating.
- Full backend suite with the test database: **685 passed, 16 skipped** (baseline 611/16). Without a test database: **623 passed, 78 skipped**.
- New pure tests:
  - truth table and register validation: 48;
  - rule keys: 11 (C0);
  - banned phrases over the register, API strings and field names across all statuses, and page copy, with the exact disclaimer: 4 new.
- Frontend build passed. Browser suites passed: `test:compliance-ui` at desktop/390/320, plus the existing `test:scans-ui`, `test:score-ui` and `test:onboarding-ui`. `git diff --check` passed.
- APIs and the browser were stubbed in the UI suite; no live scan, email or production data was used.

### Release (needs the founder's OK)

1. Back up, then apply only `20261017090000_compliance_evidence.sql` to production as `postgres`. Verify the table, RLS, the append-only grants through the `cyphward_app` connection, and that existing row counts are unchanged.
2. Merge C0, then C1. This deploys the Render API and the Vercel frontend. No scanner deploy: scanner paths are unchanged.
3. Verify `/health`, that `GET /api/v1/compliance/overview` returns 401 without auth, that `/comply` loads, and that the next completed scan's audit shows a numeric `compliance_evidence` count.

### Limitations

- Evidence starts at each domain's next completed scan; there is no backfill.
- Production currently has no complete-coverage v2 scans (4 partial in 90 days), so the scan-history requirements and most security requirements will start as not assessed.
- There are no immutable snapshots yet (C4/Packet 04).
- `rls-probe` remains an unmapped stray finding in production.

## C1 release record (16 October 2026)

**State:** released and production-verified.

- **Preflight** (read-only, founder-approved release step): no queued or running scans; application row counts recorded privately.
- **Backup:** a full logical dump through the session pooler (746 KB, readable, 31 public tables of data), stored privately outside the repository. It is now **encrypted** (see the runbook backup note).
- **Migration:**
  - Only `20261017090000_compliance_evidence.sql` was applied, as `postgres`, in one transaction with `lock_timeout 5s` and `statement_timeout 60s`, and recorded in `supabase_migrations.schema_migrations`.
  - Verified: RLS on; both indexes present; `cyphward_app` has SELECT and INSERT only (UPDATE and DELETE refused), no `BYPASSRLS`; every existing row count unchanged.
  - The two owner-console migrations (`20261016120000`, `20261016150000`), which had been applied earlier without history rows, were recorded afterwards, insert-only, with the founder's OK.
- **Merges:**
  - #21 (C0) as `2b880a8`;
  - #22 (C1) as `d470d1f`, after retargeting to `main`, a fresh CI run against `main`, and a re-check of active scans;
  - both main refs synchronised. No scanner deploy (scanner paths unchanged).
- **Verification:**
  - API live at `d470d1f`, healthy;
  - `GET /api/v1/compliance/overview` and `/requirements/{key}` return 401 without auth and appear in OpenAPI;
  - `/comply` served, and the live bundle contains the Compliance chunk.
- **First evidence:** scan `4dac094c` (cyphward.com, 17:29–17:55 UTC):
  - complete coverage;
  - evidence 1 present / 3 gaps / 1 not assessed.
  - The gaps traced to false header findings on Brevo's click-tracking host, fixed by PR #23 (`0e770c6`). The DNS SPF/DMARC changes were applied by the founder.
- **Rescan `c003bda0`** (18:26–18:52 UTC):
  - complete coverage (19/19 on 6 hosts), both domains complete, grade **C**;
  - evidence **4 present / 1 not assessed** (known-vulnerability testing, by design);
  - the old `r.info.cyphward.com` header findings resolved at 18:52.

## C2a — static privacy checks (16 October 2026)

**State:** implemented and validated locally; review-ready on `codex/compliance-c2a`. **Not released.** No migration.

### Changed behaviour

- **New optional recon stage `privacy`**, run **last** (after Nuclei) so it only uses leftover recon budget and can never starve the declared checks; worker and local mode. Hard wall-clock caps: 30 s per host, 120 s per stage. The probe, `backend/app/scanner/privacy_probe.py`:
  - fetches the homepage, a catch-all probe, policy/cookie links, the fixed paths and `security.txt`;
  - pins every hop to a public IP and follows in-scope redirects only;
  - caps bodies at 512 KB, requests at 4 s and fetches at **10 per host** (raised from the plan's 6: proving "not found" for D8 takes the homepage, the catch-all probe and 6 fixed paths). Running out of budget is never "not found";
  - checks up to 5 hosts, apex and `www` first.
- **What it records:**
  - the page found (and how), or a link off-domain (not fetched);
  - catch-all detection, and a content test (title/heading names the topic and the body differs from the homepage);
  - heuristic policy signals (mentioned / not found; emails masked) and a **SHA-256 of the normalised policy text** (the text is never stored);
  - first-response cookies, **names and attributes only**, classified tracker / infrastructure / necessary / unknown;
  - tracker scripts (direct vs loader; consent-blocked); the consent manager; `security.txt`.
- **Capability flag:**
  - `GET /scanner/protocol` advertises `privacy_v1`;
  - the worker runs the stage only when the API advertises it, and then sends `X-Scanner-Capabilities` on claim;
  - the claim records `stage_progress.privacy` as `pending`, or as `skipped` with `worker_without_privacy_capability`;
  - the new claim payload is verified against the deployed worker's contract (`c043223`, vendored under `tests/fixtures/deployed_contracts/`);
  - the stage is optional: a crash or timeout records failed hosts and the scan completes.
- **Evidence** (register `ndpa-gaid-v1.1`, a new `privacy` mapping type) is written as `externally_observed` rows in the completion savepoint:
  - **Privacy policy / cookie notice:** present when found (or linked off-domain). **Gap (D8)** only on a non-catch-all apex where every fixed path returned 404/410. Otherwise not assessed: catch-all, inconclusive, apex not checked, or fetch failed.
  - **Trackers before consent:** a gap only from a **known-tracker cookie** on the first response, or a direct tracker script with no consent manager. Infrastructure (`__cf_bm` …), necessary (session) and unknown cookies are listed, never a gap. Loaders alone or trackers behind a consent manager need the browser test. **Never present.**
  - **DPO contact:** present when a fetched policy names one; otherwise awaiting input (the customer can confirm it).
  - **Policy changed since last scan:** flagged when the fingerprint differs for the same URL; informational only.
- **Read side:**
  - a separate path for externally observed rows: the **newest row wins**, a gap stands until it expires, and expiry only marks staleness;
  - a scan without the stage (older worker) writes no rows, so the previous result stands;
  - policy mentions of lawful basis and data subject rights appear as heuristic notes on those attested requirements, without changing their status.
- **Coverage, grade and score are unchanged:** privacy is not a declared check (verified by a PostgreSQL test).
- **UI:**
  - the scan page gains a "Privacy notices (static)" row after "Known vulnerabilities" (outside the "N of 7 checks" count and coverage), with "worker update pending" for older workers;
  - the Compliance page shows the "Externally observed" source, the page found, "changed since last scan", the trackers observed and the cookie categories.

### Validation (fresh owned loopback PostgreSQL 18.6, 127.0.0.1:55439, bootstrap only, 30 migrations, restricted `cyphward_app`)

- **New tests, fixture websites only** (`httpx.MockTransport`; no network; no live third-party site):
  - probe 20, including host and stage deadlines, and the real probe output mapped through to evidence (present, D8 gap, catch-all);
  - capability, compatibility and ordering 8, including "privacy runs only after ports/TLS/Nuclei";
  - privacy truth table 27;
  - PostgreSQL privacy stage 9: claim capability ×3, the protocol advertising it, an old-worker scan with no rows, externally observed rows with coverage/score unchanged, **a failed privacy stage leaves coverage complete, grade A and score 100**, a stale attempt can't store, newest wins / the previous result stands.
- PostgreSQL modules: **72 passed**, twice in a row.
- Full backend suite with the database: **758 passed, 16 skipped**. Without it: **687 passed, 87 skipped**.
- Frontend build passed. Browser suites passed:
  - `test:compliance-ui` (desktop/390/320, now with externally observed evidence);
  - `test:scans-ui` (now asserting the privacy row, a long URL without overflow, and the unchanged "of 7 checks completed");
  - `test:score-ui`, `test:onboarding-ui`.
- `git diff --check` passed.
- **Pre-existing flake:** `test_lost_local_dispatch_is_consumed_from_queue` failed 3 of 15 runs at its 5 s bound on clean `main` here (real DNS lookups for synthetic hosts). Its bound is now 20 s, and it passed 15 of 15.

### Release

**Worker change: follow `02-release-runbook.md` → "C2a privacy stage".** The founder pre-approved the claims pause/resume and the count-only all-organisation queue query; the merge waits for the founder's "merge".

## Known flaky test (to fix properly later)

- **`backend/tests/test_scan_execution_postgres.py::test_lost_local_dispatch_is_consumed_from_queue`.** It failed 3 of 15 runs at its original 5 s bound on clean `main` (measured 16 Oct 2026). Its local pipeline still does **real DNS lookups** for synthetic `*.example.test` hosts, because `no_external` doesn't stub `resolve_host_dns`, so its run time depends on the resolver.
- **Workaround in C2a:** the bound was raised to 20 s (15 of 15 passed). That is a timing allowance, not a fix.
- **Proper fix:** stub the DNS resolver (and any other network call) in that test's pipeline, and restore a tight bound, so the test measures recovery behaviour only.

## Scoring carry-forward (branch `codex/scoring-carry-forward`)

- **Rule:** the organisation score comes from open findings. A failed, partial or timed-out stage never removes a finding or raises the score. A finding auto-resolves only when its own detector completed for that host in that scan.
- **Already enforced before this change:** Nuclei findings are never auto-resolved; an unreachable HTTP host and failed security checks leave their findings open as "not evaluated"; DNS is judged query by query.
- **Added:** `backend/tests/test_carry_forward_scoring.py`, 7 tests:
  - partial DNS (DMARC query never completed) keeps the DMARC finding open, and the score does not drop;
  - failed Nuclei and timed-out Nuclei keep their findings and points;
  - unreachable HTTP keeps the header finding and points;
  - failed security checks do not lower the score;
  - a positive control: once DMARC is answered, the same finding resolves, so the partial-DNS result is caused by the missing query.
- **Validation:** owned loopback PostgreSQL (`127.0.0.1:55432`, bootstrap run, 30 migrations, restricted `cyphward_app`). Full backend suite **792 passed, 16 skipped**. The CI PostgreSQL race list **73 passed**. Opt-in integration suites (`CYPHWARD_*_INTEGRATION`) were not run; CI does not run them.

## Decisions for Yusuf (scoring and scanner)

1. **Nuclei findings never auto-resolve.** A CVE that is fixed stays open until someone resolves it by hand. This is deliberate for now, because absence from a Nuclei run is not proof of a fix. Schedule a verified-resolution rule later: a template resolves only after a completed run that included that template and host.
2. **Tiered Nuclei defaults (from the 17 Oct count):** daily critical+high at 20 req/s (about 19 min for five hosts; 15 req/s is at the limit); weekly full safe set at 25 req/s with a one-hour budget (about 50 min estimated). Estimates are a lower bound, so confirm with a real scan before relying on them.

## C3 — attestations, owners and expiry, breach log (branch `codex/compliance-c3-rebased`)

**Status: plan only. Implementation not started.** This PR carries the C3 plan onto current `main` and records the defaults for D11–D15. The build is too large for one session, so it is split as follows (each its own PR, tests included):

1. **C3a — data and read side:** questionnaire JSON and validator, the one additive migration with its grants and RLS, the truth table (applicability, expiry, superseding, mixed DPO sources), the questionnaire and attestation API, and PostgreSQL tests for atomic superseding, append-only grants, cross-tenant rejection and audit.
2. **C3b — reminders and incidents:** the daily `compliance_reminders` cron (30/7-day thresholds, dedupe, stale-claim guard, stubbed email), incidents API with server-side 72-hour deadline, plus its timezone and edge tests.
3. **C3c — frontend and browser suite:** the "Answer questions" flow, Excluded section, Incidents tab with countdown and overdue badge, banned-phrase check, desktop/390/320 browser tests.

### Decisions for Yusuf (C3 defaults applied, per the plan's recommendations)

- **D11 — display time zone:** add `organizations.display_timezone`, default **Africa/Lagos**, editable by owners in Settings. Store UTC everywhere.
- **D12 — expired answer:** shows **Awaiting your input — renewal due**, is never presented as present, and gets reminders at 30 and 7 days before expiry.
- **D13 — "Not sure" answers:** treated as unanswered (`awaiting_input`), never as a gap.
- **D14 — who may own an answer:** any member of the organisation; owners and admins assign.
- **D15 — incident retention:** the app never deletes incidents. Closed incidents stay as history; removal is operator SQL only and audited.

## C3a — questionnaire, attestations, read side (branch `codex/compliance-c3a`)

**State:** implemented and validated locally; review-ready. Stacked on `codex/compliance-c3-rebased` (PR 32, the C3 plan), so the PR diff is C3a only. Retarget to `main` once PR 32 merges. **Not released.** Migration `20261017130000_compliance_attestations.sql` (additive; 31 migrations in total). No frontend, reminders or incidents (C3b and C3c).

### Changed behaviour

- **Questionnaire** `backend/app/compliance/questionnaires/ndpa_gaid_v1.json`: the 20 questions in plan section 2. Validated at import (`compliance/questionnaire.py`), so an invalid file stops the API. The validator checks, in both directions:
  - each `evidences` key is a register requirement that takes customer answers, in the question's group;
  - each applicability target is a conditional requirement whose `applicability_question` is that question;
  - every customer-answered requirement has a question, and every conditional requirement has a deciding question;
  - `show_if` names an earlier question; `evidence_on` only maps answers the question can take.
- **Truth table** `compliance/attestations.py` (pure): yes/no/date answers map to present/gap through each question's `evidence_on`; not sure, unanswered and hidden follow-ups are awaiting input; an expired answer is awaiting input (`answer_expired`) and never present; a not-applicable answer leaves the requirement out of the denominator with its reason. Several questions can evidence one requirement (training, DPIA, registration), and any gap beats awaiting input, which beats present.
- **DPO contact** (mixed sources): present if the answer or C2a's observation is present; the other source's gap is still listed beside it. Every requirement returns a `sources` list, so no label is shared. Customer-only requirements carry `customer_attested` only (tested).
- **Store** `compliance/attestation_store.py`: one write transaction per answer. It takes a per-(organization, question) advisory lock, reads `clock_timestamp()` after the lock (so `attested_at` orders the supersede chain), checks the owner is a member (`FOR SHARE`), supersedes the current answer, inserts the new one and writes `audit_log` in the same transaction. Answer text and notes stay out of the audit metadata.
- **API** (all tenant-scoped through `get_current_org`):
  - `GET /api/v1/compliance/questionnaire`: any member; Growth only (D1).
  - `POST /api/v1/compliance/attestations`: owner or admin only; 422 for an owner outside the organization, a bad answer or link; 409 if the current answer changed mid-write.
  - `GET /api/v1/compliance/attestations/{question_key}`: history, newest first, marking superseded rows; any member; Growth only.
- **Status read path** (`status.py`): the answers join the context, and requirement views gain `answers`, `sources` and `headline_source`. The reason text for unanswered customer requirements changed from the C1 "later release" wording.
- **D11:** `organizations.display_timezone`, default `Africa/Lagos`, in this migration. Read-only in C3a; the owner-editable setting belongs to C3c.
- **D12–D15:** expiry is 12 months by default, capped at 24, and date questions expire from their date (Q6 +183 days, Q16 +365 days). Any member may own an answer. Not sure is awaiting input. Nothing is deleted: the app role has no DELETE, and a trigger allows a current answer to be superseded once and nothing else to change except the profile-deletion `SET NULL`.

### Decisions taken for Yusuf (defaults applied; please confirm or override)

| # | Decision | Default applied | Why |
|---|---|---|---|
| C3a-1 | Migration scope | D11's `display_timezone` column is in the attestations migration, so there's still one migration in C3a. Incidents and reminders get their own migration in C3b. | §4 says one migration, which C3a keeps. The column is additive and D11 wants the default on the org. |
| C3a-2 | Starter gating | The questionnaire and history reads are Growth only (403 on Starter). Writes are not gated. | Every question sits in a Growth-locked group, so reads are gated like the requirement detail. Writes follow the D1 rule that gating applies to reads. |
| C3a-3 | A1 = No and `annual_car` | Not changed: only `registered` is excluded by A1 = No. `annual_car` is excluded only by OHL, as the plan table says. | A non-major-importance org would still see `annual_car` as awaiting input. Literal plan; please confirm. |
| C3a-4 | A1 "major importance" evidence | Yes and no both count as present for `major_importance_status`. | "No" is a determined answer, not a gap, and it also excludes `registered`. |
| C3a-5 | Hidden follow-ups | A question whose `show_if` is not met is not shown, its old answer is ignored, and a POST to it returns 422. | Keeps stale answers from counting after the prerequisite changes. |
| C3a-6 | Owner name visibility | Members see the owner's name (profile full name) on answers. | Owners need to be identifiable; no email or ID is returned. |
| C3a-7 | Superseding guarantee | **Enforced in the database.** A deferred constraint trigger checks at commit that `superseded_by` names a newer answer to the same question in the same organization. The supersede-once trigger and the composite FK also apply. | Covers the cross-question, older-row and cycle cases. Tests fail the commit for each. |

### Validation (fresh owned loopback PostgreSQL 18.6 on `127.0.0.1:55439`, socket in `/tmp`, bootstrap script only: 31 migrations, restricted `cyphward_app`)

- **Release order:** the migration must be applied **before** the API that reads or writes these tables is deployed. The status read path now queries `compliance_attestations` on every overview, so an API deployed first would fail the overview for every organisation. This follows the §10 order (migration first, then the API).
- **New tests:**
  - `test_compliance_questionnaire.py`: **51**. Validator rejections, answer normalisation, expiry, the truth table cases, merge rules and labels, and an overview check against a fake store.
  - `test_compliance_attestations_postgres.py`: **26**. Atomic superseding; queued writers stamped in supersede order (a third session holds the lock); a current answer cannot point at another question or an older answer (commit fails); a failed audit write rolls the supersede back; two concurrent writers serialise to one current answer; append-only grants; supersede-once trigger; cross-tenant FK; the HTTPS and length checks; a cross-tenant or non-member owner is refused with nothing written; every write is audited without answer text; members get 403 and nothing is written; expiry is renewal due, never present; profile deletion clears the owner without changing the answer; tenant scope; Starter gating.
  - `test_compliance_claims.py`: **+1** (questionnaire file has no verdict language).
- **Full backend suite on the owned loopback DB: 863 passed, 16 skipped.**
- **Full backend suite without a database (the CI backend job): 765 passed, 114 skipped.**
- **CI PostgreSQL race list** (`ci.yml`, now includes `test_compliance_attestations_postgres.py`): **99 passed**.
- `git diff --check`: passed.
- Frontend: not changed; `npm run build` not re-run. No browser suite in this PR.

### Limitations

- No UI yet (C3c). The API returns the statuses and sources; the Compliance page is unchanged apart from the reason wording.
- No reminders (C3b), so an expired answer is not notified yet.
- The display timezone is stored and returned, but the owner setting that changes it is not built (C3c).

## C3b — incidents and expiry reminders (branch `codex/compliance-c3b`, stacked on `codex/compliance-c3a`)

**State:** implemented and validated locally. Not released. No production access.

### Changed behaviour

- **Migration** `20261017150000_compliance_incidents_reminders.sql` (additive, after the C3a migration):
  - `compliance_incidents`: title ≤ 200, severity and status checks, `detected_at`, `became_aware_at`, `notified_commission_at`, `notified_subjects_at`, notes ≤ 4000, `created_by`, timestamps, and the plan's sanity check (`became_aware_at >= detected_at - 30 days`).
  - `compliance_reminders`: primary key `(attestation_id, threshold_days)`, `sent_at`, cascade with the answer.
  - RLS like the other app tables. Grants for `cyphward_app`: incidents SELECT, INSERT and UPDATE of `(status, notified_commission_at, notified_subjects_at, notes, severity, updated_at)` only, **no DELETE** (D15); reminders SELECT, INSERT.
- **Incidents API** (`api/compliance.py`, `compliance/incidents.py`): `GET/POST /api/v1/compliance/incidents`, `PATCH /api/v1/compliance/incidents/{id}`.
  - Owner/admin write, members read, Growth gate on every endpoint, tenant scoped (another organisation's id is a 404).
  - Every write is audited in the same transaction. The audit metadata holds field names and values for status, severity and notified times, never the title or notes text.
  - Responses carry `deadline_at` (= `became_aware_at + 72 h`, UTC), `hours_remaining`, `overdue`, `notified_late` and `commission_state` (`pending`, `overdue`, `notified_on_time`, `notified_late`), plus a `local` block in the organisation's display zone. Exactly 72 h is still pending; notified at or before the deadline is never overdue; notified after is `notified_late`, not overdue.
  - A time sent without an offset is read as wall-clock time in the organisation's display zone and stored in UTC. A time the zone skipped or repeats at a clock change is refused with a request for the UTC offset. Future times and notifications before awareness are refused.
  - The list response also carries the plain checklist and the "not legal advice" line.
- **Reminders** (`compliance/reminders.py`): job `compliance_reminders` under the existing atomic `cron_runs` claim, started by the in-process scheduler (07:00 UTC, with catch-up) and by an Inngest cron, which share the claim.
  - Finds current, unexpired answers inside 30 or 7 days with no reminder row for the smallest threshold they are inside (5 days left is a 7-day reminder only). `not_sure` answers are skipped.
  - Per answer: the reminder row and the in-app notification in one transaction, with the claim checked `FOR SHARE` in it; the emails after. The claim is re-checked before every email.
  - Email goes to the answer's owner and the organisation's owners/admins, through the mailer (`alerts` sender). It names the requirement, the expiry date (in the organisation's zone) and a link, and has no answer text, notes or evidence link.

### Decisions taken for Yusuf (defaults applied; please confirm or override)

| # | Decision | Default applied | Why |
|---|---|---|---|
| C3b-1 | Starter gating of incident writes | Incident reads **and writes** return 403 on Starter. | The task asks for the same Growth gate as the compliance API. C3a-2 left attestation writes ungated, so this differs; a Starter organisation cannot log a breach here. Easy to loosen to read-only gating if you prefer. |
| C3b-2 | Reminder timing | 07:00 UTC, one hour after the scan sweep, with its own claim name `compliance_reminders`. | Keeps the scan scheduler's loop and tests untouched. |
| C3b-3 | Both thresholds due at once | Send only the smaller threshold. | An answer first seen with 5 days left would otherwise get two emails in one run. |
| C3b-4 | A crash after the reminder commit | The email is lost, never doubled. | The plan says the row comes first so a retry cannot double-send. The in-app notification is in the same transaction as the row. |
| C3b-5 | Notified-late wording | `notified_late` is not `overdue`. `overdue` means not notified and past the deadline; a closed incident that was never notified stays overdue. | The deadline state follows what the organisation recorded; nothing is inferred about whether notification was required. |
| C3b-6 | Time entered without an offset | Read in the organisation's zone; ambiguous or skipped clock-change times are refused. | Avoids guessing a deadline that is legally sensitive. |
| C3b-7 | Notified times | Cannot precede `became_aware_at` or lie in the future (5 minutes of clock skew allowed). They can be cleared to null to correct an entry (audited). | Catches typos; keeps a correction path since the app cannot delete. |

### Validation (fresh owned loopback PostgreSQL on `127.0.0.1:55441`, bootstrap script only: 32 migrations, restricted `cyphward_app`)

- **New tests:**
  - `test_compliance_incidents.py`: **19** (no database). 72-hour edges (exactly 72 h, one minute either side, notified before, at and after the deadline), clock-change arithmetic, Lagos near midnight, skipped and repeated local times, validation, banned-phrase checks over the checklist, disclaimer, reminder and email copy, and the reminders wake time.
  - `test_compliance_incidents_postgres.py`: **24**. No DELETE and column-limited UPDATE grants; reminders insert-only; schema checks; members cannot write; Starter gate; cross-tenant list and PATCH; immutable fields refused; every write audited without notes or title; a failed audit write rolls the incident back; deadline over the API; Lagos and New York storage and display; thresholds 30/7; recipients and no answer content; retry cannot double-send; mail failure loses but never doubles; superseded and expired answers; stale claim cannot write or send; claim lost between the reminder and the email sends nothing; a held claim makes a second runner do nothing. Emails are stubbed.
- **Full backend suite on the owned loopback DB: 907 passed, 16 skipped.**
- **Full backend suite without a database: 784 passed, 139 skipped.**
- **CI PostgreSQL race list** (`ci.yml`, now includes `test_compliance_incidents_postgres.py`): **124 passed** (2 of 3 runs; the third hit the second known flaky test, below).
- **Review fix (reminder recipients):** the recipient query emailed the answer's owner without checking they are still a member, so a person who had left the organisation would still get its reminders. It now selects current members only (the owner if still a member, plus the owners and admins). New test `test_a_former_member_who_owns_an_answer_is_not_emailed` failed before the fix.
- `git diff --check`: passed. Frontend not changed.

### Limitations

- No UI (C3c). The incident form, countdown and the owner setting for the display zone are still to build.
- The Inngest platform is not wired in production (see `scheduler.py`), so the in-process loop is what runs the job.
- Release order: apply the migration before the API; the job fails (and is retried) if the tables are missing.
- Nothing deployed; the day-after `cron_runs` check in the C3 plan §10 still needs the founder's OK.
- An answer to a follow-up question that is now hidden (C3a-5) still gets reminders, because it was never superseded. Not filtered here.

## Second known flaky test (to fix properly later)

- **`backend/tests/test_scan_execution_postgres.py::test_unverified_queued_jobs_do_not_starve_local_recovery`.** It failed in 1 of 3 runs of the CI PostgreSQL list on this machine (and in two earlier full-suite runs), and passed 12 of 12 when run alone. Same cause as the first flaky test: it wraps the local pipeline in a **5 s** `asyncio.wait_for`, and `no_external` stubs discovery but not DNS or the HTTP probes, so the pipeline does real lookups for synthetic hosts and its time depends on the resolver and the machine's load.
- **Proper fix:** stub `resolve_host_dns` and the HTTP probe in `no_external` (check the other tests that use it first), then keep a tight bound.

## C3c — frontend (stacked on C3b, PR base `codex/compliance-c3b`)

- `/comply` now has three tabs: **Readiness** (default, unchanged), **Answer questions** and **Incidents**. New code: `frontend/src/pages/compliance/{Questionnaire,Incidents,shared}.tsx`, typed calls in `lib/api.ts` (all with `throwOnError` so 403/409/422 keep their status).
- **Answer questions:** applicability questions first, then one register group at a time. Follow-ups render only when the API says `shown`. The questionnaire is refetched after each save. Owner picker is the organisation's members (`GET /members`) and defaults to the viewer. Expiry is a preset list capped at 24 months (the longest option sends 729 days, inside the API's 730-day cap); date answers show "renews N days after the date" and send no expiry. Evidence link is https only, notes are capped at 1000 characters, and digit runs in text answers are refused before sending. Each attested requirement shows "You told us … on … (owner …, renews …)" labelled customer attested; expired answers read "renewal due"; an **Excluded** section lists not-applicable requirements with their reasons.
- **Incidents:** severity and status, a live hours-and-minutes countdown that ticks from the API's `deadline_at`, a red **Overdue** badge, "Notified late", create and edit forms, the six-step checklist and the not-legal-advice disclaimer. Times typed in the form are sent as typed (no offset) and read by the API in the organisation's zone, with the zone shown beside each field. Edit sends only changed fields, `null` to clear, and shows title and awareness times read-only.
- **Roles:** members get no form controls or write buttons. **Starter:** 403s on questionnaire and incidents show the Growth-plan upgrade panel in the tab, not an error.
- **Times:** shown in `display_timezone` through `Intl` (incident times from the API's `local` block), never the browser's zone.
- `backend/tests/test_compliance_claims.py` now also scans the new `pages/compliance/*.tsx` copy for banned phrases.

### Decisions for Yusuf (C3c)

| # | Decision | Default applied |
|---|---|---|
| C3c-1 | Owner setting for `organizations.display_timezone` (D11 says "editable by owners in Settings") | **Not built.** No API endpoint updates it (checked `backend/app/api`), and the task's backend contract lists none. Organisations stay on the Africa/Lagos default until an endpoint and a Settings control are added. Suggest a small follow-up PR. |
| C3c-2 | Zone on the Readiness tab for Starter organisations | The questionnaire (which carries the zone) is gated, so Starter falls back to Africa/Lagos for the dates there. |
| C3c-3 | Expiry control | Presets (3, 6, 12 default, 18, 24 months), not a free date picker. Avoids the 730-day cap rejecting the last days of "24 months". |
| C3c-4 | Questionnaire saves | Per question, not one batch, because follow-up visibility is decided server-side from saved answers. |

### Validation

- `npm run build` (tsc + vite + prerender): passed.
- `npm run test:compliance-ui`: passed at 1440/390/320. It now covers the questionnaire flow (applicability first, hidden follow-up appears after saving, owner picker, https-only link, 24-month expiry inside 730 days, date answers without expiry, digit refusal), told-us lines and the Excluded section, incidents (overdue, notified late, countdown, live tick to Overdue, create with naive times, PATCH with only changes and null), the checklist and disclaimer, members read-only (no form controls, no writes), the Starter gate, and no horizontal overflow including with forms open. The browser runs in Asia/Tokyo and the mock organisation in America/New_York, so a viewer-zone bug would fail.
- `test:scans-ui`, `test:score-ui`, `test:onboarding-ui`: passed. `test_compliance_claims.py`: 8 passed.

## Tiered Nuclei (branch `codex/tiered-nuclei`)

- **Daily tier:** critical + high, 20 requests/s, 1,500 s budget.
- **Weekly tier:** full safe set (critical, high, medium, low), 25 requests/s, 3,600 s budget.
- **Core chooses the tier at claim time** (`backend/app/core/nuclei_tier.py`). A domain gets a weekly run when no weekly run has been *attempted* for it in the last 7 days (a weekly Nuclei observation recorded by the worker); every other scan is daily. The claim carries `nuclei_tier`, and a weekly job also carries longer stage and recon timeouts (stage at least 3,600 s; recon at least 3,600 + 900 s). Older workers ignore the new field and keep their own default.
- **Operator override:** `SCANNER_NUCLEI_TIER` on the worker pins a tier and wins over the job.
- **Fair share:** the budget is split equally between hosts, cut from the *smaller* of the tier budget and the stage time really left. A host that never starts is recorded as `omitted` (`budget_exhausted`, process status `not_reached`), not failed. A host the stage deadline interrupts mid-run stays failed (`recon_stage_deadline`), as before.
- **Rate:** the tier rate now reaches the Nuclei command (it was ignored by `run_nuclei`). Legacy callers without a tier keep the old behaviour.
- **Tests:**
  - `test_nuclei_tiers.py`, 10 tests (tier defaults, unknown tier, daily and weekly severities and rates, equal shares, unreached hosts not assessed, rate flag once, weekly timeouts, job field default, share cut from stage time left);
  - `test_nuclei_tier_postgres.py`, 8 tests on the migrated database (weekly when none in 7 days, daily after one, weekly again after 8 days, daily runs don't count, other domain and other organisation don't count, and the claim itself returns the tier and timeouts).
- **Validation:** owned loopback PostgreSQL (`127.0.0.1:55432`, bootstrap run). Full backend suite **803 passed, 16 skipped**. CI PostgreSQL list **81 passed**.

## Decisions for Yusuf (tiered Nuclei)

1. **Daily scans no longer run medium and low templates.** Weekly covers them: the first scan of a domain after release is weekly, then one per 7 days.
2. **"Attempted", not "completed", counts as a weekly run.** This stops a host set that cannot fit the budget from making every scan a one-hour weekly scan. The cost is that a partial weekly run is not retried until the next week; its coverage is recorded in the evidence.
3. **Release order:** deploy the API first (older workers ignore the new field), then the worker. Until the new worker runs, scans stay on the old behaviour.
4. **Estimates:** daily about 19 min for five hosts at 20 req/s; weekly about 50 min at 25 req/s. Confirm with one real scan after release.

## Nuclei verified resolution (branch `codex/nuclei-verified-resolution`, stacked on tiered Nuclei)

- **Before:** a Nuclei finding could never resolve by itself. The scan-time rule kept absence "unknown", and the on-demand "verify fix" returned "exact-template completion was not proven", so a fixed CVE stayed open until someone resolved it by hand.
- **Rule now:** a Nuclei finding resolves in a scan only when the worker reran its **exact template on that host in that scan** and Nuclei left a **non-match receipt**, for a template that sends **a single request**.
  - At claim, Core lists up to 20 open Nuclei findings of the domain (`nuclei_verify`). The worker reruns each exact template (rate-limited, same safety exclusions) and posts `verification.clean` / `verification.unverified` with the Nuclei observation. `finalize_scan` resolves only the `(host, template)` pairs in `clean`. Older workers ignore the field, so nothing resolves until the new worker runs.
  - The rerun now passes `-matcher-status`. The receipt is Nuclei's own record that the template ran against the host and did not match.
- **Measured, and why only single-request templates:** with Nuclei 3.11.1 a two-request template printed **one** non-match record, for its last request. A receipt therefore proves a single-request template completely and a multi-request one only partly. Multi-request templates, and templates whose request count cannot be read (payloads, fuzzing, flows, non-HTTP), are never proven and stay open.
- **A receipt only counts if the answer came from the target.** A non-match record is proof only when it has no `error` field, a real HTTP response, a status that is not 401/403/429/5xx, and is not a WAF or bot-protection challenge (the same detection the privacy probe uses: Cloudflare and Vercel headers and challenge pages, including a challenge served with a 200). Otherwise the finding is reported as `not_assessed` with the detail (`bad_status`, `blocked`, `no_response`) and stays open. A mix of good and bad receipts for one template does not count.
- **Coverage of the safe set (pinned v10.4.9, after the safety exclusions):** provable templates are critical 645 of 981 (66%), high 1,220 of 1,666 (73%), medium 1,115 of 1,585 (70%), low 271 of 437 (62%).
- **Tests:** `test_nuclei_verification.py`, 31 tests (receipt parsing, request counting, the rerun verdict, the worker's reasons, finalize resolving only proven pairs, and fixture tests: a 200 non-match receipt resolves a single-request finding; a 403 Cloudflare challenge, a Vercel 200 checkpoint, 401/403/429/5xx and a missing response leave it open as `not_assessed`; the mutation checks "always resolve", "never resolve" and "every receipt counts" all fail them). `test_nuclei_tier_postgres.py` gains 5 tests on the migrated database: which findings are targets (open, Nuclei, template present, this domain and organisation, capped at 20) and the claim payload.
- **Validation:** owned loopback PostgreSQL. Full backend suite **839 passed, 16 skipped**; CI PostgreSQL list **86 passed**.

### Decisions for Yusuf (verified resolution)

1. **About 30% of templates are not provable** (multi-request or uncountable). Their findings stay open until resolved by hand. A later option is a per-template rule for multi-request templates; it needs a different kind of proof, so it is not guessed at here.
2. **Verification runs on every scan, daily and weekly.** It is cheap (at most 20 reruns, each one template). Raise or lower `VERIFY_LIMIT` if needed.
3. **A resolved finding that comes back** is reopened by the existing rules when a scan matches it again.

## Packet 04 — assessment snapshots and report integrity (branch `track-b/packet-04-snapshots`)

**State:** implemented and validated locally; review-ready. Not released. Migration `20261018100000_assessment_snapshots.sql` must be applied before the API.

- **Scope decision:** snapshots are **organisation-scoped with a per-domain section** (the score and readiness belong to the organisation since scoring v3). A report's `domain_id` is only a *focus domain*, must be a verified domain of the organisation, and the report says plainly that the score is organisation-wide.
- **Frozen content (schema v1, `backend/app/snapshots/builder.py`):** scope (organisation, verified domains, assets), dates (generated, earliest/latest observation, assessment completed), per-domain latest assessment and coverage summary, open findings as at that moment (no raw evidence blobs), scoring (model `cyphward-risk-v3`, score, grade, counts, factors), provenance (check set, coverage version, register version, per-domain Nuclei tool and template-set versions where recorded, otherwise absent, never invented), and the compliance state: register version, every requirement with status, reason, source label and per-domain evidence timestamps, readiness as **counts** (D5; no percentage anywhere), and current attestations (question, value, date, owner, answered and expiry dates, evidence link; never notes or free text).
- **Storage:** `assessment_snapshots` (JSONB `content`, `content_sha256` of the canonical text, `schema_version`, per-organisation `seq`, optional `request_key`). RLS like the other tables; `cyphward_app` has SELECT and INSERT only; a guard trigger refuses any change except the profile-deletion action clearing `created_by`. `reports` gains `snapshot_id` (composite same-tenant FK) and `report_version`; a trigger stops a snapshot-linked report's html, summary, title and snapshot from changing (domain and profile deletion still null their columns).
- **Generation:** one transaction, a per-organisation advisory lock held from before the state is read until the insert commits, `seq` taken under the lock, an audit row, and (for a report) the report row in the same transaction, so a snapshot and its report appear together or not at all. The read helpers use their own connections, so the state is fenced (a hash of scan, finding, evidence, attestation and domain markers is compared before and after the read; it re-reads up to 3 times, then returns 409 "try again"). A retried `request_key` returns the first snapshot/report.
- **API:** `GET/POST /api/v1/snapshots`, `GET /api/v1/snapshots/{id}` (members read; owners/admins create; other organisations' ids are 404; the read re-verifies the hash and reports `intact`). `POST /api/v1/reports` now freezes a snapshot and renders from it; `GET /reports` and `GET /reports/{id}` add `integrity` (`snapshot` or `legacy`), a label, `snapshot_id` and `report_version`. Starter reads the readiness counts and the security group only (D1); the full content is stored regardless.
- **Legacy:** reports without a snapshot are labelled "Legacy report … evidence cannot be verified" (Reports page shows "LEGACY · LIMITED EVIDENCE" or "FROZEN SNAPSHOT"). No backfill.
- **Tests:** `test_snapshots_postgres.py` **23 passed** (content and hash round trip through the app role, attestation free text excluded, immutability after a new scan/finding/resolution/attestation, no UPDATE/DELETE for the app role, owner-level trigger refusal, report rendered from and referencing its snapshot, legacy labelling without backfill, request-key idempotency incl. concurrent, cross-tenant snapshot/report ids and cross-tenant FK, domain mismatch (other org 404, unverified 422), RBAC, Starter filtering, 6 concurrent generations give seq 1..6, failed report insert leaves no snapshot, unassessed organisation, domain delete, profile delete, organisation delete cascade, banned phrases in content and html). Existing mock-based report tests were adapted (`conftest.py` fake layer and `test_declared_scope_copy.py` patch the snapshot builder). Full backend suite on the local database: **995 passed, 16 skipped**. CI PostgreSQL list: **164 passed**. Frontend `npm run build`: passed.
- **Local database note:** the brief's port 55441 was already in use by another session's cluster; this work used `127.0.0.1:55461` (own cluster in `/tmp/pg-b`).

### Decisions for Yusuf (Packet 04)

1. **Organisation-scoped snapshots** with a per-domain section (the plan states no default beyond "define scope first"; this follows scoring v3).
2. **Retention:** a snapshot is kept for the life of the organisation and is removed with it (cascade). There is **no automatic purge**: the app role has no DELETE by design. A fixed term (for example 24 months) needs an owner-run purge with its own privileges; say if you want it.
3. **Domain deletion keeps snapshots** (and reports, as before). A snapshot holds domain names as text, so it still names a deleted domain. Erasure of that history is by deleting the organisation.
4. **`/reports/send-email` still builds from live data** (it is a message, not an issued report). It is unchanged and is not an immutable record.
5. **Snapshots are available on every plan** (a report needs one); compliance detail is filtered for Starter on read.
6. **Quota (founder-agreed, release run):** a snapshot is one unit of the plan's `monthly_reports` quota. Usage = reports + snapshots that no report belongs to (and, with C4, packs). The charge happens inside the snapshot write under the per-organisation lock, so two concurrent requests cannot both take the last unit; a retried `request_key` is not charged twice; a report and its own snapshot count once.
7. **Retention setting (founder-agreed):** `organizations.evidence_retention_months`, default **36 (3 years)**, owner-set between 12 and 120 months (`PUT /api/v1/snapshots/retention`, audited). Each snapshot shows `retain_until`. It is a recorded policy, not a purge: the app role has no DELETE, so removal after the period is an operator-run step.
8. **Owner names stay in issued snapshots and packs (founder-agreed).** A name recorded at the time of an answer is part of the issued record; erasure of that history is by deleting the organisation. The retention text says so.

### Limitations

- A Nuclei tool version appears only where the worker recorded it in the scan results; older scans show none.
- The fence reduces, but cannot remove, a read of a state that changes mid-way; after 3 attempts the request fails with 409 instead of freezing a mixed state.
