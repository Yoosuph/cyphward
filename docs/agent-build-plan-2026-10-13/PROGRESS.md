# Agent progress record

**Last updated:** 13 October 2026
**Baseline:** `c7edb77`
**Current state:** Packets 00 and 01 are released. Packet 02 is implemented and locally validated on `codex/scan-execution-recovery`, based on `6d4a4aa`. Its migration/API/worker rollout is pending; production remains on Packet 01.

## Packet 01 pre-release review — 13 October 2026

- Reviewed the current worktree diff for admission ordering, transaction boundaries, idempotency replay, subscription serialization, scheduled identity, mobile retry behavior and migration rollback safety.
- No additional code-level blocker was found in this review. `git diff --check` passes. The previously recorded backend, real-PostgreSQL and frontend validation remains the available test evidence; this review did not rerun those suites because the temporary validation environment had already been removed.
- Release is still gated on the target database operator taking a backup and running the duplicate-active-scan preflight against the intended shared database. Do not infer that the local disposable-database migration is already applied remotely. Do not use an inherited workspace database URL as the release target.
- Packet 02 remains the next engineering packet after Packet 01 is released. Its worker/Core contract change must be rolled out with the worker and migration in the documented order; it is not included in this review.

## Packet 00 — baseline and safe test environment

- Confirmed the original worktree started at `c7edb77`; preserved the pre-existing untracked strategy files, handoff archive and build-plan directory.
- Built a temporary PostgreSQL 18.6 cluster listening only on loopback. Applied the complete migration chain to a fresh `cyphward_test` database as the expected migration owner (`postgres`). No production database URL or live service was used.
- Baseline backend result from a detached worktree at `c7edb77`: **378 passed, 16 skipped**. Baseline frontend production build passed.
- The `16` skips are optional live database integrations; their activation flags were left unset.

## Packet 01 — scan admission

- Manual and scheduled launches now share a tenant-locked transaction for domain authorization, subscription-aware quota, UTC month usage, per-domain overlap, scan insertion and optional idempotency mapping.
- Manual keys are scoped by tenant and actor. Scheduled keys are scoped by UTC run date and domain. Retries replay the same job and do not dispatch again. Subscription mutations take the same organization lock so a first subscription write cannot race an admission that observed no subscription row.
- All three launch surfaces send an intent key. Network/5xx uncertainty retains it; a definitive response clears it. The scan page opens the existing job on an overlap conflict.
- Migration `20261013090000_scan_admission.sql` adds the active-domain unique index and idempotency table, with an explicit duplicate-data preflight and an RLS policy for `cyphward_app`.
- The new PostgreSQL integration tests use independent connections and fail closed unless `CYPHWARD_TEST_DATABASE_URL` names a loopback database called `cyphward_test`. They passed as the non-superuser `cyphward_app` role.

## Changed files

- Backend: `backend/app/core/scan_admission.py`, `backend/app/api/scans.py`, `backend/app/api/billing.py`, `backend/app/core/plans.py`, `backend/app/workflows/inngest_workflow.py`.
- Tests: `backend/tests/test_scan_admission_postgres.py`, `backend/tests/conftest.py`, `backend/tests/test_plan_entitlements.py`, `backend/tests/test_scheduler.py`, `frontend/scripts/check-scans-layout.mjs`.
- Frontend: `frontend/src/lib/api.ts`, `frontend/src/pages/Scans.tsx`, `frontend/src/pages/Overview.tsx`, `frontend/src/pages/onboarding/OnboardingComplete.tsx`.
- Database and docs: `supabase/migrations/20261013090000_scan_admission.sql`, `docs/database-upgrade-runbook.md`, this build-plan directory, and the existing handoff ZIP.

## Validation evidence

- Baseline backend: **378 passed, 16 skipped**.
- Current backend suite against the disposable database, with `DATABASE_URL` explicitly overridden and `CYPHWARD_SCHEDULER_ENABLED=false`: **397 passed, 16 skipped**.
- PostgreSQL admission suite as `cyphward_app`: **14 passed** using independent connections. It covers same-key replay, payload mismatch, terminal replay, quota races, per-domain overlap, scheduled identity, default-domain binding, tenant isolation, subscription-plan semantics, concurrent first-subscription writes, rollback after an injected pre-commit failure, and UTC month calculation.
- Fresh full migration chain applied successfully to the disposable database. The duplicate active-scan preflight rejected a synthetic ambiguous pair; its probe transaction was rolled back.
- `cyphward_app` privilege probe: not superuser and no `BYPASSRLS`; table grants present for `organizations`, `subscriptions` and `scan_launch_requests`; RLS enabled on `scan_launch_requests`.
- Frontend `npm run build`: passed.
- Frontend `npm run test:scans-ui`: passed at desktop, 390px and 320px. It checks retry key reuse across an uncertain response and auth refresh, new-key creation for a later intent, and existing-scan navigation on active conflict. Vite emitted a non-failing proxy `ECONNREFUSED` log after the browser assertions passed; investigate if it recurs in CI.
- Frontend `npm run test:onboarding-ui`: passed.
- `git diff --check`: passed.
- Initial implementation validation used the disposable database and mocked delivery/scanning. The subsequent production release checks are recorded below.

## Packet 01 release — 13 October 2026

- Confirmed the intended Supabase project against its configured administrator/app-role connections and project URL. Read-only preflight found zero duplicate active domain pairs and no queued/running scans.
- Saved a full logical database dump and a separate application/public-schema dump privately outside the repository. Restored the application snapshot into an owned loopback database, supplying its extension, role and auth-function dependencies. All ten recorded application table counts matched. Applied the new migration successfully to that restored existing schema.
- Applied **only** `20261013090000_scan_admission.sql` to the intended shared database in one transaction with bounded lock/statement timeouts; recorded its version in Supabase migration history. No historical migration or seed was applied remotely.
- Verified the unique index is valid, mapping-table RLS is enabled, grants are present, and the `cyphward_app` connection can read the new table without superuser or `BYPASSRLS`. Existing application row counts were unchanged immediately after migration.
- Re-ran backend regression checks with production connections/delivery disabled: **383 passed, 30 skipped**. The 30 skips include the 14 new admission cases when their explicit test URL is absent. Those cases separately passed **14/14** against a fresh synthetic `cyphward_test` database as `cyphward_app`. Frontend production build, onboarding browser suite and the scan-page browser suite passed, including desktop/390px/320px layouts, intent replay and overlap navigation. The mocked Vite proxy emitted the same non-failing post-assertion `ECONNREFUSED` log.
- Committed implementation and the strategy/handoff documents as `c2ae2188698fc184bc24f8115069aa3e11d15448`. Pushed `origin/main` and `fork/main` and verified both remote refs match that SHA. The local hook synchronized the fork before the origin push; the explicit fork push was up to date.
- Both repositories' CI completed successfully for that revision: [origin CI](https://github.com/Yoosuph/cyphward/actions/runs/38359593995), [fork CI](https://github.com/kankarofi125/cyphward/actions/runs/38359587969).
- Independently checked the deployed API at `/api/v1/openapi.json`: the launch operation exposes `Idempotency-Key`. API `/health` reports healthy with database connected. The live `/scans` SPA serves `/assets/index-Htpuc6lQ.js`, matching the local production build with the new launch-intent implementation.
- Live verification established deployment/schema presence and health; authenticated production launch/replay was not exercised. No production scan, event, email or customer-account mutation was invoked for these checks.

Local dispatch still has its documented crash/retry limitations; this change does not establish exactly-once scanner execution. Packet 02 remains the next engineering packet. The handoff ZIP contains the updated documentation.

## Next assignment

Review the Packet 02 candidate against `02-scan-execution.md`, its tests and `02-release-runbook.md`. Complete the coordinated rollout under separate shipping authorisation. After Packet 02 is released, Packet 03 is the next engineering phase: defensible requested/evaluated/omitted/failed scan scope and coverage.

## Packet 02 design and mutation inventory

Implementation branch: `codex/scan-execution-recovery`, based on `6d4a4aa`. No Packet 02 production operation is part of this local implementation.

- Worker mutations: claim/reclaim, heartbeat/progress, stage observations, recon-to-Core handoff and failure. Cancellation also revokes authority.
- Local recon mutations: initial stage/progress, raw stage results, stage transitions and failure. Duplicate events must acquire one current claim before recon runs.
- Core mutations: stage progress/results, scan targets, asset inventory, finding inserts/updates/resolution, finding evidence, notifications, audit records, score snapshots, AI observations and final completed/failed state. Indirect notification/audit database helpers must inherit the same fence.
- Scheduler mutations: run acquisition, completion and release. Completion/release must compare a unique claim, including after same-process-ID reuse.
- Design: monotonically increasing claim generation plus an opaque token; required protocol v2 authority on worker writes; explicit worker/local/Core phases. Recon evidence is tagged by its producing attempt, which is retained across Core takeover. Legacy observations remain unchanged.
- Every helper database transaction in an execution context locks and validates the current scan claim before it reads/writes. Direct multi-record operations use the same explicit fence. External work remains outside locks. An uncertain execution write is not automatically retried by the generic database helper.
- Final score snapshot, completion notification/audit and terminal state are committed together. A bounded recovery loop consumes queued local scans and expired local/Core leases; remote recon continues to use worker polling. Email after successful terminal commit remains best-effort, with no exactly-once external-delivery claim.

## Packet 02 implementation and validation

- Added `execution_fence.py` and `scan_execution.py` for transaction-checked claim authority. The context reaches database helpers used indirectly by notification/audit code. A stale attempt raises `ClaimLost`; expiry and database time are checked after acquiring the scan lock. Execution writes are not automatically replayed after uncertain database failure.
- Worker protocol v2 requires generation/token headers and a valid UUID job path. Workers negotiate the API protocol before claiming; old APIs cannot be treated as compatible. Customer scan list/detail/launch responses omit claim tokens, and object/error representations avoid printing them.
- Recon claims tag raw observations by attempt. Atomic upsert preserves the prior committed payload on interruption and prevents duplicate stage rows. Core handoff/recovery keeps the recon generation while granting new Core authority. Legacy evidence is retained.
- Core completion persists score snapshot, completion notification/audit and terminal state together. Optional AI has a bounded deadline; failed AI is recorded without stranding mandatory completion. Local lost dispatch is consumed from the durable queue; unverified queued jobs cannot starve verified work. Active leases are not stolen at startup.
- Cron completion/release compare owner/generation/token/expiry. Scheduled admission checks and holds the acquired cron authority in its transaction. Only a successfully completed owner emits the `cron.ran` marker.
- Added migration `20261013130000_scan_execution_fencing.sql`, plus an explicit fresh-test-DB bootstrap and PostgreSQL CI job. The bootstrap never loads .env, rejects non-loopback/differently named destinations and refuses an existing application schema.
- Rehearsed the full **25-migration** chain in an owned loopback PostgreSQL 18.6 database named `cyphward_test`, using synthetic tenants. Verified the restricted `cyphward_app` role; tests used independent connections. No restored customer snapshot was used.
- Final full backend result: **424 passed, 16 skipped**. This includes **20 execution PostgreSQL tests** and **14 admission PostgreSQL tests**. It covers same-ID reuse, expiry, cancel/write and cancel/handoff races, lock-held expiry/reclaim, indirect stale Core writes, observation/terminal rollback, Core restart, duplicate delivery, lost local dispatch, unverified-queue starvation, stale scheduler admission/complete/release, protocol negotiation and token confidentiality. The 16 opt-in external integrations remain unrun.
- Frontend production build passed. Focused static checks for new modules/tests passed; `git diff --check` passed. Existing UI behavior is preserved; no new browser visual regeneration was needed for this backend/worker packet.
- Prepared `scanner-v1-drain.patch`, an API-only bridge against `6d4a4aa`. Applied and checked in a detached worktree: **19 v1 worker/bridge tests passed**, including pausing new allocation while preserving the queue and held-job progress. The bridge has not been deployed.
- Published implementation commit `50233b68dab9e0f4bfeb92e7d1a0066d960e88fd` on `codex/scan-execution-recovery` in both repositories and verified the remote refs match. Both `main` branches remained at `6d4a4aa`.
- Opened [draft PR #1](https://github.com/Yoosuph/cyphward/pull/1). [CI for the implementation](https://github.com/Yoosuph/cyphward/actions/runs/38404901759) passed backend regression, frontend build and the new PostgreSQL admission/execution race job. This is remote synthetic CI evidence, not a production scan.
- Coordinated production readiness remains a separate release gate. No Packet 02 migration, live scanner replacement, production scan/event/email or customer-data mutation has been performed. The owned scratch PostgreSQL server was stopped and the temporary v1 bridge worktree removed after validation.

Accepted intermediate asset/finding/notification writes remain incremental; cancellation does not erase already accepted history. Email is best-effort after terminal commit. Coverage/versioned assessment/report work remains in Packets 03–04. The rollout runbook explains the drain gate, additive upgrade, compatible deployment order, recovery and rollback boundaries.

## Packet 02 rollout checks in progress

- Shipped the separate v1 drain bridge (`f511403`), set claims paused and verified authenticated 204 responses. Scanner and cron work drained before stopping the idle worker and preserving its image for rollback.
- Took fresh full/application dumps from one exported PostgreSQL snapshot. Restored the application privately, matched all 11 table counts and rehearsed the upgrade. Applied only the new execution migration in production; row counts were unchanged and both new unique indexes/app-role access were verified.
- Merged PR #1 as `11cdcea` and synchronized both main refs. Render API and primary VPS CD completed. Verified v2 protocol negotiation, required authority headers, API/database health, worker source/image protocol and an authenticated empty claim from the actual container while claims stayed paused.
- Final readiness regression reproduced delayed heartbeats/duplicate progress moving a finished stage backward. Added terminal-state and stage-order preservation under the same claim transaction. Fresh full validation after that fix: **426 passed, 16 skipped**, including **21 execution PostgreSQL cases** and **14 admission cases**. Claims remain paused until this final fix is deployed and checked.

Never include credentials, private keys, customer evidence or raw production personal data in this record. Keep implementation, validation and deployment states separate.
