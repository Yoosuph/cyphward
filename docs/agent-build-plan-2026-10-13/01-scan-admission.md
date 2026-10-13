# Packet 01 — atomic, retry-safe scan admission

**Status:** implemented and validated; production migration applied, application release in progress. **Priority:** first implementation packet.
**Problem:** two requests can separately pass quota/overlap checks and create duplicate or excess work. Manual and scheduled requests currently resolve entitlements differently.
**Result:** a single admission policy commits at most one accepted job for the same intent, never exceeds the applicable scan allowance under concurrent admissions, and prevents simultaneous jobs for the same organisation/domain.

This packet changes admission. It does not prove exactly-once tool execution, redesign scoring, introduce worker claim tokens, activate billing, or replace scanner infrastructure.

## 1. Read these paths before editing

| Path / symbol | Reason |
| --- | --- |
| `backend/app/api/scans.py: LaunchScanRequest, launch_scan` | Manual scope lookup, quota check, insert, event/fallback and response |
| `backend/app/workflows/inngest_workflow.py: _daily_scan_sweep, run_daily_scan_schedule` | Scheduled selection, quota, insert, dispatch and cron claim |
| `backend/app/core/plans.py` | Scan usage, monthly limits and legacy mapping |
| `backend/app/billing/subscriptions.py: resolve_plan` | Trial/active/expired/cancelled subscription semantics |
| `backend/app/core/database.py: get_db, _run_query` | Per-call commits; transaction boundary must be explicit |
| `backend/app/core/scan_recovery.py` | Existing local restart behavior |
| `frontend/src/lib/api.ts: apiFetch, launchScan` | Authentication replay, request options and error handling |
| `frontend/src/pages/Scans.tsx` | Main launch UI |
| `frontend/src/pages/Overview.tsx` | Dashboard launch UI |
| `frontend/src/pages/onboarding/OnboardingComplete.tsx` | Onboarding launch UI |
| `backend/tests/test_plan_entitlements.py`, `test_billing.py`, `test_scheduler.py`, `test_api.py` | Existing quota and response expectations |
| `backend/tests/conftest.py` | Fake SQL matching; do not confuse it with a transactional database |
| `supabase/migrations/`, `docs/database-upgrade-runbook.md` | Existing schema, grants and upgrade constraints |

Search for all other runtime `INSERT INTO scans` and `launchScan` calls again. Seed scripts are fixtures, not alternate production launch APIs. Avoid circular imports between the new shared admission code and workflow dispatch.

## 2. Product and API decisions for this packet

These are proposed implementation defaults, deliberately stated so the agent does not invent incompatible behavior while coding. Record any material contradiction found in current source.

1. **Permissions:** preserve owner/admin authorization and tenant-scoped verified-domain selection. Reject unverified or another tenant's domain. Existing no-domain-ID requests continue to select the first eligible domain.
2. **Overlap:** at most one `queued` or `running` scan for a given `(org_id, domain_id)`. Different domains in the same organisation may be admitted within quota; worker capacity controls execution. Replace the scheduler's inconsistent organisation-wide prefilter with this explicit per-domain policy. A second distinct request for an active domain returns a useful conflict and creates no new row.
3. **Quota:** use subscription-aware `resolve_plan` semantics for manual and scheduled admissions. Read authoritative state during admission. Preserve current plan limits and the rule that newly created scan rows count toward the UTC calendar-month allowance, including scans that later fail/cancel. Do not introduce refunds or change plan prices.
4. **Idempotency:** support an optional `Idempotency-Key` header for backward compatibility. New browser requests supply a fresh opaque UUID for each deliberate launch intent. Scope persisted keys to tenant, initiating actor and server-owned request namespace. Scheduled keys use a separate server namespace and UTC schedule date plus domain.
5. **Replay:** a valid repeated key and matching request returns the same scan ID, even if the scan has since completed, failed or been cancelled. Return current job status; do not claim a new scan was queued. Do not reapply quota or dispatch again solely because the request was replayed. Check current caller access before exposing anything.
6. **Conflict:** a reused key with a different request fingerprint returns HTTP 409. Do not silently repurpose the key. Persist the original selector/fingerprint and resolved domain, so an omitted-domain replay does not select a different default after domain changes.
7. **Legacy requests:** missing keys still receive atomic quota and active-domain protection. Do not promise full replay deduplication once a legacy request's previous job has become terminal.
8. **Response compatibility:** preserve the successful response's `message`, `scan` and `domain` fields and existing dispatch information. New metadata such as `replayed` may be additive. Preserve HTTP 402 for exhausted quota and existing permission/not-found behavior.
9. **Useful conflicts:** use a plain-text `detail` plus stable top-level `code` such as `scan_already_active` or `idempotency_key_reused`. An active scan ID may be returned only after tenant/permission checks. Extend the frontend error object to preserve code/context without breaking existing string-detail callers.
10. **Retention:** declare a 90-day initial minimum for successful request-key mappings, subject to authorised tenant deletion. This packet need not add a cleanup job. Keep replay stable while the mapping is retained and never silently delete keys when a scan becomes terminal. Validate key format/length and bound storage; use a documented maximum of 128 characters.

If a replay's underlying domain has been removed or caller permissions revoked, deny access safely without creating a replacement scan. Do not retain personal/customer records indefinitely merely to preserve idempotency; later retention work must document the guarantee's boundary.

## 3. Transaction design requirements

Create a shared admission function in a small backend module, used by both entry points. Its result should distinguish **created**, **replayed**, **active conflict**, and **quota rejected**. HTTP and cron adapters translate those outcomes; they must not duplicate policy.

Within one connection and explicit database transaction:

1. Establish tenant admission serialization using an organisation row lock or an equivalently justified database mechanism. An in-process lock is insufficient across replicas.
2. Inspect a matching persisted request key before performing new-admission quota/overlap decisions; preserve safe access checks and fingerprint verification.
3. Recheck selected-domain ownership/verification and authoritative organisation/subscription state. Use consistent lock ordering where more than one row must be locked.
4. Check active-domain overlap and current-month usage under that serialization boundary.
5. Insert the new queued scan, initial stage progress and successful request-key mapping atomically. Record the admission audit atomically if possible; otherwise specify and test audit-failure behavior so committed work cannot become a duplicate after a retry.
6. Commit before publishing events or invoking any pipeline. Never hold a database lock while waiting for HTTP, DNS, tools, email or Inngest.

All runtime creators must participate in the same serialization policy. Add database uniqueness for active domain jobs and persisted request keys where compatible with existing data, rather than relying only on a pre-insert read. Inspect duplicates before introducing the index and prepare a repair proposal if needed; do not delete data to make migration succeed.

Capture a consistent UTC admission timestamp for both the quota window and new row's creation time, including month-boundary waits. Make scan-usage display use the same month definition without changing unrelated domain/member/report quotas.

Use bounded lock/transaction timeouts and explicit rollback on failure. Pooled connections must not return with an open failed transaction. Do not build the transaction from independent `execute_one` calls that each commit. If retrying a database conflict or uncertain commit, retry the same request identity; do not issue a new scan with a new key.

Document concurrent subscription-change semantics and verify no stale request-supplied plan determines admission. Preserve current trial, active, expired, cancelled and legacy behavior. Avoid a general billing rewrite.

## 4. Dispatch boundary and limitations

Remote mode's committed queued row is the durable worker input. Event publication failure must not create another row or trigger local reconnaissance. A replay must not dispatch again.

For local mode, preserve the existing event/fallback behavior and startup recovery contract. The current design has crash/duplicate-delivery limitations; describe them accurately and defer a durable outbox/consumer-fencing redesign to Packet 02. Do not claim that one admitted row proves exactly-once execution. A failed/cancelled replay returns that same job; a deliberate new launch requires a new intent/key.

Only newly created jobs enter the normal dispatch adapter. Preserve existing audit action meaning and cron result fields; add separate replay/overlap counts if needed. Scheduler retries for the same day/domain must not create a second scheduled job even if the original has already become terminal. Keep the daily 06:00 UTC trigger unchanged.

## 5. Frontend behavior

Apply the same intent/key lifecycle to all three launch surfaces through shared code where practical. Generate the key before sending, preserve it through authentication refresh and an uncertain network retry, and clear it on a definitive outcome or deliberate new intent. Scope/reset pending intents when the selected organisation/domain changes; never carry one customer's pending launch into another workspace.

Repeated clicks while pending remain disabled. A network error offers retry of the same intent. If a modal is reopened after an uncertain result, preserve that pending intent during the current page session. A page reload may create a new intent unless explicitly persisted; the server active-domain guard still applies. Document this boundary rather than claiming deduplication for every lost client state.

For an active-domain conflict, display that work already exists and provide a supported route to inspect it. Add selection/navigation plumbing only if needed; do not link to an unsupported scan-detail URL. Quota errors explain the allowance without activating payments. Preserve the approved scan page layout, history scrolling and non-overlapping polling.

## 6. Required acceptance tests

Use independent real PostgreSQL connections and synchronization barriers for races. Seed unique synthetic tenants, users, subscriptions and domains in an owned disposable database. Stub all external dispatch/tool/email calls.

| Case | Required result |
| --- | --- |
| Two requests, same actor/tenant/key/payload | Same scan ID; one row and one successful key mapping; dispatch adapter called for creation only |
| Same key, different domain/selector | HTTP 409; no additional job or mutation of the original mapping |
| Same key after terminal status | Original ID/current status; no new allowance consumption or dispatch |
| Replay after quota becomes exhausted | Original authorised result remains retrievable without being treated as a new admission |
| Replay after default-domain order changes | Original resolved domain remains bound to that request |
| Distinct keys, same active domain | One creation, one useful conflict; no generic uniqueness/500 error |
| Distinct domains, one allowance remaining | At most one creation across concurrent requests |
| Manual versus scheduler, same domain | At most one active job, with the same policy on both paths |
| Scheduler retry after original job completes | Same scheduled identity for that UTC day/domain; no second scheduled row |
| Different domains, available allowance | Both can be admitted; no accidental organisation-wide one-job restriction |
| Trial/active/expired/cancelled subscription | Manual and cron agree with `resolve_plan`, even when `organizations.plan` differs |
| UTC month rollover and non-UTC DB session | Counted usage and insertion timestamps use the same UTC period |
| Unverified/cross-tenant/member requests | Existing authorization boundaries hold; conflict/replay does not leak another tenant's scan |
| Same raw key in different tenants | Independent isolated identities; no cross-tenant deduplication or result leak |
| Failure before commit | No partial scan/key mapping; connection rolls back cleanly |
| Lost HTTP response after commit | Retrying the same key returns the committed job |
| Remote event outage | Queued row survives; no local scanner fallback; no duplicate creation |
| Frontend auth/network replay | Same intent key is reused; definitive new launch gets a different key |
| Browser regression | All launch surfaces, role restrictions, errors, workspace change, 320px/390px/desktop, history scroll and slow polling remain usable |

Also test migration application against a representative existing schema, duplicate-data rejection with a clear runbook, least-privileged database access and optional-key compatibility. A concurrency test that mocks database locks or merely asserts SQL strings does not satisfy these cases.

## 7. Definition of done and handoff

- One shared admission policy serves manual and scheduled paths.
- Additive migrations and API compatibility are documented; no unrelated schema cleanup.
- Focused tests, required isolated-PostgreSQL races, backend regression and relevant frontend checks have actual results recorded.
- The change is reviewed for tenant boundaries, transaction lifetime, uncertainty after commit and duplicate dispatch assumptions.
- `PROGRESS.md` records modified files, test command(s), new migration names, decisions, limitations and release order.
- Final response clearly states whether the work is review-ready, committed, pushed, deployed or production-verified. Do not blur these states.

If isolated PostgreSQL cannot be run, complete the implementation and safe test harness that can be completed locally, then mark the concurrency evidence incomplete. Do not call Packet 01 validated or release-ready based solely on fake-database tests.
