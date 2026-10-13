# Paste this into the next AI coding agent

You are working on Cyphward in `/home/consigliere/Desktop/cyphward`.

Read before editing:

1. `AGENTS.md` and applicable nested instructions.
2. `docs/agent-build-plan-2026-10-13/README.md` and `PROGRESS.md`.
3. `02-scan-execution.md` and `02-release-runbook.md` in that directory.
4. `.github/workflows/deploy-scanner.yml` and `.github/workflows/ci.yml`.
5. `01-scan-admission.md` and the growth strategy for preserved foundations/context.

**Packet 01 is released. Packet 02 is implemented and locally validated on `codex/scan-execution-recovery`, based on `6d4a4aa`. Its production migration/API/worker release is pending.** The next assignment is reviewing and coordinating that release, not rebuilding admission or silently combining later packets.

Inspect the actual commit, branch and working tree first. A main-only checkout may lack the candidate; obtain the review branch before concluding that the implementation is missing. Preserve other existing changes. The strategy/handoff documents are committed.

Review the complete mutation inventory and transaction/state-transition design in `PROGRESS.md`. Required v2 claim authority covers worker, local execution, Core/helper writes and cron ownership. Observations are bound to the producing recon attempt, which survives Core takeover. Terminal score/notification/audit records and completed state commit together. Verify that new direct database operations use the explicit claim fence and that no optional compatibility path bypasses it.

Run real-PostgreSQL acceptance tests using an owned, freshly bootstrapped loopback database named `cyphward_test`, explicit test/application URLs and the restricted role. `backend/scripts/bootstrap_test_database.py` refuses a nonempty application schema and never loads workspace credentials. Never run acceptance tests against a restored customer snapshot, live service or inherited production URL. Stub external scanning, AI and delivery. Report actual results and skips.

Local validation recorded 424 backend passes, 16 optional integration skips, a passing frontend build, and 19 tests for the v1 drain bridge in a detached baseline worktree. Verify evidence against the actual candidate revision; do not label these local results as a production scan or completed rollout.

For authorised shipping, follow `02-release-runbook.md` exactly: prepare the API-only v1 drain bridge, pause new claims while held work finishes, verify zero running legacy attempts, back up/restore-rehearse, apply only the additive execution migration, coordinate both v2 code sides while claims remain paused, then enable and validate. The supplied bridge patch targets the released v1 source and is not meant to be applied to the rewritten v2 handler. Inspect mirrored CD behavior before releasing to main: a scanner/shared-path push can restart the live VPS automatically.

Carry forward separate explicit shipping authorisation from the session without asking again. This reusable handoff itself does not grant live worker replacement or a production scan. Resolve routine review fixes and test-environment choices autonomously. If a required release action needs new authority or cannot be made safe, complete independent preparation and explain the exact unresolved prerequisite.

Preserve deferred payment activation, dashboard access before DNS verification, verified ownership for scanning, tenant/RBAC boundaries, subscription-aware admission, the scan UI and customer history. Accepted intermediate writes remain incremental; do not claim that cancellation rolls back previously accepted inventory/findings. Email remains best-effort after terminal commit. Do not promise exactly-once external execution/delivery.

After Packet 02 is released, the next engineering phase is Packet 03: defensible requested/evaluated/omitted/failed scan scope and coverage. Packet 04 adds versioned assessment/report reconstruction; later Compliance, Academy and wider admin work remain separate.

Finish with review changes, migrations, protocol version, evidence, rollout state and the next prerequisite. Update `PROGRESS.md` and the handoff archive. Never blur local validation, Git publication, API deployment, worker deployment and live scan verification.
