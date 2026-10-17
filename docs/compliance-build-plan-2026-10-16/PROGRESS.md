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
