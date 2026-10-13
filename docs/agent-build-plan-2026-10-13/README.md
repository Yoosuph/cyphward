# Cyphward implementation handoff

**Prepared:** 13 October 2026
**Source baseline inspected:** `c7edb77` on local `main`
**Purpose:** Give the next AI coding agent a sequenced, testable implementation plan.
**Current task:** Packets 00 and 01 are implemented and validated. Packet 01's production migration has been applied after a verified private backup/restore rehearsal; application shipping and live verification are in progress. See `PROGRESS.md` for the exact delivery state.

Start with [START-HERE.md](START-HERE.md). The first implementation specification is [01-scan-admission.md](01-scan-admission.md). Record progress in [PROGRESS.md](PROGRESS.md). The business rationale is in [the growth strategy](../growth-and-competitive-strategy-2026-10-12.md).

## 1. The outcome and first assignment

The product should reliably carry a customer through **verified domain → useful assessment → prioritised work → supported verification → trustworthy evidence → recurring monitoring**. Compliance and Academy should extend this flow when buyer demand supports them.

**The next agent's initial assignment is Packet 00 and Packet 01 only.** Complete a reviewable, tested change for safe scan admission. Do not attempt the entire roadmap in one branch or silently start later packets. Later work is specified below so the first change leaves appropriate boundaries.

The first delivery target is a **review-ready implementation**, with actual test evidence and migration/release instructions. This handoff does not itself issue an instruction to deploy or change production data. If the user separately authorises shipping, carry that authorisation forward without asking again for the same action.

## 2. Preserve these established decisions

- Payment-system activation is deferred. Do not enable checkout, webhooks, automatic charging or live billing-provider operations. Existing subscription-aware limits must still be enforced.
- A new user may reach the dashboard before adding or verifying a domain. Domain ownership verification remains mandatory for scans. Preserve owner/admin launch permissions and tenant isolation.
- Existing remediation tasks, assignees, due dates and rechecks are foundations to extend. Existing `/platform` is the staff console; do not create a second administration system.
- Keep `/scans` desktop/mobile design, scrollable history, keyboard support, truthful coverage states and reliable slow-response polling. Filters currently apply to loaded history, not server pagination.
- Preserve “not assessed,” partial/failed/skipped checks, and the distinction between a scan's historical score and current organisation risk. Failed or missing evidence must not certify a fix.
- Preserve actual customer data and historical results. Do not seed production demo tenants, assign a default customer domain, invent findings, or rewrite old scans to look successful.
- Do not reactivate unsupported compliance/certification claims or promise that a domain scan establishes whole-company security.
- Use the repository's `AGENTS.md` model rule when the runtime supports it. Concurrency, authorisation, tenant isolation and evidence-integrity design need complex reasoning. If switching is unavailable, do not claim that a switch occurred.

## 3. Facts the next agent must know

The following are source observations at the baseline, not proof of a new production incident:

| Area | Current behavior | Planning consequence |
| --- | --- | --- |
| Manual admission | `launch_scan` checks quota and then inserts through a separate database call. No request idempotency or active-domain guard. | Make admission atomic before increasing workload. |
| Scheduled admission | `_daily_scan_sweep` checks `organizations.plan`; manual admission uses subscription-aware `resolve_plan`. | Use one entitlement/admission policy. Expired or cancelled subscriptions must behave consistently. |
| Scheduler overlap | Candidate selection excludes organisations with active scans, but snapshots multiple domains before inserting. | Current behavior is not a dependable organisation-wide concurrency limit. Packet 01 explicitly selects per-domain non-overlap. |
| Database helpers | `execute_one`/`execute_query` commit individual calls. | Consecutive helper calls do not form an atomic business transaction. |
| Worker writes | `_held_job` checks scanner ID and running status separately from writes; observations are deleted and inserted in separate calls. | Packet 02 must fence every mutation using a current claim and transaction. |
| Delivery | Admission comments mention exactly-once dispatch, but duplicate delivery/local execution and process crashes require separate treatment. | Packet 01 proves admission idempotency, not exactly-once execution. |
| Cron ownership | Claim acquisition is atomic, but completion/release do not compare a claim generation. | Packet 02 includes stale scheduler-owner behavior. |
| Reports | Report generation combines live findings with the latest assessment. | Packet 04 must introduce an explicit, consistent snapshot contract. |
| Existing tests | Most backend tests use SQL-pattern-matching fake data. Several optional integration tests explicitly target configured real/production URLs and mutate records. | Never enable those flags against inherited credentials. New concurrency tests require an isolated disposable database. |

Relevant source:

- [Scan API](../../backend/app/api/scans.py), [workflow and scheduler body](../../backend/app/workflows/inngest_workflow.py), [scheduler trigger](../../backend/app/scheduler.py).
- [Plans and usage](../../backend/app/core/plans.py), [subscription resolution](../../backend/app/billing/subscriptions.py), [database helpers](../../backend/app/core/database.py).
- [Worker API](../../backend/app/api/scanner_jobs.py), [cron claims](../../backend/app/core/cron_claim.py), [shared contracts](../../shared/contracts.py).
- [Remediation](../../backend/app/api/remediation.py), [reports](../../backend/app/api/reports.py), [frontend API helper](../../frontend/src/lib/api.ts).

## 4. Packet 00 — baseline and safe test environment

**Owner:** implementing agent. **Dependencies:** none.

1. Read root and applicable nested `AGENTS.md` files. Record the actual commit and working-tree changes. Revalidate relevant source if HEAD differs from the baseline.
2. Preserve the growth-strategy Markdown, PDF and Word files. They were untracked when this handoff was prepared. A new clone will not contain uncommitted documents; transfer this handoff and the strategy explicitly or include them in an authorised documentation commit.
3. Read the linked implementation/scanner reports as historical evidence, then inspect current code. Do not restore an old behavior simply because an older review describes it.
4. Identify external side effects before running tests. Configure test-only secrets, disable actual email/event/scan delivery, and ensure test startup cannot schedule production work.
5. Create an explicitly disposable PostgreSQL test database or container. Use synthetic tenants and domains. The proposed new test-DB configuration must fail closed when absent and must not fall back to `DATABASE_URL` from the workspace.
6. Inspect migration ordering and prerequisites. Some historical migrations and seed scripts are destructive; apply them only to the owned disposable environment after understanding them. Never run a generic database reset against an inherited URL.
7. Record baseline test/build results. Existing skips are limitations, not passed integration checks. Fix regressions caused by the packet; record unrelated pre-existing failures separately.

**Done when:** the source map, proposed behavior, test destination and baseline results are recorded in `PROGRESS.md`. This preparation should lead directly into Packet 01; it is not a reason to stop for routine confirmation.

## 5. Implementation sequence

Each packet gets a focused change, acceptance evidence and an updated progress record. Split large packets into reviewable subchanges with explicit compatibility boundaries.

| Packet | Outcome | Dependencies | Scope and completion evidence |
| --- | --- | --- | --- |
| 01 | Safe scan admission | 00 | Shared transactional quota/overlap policy, idempotency, all three UI launch surfaces and real database race tests. Full specification is linked above. |
| 02 | Safe job execution and recovery | 01 | Current claim required for worker/Core writes; atomic observations; stale-owner rejection; reliable recovery and delivery semantics. |
| 03 | Defensible scope and coverage | 02 for authoritative persistence | Versioned target/check evidence, consistent limits/deadlines and honest omitted/failed scope. |
| 04 | Trustworthy assessment/report snapshots | 03 | Versioned reports reproduce the selected assessment; current findings cannot silently alter historical claims. |
| 05 | Activation and remediation follow-through | 01; use 03–04 for assessment/evidence claims | Role-aware checklist, existing task ownership/deadlines surfaced, evidence-linked verification, useful phone layouts. |
| 06 | Operations and outcome measurement | Instrument alongside 01–05; consolidated views after contracts stabilise | Worker/queue visibility, support recovery, activation and resolution metrics with precise definitions. |
| 07 | First compliance evidence workflow | 04–06 plus validated buyer need | One practitioner-reviewed requirements set and attributable evidence with owners/review states. |
| 08 | Assigned Academy pilot | Validated employer demand; evidence model from 07 where relevant | Short assigned lessons, assessment, completion/version records and measured usefulness. |
| 09 | Wider admin/partner capabilities | Proven workflows and recurring support/partner need | Customer-authorised access, least privilege, auditability and economical service delivery. |

The founder's buyer interviews, pilot pricing, manual invoicing and cost recording can run alongside engineering. An AI agent must not invent revenue/customer traction or send outreach merely because those activities appear in the business roadmap.

## 6. Contracts for later packets

### Packet 02: execution ownership, separate from admission

Inspect [worker API](../../backend/app/api/scanner_jobs.py), [worker runner](../../scanner/runner.py), [worker client](../../scanner/client.py), [shared contracts](../../shared/contracts.py), [finalisation](../../backend/app/workflows/inngest_workflow.py), [startup recovery](../../backend/app/core/scan_recovery.py) and [cron ownership](../../backend/app/core/cron_claim.py).

Use a per-claim generation/token so reusing a scanner ID cannot authorise an old attempt. Check current ownership, status and expiry atomically with every progress, observation, complete and fail mutation. Replace observation delete/insert with an atomic operation. Carry ownership into Core finalisation so stale finalisers cannot overwrite current findings, scores or terminal states. Fence scheduler completion/release after takeover as well.

Prove cancel-versus-write, expiry/reclaim, same-scanner-ID reuse, stale complete/fail, duplicate observations, duplicate delivery and Core restart scenarios against real PostgreSQL. Test intermediate data, not only the final status.

Document local versus remote dispatch recovery. If adding a durable outbox, define delivery retries and consumer idempotency; an outbox does not itself establish exactly-once execution. Keep external work outside database locks.

Any Core/worker contract change needs an explicit version and rollout sequence. Do not add an optional token that silently disables fencing for older workers. Prepare additive schema, compatible release steps, queue handling and rollback without dropping evidence. This packet is not permission to modify a live worker.

### Packet 03: coverage and limits

Extend the existing tool/normalisation model. Persist target identity, requested/evaluated check or template identifiers, tool/template versions, outcome, time, exclusions and cap reasons. Distinguish successful evaluation with no finding from failure, omission and unknown legacy coverage.

Use one policy for local/remote scope and end-to-end deadlines. Prioritise explicitly registered hosts and expose omitted hosts. Treat ports/TLS as inventory unless supported reviewed rules justify findings. Validate actual connection boundaries and redirects before claiming safe network isolation.

Acceptance includes partial-target failure, missing template, empty discovery, HTTP-only targets, exhausted budget and unavailable legacy evidence. A finding resolves automatically only when matching target/rule evidence supports it. Scoring changes, if needed, require explicit versioning and historical compatibility.

### Packet 04: assessment and report integrity

Define whether an assessment is domain-scoped or organisation-scoped before designing storage. Never label an organisation-wide current score as an immutable score for one historical domain scan.

Create a consistent snapshot containing scope, observation/assessment dates, coverage, findings, provenance and scoring version. Generate the report from that snapshot and retain report version. Protect exports with tenant permissions and defined retention. Use private artifact delivery if artifacts are introduced.

Prove that later scans, task updates and score changes do not silently rewrite an issued report. Old reports without sufficient evidence must be labelled legacy/limited; do not fabricate backfilled snapshots. Test cross-tenant IDs, domain mismatch, concurrent generation and unassessed results. Snapshot immutability must coexist with authorised data deletion and retention policies.

### Packet 05: customer workflow

Extend [Overview](../../frontend/src/pages/Overview.tsx), [Findings](../../frontend/src/pages/Findings.tsx), [Remediation](../../frontend/src/pages/Remediation.tsx), [overview API](../../backend/app/api/overview.py) and the existing remediation API.

Derive setup milestones from real state: domain verified, usable assessment available, results reviewed and an action agreed. A completed job with inadequate coverage is not automatically a usable assessment. Define the criterion before coding. Accounts with no actionable findings can complete an appropriate review milestone without creating a fake task. Teammate invitation is optional and must respect plan limits.

Make assignee, due date, overdue state and verified recheck history usable on mobile and desktop. Manual acknowledgement or accepted risk must remain distinct from tool-supported verification. Do not convert viewing a page or clicking launch into a completed assessment event.

Acceptance includes members versus owners/admins, clean assessed results, unassessed/partial scans, failed refresh, workspace switching, 320px/390px/desktop widths, keyboard access and existing history scrolling.

### Packet 06: support and measurement

Extend the existing `/platform` authorisation boundary. Show worker version/capabilities/last seen, queue wait, overdue work, failure/partial counts and delivery recovery. Any retry/cancel operation uses the same lifecycle rules; staff actions need scoped authorisation and audit reasons.

Record minimal events needed to measure activation, resolution and support effort. Define each denominator and tenant scope. Do not send raw scan evidence or customer questionnaire content to analytics by default. Separate operational records from financial/customer-success records where their permissions differ.

### Packets 07–09: demand-gated expansion

Before compliance implementation, choose the exact requirements set and have a qualified practitioner review applicability and wording. Each evidence record needs source, owner, date, review state and freshness. Tool observations, customer assertions and practitioner reviews remain distinguishable. AI output is a draft with sources and human approval.

Before Academy implementation, identify the paying employer and learning need. Implement a small assigned-learning pilot with content version, quiz/assessment and completion record. A completion certificate must not imply accredited professional qualification.

Build partner access and module administration after those workflows exist. Keep platform staff authority separate from customer organisation roles. Customer-visible, time-limited access grants are preferable to unrestricted impersonation.

## 7. Validation and evidence rules

The following commands already exist. Run them from repository root in the isolated test environment described in Packet 00, choosing the suite appropriate to the packet:

```bash
npm test
npm run build --workspace frontend
npm run test:scans-ui --workspace frontend
npm run test:score-ui --workspace frontend
npm run test:onboarding-ui --workspace frontend
git diff --check
```

The backend command alone does not prove database concurrency. Packet 01 must add and document a safe executable command for its new real-PostgreSQL tests; that command does not exist yet. It should provision or explicitly select only the owned disposable database, use independent connections, and fail if the required isolation cannot be established.

Run relevant tests after changes and required full checks once the packet is complete. Do not repeatedly run unchanged passing suites without a new reason. Browser regressions use mocked APIs and must be reported as such. Normal scans UI tests should not overwrite committed screenshots; explicit screenshot regeneration is separate.

Acceptance evidence must state what was checked locally, against isolated PostgreSQL, against mocked APIs and against an authorised deployed environment. Never label unrun checks, skipped tests or source inspection as production verification.

## 8. Migration, release and rollback boundaries

- Add new migrations. Do not edit already-applied historical migrations as a substitute for upgrading an existing installation.
- Inspect existing rows before proposing new uniqueness constraints. If duplicates exist, provide a bounded repair plan; do not automatically delete scans or rewrite customer history.
- Document new tables/indexes, role privileges, retention and rollback. Test application access using a representative least-privileged role.
- Record deployment order for schema, Core, worker and frontend. A mixed release must not break old callers or bypass a safety contract.
- A successful Git push is not evidence of a successful deployment. The previous frontend rollout required explicit Vercel deployment even after CI passed; verify current configuration before selecting the release procedure.
- When shipping is authorised, preserve the user's two-repository rule: push `origin main`, then `fork main`, and verify both `main` SHAs. The local origin pre-push hook may sync the fork first, but its warning behavior does not prove both pushes succeeded. Never force-push to make them match.
- Scanner-related path changes can trigger the existing scanner deployment workflow on a main push. Review that consequence before shipping a contract or scanner change.
- Do not publish credentials or use production customer tokens for fixtures. Use legitimate authorised test accounts and declared scan scope for any live validation.

Avoid redundant approval questions. Routine local investigation, implementation and testing within the assigned packet should proceed. If a live migration, destructive repair or other consequential action lacks authorisation, complete the reviewable patch and precise runbook first, then identify only the specific decision needed. A missing safe test database is a reason to provide a disposable harness, not to fall back to production.

## 9. Completion report required from each agent

Report: packet and revision; problem and changed behavior; files/migrations; tests with actual results and skips; source/API compatibility; remaining limitations; deployment state; and the next packet's prerequisites. Update `PROGRESS.md` before handing off.

Use these states precisely: **planned**, **implemented**, **validated**, **review-ready**, **released**, **production-verified**. Validation is scoped to the listed tests. Do not mark a whole packet production-verified because one endpoint or tool probe succeeded.

If a new issue changes the design, record the evidence and revise the affected contract before broad implementation. Ask the user only when the decision changes the agreed product scope, commercial terms or consequential authority; resolve normal implementation details using the explicit packet rules.
