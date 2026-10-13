# Paste this into the next AI coding agent

You are implementing Cyphward in `/home/consigliere/Desktop/cyphward`.

Read these files in order before editing:

1. `AGENTS.md` and any applicable nested instructions.
2. `docs/agent-build-plan-2026-10-13/README.md`.
3. `docs/agent-build-plan-2026-10-13/01-scan-admission.md`.
4. `docs/agent-build-plan-2026-10-13/PROGRESS.md`.
5. `docs/growth-and-competitive-strategy-2026-10-12.md` for commercial context.

**Packets 00 and 01 are complete and locally validated.** Review the recorded diff and evidence in `PROGRESS.md`, address any review findings, and preserve the release boundary. Do not implement the other roadmap packets in this assignment.

First inspect the actual commit, working tree, relevant source and test environment. The documented source baseline is `c7edb77`; recheck if the repository has advanced. Preserve existing changes, including untracked strategy/handoff files. If this is another checkout, obtain the referenced handoff files before proceeding; a clone may not include them yet.

Build one shared transactional scan-admission path for manual and scheduled launches. Follow the packet's explicit semantics for subscription-aware quota, per-domain overlap, idempotency, UTC accounting, error responses and frontend retry behavior. Extend all three existing launch surfaces. Preserve the current public API shape where specified and the approved desktop/mobile scan UX.

Use an explicitly disposable PostgreSQL environment for race tests. Existing workspace database credentials and some opt-in integration fixtures may target production; do not use them as a shortcut. Stub external delivery and scanning. Prove behavior with real independent database connections, not only mocked SQL tests.

Payments remain deferred. Preserve dashboard access before DNS verification, mandatory verified ownership for scanning, roles and tenant boundaries, existing subscriptions/limits, truthful scores and coverage, and customer history. Do not redesign authentication, worker contracts, scoring, reports, Compliance, Academy or the staff console as part of this packet.

Apply the model-selection rule honestly when supported. Use strong reasoning for transaction and data-integrity design. Resolve routine implementation choices within the specification without unnecessary confirmation. If a material decision contradicts the specification or needs additional authority, explain the exact issue after completing independent useful work.

Run the required checks, document actual passes/failures/skips and update `PROGRESS.md`. Treat durable dispatch/execution guarantees as separate from admission idempotency. Do not claim exactly-once execution from the first packet.

The requested deliverable is a review-ready change with migration and release instructions. Follow any separate explicit shipping authorisation in the session; this prompt itself does not request production migration, deployment, live scanning or customer messaging. When shipping is authorised, follow the documented dual-remote rule and verify deployment independently of Git push.

Finish with the behavior changed, files/migrations, evidence, limitations, exact delivery state and next prerequisite. If a required concurrency check could not run, state that Packet 01 is not fully validated.
