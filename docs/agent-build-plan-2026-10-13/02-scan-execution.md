# Packet 02 — safe scan execution and recovery

**Status:** specified; not implemented.
**Dependency:** Packet 01, implementation commit `c2ae218`, is released.
**Deliverable:** a tested implementation with additive migrations and a coordinated API/worker rollout plan.

## 1. Problem and required outcome

Admission now prevents duplicate active jobs and makes launch retries return the same scan. Execution still identifies attempts mainly by scanner ID. A delayed worker can reuse that identity after a lease takeover, and ownership checks can race later database writes. Core finalisation and scheduler completion also need protection from stale owners.

Give every worker, local pipeline, Core finaliser and scheduler claim a distinct generation/token. After cancellation, expiry or takeover, the previous attempt must be unable to change observations, findings, scores, progress or terminal state. Observation replacement must be atomic. Recovery must resume the correct work without silently mixing evidence from different attempts.

This packet is an execution/recovery change. Preserve the scan UI, ownership verification, tenant boundaries, subscription-aware admission, truthful coverage and historical evidence. Payment activation, Compliance, Academy, report redesign and wider admin work remain outside this packet.

## 2. Read and map before editing

- `backend/app/api/scanner_jobs.py`: worker authentication, claim, progress, observations, complete and fail.
- `scanner/client.py`, `scanner/runner.py`, `shared/contracts.py`: request retry, heartbeat, job protocol and stage payloads.
- `backend/app/workflows/inngest_workflow.py`: local recon, Core finalisation, database-writing helpers, event handler and daily scheduler.
- `backend/app/core/database.py`: individual helpers commit separately; consecutive calls are not a transaction.
- `backend/app/core/scan_recovery.py`, `backend/app/core/cron_claim.py`, `backend/app/scheduler.py`: startup recovery and stale cron takeover.
- `backend/app/api/scans.py`: admission, dispatch and cancellation. Preserve Packet 01's replay behavior.
- Notification/audit helpers called by the pipeline, plus the existing scanner, cancellation, scheduler and admission tests.

List every mutation made directly or indirectly by an execution attempt. A protected worker API with an unfenced Core/helper path is incomplete. Record this inventory and the proposed state transitions in `PROGRESS.md` before implementation.

## 3. Ownership contract

1. Claim acquisition is atomic and assigns a new generation and unpredictable token. Reusing a scanner ID never reuses authority from an older attempt.
2. Every mutation checks the exact current owner, generation, token, allowed state and unexpired lease in the same transaction as the mutation. A separate read followed by a write is insufficient.
3. A stale attempt receives a useful conflict and writes nothing. Heartbeats cannot revive expired claims. Check affected-row counts; do not report success after a rejected write.
4. Cancellation and takeover serialize against execution writes. Keep locks bounded and external scanning, AI calls and email delivery outside database locks.
5. Core handoff and recovery grant new authority. Old workers cannot write after handoff; old finalisers cannot write after recovery grants a new claim.
6. Local execution and duplicate event delivery use the same ownership discipline. Do not leave an optional-token path that bypasses fencing.
7. Cron complete/release operations compare the acquired claim's generation/token. An old process must not complete or release a replacement process's run.

Choose the concrete schema after examining existing rows and permissions. Add new migrations; preserve legacy data. Do not backfill fabricated successful attempts or delete historical observations to make a constraint succeed.

## 4. Evidence and finalisation

- Replace observation delete/insert with a transaction protected by the current claim, or an equivalent atomic upsert. An injected failure must preserve the previous committed payload.
- Distinguish the authoritative recon attempt from later Core recovery generations. Core must load the completed recon attempt's evidence; a reclaimed worker must not inherit omitted stages from an older attempt.
- Preserve older evidence as history. If introducing attempt-specific uniqueness, inspect existing duplicate stage rows and define legacy handling before imposing the constraint.
- Fence all Core asset/finding/evidence reconciliation and scoring writes, including helper calls. Check both intermediate and terminal data in tests.
- Persist the terminal state and its mandatory score/result records consistently. Do not release ownership first and then attempt unfenced snapshot/result writes.
- Define what happens when optional AI analysis outlives mandatory scoring or the Core lease. It must not authorise stale writes to completed assessments.
- Recovery and duplicate delivery must not produce duplicate authoritative records. If notification/email delivery remains best-effort, document its limits precisely; do not claim exactly-once external delivery.

## 5. Delivery and recovery

Remote mode already has a durable queued scan row that the worker polls. Preserve that queue during event-gateway failures and never run remote recon in the API process.

Specify local-mode behavior for a crash after admission but before dispatch, duplicate delivery, restart during recon and restart during finalisation. Use a durable retry/outbox or another demonstrably recoverable queue-consumption strategy where needed. An outbox still requires idempotent consumers and bounded retries; it does not establish exactly-once scanning.

Core recovery must select only Core work. Worker lease recovery must not restart recon for a Core-owned scan merely because its lease expired. Stop stale work promptly when a heartbeat loses authority, while retaining the database fence as the final protection.

## 6. Protocol and rollout

Define an explicit next protocol version in the shared contract. Required claim authority travels with the job and every job mutation. Reject incompatible workers before granting them a job; do not allocate a v2 job that a v1 worker cannot safely process.

Prepare the release procedure before shipping:

1. Apply additive schema after a backup and restore rehearsal.
2. Inspect/drain existing legacy worker and Core attempts; define how queued jobs wait safely during the transition. Preserve their evidence and history.
3. Coordinate API and worker deployment so no period silently permits unfenced writes. Record the exact order, readiness checks and handling of incompatible workers.
4. Verify worker version/capabilities and lease recovery. A controlled live scan requires an authorised verified target and a separately recorded live test; local mocks are not that evidence.
5. Define rollback for both code sides. Retain additive data and evidence. Do not roll back only the API if that would silently ignore the new claim authority.

Local implementation and tests can proceed independently. This specification does not itself authorise restarting or replacing the live VPS worker. Carry forward any separate explicit deployment authorisation from the session.

## 7. Required acceptance evidence

Use synthetic tenants in a fresh, owned loopback `cyphward_test` database. Never run race tests against a restored customer snapshot, inherited workspace URL or live service. Use independent connections and test as the restricted application role.

| Scenario | Required result |
| --- | --- |
| Same scanner ID, new claim | Old token/generation rejected on every mutation |
| Expired claim before takeover | No heartbeat revival or progress/observation/complete/fail write |
| Cancellation versus write | Serialized result; no write after cancellation commits |
| Expiry/reclaim versus observation replacement | Current attempt's payload survives; stale attempt changes nothing |
| Failure between replacement operations | Entire operation rolls back; prior payload preserved |
| Reclaimed recon skips a stage | Prior attempt's stage cannot become current evidence |
| Worker completion versus cancel | At most one valid handoff; cancelled scan is never resurrected |
| Worker writes after Core handoff | Rejected without changing intermediate evidence |
| Core recovery versus old finaliser | Old progress, findings, scoring and complete/fail mutations rejected |
| Core restart around terminal persistence | Mandatory results and terminal state remain consistent; no duplicate authoritative record |
| Duplicate event delivery/local execution | One current claim; no concurrent authoritative pipeline writes |
| Stale scheduler complete/release | Replacement claim remains owned and unchanged |
| Protocol mismatch/missing authority | Useful rejection; no job allocated or data mutated |
| Queue/event outage/restart | Documented bounded recovery with no remote-to-local fallback |
| Tenant/RLS/permissions regression | Existing isolation and least-privilege boundaries still hold |

Keep external scanners, AI providers and delivery stubbed for local acceptance tests. Re-run relevant existing scanner/cancellation/scheduler tests, the Packet 01 admission tests, and required full regression/build checks. Report actual passes, failures and skips. Do not equate SQL-string assertions with PostgreSQL race evidence.

## 8. Completion record

Update `PROGRESS.md`, `START-HERE.md` and the handoff archive. Report the state-transition design, migrations, protocol version, rollout/rollback instructions, actual test commands and results, remaining limitations, exact shipping state and prerequisites for Packet 03.

Packet 02 is complete only when worker, local execution, Core and cron ownership are covered. A worker-only patch or untested Core fencing is a partial implementation.
