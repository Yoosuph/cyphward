# Scanner and feature readiness before broader administration

Reviewed current local source on 11 October 2026. This is a follow-up to the
earlier platform, onboarding and mobile reviews, rather than a replay of their
original findings. Existing working-tree changes were preserved. No customer
domain was scanned and no deployed worker, database, network policy or migration
was inspected. Payment-system activation remains deferred.

## Changes made in this pass

- **Mobile dashboard identity:** Topbar's 17px shield and abbreviated CYPH text
  became a 32px shield with the full CYPHWARD wordmark. Brand visibility follows
  the 901px desktop-navigation breakpoint. At narrow phone widths the secondary
  section label gives way to the brand. Browser checks measure the logo and
  check overflow at 320, 390, 820 and 1280px.
  Visual inspection also found duplicate SVG paint IDs shared with the hidden
  sidebar. Each logo now owns unique gradient/filter IDs, restoring its shield
  instead of displaying only the small central mark.
- **Tool failure coverage:** Nuclei, Naabu and SSLyze batches distinguish
  successful hosts from failed hosts. Missing tools, refused targets, non-zero
  exits, timeouts and malformed output are not clean empty assessments. Empty
  eligible-target lists are skipped. Results from successful hosts survive a
  partially failed batch.
- **Finding integrity:** local recon and remote recon persist per-host coverage;
  failed Nuclei targets do not automatically close previous findings. Legacy
  attempted-only payloads retain findings until fresh coverage is available.
  A general stage failure without partial-host proof cannot authorize closure.
- **Remediation integrity:** non-zero Nuclei template reruns are inconclusive.
  HTTP without an observed certificate cannot verify a TLS certificate fix.
  Unreachable HTTP and unobserved certificates cannot auto-resolve corresponding
  existing findings during finalization.
- **Cancellation:** a heartbeat reporting lease loss interrupts active recon,
  and tool subprocesses are cleaned up on cancellation. The worker checks the
  lease at least every 30 seconds while a stage runs, rather than merely logging
  loss and continuing. This is cooperative cancellation, not instantaneous
  interruption of blocking synchronous calls.
- **Visible partial results:** the Scans page shows failed/skipped states,
  reasons, host counts where available and “Completed with limited coverage.”
  Security-check exceptions are recorded as failed stages. A completed job is
  not presented as proof that every check ran.
- **Honest claims:** negotiating TLS 1.2/1.3 no longer claims that legacy TLS is
  prohibited. The mobile findings indicator no longer starts with a fabricated
  count of five.
- **Scan-launch readiness:** owners/admins can launch from verified domains;
  members are not offered the restricted launch action. Users with no verified
  domain are directed to domain setup rather than submitting a failing scan.

Relevant implementation:
[tool results](../../backend/app/scanner/tool_results.py),
[Nuclei runner](../../backend/app/scanner/nuclei_runner.py),
[worker](../../scanner/runner.py),
[finalization](../../backend/app/workflows/inngest_workflow.py),
[Topbar](../../frontend/src/components/Topbar.tsx),
[scan screen](../../frontend/src/pages/Scans.tsx).

The original assumption that Nuclei exit code 1 means “no matches” was unsafe:
the CLI has fatal runner/configuration paths. Non-zero results now provide no
closure proof. [ProjectDiscovery's CLI source](https://github.com/projectdiscovery/nuclei/blob/dev/cmd/nuclei/main.go).

## Remaining scanner foundations, in priority order

| Priority | Confirmed gap / practical consequence | What to build before relying on it in administration |
|---|---|---|
| P1 | **Coverage is still coarser than a rule.** A successful process does not prove every previous template was loaded/evaluated. Nuclei defaults to `http/` and HTTPS, even for hosts discovered via HTTP. DNS helpers catch query errors as empty records; `robots.txt` errors are swallowed. | A versioned scan manifest with actual target URLs, per-record/per-rule outcomes, evaluated template IDs, tool/template versions, target exclusions and cap reasons. Resolve a finding only from proof for its corresponding rule. Preserve “not evaluated” for unavailable evidence. |
| P1 | **Port/TLS outputs are stored but not fully consumed.** Finalization builds finding input from shared security checks and Nuclei; separate `open_ports` and `tls_profiles` do not feed equivalent normalization. | Reviewed port-exposure and TLS rules with evidence/remediation, or display these stages explicitly as inventory/diagnostics until supported. Port numbers alone should not claim an authenticated service or a vulnerability. |
| P1 | **Lease/observation writes lack a complete atomic boundary.** `_held_job` checks identity/status separately from delete/insert of observations. It does not reject expiry itself. Reuse of the same scanner ID cannot distinguish an old claim attempt from a new one. | Per-claim generation/token, expiry checked with every mutation, and a transactional observation upsert guarded by the current claim. Test cancel/reclaim/stale submissions against real PostgreSQL. |
| P1 | **Launch and quota checks can race.** Manual launch counts usage and inserts separately, with no request idempotency or active-domain guard. Concurrent requests can enqueue duplicate work or exceed the final allowance. | A transactional launch operation with idempotency and a defined overlap policy, shared by manual and scheduled scans. This is workload protection; payment integration is not required. |
| P1 | **Runtime/cap behavior differs.** Local DNS caps at 40; remote jobs can permit 500. Timeout values are largely per target, so a “300 second” setting does not bound a whole stage with many hosts. Owner-registered hosts can lose priority when discovered hosts reach the cap. | One scan-policy object used in local and remote modes; explicit end-to-end deadlines and prioritization of apex/registered hosts. Record omitted hosts and avoid claiming full-domain coverage. |
| P1 | **Some target connections are re-resolved by tools.** HTTP/Naabu pin approved IPs; Nuclei/SSLyze validate a hostname before subprocesses connect by name. Core also performs some outbound checks. | Validate deployed egress restrictions and public-IP enforcement at connection time; define the worker/Core network boundary. Public-IP preflight alone does not settle DNS rebinding. |
| P1 | **Blocking work can delay Core.** Synchronous PostgreSQL/DNS calls still occur in async execution, including finalization. A bounded pool is implemented, but event-loop isolation is unfinished. | Move blocking work off the event loop or use async clients consistently. Test API responsiveness, queue age and lease recovery under realistic load. |
| P2 | **Operational health is shallow.** The current platform endpoint reports DB connectivity, active count and last daily cron completion. It has no worker capability/version/last-seen record or detector-failure summary. | Persist worker health/capabilities, queue wait and run age, tool availability, failure/partial counts and scheduler freshness. Separate a legitimate queued scan from an overdue job. |
| P2 | **Scan history can grow without bounds.** Scan list/detail return unbounded history/raw payloads; a defined retention/size policy is not evident in those paths. | Pagination, bounded evidence responses, private artifact storage where appropriate and documented retention/export behavior. |

These items are source findings or architectural risks, not demonstrations of
production exploitation. The new tests protect process-failure handling; they
do not certify all protocol/template, DNS, network or transaction behavior.

## Product features to finish around scanning

1. **Phone-friendly work lists:** Domains, Scans, Assets, Remediation, Reports
   and Team still rely on wide tables for important actions. Start with domain
   verification and scan result actions on phone cards.
2. **Trustworthy assessment/report snapshots:** distinguish current organization
   risk from historical scan posture and associate coverage, scope and versions
   with exports. Reports currently combine live findings with the latest
   assessment and a primary-domain label; this is not an immutable per-domain
   audit snapshot.
3. **Activation/result handoff:** show first completed scan, first finding
   reviewed and optional teammate invitation from actual records. A retry or
   a launch-button click is not a completed assessment.
4. **Role-aware actions everywhere:** dashboard onboarding and scan launch are
   role-aware; domain pages still expose actions that can fail the backend admin gate
   for ordinary members. Keep backend checks and reflect permissions in the UI.
5. **Delivery/recovery visibility:** record email/integration failure and retry
   outcomes so support can distinguish delivery failures from identity/permission
   failures. The platform page currently treats every health-fetch error as
   lack of a platform grant, including network/server failure.

Compliance and Academy do not need to be complete before the first useful admin
console. Their real models and workflows should precede controls that administer
those modules. Avoid adding empty compliance approvals or course-management
screens while their customer workflows still redirect elsewhere.

## Administration recommendation

There is already a small staff console at `/platform`: gated health, tenant
lookup and overdue-scan lookup with audit reasons. Organization owner/admin
membership is separate from platform-staff authority. Build on that foundation.

Prioritize trustworthy scanner state and operational telemetry, then expand
administration around actual support tasks: worker/queue health, tenant lookup,
failed/partial scans, user/invite recovery and email delivery. Require audited,
scoped authorization for any retry/cancel/change operation; staff identity and
customer roles must remain separate. Add customer-visible access grants if
staff will inspect tenant evidence. Broader billing, compliance and Academy
controls can follow their actual workflows.

## Validation and rollout

Tests use fake subprocesses, mocked browser APIs and the offline database.
No real scan, user message, DNS modification or payment was performed.

- Focused tests cover non-zero exits, timeouts, malformed output, partial positive
  results, skipped targets, stale/legacy coverage, unreachable HTTP, missing
  certificates and interruption on lease loss.
- Browser regression covers the 32px/full-wordmark mobile logo, phone/tablet
  overflow and visible failed/skipped/partial scan results.
- Production frontend build and the full backend suite are checked after edits.

Latest results: **373 backend tests passed, 16 skipped**; frontend build and
browser regression passed. Integration skips are not treated as production
validation. [Mobile dashboard preview](mobile-dashboard-logo-390.png) uses a
synthetic account with mocked responses, not customer data.

Deploy updated **Core and worker together**. The new coverage fields are additive
and need no database migration. Until workers emit successful-host evidence,
Core conservatively retains old Nuclei findings; it must not interpret older
attempted-only observations as clean checks. Verify actual installed tools,
template packs, network policy and cancellation behavior in a controlled,
authorized scan before describing the deployment as validated.
