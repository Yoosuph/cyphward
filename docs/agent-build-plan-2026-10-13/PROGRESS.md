# Agent progress record

**Last updated:** 13 October 2026
**Baseline:** `c7edb77`
**Current state:** Packets 00 and 01 are complete. Packet 01 is released as implementation commit `c2ae218` on both repositories, with its production migration and live API/frontend verified. Packet 02 is specified in `02-scan-execution.md`; its code is not implemented.

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

Implement Packet 02 using `02-scan-execution.md` and the current source. The new specification includes worker/local/Core/cron ownership, evidence across attempts, real-PostgreSQL acceptance cases, and protocol rollout/rollback requirements. It is a specification, not implementation evidence. `START-HERE.md` now points the next agent to this assignment.

Never include credentials, private keys, customer evidence or raw production personal data in this record. Keep implementation, validation and deployment states separate.
