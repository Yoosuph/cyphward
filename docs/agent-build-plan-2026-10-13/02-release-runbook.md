# Packet 02 coordinated rollout

**State:** completed rollout; see `PROGRESS.md` for revisions and evidence. The procedure below remains the reference for coordinated deployments.
**Protocol:** v2. API and worker share `shared/contracts.py`.

This runbook is part of the review deliverable. Perform live worker replacement only under the session's separate shipping authorisation. Do not merge this branch casually: the main-branch scanner workflow rebuilds/restarts the VPS, and Render deploys the API independently.

## 1. Prepare and establish the drain gate

- Validate the candidate and scanner image from the same revision. Keep production on the released Packet 01 code while reviewing.
- Identify the repository responsible for scanner CD. Mirror pushes must not cause two independent CD jobs to operate on the same VPS; repository-level concurrency alone does not coordinate two repositories.
- For the current remote deployment, prepare the supplied `scanner-v1-drain.patch` as a **small separate API-only release** against the deployed v1 source. It adds `SCANNER_CLAIMS_ENABLED`, defaulting to true, without changing the worker contract. It does not change scanner/shared paths or require a migration.
- Set `SCANNER_CLAIMS_ENABLED=false` on that v1 API release. The patched claim handler still runs legacy Core recovery, then returns 204 instead of allocating new recon. Held jobs retain progress/observation/complete/fail access. Existing and newly admitted queued jobs remain recorded.
- The bridge was checked against `6d4a4aa` in a detached worktree: its existing worker tests plus an explicit queue-preservation/held-write test passed (19 tests). If production has advanced, rebase and repeat that compatibility check. Do not apply the patch to the already rewritten v2 handler.

A gate is required before stopping the old worker. A zero-running query by itself cannot prevent it from claiming another queued job immediately afterward. If the v1 bridge/gate is unavailable, pause this cutover and prepare it; do not kill customer scans to force a clean preflight.

## 2. Drain and back up

With new v1 recon claims paused, allow held worker and Core attempts to finish. Poll privately:

```sql
SELECT id, status, current_stage, claimed_by, lease_expires_at
FROM scans
WHERE status = 'running'
ORDER BY started_at, created_at;
```

Proceed only when there are **no running legacy attempts**. Queued jobs may wait safely. Stop the old VPS worker after the gate and drain checks. Recheck running rows after stopping. If any remain, investigate their actual owner/recovery state; do not fabricate v2 authority, delete observations or bulk mark customer scans successful/failed.

Take a fresh private backup and rehearse restoring the application schema. Do not reuse an old backup merely because Packet 01 had one. Record backup checksums, restore result, preflight timestamp and application row counts outside public artifacts containing customer data.

For local-mode deployments, drain old unleased pipelines too and prevent new v1 local execution through an operator maintenance window. The remote scanner gate does not control old local pipelines.

## 3. Expand the schema

Apply **only** `20261013130000_scan_execution_fencing.sql` in a transaction with bounded lock/statement timeouts. Record the migration version through the normal migration mechanism. Do not replay destructive historical migrations or seeds remotely.

The migration adds:

- Current claim generation/token, recon observation generation and execution phase on scans.
- Attempt generation and a partial attempt/stage unique index on raw results; legacy NULL-generation rows are preserved.
- A nullable assessment scan ID and partial unique assessment index on score snapshots; historical snapshots remain intact.
- Generation/token/expiry on cron claims.

Verify index validity, existing row counts, app-role grants and RLS behavior. Existing table privileges cover the additive columns; verify through the actual restricted application connection rather than assuming a successful administrator migration proves app access.

## 4. Deploy v2 while claims remain paused

1. Deploy the candidate API and worker from the same approved revision. Keep `SCANNER_CLAIMS_ENABLED=false` throughout deployment.
2. New workers negotiate `GET /api/v1/scanner/protocol` before POSTing a claim. A v1 API returns no compatible protocol metadata, so the v2 worker backs off without allocating a v1 job. This helps with deployment order, but does not replace draining legacy attempts or waiting for all old API replicas to leave service.
3. v2 API authentication still requires bearer key, scanner ID and timestamp, plus `X-Scanner-Protocol: 2`. Job mutations also require `X-Claim-Generation` and `X-Claim-Token`. Missing, invalid, expired or superseded authority cannot become an optional compatibility bypass.
4. Independently verify API revision, `/health`, v2 OpenAPI and authenticated protocol negotiation. Inspect worker image/source revision and service state; a log containing `polling` only proves startup, not successful protocol negotiation.
5. In remote mode, v2 workers get 204 while claims are paused. Core recovery runs independently. No queued scan should be assigned to local recon.
6. After both sides are ready and every API replica is v2, set `SCANNER_CLAIMS_ENABLED=true`. Observe queued claims, lease renewal, recon-to-Core handoff and eventual terminal records.

Keep keys/tokens out of command output, screenshots, Git and this handoff. This protocol uses opaque attempt tokens; customer list/detail/launch responses exclude them.

## 5. Authorised live validation

Use a separately authorised verified domain for a controlled scan. Record the scan ID and source/tool versions privately as needed. Confirm:

- Launch retry returns one scan and does not consume additional admission allowance.
- Job mutations use the returned v2 attempt authority; no v1 request allocates work.
- Observation rows belong to the current recon attempt; old evidence cannot fill a newly omitted stage.
- Handoff revokes worker authority and retains the producing recon generation for Core.
- Completed state, one score snapshot, completion notification and audit record are committed consistently.
- Frontend tracker, current score, history and reports still work with the resulting assessment.

Do not deliberately crash the live worker or inject customer-data race tests. Failure/reclaim/cancel acceptance evidence comes from the independent-connection synthetic PostgreSQL tests. A live read-only deployment check is not a live launch/replay test.

## 6. Recovery and rollback

- Remote queued scans survive event-gateway outages and are polled by the worker. API replicas recover expired Core claims without restarting recon.
- Local queued scans are consumed by the independent recovery loop, including lost dispatch. New local attempts lease for 120 seconds and heartbeat at most every 30 seconds; Core leases last 900 seconds. After a crash, recovery waits for lease expiry plus a polling tick rather than stealing a live owner's job.
- Per-process recovery concurrency is bounded at two tasks. `CYPHWARD_EXECUTION_RECOVERY_ENABLED=false` disables that consumer; if disabled in local mode, lost dispatch cannot be recovered by that loop.
- Optional AI has a bounded deadline (`CORE_AI_TIMEOUT_SECONDS`, default 120 seconds). A failed/timed-out AI stage is recorded while mandatory assessment completion remains possible under the current claim.
- If a rollout check fails before enabling claims, keep queued work paused and fix readiness. Retain the additive schema and historical evidence.
- Once v2 attempts exist, prefer a forward fix. A v1 API rollback ignores fencing and attempt-specific evidence, so rolling back only one code side is unsafe. Drain v2 attempts with the gate, back up and explicitly reconcile queue/evidence compatibility before a coordinated two-sided rollback.
- Accepted intermediate asset/finding/notification writes are incremental and are not retrospectively erased by cancellation. Every subsequent write still requires the live claim. Versioned report/assessment reconstruction remains Packet 04.
- Emails after authoritative completion remain best-effort: a crash after the terminal commit can lose email delivery. External scanning/email is not claimed to execute exactly once.

## 7. Repeatable synthetic checks

`backend/scripts/bootstrap_test_database.py` takes only explicit `CYPHWARD_TEST_DATABASE_ADMIN_URL` and `CYPHWARD_TEST_DATABASE_URL`. Both must identify the same owned loopback database named `cyphward_test`; the application role must be `cyphward_app`. Bootstrap refuses an existing application schema. It never loads workspace .env or falls back to its production URL.

After bootstrap, set `DATABASE_URL` to the same synthetic application URL, disable scheduling/recovery and external providers, then run:

```bash
python -m pytest backend/tests/test_scan_admission_postgres.py backend/tests/test_scan_execution_postgres.py -q
python -m pytest backend/tests -q
npm run build --workspace frontend
git diff --check
```

The PostgreSQL CI job creates an owned loopback cluster and runs the same bootstrap and acceptance modules. Tests use synthetic tenants, independent connections and the restricted role. Never use the private restore-rehearsal database holding customer records for these tests.
