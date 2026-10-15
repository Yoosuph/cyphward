# Packet 03 — defensible scan scope and coverage

**Status:** in progress on `codex/scan-scope-coverage`; target-selection, DNS evidence and conservative Nuclei evidence/resolution implemented and locally validated, not released. The evidence-gated scoring slice is also implemented. Release scope was trimmed on 15 October 2026 (below). Declared-scope completeness and the organisation grade gate are implemented and validated on the review branch; the remaining step is the coordinated release.
**Dependency:** released Packet 02. Preserve protocol v2 ownership, attempt-specific evidence and monotonic progress.
**Outcome:** users can tell what a scan evaluated, what it omitted or failed to evaluate, and what its findings/score can support.

## Release scope (trimmed 15 October 2026)

Reaching paid pilots now takes priority over exhaustive proof. Packet 03's release scope is:

- target selection and recorded omissions;
- DNS query evidence and the exact-query email-check gate;
- Nuclei process evidence with conservative no-match handling;
- the `cyphward-risk-v3` evidence gate with nullable snapshots;
- **declared-scope completeness**: coverage is complete when every check in a versioned declared check set (`cyphward-checks-v1`) has a conclusive outcome for every in-scope target. Nuclei is reported separately and does not gate completeness.

Moved to **Packet 03b** (not part of this release): a per-template Nuclei completion adapter, per-check identities beyond the declared set, shared end-to-end deadlines across queue/recon/Core (recon-phase budgets landed in `454c10f`), and external-tool/egress boundary verification. Until 03b ships, Nuclei no-match results stay inconclusive, and the customer-facing scope line says so.

The numbered contract below remains the long-term target. Items it lists that fall under 03b are not release blockers for Packet 03.

## Read and map the current behavior

Inspect `shared/contracts.py`, `scanner/runner.py`, local recon/Core finalisation in `backend/app/workflows/inngest_workflow.py`, scanner tool runners, `tool_results.py`, `detectors.py`, the scan/overview/report APIs, risk engine and frontend coverage display. Verify actual source before treating historical observations as current bugs.

Trace requested hosts/checks through discovery, scope filtering, caps, invocation, tool output, persisted observations, normalisation, resolution and presentation. Record where local/remote limits differ and where a cap, timeout or omission loses its reason. Keep a table of those verified source findings in `PROGRESS.md`.

## Implementation contract

The first slice adds `discovery.target_selection` version 1 to existing attempt-specific JSON observations. It records validated in-scope requested hosts, hosts selected for DNS, omitted candidate reasons and selection limits. This is intent, not evidence of successful evaluation. It requires no migration, keeps worker protocol v2 and allows older workers/history to remain explicitly unknown. `SCANNER_DNS_MAX_HOSTS` (default 40) is transported in job limits; both execution paths use the same selection function. Prioritise the scanned domain, sorted registered hosts, then sorted passive hosts. No historical backfill or network-policy deployment is included. See `PROGRESS.md` for actual evidence and remaining work.

The DNS slice adds `records.query_coverage` version 1: each question records its exact name/type, source, timestamps and answered/no-data/NXDOMAIN/failed outcome. DoH retries only failed questions and preserves prior failure evidence. Both paths retain partial DNS observations while flagging incomplete host coverage. SPF and DMARC checks, automatic resolution and remediation verification require their exact completed question. Missing/legacy metadata and unidentified DNS rules remain unknown. Deploy the updated Core/API before the updated worker so old worker evidence is handled conservatively; no protocol bump or schema migration is needed for these additive fields. DNS evidence does not establish complete Nuclei/template coverage or sufficiently evaluated scoring.

The Nuclei slice records `tool_coverage` version 1: observed engine version when available, requested selector/severity filter, batch times, per-host timeout, process outcomes and matched template identities. Template-set version, evaluated templates and negative verification remain explicitly unknown. A successful process is not an exact-template negative receipt; current Nuclei findings therefore remain open when absent from a subsequent scan, and no-match remediation returns inconclusive. Positive exact-template matches still reproduce findings. The UI calls these completed tool runs and explains the evidence limit. This is deliberately conservative until an actual per-template completion adapter exists; do not fabricate coverage from aggregate counts or failed-matcher events.

The scoring slice introduces `cyphward-risk-v3`, nullable score snapshots and assessment coverage version 1. It blocks numeric healthy scores from empty/failed/unassessed evidence, preserves a qualified known-risk index for partial assessments with open risk, and removes unsupported grades/category health/summary strengths. It requires the new migration and coordinated Core/API/frontend deployment. See [scoring release notes](03-scoring-release-notes.md) for eligibility, compatibility and limitations.

1. Define a versioned assessment scope/coverage contract. Persist target identity, requested checks/templates, evaluated checks/templates, tool/template versions, outcomes, timestamps, limits and exclusion/cap reasons. Bind authoritative observations to Packet 02's producing recon attempt and current claim.
2. Distinguish successful evaluation with no finding from failure, omission, skipped checks and unknown legacy coverage. Missing fields from old workers/history cannot become evidence of a clean check. Do not backfill fabricated success.
3. Use one explicit policy for local/remote scope, limits and end-to-end deadlines. Prioritise registered hosts, explain the domain-apex policy and expose omitted targets. A passive discovery result is not an exhaustive asset inventory.
4. Keep verified-domain authorisation mandatory. Scope rules must hold through redirects, DNS resolution and actual connection/tool boundaries. Do not describe mock URL checks as proof of network isolation. Revalidate private/link-local/metadata targets and external-tool behavior; define any necessary egress enforcement and deployment boundary before changing the live VPS.
5. Keep ports/TLS observations as inventory unless supported reviewed detector rules justify findings. Successful tool execution is not proof that every expected rule/template ran on every target.
6. Gate resolution on the exact detector/check that completed for the relevant target. Failed or unattempted checks must leave a finding open or not evaluated; absence of output cannot certify a fix.
7. Define when an assessment is sufficiently evaluated to be scored. Empty/failed/unassessed evidence must not manufacture a healthy score. Preserve the distinction between current organisation risk and the selected scan's assessed scope. Change scoring only to enforce truthful assessed/partial/unknown semantics; document any model-version change explicitly.
8. Expose requested/evaluated/failed/omitted counts and meaningful reasons through API/UI without implying a domain scan proves whole-company security. Preserve the approved desktop/mobile design, scrollable history, slow polling, access controls and workspace isolation.

Choose concrete schema after examining existing records. Add migrations; preserve historical data. This packet does not replace Packet 04's immutable assessment/report reconstruction or build Compliance, Academy, payments or wider administration.

## Compatibility and release

Specify coverage-contract capabilities and version explicitly. If old v2 workers can safely operate with unknown coverage, represent that unknown state conservatively. If the change requires a new protocol, use a coordinated drain/migration/API/worker rollout as in `02-release-runbook.md`; do not silently make authority optional or accidentally trigger scanner CD while preparing a candidate.

Maintain a review branch and additive schema. External tool/template upgrades, network enforcement and live scans need an explicit bounded deployment/test plan. A previous controlled scan is not blanket permission to scan arbitrary customer domains.

## Acceptance evidence

Use synthetic tenants, explicitly owned loopback PostgreSQL and stubbed external delivery/scanning for normal regression. Persist representative fixture observations from successful, empty, partial, failed, timed-out and capped stages. Required cases include:

- Legacy/missing coverage remains unknown and cannot auto-resolve findings.
- A clean evaluated check is distinguished from a skipped/failed check with an empty payload.
- Registered host and passive host counts exceeding a cap produce a deterministic target set and explicit omissions.
- Local/remote runs apply the same documented scope/limit policy.
- Per-target partial tool results only support the successful target/check pairs.
- Stale attempts cannot change coverage or overwrite a later assessment's evidence.
- Private-address, link-local/metadata, out-of-scope redirect and DNS-rebinding cases are addressed at the actual relevant boundaries. State exactly which connection/tool tests ran and which deployment controls remain unverified.
- A zero-evaluated or failed assessment produces truthful unassessed/partial presentation rather than a false healthy score.
- Tenant/role boundaries and all Packet 01/02 concurrency and recovery guarantees remain intact.
- Desktop/390px/320px coverage, history and tracker layouts remain usable; observed browser APIs and real backend evidence are reported separately.

Run the required backend/PostgreSQL suites, frontend build and relevant coverage/score/browser checks. Record actual passes, failures and skips. Use real independent connections for persistence/ownership claims; mocks alone do not prove them. Do not run race fixtures against production credentials or a restored customer snapshot.

## Done and next prerequisite

Update `PROGRESS.md`, `START-HERE.md`, API/worker compatibility instructions and the handoff archive. Deliver the coverage schema/version, migration, source findings, implementation, actual evidence, limits and exact shipping state.

Packet 04 starts after this evidence contract is stable: versioned assessment/report snapshots that reproduce the selected assessment. Consolidated operations/admin capabilities follow the proven workflows in Packet 06.
