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

### Independent review before release (Packet 04, release run 18 Oct 2026)

- **Reviewer:** a fresh subagent that did not write the code. Fable was requested first and was **not available** (it needs usage credits), so the review ran on **Opus**.
- **Round 1: REJECT.** One blocker:
  - **Connection-pool starvation.** A snapshot write held one pooled connection and the per-organisation lock, then checked out more connections for its reads, with no bound on the lock wait. With roughly 20 concurrent requests (one admin retrying in a loop is enough) the pool of 20 would fill with waiters, the lock holder could not get its second connection, and every other tenant's requests would time out. Quota did not help because it ran after the lock. **Fix:** at most 3 builds run per process (waiters hold nothing and give up after 6 s with a 503 and `Retry-After`), and the advisory-lock wait is bounded at 8 s. Tests: a busy slot gives a 503 and writes nothing; a held lock is waited for briefly; with 8 simultaneous builds at most 3 ran at once (the test fails if the cap is removed).
  - **Should-fix, all done:** the Reports page showed "FROZEN SNAPSHOT" for any non-legacy value (now only when `integrity` is `snapshot`; otherwise "INTEGRITY NOT CONFIRMED"); the retention note, the owner-name disclosure and an owner-only retention control now appear on the Reports page; the Reports page now sends a `request_key` per click so a double-click is not charged twice; a malformed snapshot id is a clean 404 (the broad `except` that hid database errors is gone); `total` is the real count; added tests for the 409 path, a report retried at the quota limit, owner names kept in issued snapshots, `retain_until` following the setting, every guarded report column, and the banned-phrase list extended (certification, adequate, adequacy, guarantee, meets the requirement) over the retention text, labels and list responses.
  - **Notes, accepted and recorded:** storage per snapshot is bounded by the monthly reports quota, not by size; `reports_snapshot_fk` has no ON DELETE action, so an operator purge after the retention period must delete a snapshot's reports first; the read fence does not cover `assets`, the organisation name or finding edits that do not bump `updated_at`.
- **Production database role:** the API connects as `cyphward_app` (checked, username only), so the append-only grants apply in production.
- **Round 2: APPROVE** (same reviewer, on `a047a2d`). The pool arithmetic holds: a build holds the lock connection and checks out one more at a time, so at most 3 builds x 2 = 6 of the 20 pooled connections per process; the `/reports` path adds none; `SET LOCAL lock_timeout` is confined to the transaction and a timeout rolls back cleanly. **Accepted should-fix, recorded:** a request that is waiting holds no connection but does occupy a threadpool thread for up to 6 s (plus up to 8 s on the organisation lock), and one organisation can occupy all 3 build slots (other organisations then get a 503 for a few seconds). It is bounded and needs an authenticated owner/admin. A later fix is `pg_try_advisory_xact_lock` with an immediate 503, a per-organisation slot, and a rate limit on these endpoints. The 503 text says "another snapshot" even if the timeout was a deletion in progress.
- **Rehearsal:** a fresh database built from `main`'s migrations (33), then this migration applied with the production apply tool: no existing table changed, one new table, 42 snapshot tests pass on that database.

### Limitations

- A Nuclei tool version appears only where the worker recorded it in the scan results; older scans show none.
- The fence reduces, but cannot remove, a read of a state that changes mid-way; after 3 attempts the request fails with 409 instead of freezing a mixed state.

## C4 — NDPA readiness evidence pack and DPO six-monthly section (branch `track-b/c4-evidence-pack`, stacked on Packet 04)

**State:** implemented and validated locally; review-ready. Not released. Migration `20261018120000_evidence_packs.sql` (after the Packet 04 migration). Adds `reportlab` to `requirements.txt`.

- **Pack (`backend/app/packs/`):** one neutral document (`document.py`) rendered twice: HTML (`render.to_html`) and PDF (`render.to_pdf`, reportlab, pure Python, Helvetica, uncompressed, `invariant=1`). Built only from a snapshot's frozen content: scope, dates, snapshot id and hash, register version, readiness as counts (D5), every requirement with status, source labels and evidence references (observation time and scan, linked finding titles, customer answer owner/answered/expiry/https link), prioritised gaps (gap by worst linked finding severity, then not assessed, then awaiting input) with the register's suggested next step, the register `DISCLAIMER`, and "not a Compliance Audit Return … a DPCO may use this pack as supporting evidence".
- **D4 marker:** every clause with `clause_verified: false` reads "… · reference pending review" in the table (HTML and PDF) and a summary line counts them. All 29 are unverified today.
- **All not assessed:** states "N of M … have evidence" with zero, and "Nothing has been recorded as evidence yet … says nothing either way about your obligations".
- **Immutable:** `evidence_packs` stores `issued_at`, the snapshot id, the HTML and PDF bytes and their sha256, and the frozen DPO data. `cyphward_app` has SELECT and INSERT only; a guard trigger refuses any change except the profile-deletion action clearing `issued_by`. Downloads serve the stored bytes (ETag = sha256). A second issue makes a new row; it can reuse a snapshot or freeze a new one. Issue refuses a snapshot whose content no longer matches its hash (409).
- **DPO section (GAID Art. 13 and register clause label):** window = 183 days ending at the snapshot's own time (so it is fixed by the snapshot, not the issue time). Counts: scans run and by outcome, coverage of completed scans (complete/partial/not assessed/not recorded), findings opened and resolved by severity, open at the snapshot, incidents logged by status and severity and how many had the Commission notified (no titles or notes), and the notices and consent observations from the snapshot. Issued with the pack (`include_dpo`, default on) or on its own (`kind: dpo_section`). States plainly that it is not a Compliance Audit Return.
- **Reminder:** the existing daily `compliance_reminders` job (same `cron_runs` claim) now also sends a once-per-half-year reminder (`dpo_reminders`, key `YYYY-H1/H2`) to owners and admins of Growth organisations that have a verified domain and have not issued a pack this half-year. In-app notification type `compliance_report_due`, plus email; the reminder row and notification commit together before any email.
- **API (Growth only; Starter 403 on reads and writes):** `GET/POST /api/v1/packs`, `GET /api/v1/packs/{id}`, `/{id}/html`, `/{id}/pdf`. Members list and download; owners/admins issue; `request_key` makes a retry return the first pack. Other organisations' pack and snapshot ids are 404.
- **Frontend:** a Packs tab on /comply (issue both kinds, list, download PDF/HTML through an authenticated Blob fetch). Members see the list read-only; Starter sees the existing Growth gate.
- **Tests:** `test_packs_postgres.py` **21 passed** (content, pending markers in HTML and PDF text, honest all-not-assessed, non-Latin organisation name, byte-identical re-download after later scans and answers, new pack on re-issue, append-only grants and trigger, altered snapshot refused, cross-tenant and cross-tenant FK, RBAC, Starter gate, concurrent issue by key and distinct, DPO counts with no incident title or note, standalone DPO and lean pack, window fixed by the snapshot, banned phrases over HTML and PDF-extracted text, organisation delete cascade, reminders per half-year and none after an issued pack). Full backend suite on the local database **1016 passed, 16 skipped**. CI PostgreSQL list **185 passed**. Frontend: `npm run build` passed; `test:compliance-ui` passed (now covers Packs at desktop/390/320, member read-only, Starter gate, no verdict language); `test:scans-ui`, `test:score-ui`, `test:onboarding-ui` passed.

### Decisions for Yusuf (C4)

1. **Packs are Growth only** (D1), including downloads.
2. **PDF text:** Helvetica covers Latin-1, so other characters are folded (an organisation called "Ọ̀ṣun" prints as "Osun" in the PDF; the HTML keeps it). A bundled Unicode font would fix that at the cost of a binary in the repo.
3. **Reminder cadence:** calendar half-years (January and July), first run after deploy reminds Growth organisations once for 2026-H2.
4. **DPO window** is 183 days ending at the snapshot time. Incident status counts are as recorded at issue time.
5. **The register's DPO clause** is "GAID 2025 Arts. 11–13; NDPA 2023 s.32" (unverified); the pack prints the register's wording, not a hand-written Art. 13.
6. **Before sending any pack to customers** the founder or a partner DPCO must review the register (D4); until then every reference shows "reference pending review".

### Limitations
- Packs and snapshots have no automatic purge (see Packet 04 decision 2).
- The PDF is plain tables, not a designed layout.

## Release run, 18 Oct 2026 (Packet 04, then C4, then C5)

### Packet 04 (#38): released and production-verified

- **Gates:** founder-agreed changes added (quota, 36-month retention setting, owner names kept); independent review APPROVE in round 2 (round 1 REJECT, fixed); CI green on `792580a`; full suite on the owned loopback database 1014 passed / 16 skipped, CI PostgreSQL list 183 passed; migration rehearsed on a fresh database built from `main`'s 33 migrations (42 snapshot tests pass on it).
- **Backup:** `~/cyphward-release-backups/2026-10-18-release-pr38/full.dump.gpg`, AES-256, checksum of the decrypted dump verified (`b2bd6fb5…`), plaintext shredded.
- **Migration:** only `20261018100000_assessment_snapshots.sql` (sha256 `92be5ab8ed4f350d`, the same file that was rehearsed), applied as `postgres` in one transaction with `lock_timeout 5s` and `statement_timeout 60s`, recorded in `supabase_migrations.schema_migrations`. No existing table's row count changed; new table `assessment_snapshots`. Verified: row-level security on; `cyphward_app` has SELECT and INSERT only (UPDATE and DELETE refused); both guard triggers present; `reports.snapshot_id` and `report_version` added (the 5 existing reports stay legacy, `snapshot_id` null); `organizations.evidence_retention_months` default 36 on both organisations.
- **Merge:** `a7e9719f2bc6567176c215fdda62d552a7f1b63f` (previous main `e20c3cfdc137`); fork `main` synced; API deploy live at `a7e9719` at 00:29 UTC.
- **Post-checks passed:** `/health` healthy; `GET`/`POST /api/v1/snapshots`, `GET`/`PUT /api/v1/snapshots/retention`, `GET /api/v1/snapshots/{id}`, `GET`/`POST /api/v1/reports` all return 401 unauthenticated; `app.cyphward.com/comply` serves 200; the live Reports bundle contains the new label ("INTEGRITY NOT CONFIRMED") and the retention note.

### C4 (#40): changes made for release

- **Quota:** an evidence pack is one unit of `monthly_reports`. Usage = reports + packs + snapshots that neither a report nor a pack belongs to. A pack made from an existing snapshot takes over that snapshot's unit (no extra unit); a second pack from it is a new unit. A pack with a fresh snapshot uses exactly one unit, including the last one; a refused pack leaves nothing behind. The charge is made under the same per-organisation lock as snapshots (packs now take the `snapshot:` lock key), so a pack and a snapshot cannot both take the last unit.
- **Pool safety:** pack issuance uses the same bounded build slots and bounded lock wait as snapshots (`snapshots.build_slot()`); both give a 503 with `Retry-After`.
- **Retention:** pack summaries show `retain_until` (issued date plus the organisation's retention period) and the list carries the retention text, including the owner-name disclosure; the Packs screen shows both. Owner names recorded at answer time stay in issued packs (founder-agreed).
- **Migration:** `20261018120000_evidence_packs.sql` now sets `lock_timeout 5s` and `statement_timeout 60s` inside its transaction.
### Independent review before release (C4, release run 18 Oct 2026)

- **Reviewer:** a fresh subagent, different from the Packet 04 reviewer, that did not write the code. Opus (Fable was not available: it needs usage credits).
- **Round 1: REJECT.** Two blockers:
  1. **Orphan, charged snapshots.** With no `snapshot_id` the API created a snapshot (charged, committed on its own) and then issued the pack in a second transaction. Any failure in the second step (a busy slot, a lock timeout, a pool timeout, a render error) left a charged snapshot with no pack; N concurrent retries with one key froze N snapshots and charged N units. **Fix:** a pack with a fresh snapshot is now built inside the snapshot's own transaction (`store.issue_with_new_snapshot`, through `snapshots.create(on_insert=...)`): the snapshot, the pack and the quota charge commit together or not at all, under one lock, and a retry with the same key finds the first pack. A request key that already belongs to a snapshot without a pack is a 409. Tests: a render failure leaves 0 snapshots, 0 packs, 0 units; five concurrent requests with one key make exactly 1 snapshot, 1 pack and 1 unit; a busy slot leaves nothing; the key-clash cases.
  2. **PDF crash for large organisations.** A requirement's evidence references went into one table cell, and a PDF row cannot split across pages, so about 40 references raised a layout error and every retry used another unit. **Fix:** at most 8 references per cell (each at most 200 characters), then "and N more references, all of them in the snapshot this pack was made from", in the HTML and the PDF alike. Test: 600 linked findings render both documents. The test fails if the cap is removed.
  - **Should-fix, done:** the DPO counts are read when the pack is issued (the window is fixed by the snapshot), so two packs from one snapshot can differ; the document docstring said otherwise and the section now says so in plain words. A malformed pack or snapshot id is a 404 and a database error is no longer reported as "not found". The pack list shows the real total. The UI sends a request key per click. A request key reused for a different pack or kind is a 409. The six-monthly reminder is suppressed only by a pack that contains the DPO section.
  - **Notes, accepted:** pack storage grows with the monthly quota (no plan is unlimited), uncompressed PDFs; the claim-language scan of the HTML and PDF now uses the full banned list.

- **Round 2: APPROVE** (same reviewer, on `a149a6a`): both blockers fixed; atomicity, pool use (about 6 of 20 connections per process) and the harmless `SET LOCAL lock_timeout` re-checked. **Should-fix, done:** the reviewer rendered the capped cells and found 12 references of 280 characters could still overflow a PDF row (uppercase, wide or unbroken text). The cap is now 8 references of at most 200 characters, with a worst-case test (wide capitals, an unbroken string, long mixed text, 900 findings in every requirement) that fails at the old cap. **Notes, accepted and recorded:** the same request key sent at the same moment to the explicit-snapshot path and the fresh path can give a 500 (everything rolls back; only the status code is wrong); a retry racing the first request can return the earlier pack even if it asked for another kind; the per-organisation lock is held a little longer (the snapshot build, the DPO counts and the PDF), still bounded by the 8 s wait.
- **Rehearsal:** a fresh database built from `main`'s 34 migrations, then `20261018120000_evidence_packs.sql` (sha256 `58a254e4f2babfac`) applied with the production apply tool: no existing table changed, two new tables, 81 pack and snapshot tests pass on that database.
- **Tests added:** 10 in `test_packs_postgres.py` (quota boundary, takeover, retry, pack-vs-snapshot race, cross-organisation, busy slot and held lock, retention date and text, banned phrases) plus Packs assertions in the compliance browser suite. Mutation checks (pack not charged; usage ignoring packs) fail them.

## C5 — AI-drafted documents (branch `claude/priceless-borg-c5932c`, base `main`)

Four drafts (privacy policy, cookie notice, breach response plan, retention schedule) built from the organisation's own answers and observations, on a new **Documents** tab of `/comply`.

- **How a draft is made (`backend/app/compliance/documents.py`, `document_store.py`):**
  1. `build_inputs` turns the current questionnaire answers (only *usable* ones: shown, not expired, not "not sure"), the organisation's name, its verified domains and the latest consent observations (status only, never evidence details) into a list of facts, each `set` or `missing`.
  2. `build_template` writes the whole draft deterministically. A set name/domain becomes a `{{SLOT}}` token, a missing fact a visible `[MISSING: …]` placeholder. **The placeholder list is computed from the inputs**, stored with the draft, and re-checked against the final text.
  3. The AI provider may only reword that tokenised template (`AIProvider.draft_document`, default returns `None`; implemented in `CloudLLMProvider` through the existing `_call_llm` and the privacy sanitizer, which must leave the template unchanged or nothing is sent). It never sees a name, an email, a domain, a note or any free text. (Template wording can reveal a yes or no answer, for example "we do not store ..."; nothing identifying is in it.) **From the release review on, this path is OFF by default** (see below): nothing is sent to a model unless an operator sets `COMPLIANCE_DOCS_MODEL=on`.
  4. `validate_model_text` rejects output that changes, drops or repeats a token or placeholder, adds a digit, address or link, adds a capitalised word not in the template, adds markup, is out of length range, or hits the banned list. Two attempts, then the deterministic template is stored (`generator = template`, `fallback_reason` recorded). Provider errors and "no provider" also fall back.
  5. Code substitutes the customer's values afterwards, adds the header (`Draft — not legal advice`, version, UTC date) and the closing label, and runs the banned list and placeholder check on the finished text.
- **Observed signals** come only from the organisation's verified, non-revoked domains, as on the readiness page.
- **Evidence semantics:** a `no` answer is never written as a fact (it becomes a placeholder saying the customer reported it is not in place), except "no transfers outside Nigeria", which describes practice. Approval is recorded as `customer_attested` (approver, time, text hash, open placeholder count) and **does not touch the register, `status.py` or `compliance_evidence`**; a test compares `overview()` before and after approving all four. Approvals show only on the Documents tab and in `audit_log`.
- **Storage (migration `supabase/migrations/20261018200000_compliance_documents.sql`, additive):** `compliance_documents` (append-only versions, text must start with the label, `UNIQUE(org,kind,version)`), `compliance_document_approvals` (append-only, composite FK `(document_id, org_id)`, `UNIQUE(document_id)`, `source` CHECK = `customer_attested`), `compliance_document_quota` (per org per UTC day, `CHECK n <= 10`). RLS like the other tables. `cyphward_app`: SELECT + INSERT on the two document tables (no UPDATE/DELETE), SELECT + INSERT + `UPDATE(n)` on the quota. Rows go only with the organisation (cascade).
- **API (`/api/v1/compliance`):** `GET /documents`, `GET /documents/{id}`, `POST /documents/{kind}/generate` (owner/admin, 201; 429 at the cap), `POST /documents/{id}/approve` (owner/admin, latest version only, once; 409 otherwise). Members read; Starter gets 403 with the Growth-plan detail on all four. Other organisations' ids are 404. Both writes audit inside the same transaction (`compliance.document.generated`, `compliance.document.approved`) without document text.
- **Cap:** 10 generations per organisation per UTC day. The slot is reserved (conditional upsert, committed) **before** the model is called; no transaction is open during the call.
- **Frontend:** `pages/compliance/Documents.tsx`, calls in `lib/api.ts`, tab in `Compliance.tsx`. Status chips (not generated / draft / approved), "answers changed since this version" note, banner, highlighted placeholders, copy/download as text or Markdown, approve with a confirmation that says what approval does not mean, version history, read-only for members, Growth gate for Starter.
- **Tests (all with a stub AI provider, no network):**
  - `test_compliance_documents.py`, 42 tests: label/version/date on all four; placeholders from inputs; `no`, expired, not-sure and hidden answers; observed signals; retention schedule has no periods; banned phrases on every template/combination against the union of the existing banned lists; claim-bearing customer text is dropped; markup cleaning; each kind of invalid model output rejected (dropped/duplicated token, invented number, spelled-out number, month or weekday, reused digit, email, name, placeholder, banned phrases, markup); retry; provider errors.
  - `test_compliance_documents_postgres.py`, 23 tests on the migrated database: append-only grants, composite FK, source CHECK, label CHECK, quota CHECK; stored label/placeholders/audit without text; a new version never edits the old; a prompt-injection answer and notes never reach the prompt, and the DPO name is substituted after the model; unsafe model output blocked; failed audit write leaves no document; members cannot generate/approve; Starter gated on all endpoints; cross-tenant read/approve 404; approval workflow (latest only, once, history, audit); overview unchanged by approval; stale flag; cap (429, model not called); cascade on organisation delete; cookie-notice observations of revoked, unverified or deleted domains are ignored.
  - `test_compliance_claims.py` +1 (document copy); the page-copy scan already covers `pages/compliance/*.tsx`.
  - `check-compliance-page.mjs` extended: admin, member and Starter paths at 1440/390/320 (statuses, banner, highlighted placeholders, copy keeps the label, approve flow and wording, history, generate, no member writes, no overflow, no verdict language).
- **Validation (owned loopback PostgreSQL, port 55442, bootstrap run):** full backend suite **1038 passed, 16 skipped** (the skips are the opt-in `*_INTEGRATION` suites); CI PostgreSQL list (now including the new file) **164 passed**; `npm run build` passed; `npm run test:compliance-ui` passed at 1440/390/320. No other browser suite touches `/comply`.
- **Files:** `backend/app/compliance/{documents,document_store}.py`, `backend/app/api/compliance.py`, `backend/app/ai/{base,llm_provider}.py`, the migration, the two new test files and the edits above, `frontend/src/pages/compliance/Documents.tsx`, `frontend/src/pages/Compliance.tsx`, `frontend/src/lib/api.ts`, `frontend/scripts/check-compliance-page.mjs`, `.github/workflows/ci.yml`.
- **Compatibility:** additive migration; apply it before the API. The worker is untouched.
- **Limitations:**
  - The **retention schedule has no questionnaire input**: it is a table of placeholders (plus the DPO name and whether an erasure process exists). Nothing is invented. A later questionnaire version could collect categories and periods.
  - Many facts (address, DPO contact, purposes, lawful basis, cookie list, response lead) are not collected anywhere, so they are always placeholders. Cookie names from scans are not used.
  - Reworded text is checked structurally; the check cannot judge whether a sentence still says the same thing, which is why the model sees only the fixed template and cannot add facts, and why the draft carries the practitioner-review label.
  - The daily cap bounds cost per organisation but does not stop several requests already past the reservation from running together (at most the cap per day). No per-user limit.
  - Exports are the stored Markdown or a plain-text copy (heading marks removed). No PDF/Word.
  - **Model rewording is off by default.** The check on model output is a deny-list of patterns and cannot tell a faithful rewording from a paraphrased claim, an invented commitment, a flipped negation or a dropped sentence (the release reviewer demonstrated each). Enabling it needs a stronger check first (output words limited to the template's words plus connectives, negations preserved, one normaliser for every comparison).
  - Lowercase invented entities in reworded text (for example "we use google analytics") cannot be detected by the structural check; the model sees no such names, and the practitioner-review label stands.
  - Not yet run against a live model (stub only). Without `GEMINI_API_KEY`/`OPENAI_API_KEY` every draft uses the standard wording (`generator = template`).

### Independent review before release (C5, release run 18 Oct 2026)

- **Reviewer:** a fresh subagent that did not write the code. Opus (Fable was not available: it needs usage credits).
- **Round 1: REJECT.** Two blockers:
  1. **The model-output check was too weak.** It blocked only a short list of patterns. The reviewer ran the pure validator and showed it accepting: a paraphrased claim ("fulfils every legal obligation that applies to us"), an invented commitment ("we encrypt all personal data and never share it with third parties"), a flipped negation ("we do not store" turned into "we store"), a dropped sentence, and banned words disguised with zero-width characters, a Cyrillic letter, full-width letters or hyphens. The same gap let "Cert<zero-width>ified DPO" through as a DPO name. **Fix (the reviewer's recommendation for this release):** the model path is **off by default** and the stored draft is the deterministic, grounded template (which already meets every requirement); `COMPLIANCE_DOCS_MODEL=on` turns it on and it has a hard overall timeout. One normaliser (NFKC, invisible format characters removed, look-alike Cyrillic and Greek letters folded to Latin, each token checked with its hyphens and dots removed) now backs the banned-phrase check on model output, on customer values and on the final text; legitimate letters with diacritics in names are kept.
  2. **No timeouts in the migration file.** It now sets `lock_timeout 5s` and `statement_timeout 60s` inside its transaction, with a test.
  - **Should-fix, done:** an overall timeout on the model step (45 s); a bounded lock wait (8 s) on generate and approve, with a 503 and `Retry-After`; concurrent-generation, paraphrase and Unicode, model-timeout, held-lock and migration-timeout tests; mutation checks (model on by default; no folding) fail them.
  - **Notes:** the shared Gemini cool-down on the AI provider singleton could push other AI features to their fallback during a burst of drafts; it does not apply while the model path is off.
- **Round 2: APPROVE** (same reviewer, on `508901c`). With the flag off nothing can reach a provider (one caller of `draft_document`, inside the flag-on branch); the bypasses shown in round 1 are closed (zero-width, Cyrillic, full-width, hyphenation, soft hyphen) and the four composed templates and real Nigerian names (with diacritics, "Guaranty Trust Bank") still pass. **Notes, accepted and recorded:** a few disguises still pass in a customer's own name or domain field only (accented Latin letters, an Armenian look-alike, a hyphen-plus-space split), a low risk because the text appears only in that customer's own draft (a later hardening: strip combining marks inside the fold and join hyphen-plus-space splits); a name containing a banned stem (for example "Customer Satisfaction Ltd") becomes a bare `[MISSING: ...]` without a note saying why; enabling the model needs only one environment variable, so a startup warning or a second acknowledgement would make an accidental enable harder; a 503 on generate comes after the unit is reserved, so it uses one of the 10 daily drafts (bounded, rare).
- **Production flag:** `COMPLIANCE_DOCS_MODEL` is not set on the production API (checked, names only), so the model path is off.
- **Rehearsal:** a fresh database built from `main`'s 35 migrations, then `20261018200000_compliance_documents.sql` (sha256 `0313c4f7af2cc3d1`) applied with the production apply tool: no existing table changed, three new tables, 82 document tests pass on that database.
- **Decision for Yusuf:** drafts are the standard, grounded wording for now (the screen says "standard wording"). Say if you want the AI rewording back; it should wait for the allow-list check described above.

### Decisions for Yusuf (C5)

| # | Decision | Default applied |
|---|---|---|
| C5-1 | What the model may do | Reword a fixed, tokenised template only; it never sees answers, names, domains or notes. Customer text is substituted by code afterwards. |
| C5-2 | Output that fails a check | Two attempts, then the deterministic template. Never edited or "repaired". |
| C5-3 | Customer text containing a claim (for example a DPO entered as "Certified DPO") | Treated as missing and shown as a placeholder, not used. Same for an organisation name that trips the banned list. |
| C5-4 | Approving a draft that still has placeholders | Allowed; the approval records how many were open and the screen says so. Blocking it would make the retention schedule unapprovable. |
| C5-5 | Which version can be approved | The latest only, once. A newer version shows as draft again; older approvals stay in the history. |
| C5-6 | Daily cap | 10 generations per organisation per UTC day (a failed or fallback draft counts, because the slot is reserved before the model call). |
| C5-7 | Banned list for generated text | Union of the existing test lists plus guarantee, adequate/adequacy, "meets the requirements", "legally sufficient", `certif*`, "complies", "in compliance". Substring match, like the existing tests, so it is deliberately strict. |
| C5-8 | Draft text includes a reviewer section ("Inputs behind this draft") | Yes, listing each input and its source (your answer / observed / profile), to be removed before publishing. No answer text beyond what is in the body. |

### C4 (#40): released and production-verified

- **Gates:** founder-agreed changes added (quota, retention date on packs, owner names kept); independent review APPROVE in round 2 and confirmed again on the final head (round 1 REJECT, fixed); CI green on `a0f56bd`; full suite on the owned loopback database 1054 passed / 16 skipped, CI PostgreSQL list 223 passed; migration rehearsed on a fresh database built from `main`'s 34 migrations (81 pack and snapshot tests pass on it).
- **Backup:** `~/cyphward-release-backups/2026-10-18-release-pr40/full.dump.gpg`, AES-256, checksum verified (`04d8396d…`), plaintext shredded.
- **Migration:** only `20261018120000_evidence_packs.sql` (sha256 `58a254e4f2babfac`, the file that was rehearsed), applied as `postgres` in one transaction with `lock_timeout 5s` and `statement_timeout 60s`, recorded in `supabase_migrations.schema_migrations`. No existing table's row count changed; new tables `evidence_packs` and `dpo_reminders`. Verified: row-level security on; `cyphward_app` has SELECT and INSERT only; the guard trigger `evidence_packs_guard`; the organisation-composite foreign key to `assessment_snapshots`.
- **Merge:** `400fe60da235d629588b7f83b653f60cb7c13952` (previous main `a7e9719f2bc6`); fork `main` synced; API deploy live at `400fe60` at 01:06 UTC.
- **Post-checks passed:** `/health` healthy; `GET`/`POST /api/v1/packs`, `GET /api/v1/packs/{id}`, `/pdf` and `/html`, `/api/v1/snapshots` and `/api/v1/reports` return 401 unauthenticated; `app.cyphward.com/comply` serves 200; the live Compliance bundle contains the Packs tab. One transient result is recorded for honesty: the very first `GET /api/v1/packs` after the deploy returned a connection failure (curl `000`) while the service was warming; six of six retries returned 401 and `/health` stayed 200.
- **First real pack (INNOVATECH, through the application code and the restricted `cyphward_app` role):** snapshot `231f4104` (seq 1, content sha256 `84f60b156390…`), readiness pack `0d81dd14` (html sha256 `f62164754625…`, pdf sha256 `66f5dac40894…`, PDF 61,015 bytes, DPO window 18 Apr to 18 Oct 2026). The stored bytes match their stored hashes; two audit rows (`snapshot.created`, `compliance.pack.issued`); the pack used one unit of the monthly reports quota (its snapshot is not counted again). The PDF was rendered to images and read: title, scope, dates and register version, the supporting-evidence and "not a Compliance Audit Return" notices, readiness as counts (7 of 29 applicable requirements have evidence, 18 awaiting input or upcoming checks, 4 not assessed), per-requirement status with source labels, 31 "reference pending review" markers, and the customer answer shown with its owner. No banned phrase appears in the PDF text. Saved with its text and page images in `~/cyphward-release-backups/2026-10-18-first-pack/`. The database layer reported one transient pool timeout on its first attempt and retried automatically.

### C5 (#39): released and production-verified

- **Gates:** `main` merged in with the tested conflict resolution (both the Packs and Documents tabs, both sets of API helpers, the union of the CI test lists); independent review APPROVE in round 2 (round 1 REJECT, fixed); CI green on `9f0aab6`; full suite on the owned loopback database 1137 passed / 16 skipped, CI PostgreSQL list 251 passed; migration rehearsed on a fresh database built from `main`'s 35 migrations (82 document tests pass on it).
- **Backup:** `~/cyphward-release-backups/2026-10-18-release-pr39/full.dump.gpg`, AES-256, checksum verified (`60edabef…`), plaintext shredded.
- **Migration:** only `20261018200000_compliance_documents.sql` (sha256 `0313c4f7af2cc3d1`, the file that was rehearsed), applied as `postgres` in one transaction with `lock_timeout 5s` and `statement_timeout 60s`, recorded in `supabase_migrations.schema_migrations`. No existing table's row count changed; new tables `compliance_documents`, `compliance_document_approvals`, `compliance_document_quota`, all empty. Verified: row-level security on; `cyphward_app` has SELECT and INSERT only on all three, and may update only `n` on the quota table; the "Draft — not legal advice" label constraint; the organisation-composite foreign key on approvals; the quota CHECK (`n <= 10`).
- **Merge:** `d8496335da09b2ddb1828af211198398db506844` (previous main `400fe60da235`); fork `main` synced; API deploy live at `d849633` at 01:37 UTC.
- **Post-checks passed:** `/health` healthy; `GET /api/v1/compliance/documents`, `GET /documents/{id}`, `POST /documents/{kind}/generate`, `POST /documents/{id}/approve`, the questionnaire, packs and snapshots endpoints all return 401 unauthenticated; `app.cyphward.com/comply` serves 200; the live Compliance bundle contains both the Documents and Packs tabs. `COMPLIANCE_DOCS_MODEL` is not set on the production API, so drafts are the standard grounded wording and nothing is sent to a model.

### Release run summary (Packet 04, C4, C5; 18 Oct 2026, 00:05 to 01:40 UTC)

| PR | Merge commit | Review rounds | Backup checksum | Migration sha256 | Full suite / PostgreSQL list (local) |
|---|---|---|---|---|---|
| #38 Packet 04 | `a7e9719f2bc6` | REJECT, APPROVE | `b2bd6fb5…` | `92be5ab8ed4f350d` | 1014 passed, 16 skipped / 183 |
| #40 C4 | `400fe60da235` | REJECT, APPROVE, APPROVE on the final delta | `04d8396d…` | `58a254e4f2babfac` | 1054 passed, 16 skipped / 223 |
| #39 C5 | `d8496335da09` | REJECT, APPROVE | `60edabef…` | `0313c4f7af2cc3d1` | 1137 passed, 16 skipped / 251 |

- **No post-check failed, so no revert was needed.** Releases ran in the agreed order, one at a time, each verified before the next.
- **Reviewer model:** Fable was requested for every review and was not available (it needs usage credits), so each review ran on Opus, with a fresh reviewer for each PR (one reviewer per PR; the same reviewer re-checked its own PR's fixes).
- **What the reviews caught:** #38 could starve the shared connection pool (fixed: at most 3 builds per process, bounded lock waits); #40 could leave charged orphan snapshots and crash the PDF for large organisations (fixed: one transaction, capped references); #39's output check could not stop paraphrased claims or invented commitments (fixed: model rewording off by default, normalising filter, migration timeouts).
- **Founder-agreed changes made before release:** snapshots and packs count against the monthly reports quota (usage = reports + packs + snapshots that neither a report nor a pack belongs to); a retention setting, default 36 months, owner-set, shown as `retain_until`, with no automatic purge; owner names kept in issued snapshots and packs and disclosed in the retention text.
- **First real pack:** see "C4 (#40): released" above (INNOVATECH, saved in `~/cyphward-release-backups/2026-10-18-first-pack/`).
- **Left alone on purpose:** nothing under `scanner/` or `shared/` was touched by any of the three PRs; no migration was destructive; no data was deleted.

### Decisions for Yusuf (release run)

1. **AI rewording of drafts is off.** Say if you want it back; it needs the allow-list output check first, and one environment variable (`COMPLIANCE_DOCS_MODEL=on`) turns it on.
2. **Removal after the retention period is an operator step.** A snapshot that a report points to cannot be purged until that report is deleted first (`reports_snapshot_fk` has no ON DELETE action); write the purge runbook before the first snapshot reaches 36 months.
3. **Accepted should-fix items,** each recorded above with its reviewer: threadpool occupancy and one organisation taking all three build slots (add `pg_try_advisory_xact_lock`, a per-organisation slot and a rate limit on the snapshot and report endpoints); the DPO counts being read at pack issue time; a request key raced on both pack paths can give a 500 or an earlier pack of another kind; hardening of the banned-word filter for accented Latin letters and hyphen-plus-space splits in customer name fields.


## C6 — evidence file uploads (branch `claude/infallible-agnesi-011c96`, base `main`)

Customer owners and admins can attach files (PDF, PNG, JPG/JPEG, DOCX, up to 10 MB) to the evidence of a questionnaire answer; every member can see and download them. Growth plan only. The bytes live in a **private** Supabase Storage bucket `evidence-files`; the database holds one row per file. This is plan decision D2 ("file uploads later: private bucket, tenant-scoped signed URLs, size and type limits, retention") built. An attachment is something the customer chose to attach: the screen says Cyphward does not read or review it, and it changes no register status.

### What was built

- **Storage interface** `backend/app/storage/`: `put`, `create_signed_url`, `delete`, `delete_prefix` (plus `list_objects` for reconcile). `SupabaseStorage` (httpx, service role from `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`, key only in request headers, fixed error texts with no body or header, plain `http://` refused except loopback) and `MemoryStorage` (thread-safe fake with failure switches). An autouse fixture in `conftest.py` installs the fake in every test and clears the two variables, so no test can reach Supabase. Without configuration uploads answer **503** with `Retry-After`, nothing else changes.
- **Rules** `backend/app/compliance/evidence_files.py` (pure): extension and magic bytes must agree (`%PDF-`, PNG signature, `FFD8FF`, DOCX = zip with `[Content_Types].xml`, a `word/` part and a Word main content type); refused: empty, over 10 MB, mismatches, second extensions (`report.exe.pdf`), macro-enabled content types, password-protected and path-traversal zips, DOCX with more than 1000 parts or expanding past 50 MB or 100x (checked from the zip directory, never by unpacking). Stored content type comes from the validated type. Names are cleaned (last path segment, control, bidi and zero-width characters removed, Windows-reserved characters to `_`, 120 characters) and stored as a display name only. Object path is `org/<org_id>/<file_uuid>`; a CHECK makes the database refuse any other path.
- **Store** `backend/app/compliance/evidence_file_store.py` and **API** (end of `backend/app/api/compliance.py`): `GET /api/v1/compliance/evidence-files` (any member), `POST` (owner/admin; the file is the raw request body, name in `X-File-Name`), `GET /{id}/download` (any member; checks the organisation in the database, writes the audit row, then returns a 60-second signed URL with the Storage `download` parameter, so Cyphward's link is served as an attachment, plus the display name; `Cache-Control: no-store`), `DELETE /{id}` (owner/admin). Cross-tenant and malformed ids are 404 (ids are taken as text, not `UUID`, so no 422).
- **Upload order (no connection or lock while bytes move):** Growth and role check, name check, storage configured, a per-process semaphore (4 uploads at a time, waiters get 503 + `Retry-After` after 10 s and hold no connection), body read with a hard stop one chunk past 10 MB (and an early 413 on a declared length), content check, unlocked quota pre-check, `put`, then ONE short transaction (`lock_timeout 5s`, per-organisation advisory lock, caps and rate checked from the table itself, row insert, audit insert). If anything fails the object is deleted again (compensating delete); a lock wait is 503 + `Retry-After`. The rate limit is counted from `uploaded_at` rows inside the same transaction, not through `rate_limit.check_rate_limit` (which commits on its own and would leave a charge behind a failed insert).
- **Caps (per organisation, defaults in `evidence_files.py`):** 100 active files, 500 MB active total, 30 uploads per hour (removed uploads still count toward the hour). Active files only count toward the first two.
- **Removal:** owner/admin; sets `removed_at`/`removed_by` and writes audit in one transaction, then deletes the object. If the delete fails the row stays marked (the file does not download either way) and `reconcile` retries.
- **Organisation closing** (`POST /api/v1/organizations/close`, the only `DELETE FROM organizations` in the code): closing never waits for storage and is never blocked by it. If the organisation has file rows its id is first written to `compliance_evidence_purge_queue` (no foreign key); the rows are deleted; then `delete_prefix org/<id>/` runs and clears the entry. If storage fails or is unset the entry stays queued and `reconcile_evidence_files.py` retries it (an entry whose organisation still exists, because the database delete failed, is dropped unused). Nothing is deleted from storage before the rows, so a failed database delete cannot leave rows pointing at nothing.
- **Reconcile** `backend/scripts/reconcile_evidence_files.py`: read-only report by default; `--delete --yes-delete` deletes orphans (objects with no row, and objects whose row is marked removed), at most `--max` (default 50) per run, and refuses when the table has no rows but storage has objects; objects with no row younger than 15 minutes (`--min-age`) or of unknown age are left (an upload may be between its put and insert); it also works through the purge queue; also lists active rows whose object is missing (never changed); `--check-bucket` fails if the bucket is public or missing; exits 1 when it finds something to do.
- **Audit:** `compliance.evidence_file.uploaded`, `.download_link_issued`, `.removed`, with file id, size, content type and question key; never the file name or any content.
- **Migration** `supabase/migrations/20261019100000_compliance_evidence_files.sql` (sha256 recorded at release): one transaction, `lock_timeout 5s`, `statement_timeout 60s`; table `compliance_evidence_files` with RLS, `REVOKE ALL`, then SELECT, INSERT and UPDATE (`removed_at`, `removed_by`) only; guard trigger (a row can be marked removed once; nothing else changes; a deleted profile may clear `uploaded_by`/`removed_by`); `(org_id, id)` unique key; composite `(org_id, attestation_id)` foreign key to `compliance_attestations`; `ON DELETE CASCADE` from organizations; the `compliance_evidence_purge_queue` table (SELECT, INSERT, DELETE for the app role; no foreign key); `REVOKE ALL` from `anon` and `authenticated` where those roles exist; a `DO` block creates the bucket row (private, 10 MB, four MIME types, upsert re-asserts private) only where `to_regclass('storage.buckets')` exists. No policy is created on `storage.objects`.
- **Frontend:** `frontend/src/pages/compliance/EvidenceFiles.tsx` under each question on "Answer questions": file list (name, type, size, date, uploader), DOWNLOAD (calls the API, then follows the signed link as a download), REMOVE with the existing `ConfirmDialog`, ATTACH EVIDENCE (owner/admin) with client checks mirroring the server, a progress bar (XHR) and error messages. The list loads once per page; if it fails the file area is simply hidden. Browser suite extended (desktop/390/320).

### Tests

- `backend/tests/test_evidence_files.py`: **57** (rules, names, zip bombs, fake, REST implementation against a mock transport, banned phrases on all new copy and fixtures including the frontend component).
- `backend/tests/test_compliance_evidence_files_postgres.py`: **77** (grants, guard, migration one-transaction/idempotent/private bucket in a rolled-back simulated storage schema, upload/list/download/remove with roles, Starter and cross-tenant, caps and rate also under concurrency, the last-slot race, compensating delete, no database connection while bytes move, lock wait 503, semaphore, streaming limit, audit without names, reconcile, organisation closing and its failure path, no service key in any response or log, snapshots and packs carry no file data). Added to the CI PostgreSQL list.
- Full backend suite on the local database: **1269 passed, 16 skipped** (the two known flaky scan-execution tests deselected). CI PostgreSQL list locally: **326 passed** (the 15 files in the workflow list, the two known flaky scan-execution tests deselected). Frontend: `npm run build` and `test:compliance-ui`, `test:scans-ui`, `test:score-ui`, `test:onboarding-ui` all pass.
- **Mutation checks** (each mutation made, the named tests run, each failed, then reverted): quota check removed; advisory lock removed; compensating delete removed; download without the `removed_at IS NULL` filter; download without the organisation filter; magic-byte check disabled; `download` parameter dropped from the signed URL; storage purge removed from organisation closing; Growth gate removed from upload; owner/admin gate relaxed on upload; removal audit dropped; file name added to the audit metadata. 12 of 12 killed.

### Decisions for Yusuf (C6)

| # | Decision | Default applied |
|---|---|---|
| C6-1 | Upload transport | The file is the raw request body with the name in a percent-encoded `X-File-Name` header; no multipart. This avoids a new dependency (`python-multipart` is not in `requirements.txt`) and lets the server stop reading at 10 MB. |
| C6-2 | Memory | A file is held in memory (at most 10 MB) while it is checked, because a DOCX is validated from its zip directory. At most 4 uploads run per process, so the cost is bounded at about 40 MB per process. |
| C6-3 | Caps and rate | 100 active files, 500 MB active total, 30 uploads per hour per organisation. Edit the constants in `evidence_files.py`. |
| C6-4 | Organisation closing and storage | Closing is never blocked by storage. The cleanup is recorded in a small queue table (in the same migration) before the rows go, run right after, and retried by the reconcile script if it failed. Chosen over fail-closed because a storage outage or unset keys must not stop a customer deleting their data.
| C6-5 | Snapshots and packs | Left alone. They embed no file data (a test proves it for a created snapshot and pack); adding an attachment list would risk changing the hash of existing snapshots for little value. |
| C6-6 | Download link audit | The audit row is written (with the file lookup, in one transaction) before the link is signed, so a storage failure while signing leaves an audited attempt. Members' downloads are audited too. |
| C6-7 | What a removed file leaves behind | The object is deleted at once. The database row stays marked removed, including the display name, as the trail of what was attached; it is deleted with the organisation. Say if removed rows should lose the name. |
| C6-8 | What a file belongs to | The question, so it survives re-answering. It also records the answer that was current when it was added (nullable, same-tenant foreign key). |
| C6-9 | Double extensions | Strict: a name with a second extension-like part (`report.final.pdf`, `v1.2.pdf`) is refused with "rename the file". `Policy v2.1.pdf` is fine (a space or digit start is not an extension). |
| C6-10 | No malware scan | Not built. Files are never opened by Cyphward, are always served as attachments from the Storage domain, and macro-enabled DOCX content types are refused, but a PDF can still carry active content. A scanner would be a separate packet. |
| C6-11 | Workspace export | Does not yet list file metadata (the export is an existing endpoint with its own test fixtures). Add it if the data-portability promise should cover attachments. |
| C6-12 | Reconcile | Run by hand (report mode is safe at any time). It is not scheduled; suggested weekly. |
| C6-15 | Refused uploads | Every upload attempt (saved or refused) counts against 60 attempts per organisation per hour (existing shared `rate_limits` table), on top of the 30 saved files per hour. One organisation may use at most 2 of the process's 4 upload slots. Download links: 30 per user per minute. |
| C6-16 | Uploads switch | New uploads need `EVIDENCE_UPLOADS_ENABLED=true` (default off) as well as the two Supabase variables. Unsetting either never blocks downloads, removal or closing a workspace. |
| C6-14 | Retried uploads | Uploads carry no request key, so a retry after an unseen success makes a second file (it counts against the caps; the owner can remove it). The UI disables ATTACH while a file is sending. |
| C6-13 | Who sees what | Owners and admins attach and remove; every member lists and downloads. Starter gets the existing Growth-plan 403 on all of it, including listing. |

### Limitations

- **The Supabase Storage REST calls were written from the documented API and tested against a mock transport only: this build has no network access, so they have not run against a real Storage service.** The first real upload, signed link, delete and prefix delete need the smoke test below before customers see the feature.
- **"Attachment only" holds for the links Cyphward issues, not for the signed token.** The `download` parameter is a query parameter that the signed token does not cover: anyone holding a link can drop it within its 60 seconds and view the file inline, on the Supabase storage domain and never on the app origin. We cannot add `X-Content-Type-Options: nosniff` on Supabase either. The exposure is limited to someone who already holds a valid 60-second link to a file in their own organisation, and to the four allowed types.
- **Other accepted risks:** the service role key can reach every Supabase project resource, so keep it only on the API service; a lapsed subscription (Starter) also hides the organisation's own files and blocks downloading them until the plan returns; the workspace export does not include files; on Supabase the default privileges for `anon` and `authenticated` are revoked by the migration on the two new tables, but check `storage.objects` policies by hand (runbook).
- A request body that is sent too slowly is refused after 60 s (408) so it cannot hold an upload slot.
- Large organisations: `delete_prefix` lists and deletes in pages of 100 (bounded at 50 rounds) and the reconcile listing stops at 100,000 objects.
- The upload slot semaphore is per process; with several API replicas the cap is per replica.
- **Body size through the proxy is unverified: the 9 MB smoke test must pass before release.** The browser reaches the API through the Vercel `/api/(.*)` rewrite to Render. If Vercel caps request bodies below 10 MB on that path, large uploads will fail at the proxy (the app would show "The upload failed"). Test a file of about 9 MB in the smoke test; if it fails, lower the limit or send uploads to the API origin directly (CORS already allows it).
- A client that disconnects between the storage put and the insert can leave an object behind; reconcile removes it after 15 minutes.

### RUNBOOK (operator)

1. **Order:** apply the migration, set the two variables on the API, deploy the API, then the frontend. Until the variables are set uploads answer 503 and the file area says uploads are not available; nothing else changes.
2. **Render environment (API service):** `EVIDENCE_UPLOADS_ENABLED=true` (the on switch; unset it to stop new uploads while downloads, removal and closing still work), `SUPABASE_URL` (the project URL, `https://<ref>.supabase.co`) and `SUPABASE_SERVICE_ROLE_KEY` (the project's service role key). Never put either in the frontend or in git. To turn uploads off again, unset either variable.
3. **The bucket:** on the hosted Supabase project the migration creates the `evidence-files` bucket (the storage schema exists there), private, 10 MB, the four MIME types. If the storage schema is missing, or the bucket row is not there after the migration, create it with the Storage API using the service role key from your shell (do not paste it anywhere): `POST {SUPABASE_URL}/storage/v1/bucket` with `{"id":"evidence-files","name":"evidence-files","public":false,"file_size_limit":10485760,"allowed_mime_types":["application/pdf","image/png","image/jpeg","application/vnd.openxmlformats-officedocument.wordprocessingml.document"]}`.
4. **Verify it is private:** (a) `python backend/scripts/reconcile_evidence_files.py --check-bucket` prints `bucket evidence-files: private` (exit 1 otherwise); (b) in the Supabase dashboard the bucket shows as Private; (c) in SQL: `SELECT public FROM storage.buckets WHERE id='evidence-files'` is `false`, and list ALL policies with `SELECT * FROM pg_policies WHERE schemaname='storage' AND tablename='objects'`: none may allow `anon` or `authenticated` on this bucket (a broad policy such as one covering every bucket would); (d) an unauthenticated request to `{SUPABASE_URL}/storage/v1/object/public/evidence-files/org/x/y` is refused.
5. **Smoke test after release:** as an owner on a Growth organisation upload a small PDF to an answer, download it (the browser saves it, it does not open) and, on the signed link, check with `curl -sI` that `Content-Type` is the file's type, `Content-Disposition` is `attachment` and note whether `X-Content-Type-Options` is present (it may not be), remove it, and check the object is gone from the bucket. Repeat with a file of about 9 MB (it must get through the Vercel proxy). Then run the reconcile script in report mode: it should list nothing.
6. **Housekeeping:** run `python backend/scripts/reconcile_evidence_files.py` weekly (it also retries queued workspace purges); use `--delete --yes-delete` only after reading the report.
