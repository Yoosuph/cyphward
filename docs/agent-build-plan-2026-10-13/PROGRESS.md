# Agent progress record

**Last updated:** 15 October 2026
**Baseline:** `c7edb77`
**Current state:** Packets 00–02 are released. Packet 02's production migration, API and VPS worker are verified; claims are enabled. API implementation revision is `1948e42`, worker-affecting revision is `11cdcea` (worker/shared files are identical between those revisions). Packet 03 target-selection, DNS/Nuclei-evidence and scoring-gate slices are implemented on the review branch `codex/scan-scope-coverage`, based on `76c80a4`; they are not deployed and Packet 03 is not complete.

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

Implement Packet 03 using `03-scan-scope-and-coverage.md`. Preserve the released admission/execution guarantees. The outcome is defensible requested/evaluated/omitted/failed scan scope and coverage, not report redesign or wider admin expansion.

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

## Packet 02 completed rollout

- Shipped the separate v1 drain bridge (`f511403`), set claims paused and verified authenticated 204 responses. Scanner and cron work drained before stopping the idle worker and preserving its image for rollback.
- Took fresh full/application dumps from one exported PostgreSQL snapshot. Restored the application privately, matched all 11 table counts and rehearsed the upgrade. Applied only the new execution migration in production; row counts were unchanged and both new unique indexes/app-role access were verified.
- Merged PR #1 as `11cdcea` and synchronized both main refs. Render API and primary VPS CD completed. Verified v2 protocol negotiation, required authority headers, API/database health, worker source/image protocol and an authenticated empty claim from the actual container while claims stayed paused.
- Final readiness regression reproduced delayed heartbeats/duplicate progress moving a finished stage backward. Added terminal-state and stage-order preservation under the same claim transaction. Fresh full validation after that fix: **426 passed, 16 skipped**, including **21 execution PostgreSQL cases** and **14 admission cases**. Shipped the fix as `1948e42`; [origin CI](https://github.com/Yoosuph/cyphward/actions/runs/38458071720) and [fork CI](https://github.com/kankarofi125/cyphward/actions/runs/38458068465) passed.
- Enabled claims and explicitly redeployed the API with the new environment value. Verified the enable deployment was live, authenticated v2 metadata was correct and database health was connected before bringing the worker back into normal service.
- VPS service/container are active with the existing 640 MiB memory/no-extra-swap limit. Container protocol is v2 with required claim fields. Authenticated negotiation/empty claims succeeded from the actual container while paused; normal daemon polling after enable showed successful protocol requests and no authentication/version errors.
- Both main refs were synchronized at the implementation revision. Fork scanner CD is intentionally skipped; only the primary repository operates the VPS. The API-only final fix did not change worker/shared source relative to the verified worker revision.
- Post-rollout historical scan counts matched the private preflight; no queued/running jobs were present. No synthetic tenant or scan was inserted into production, and no new live domain assessment was invoked for validation. Real-database mutation/race evidence remains synthetic local/CI evidence; live checks established migration, deployment, authentication, readiness and polling.
- Fresh private full/application dumps and restore/migration verification are retained outside Git. Temporary database servers and the bridge worktree are cleaned up after release.

Never include credentials, private keys, customer evidence or raw production personal data in this record. Keep implementation, validation and deployment states separate.

## Packet 03 — target-selection foundation, 14 October 2026

Review branch: `codex/scan-scope-coverage`, based on released main `76c80a4`. This is the first slice, not the completed packet or a production release.

### Verified source findings

| Boundary | Source finding | Current action or remaining work |
| --- | --- | --- |
| DNS target selection | Local recon sliced discovery to 40; worker used up to 500. Sorted discovery/seed union could omit registered hosts. | Both now use `shared/scan_scope.py`, with explicit `SCANNER_DNS_MAX_HOSTS` job limits (default 40). Scanned domain first, sorted registered hosts next, then sorted passive hosts. |
| Selection evidence | Scope/cap filtering did not persist exclusion reasons. | New discovery `target_selection` version 1 records requested/selected hosts, limits and invalid/out-of-scope/cap reasons under the producing attempt. Selection is intent, never successful evaluation. |
| Worker probe inputs | Worker HTTP/ports selected any DNS hostname, unlike local gating on `primary_ip`. | Worker now also requires a public-address DNS result and suffix scope; existing actual connection/tool guards remain in place. |
| DNS outcomes | Resolver catches individual query errors and returns empty fields; DoH fallback queries a smaller record-type set. | Still outstanding: distinguish negative DNS answers from failed/unattempted per-record checks before allowing DNS finding resolution. |
| Tool coverage | Tool batches distinguish host success/failure; Nuclei success does not prove each template ran. | Still outstanding: requested/evaluated check/template identity, tool/template versions and conservative detector-specific resolution. |
| Network enforcement | HTTP pins requests to revalidated IPs; Naabu passes a validated IP; Nuclei receives a hostname after a preflight resolution check. | No new claim of complete external-tool network isolation. Actual tool/egress boundaries and deployment controls require further review/testing. |
| Scoring | Finalizer passes a completed assessment to organization scoring without a per-check evaluation gate. | Still outstanding: truthful unassessed/partial semantics and distinguish organization risk from selected-scan assessment scope. |
| Customer presentation | Existing scan details expose only current-producing-attempt raw observations. | Discovery details now show requested/selected/excluded targets with readable reasons. Missing/unknown version explicitly says selection was not recorded. Existing history remains scrollable. |

### Compatibility and validation

- Additive JSON observation contract; no new migration and no historical backfill. Required protocol v2 authority stays intact. Older v2 workers may still operate without selection records; their coverage remains unknown. Upgraded workers default to the conservative 40-host DNS cap when an older API lacks the new job limit. The complete coverage contract is still to be designed/implemented.
- Fresh owned PostgreSQL 18.6 cluster bound only to `127.0.0.1:55433`; full 25-migration bootstrap; test database `cyphward_test`, restricted `cyphward_app`. No restored customer snapshot or inherited production database connection was used.
- Full backend suite: **434 passed, 16 skipped**. This includes **22 execution PostgreSQL cases** and the preserved admission cases. The new independent-connection case verifies current-attempt target-selection persistence, retained older evidence, stale-write rejection and Core loading only the current producing attempt.
- Local/worker stubbed recon cases verify the same deterministic selection, registered/apex priority under caps, explicit invalid/out-of-scope omissions and no worker HTTP probe for a DNS result without a public address.
- Frontend production build passed. Scan-page browser suite passed desktop/390px/320px with expanded exclusions, legacy unknown-selection text, scrollable history and preserved launch/RBAC/polling behavior. Browser APIs and external scanners were stubbed; this is not live scanning/network-isolation evidence. The prior non-failing Vite post-assertion proxy `ECONNREFUSED` recurred.
- No production migration, main push, worker replacement, live target scan or customer-account mutation is part of this slice. Review branch publication does not deploy the VPS.

Next: complete versioned per-target/check outcomes and tool/template identity, explicit downstream omissions and deadlines, conservative DNS/template resolution and truthful scoring. Then perform the packet's complete acceptance/release review. Do not begin Packet 04 or broader admin work yet.

## Packet 03 — DNS query evidence and email verification, 15 October 2026

Continued the same review branch and [draft PR #2](https://github.com/Yoosuph/cyphward/pull/2). The initial target-selection implementation `d7bbfc5` passed all three primary-repository CI jobs before this continuation.

- Verified the resolver swallowed all per-question errors, DoH discarded answers for other native questions when A succeeded, and the old resolution/recheck gates could use unrelated DNS/HTTP success as proof of an email check. These source findings are addressed by this slice.
- Added `records.query_coverage` version 1, keyed by A/AAAA/CNAME/MX/TXT/NS/DMARC. Each record includes the exact question name/type, source, start/completion timestamps and answered/no_data/nxdomain/failed outcome. A negative DNS response is distinct from timeout/SERVFAIL, malformed data and truncated responses.
- DoH retries only failed questions, queries the complete supported set, filters answers by record type and correctly joins TXT chunks. Fallback preserves the native attempt's failure metadata and unrelated native answers. Socket-derived IP inventory does not certify TXT or DMARC evaluation. Blocking native/socket work runs outside the event loop so it cannot block lease heartbeats.
- Both local and remote DNS stages preserve partial observations and attempted/successful/failed host coverage. A host is fully assessed only when all seven supported questions have conclusive outcomes. Per-query successes remain available when another query fails. Invalid/mismatched returned hosts cannot become success or inject observations for another target.
- SPF and DMARC finding generation, baseline resolution and remediation verification use the exact query required by a known check. Legacy/missing coverage and unknown DNS rule titles cannot certify a fix. A DNS-only recheck does not depend on an unrelated HTTP probe. This is still the existing limited email-check set, not validation of every SPF/DMARC mechanism or policy syntax.
- Fresh synthetic loopback `cyphward_test` database on port 55433, full 25-migration bootstrap, restricted `cyphward_app` connection. Full suite: **455 passed, 16 skipped**, including all admission/execution PostgreSQL cases and **21 new DNS cases**. The subsequent DNS-only HTTP-independence refinement passed the **34-test DNS/remediation subset**, then the final full regression again passed **455/16**. DNS, DoH, HTTP and checker dependencies were stubbed where exercised; no live target scan or live DNS query was required by the new tests.
- No frontend source changed in this continuation; the prior build/browser evidence remains scoped to the target-selection slice. Existing UI consumes DNS batch coverage/failure reasons through the existing raw-result contract. This is not a fresh visual or deployment verification.
- Additive JSON only: no migration, backfill or authority change. Core/API must be upgraded before the worker on release; old workers then yield unknown email-query coverage instead of false proof. Production remains unchanged; PR #2 remains draft.

Remaining Packet 03 work: other per-target/check and template outcomes, tool/template version identity, end-to-end deadlines/downstream omissions, actual external-tool/egress boundaries, conservative template resolution, truthful partial/unassessed scoring and full acceptance/release review. Packets 04–09 remain later phases.

## Packet 03 — Nuclei process evidence versus template proof

Implementation: `2eebec3`, same review branch and draft PR #2. Production remains unchanged.

- Source review confirmed that successful-host lists and empty Nuclei JSONL were sufficient to auto-resolve template findings and verify remediation. [ProjectDiscovery describes JSONL as match output](https://projectdiscovery.io/open-source); matcher-status is a match-event field, not a complete per-template execution receipt. We conservatively do not infer a clean template result from absent output.
- Nuclei batches now persist `tool_coverage` version 1: a bounded actual `-version` lookup, requested selector and severity filter, timestamps, per-host process outcome and timeout, and matched template IDs. Unknown/unavailable engine identity remains null. Template-set identity, evaluated templates and negative verification remain explicitly unknown; no synthetic enumeration or completion was introduced.
- Baseline resolution no longer treats successful-host/process lists, including legacy payloads, as template proof. No-match template rechecks are inconclusive and preserve open findings/tasks; confirmed matches for the exact requested template still reproduce findings. The API also rejects an unsupported clean assertion with no matching output. This temporarily limits automatic Nuclei fix verification until genuine per-template completion evidence is available.
- Parser ignores failed-matcher events, rejects explicit error events/invalid matcher status/missing template identity in strict mode, and does not turn those records into vulnerability findings. Engine-version failure/timeout is bounded and reaps the process; an empty batch starts no process. Existing scan subprocess credential isolation is preserved.
- Customer scan details distinguish completed tool runs from checked targets and explain unknown template evaluation. Engine version is shown only when observed. No scoring formula or historical data changed in this slice.
- Preserved unrelated pre-existing billing/public-page changes in the shared workspace. Final verification used an isolated detached checkout of the committed scanner candidate, excluding those unrelated edits. A fresh owned PostgreSQL 18.6 loopback cluster on port 55434 was bootstrapped with all 25 migrations and used through restricted `cyphward_app`.
- Isolated backend suite: **468 passed, 16 skipped**, including the admission/execution PostgreSQL cases and **13 new Nuclei evidence cases**. Frontend production build and browser scan suite passed at desktop/390px/320px, including engine-version/unknown-template text, target scope, history scrolling, role boundaries and intent retry behavior. External tool/version/DNS and browser API calls were stubbed; these are not live template/network-isolation tests.
- No schema migration, main push, VPS replacement, template upgrade, customer scan or production mutation was performed. Review-branch publication does not deploy the scanner.

Next scoring prerequisite verified in source: `score_snapshots.score` is NOT NULL and finalizer completion notifications compare/format a numeric score. A truthful unassessed outcome must update schema, atomic completion, current organization assessment selection, reports and UI together. Do not substitute zero/100 or let an empty scan manufacture a healthy score. Complete remaining template evidence/deadline/egress acceptance before the packet's release.

## Packet 03 — evidence-gated scoring and nullable completion

Implementation `7ee8010`, UI/nullable-history refinements `92eeb49` and `d72bd7a`. Continued the same review branch; not deployed. See `03-scoring-release-notes.md` for the exact contract and rollout boundary.

- `cyphward-risk-v3` keeps severity weights/formula but requires conclusive evaluated security-check evidence. No evidence or legacy/failed assessment yields no numeric score/grade. Partial coverage with known scored open findings yields a qualified known-risk index without a grade or unchecked category health. Partial zero-risk output remains non-numeric rather than manufacturing 100.
- Coverage is derived from authoritative current-producing-attempt observations and successful security-check tasks, with evaluated host/check groups. Inventory and successful tool processes are insufficient. Current adapters never emit complete coverage. The engine's complete branch is reserved for future validated evidence; synthetic complete fixtures are explicit test inputs, not backfilled customer data.
- Added migration `20261015120000_assessment_score_coverage.sql`: allow NULL snapshot scores and add `assessment_coverage jsonb`. Atomic fenced completion writes coverage/snapshot/null score, scan state, audit and a truthful notification together. Existing historical values are untouched. Latest current-risk reads retain completed-scan provenance with unknown coverage rather than inventing historical evaluation.
- v3 trend history excludes null scores and older models. Counts, known risk points and negative drivers survive insufficient coverage. Organization risk remains distinct from selected-scan coverage; retained other-domain findings still count in known-risk burden.
- Dashboard, board report copy/view, report metadata/email, scan detail/status and notifications support the new states. A partial assessment stays partial even if all seven stage processes completed. The existing numeric-availability boolean does not certify full coverage.
- Removed hardcoded clean-surface/TLS strengths and invented actions from the fallback executive summary. Partial/unknown summaries use grounded deterministic findings rather than the LLM. No change to the separate general chat behavior is claimed.
- Preserved unrelated shared-workspace billing/public-site edits. Verification ran on an isolated committed candidate with explicit test connections, external scanning/delivery disabled/stubbed and a freshly bootstrapped owned loopback PostgreSQL 18.6 database on port 55435. The complete **26-migration** chain succeeded, with restricted `cyphward_app` access.
- Full isolated backend suite: **481 passed, 16 skipped**, including **23 execution PostgreSQL cases**, **14 admission cases** and **12 new eligibility cases**. A new real-PostgreSQL case completed an unassessed scan with a null snapshot score/coverage and one non-misleading notification under the existing fence. After the nullable-history/mail-text refinement, the **60-test scoring/mail/eligibility/execution subset** passed.
- Frontend build, score browser suite and scan-page suite passed. Browser coverage includes desktop/390px/320px scan layouts, score refresh/stale-response protection, partial/no-score output after a completed scan, preserved logo/history/RBAC, and completed stages with still-partial coverage. Final type-only refinement passed the production build again. Browser APIs/tool/network calls were stubbed; no live domain was scanned.
- Production migration/API/VPS/frontend remain unchanged. No private data, credentials or backups were added to the repository. New release notes require migration before Core/API, conservative old-worker compatibility, no historical backfill and preservation of null records on rollback.

Next: finish actual per-template completion evidence, remaining per-target/check/tool identities and omission reasons, consistent end-to-end deadlines and real external-tool/egress boundary acceptance. Review and coordinate the full Packet 03 release before Packet 04. Payment activation remains deferred.
