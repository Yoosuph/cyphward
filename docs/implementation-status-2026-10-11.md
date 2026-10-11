# Review implementation status — 11 October 2026

Compared the [platform/business review](platform-and-business-review-2026-10-03.md),
[mobile review](mobile-review-2026-10-05/README.md), and
[onboarding review](onboarding-review-2026-10-10/README.md) with current source,
commit history, and the local working tree. The original reports remain historical
records; their original wording does not describe today's implementation status.

“Implemented” below means present in the local code. It does not confirm that
production runs this revision or that migrations have been applied there. The
onboarding/invitation/email changes currently include uncommitted working-tree work.
No production account, payment, DNS record, scan, or deployment was changed.

**Current user priority:** Payment-system activation is deferred. The public
company/brand-search work is tracked in the
[brand verification note](brand-search-verification-2026-10-11.md).

The subsequent [scanner/feature readiness review](scanner-feature-review-2026-10-11/README.md)
records additional tool-failure, coverage and cancellation fixes and the remaining
foundations recommended before expanding administration.

## Platform and architecture review

| Original finding | Current status and evidence | Remaining work |
|---|---|---|
| Registration can adopt a Google account | Implemented: existing-account adoption blocked; explicit ownership checks. Commit `f545b15`, `backend/tests/test_own_auth.py`. | Verify deployed revision and account-linking behavior with a controlled production account. |
| Invitations grant membership before verified acceptance | Implemented: expiring, single-use invite tokens; verified-email matching and atomic acceptance. `backend/app/api/members.py`, `backend/tests/test_member_invite.py`. | Deployed migration and actual email-delivery checks. |
| Logout/session revocation and atomic token consume | Partially implemented: session-bound access tokens, revoked-session checks, atomic refresh/reset consumption (`e942c87`). This pass adds one shared browser refresh request and rejects late responses after account switching/sign-out. | Browser refresh tokens still use JavaScript-readable localStorage; HttpOnly cookie design remains open. |
| Cancelled scans can resume/finalize | Implemented: conditional lifecycle transitions (`850950b`), scanner-integrity tests. | Real worker/restart and production-concurrency validation. |
| Missing detector results resolve findings | Implemented: detector identity and coverage gate (`438352b`), baseline-coverage tests. | Validate coverage against actual worker outputs and failed detectors. |
| Remediation checks a different detector | Implemented: original detector/template recheck with inconclusive outcomes (`a0a88b2`), remediation tests. | Real tools and detector-version validation. |
| Empty findings fabricate a perfect score | Implemented: not-assessed state, versioned organization score/snapshots (`d5fb5cd`). Report example domain, findings and compliance claim also removed in the working tree. | Live first-scan/result validation; immutable exported assessment snapshots remain a broader follow-up. |
| Database pool bypasses capacity limit | Partially implemented: bounded pool, timeout/backpressure, no unpooled fallback (`0e6d1b4`). | Synchronous database calls still occur in async paths; event-loop isolation/async-driver work remains. |
| Worker/network boundary and SSRF | Partially implemented: public-IP checks and scoped redirect handling (`c2300ad`), scanner SSRF tests. | Core still performs some outbound checks; production egress policy, DNS-change behavior and service-boundary validation remain. |
| Duplicate schedulers and volatile jobs | Implemented: atomic cron claim and orphan recovery (`cecc694`), job/claim tests. | Verify authoritative scheduler configuration and restart behavior in the deployment. |
| Tenant isolation and auth-table exposure | Migration and integration-test code implemented (`1a961b1`, auth-table RLS migration). | Confirm deployed role, grants, RLS and migrations with real PostgreSQL; local offline tests do not establish this. |
| Internal platform administration missing | Implemented: separate staff authorization/audit routes and platform console (`9236f06`, `6728862`). | Staff SSO and customer-visible, time-limited support access remain enhancements. |
| Plans disconnected from entitlements | Implemented: quota checks, authoritative subscription/trial records, Starter/Growth catalog (`83a2874`, `80f103e`, `38a7bed`). | Billing remains manual with a provider seam; automated payments and renewals are not complete. |
| Cross-tenant report domain relationships | Implemented: domain validation, scoped joins and composite constraints (`79f7a69`). | Apply/verify constraints in deployed PostgreSQL. |
| Owner permissions can be overwritten | Implemented: invitation protections and transactional last-owner protection (`5d0a172`); member tests. | Production concurrency validation. |
| Compliance claims imply certification | Partially implemented: readiness framing and informational claims (`32151bd`); fixed COMPLIANT email label removed. | A real compliance workspace with evidence owners/review is still absent. |
| Data export/deletion missing | Implemented: workspace export/closure, account deletion and audit preservation (`ec04fde`, `bd6531a`). | Operational retention, backup expiry and deletion evidence need deployment verification. |
| Destructive migration lacks upgrade instructions | Runbook implemented (`e5c4c08`). | Backup/export/restore decisions remain deployment-specific. |
| Rate limits are process-local; admin MFA missing | Implemented: shared PostgreSQL limits, email step-up and TOTP (`14e3cc0`, `29c92ce`). | Deployed configuration and recovery/delivery testing. |

## Onboarding review

| Finding | Status after this implementation pass |
|---|---|
| Plan mismatch and unrestricted enterprise selection | Implemented: Starter/Growth, prices, selected-plan propagation, separate 30-day trial entitlements. Onboarding now derives plan names/prices from the public catalog. |
| Invitation lost during authentication | Implemented in working tree: guards preserve query, acceptance returns/selects the invited organization, retryable failures retain the invitation. Longer-lived recovery and retry UX still merit a dedicated test with real delivery. |
| Skip falsely certifies domain readiness | Implemented: email/workspace unlock dashboard, setup can be deferred, dashboard prompts are resumable, verified ownership remains mandatory for scans. Member prompts are role-aware. |
| Bootstrap outage deletes session | Implemented: explicit retry screen preserves the session and URL; bootstrap and token-refresh outages retain credentials. Retry restores server-derived state and the selected workspace. Browser regressions cover 503 recovery with an invitation and an expired access token. |
| First-scan button only navigates | Implemented: explicit action launches the verified domain, disables during submission, surfaces errors, explains allowance usage and routes to scan progress. Full first-result guided activation remains open. |
| Mobile stepper, plans, OTP and cookie obstruction | Implemented: compact labeled progress, stacked phone plan options, shrinking OTP fields, reserved form space while the cookie notice is visible. Physical-device/keyboard checks remain open. |
| No way to correct/switch a mistyped email | Partially implemented: visible sign-out/use-another-account action preserving query. Secure in-place email correction is not implemented. |
| DNS help, host copying and subdomain instructions | Implemented: shared instructions in onboarding and Domains; editable DNS-zone context, correct relative host, full record name, value, TTL, administrator instructions and clipboard-error help. No silent messages are sent. |
| Nonfunctional “keep me signed in” checkbox | Implemented by removing the misleading control. Existing session persistence and idle timeout continue to apply. |
| Resumable activation checklist | Partially implemented: domain setup prompt uses actual domain state. First completed scan, first finding review and teammate invitation are not yet a full checklist. |
| Business context and Compliance/Academy onboarding | Pending. Gather context progressively when real module workflows are ready; do not gate learning or compliance collaboration on DNS. |

## Mobile review

| Finding | Current status |
|---|---|
| Navigation gap at 768–900px | Implemented this pass: public menu and app More Pages sheet remain available until desktop navigation appears at 901px. |
| OTP fields clipped at 320px | Implemented this pass: fields shrink within their row; browser regression checks all six bounds. |
| Wide operational tables hide actions | Pending: Domains, Assets, Scans, Remediation, Reports and Team need useful phone summaries with primary actions visible. |
| Floating social links overlap text | Implemented this pass: floating links hidden below desktop width; footer links remain available. |
| More Pages sheet leaks scrolling and keyboard focus | Implemented this pass: shared scroll lock, initial focus, focus trap, Escape and focus restoration; sheet scrolls in short viewports. |
| Small touch targets | Partially implemented: DNS copy actions, public menu, sheet close and main menu rows now have 44px areas. Other icon/filter controls still need review. |

## Next work, in order

1. Add phone summaries/actions to operational lists, starting with Domains and Scans.
2. Build the activation checklist from actual completed scans and finding-review events.
3. Complete secure email correction and browser-session storage design as dedicated authentication changes.
4. Validate deployed migrations, database role, real worker coverage and manual billing lifecycle before considering those findings production-verified.
5. Build a narrow compliance evidence workflow and assigned learning pilot; the existing Academy route remains a redirect, not a functioning module.

## Validation

The maintained browser regression is `npm run test:onboarding-ui --workspace frontend`.
It covers dashboard access with no verified domain, truthful zero counts, stale
workspace cache replacement, subdomain DNS names, clipboard failure, tablet menus,
keyboard focus/scroll locking, the 320px OTP row, and bootstrap/refresh outage recovery
with invitation preservation. All API responses are mocked.
Frontend production build and the backend offline suite are the additional checks.
Validation passed: production build, onboarding/mobile/session browser regression,
existing score browser regression, and **353 backend tests passed, 16 skipped**.
The browser session checks also exercise concurrent refresh and a late response
after switching accounts. Skipped integration checks are not counted as verification.
Production delivery, real DNS propagation, physical devices, migrations and payments
were not exercised in this pass.
