# Paste this into the next AI coding agent

You are implementing Cyphward in `/home/consigliere/Desktop/cyphward`.

Read these files in order before editing:

1. `AGENTS.md` and any applicable nested instructions.
2. `docs/agent-build-plan-2026-10-13/README.md`.
3. `docs/agent-build-plan-2026-10-13/PROGRESS.md`.
4. `docs/agent-build-plan-2026-10-13/02-scan-execution.md`.
5. `docs/agent-build-plan-2026-10-13/01-scan-admission.md` for the released foundation.
6. `docs/growth-and-competitive-strategy-2026-10-12.md` for commercial context.

**Packets 00 and 01 are complete. Packet 01 is released as implementation commit `c2ae218`, with its production migration and live API/frontend verified. Your assignment is Packet 02 only.** Implement safe execution ownership and recovery. Packet 02 is specified, but its code has not been built.

First inspect the actual commit, working tree, relevant source and test environment. Documentation may have advanced beyond the implementation revision. Preserve existing changes. The strategy and handoff files are now committed, so a current clone should contain them. Do not repeat Packet 01 or replay historical migrations in a shared database.

Map every mutation made by worker, local recon, Core finalisation and scheduler attempts, including helper calls. Design the state transitions and lock order before editing. Use a new generation/token for each claim and atomically verify current ownership, allowed state and expiry with every mutation. Protect intermediate findings, observations and scores as well as terminal status. Keep external work outside database locks.

Make observation replacement atomic and distinguish recon evidence across attempts from later Core recovery ownership. Preserve historical records. Define local dispatch/restart recovery and reject stale scheduler completion/release. A worker-only patch is incomplete: local pipelines and Core writes also need fencing.

Version the worker/API contract explicitly. Required authority must never become an optional bypass for old workers. Prepare additive schema, queue/drain handling, coordinated rollout and rollback for both code sides. Inspect the scanner deployment workflow before pushing any worker/shared-contract paths: a push to those paths can deploy the live VPS. Do not trigger that deployment accidentally while preparing a local review candidate.

Use a freshly migrated, owned loopback database named `cyphward_test` for concurrency tests, with explicit test and application URLs. Never run tests against inherited production credentials or a restored customer backup. Stub scanners, AI, email and event delivery. Prove behavior with independent PostgreSQL connections and check intermediate data, not only final status.

Payments remain deferred. Preserve dashboard access before DNS verification, verified ownership for scanning, tenant/RBAC boundaries, subscription-aware admission, the approved scan UI, truthful scores/coverage and customer history. Do not build later roadmap packets or redesign reports, Compliance, Academy or the staff console in this assignment.

Apply the model-selection rule honestly when supported. Use strong reasoning for claim, transaction and data-integrity design. Resolve routine implementation choices within the specification without unnecessary confirmation. If a material decision contradicts the specification or needs additional authority, explain the exact issue after completing independent useful work.

Run required acceptance and regression checks; record actual passes, failures and skips in `PROGRESS.md`. Update the handoff archive. Distinguish admission idempotency, execution fencing, dispatch recovery and external-delivery limits. Do not claim exactly-once scanning or delivery from an outbox or lease alone.

The initial deliverable is a review-ready Packet 02 implementation with migrations and coordinated release instructions. Carry forward separate explicit shipping authorisation from the session; this reusable handoff itself does not request live worker replacement, production scanning or customer messaging. When shipping is authorised, synchronize both remotes and verify deployment independently of Git push.

Finish with changed behavior, files/migrations, protocol version, evidence, limitations, exact delivery state and the prerequisite for Packet 03. If required real-database checks could not run, state that Packet 02 is not fully validated.
