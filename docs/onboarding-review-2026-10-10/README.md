# Onboarding review — 10 October 2026

**Implementation update:** See [11 October implementation status](../implementation-status-2026-10-11.md) for completed fixes and open items. The scenarios below describe the original reviewed state.

## Current status — 11 October 2026

The six prioritized defects below have code fixes. Some of the broader
activation and account-management recommendations remain unfinished. These
changes are local; production deployment, real email delivery, DNS propagation,
payments and physical-device behavior have not been verified.

| Original finding | Current implementation | Still outstanding |
|---|---|---|
| 1. Plans and entitlements disagree | Starter/Growth catalog, displayed prices, selected-plan propagation and separate 30-day trial subscriptions; onboarding reads the public plan catalog. | Payment activation is deferred at the user's request; deployed entitlement verification remains open. |
| 2. Invitation lost during onboarding | Routing guards preserve the invitation; acceptance refreshes memberships and selects the returned workspace; retryable failures retain the token. | Actual invitation delivery and full registration-to-acceptance testing. |
| 3. Skip falsely completes domain verification | “Do this later” opens the dashboard; login does not require a verified domain; a resumable domain prompt and role-aware actions remain visible. The backend still requires ownership verification before scans. | Full activation checklist beyond domain setup. |
| 4. Bootstrap outage signs users out | Explicit reconnect/retry screen retains the session and URL. Expired access-token refresh outages also retain credentials. Concurrent refresh requests are shared, and late responses cannot overwrite another account. | Production connection/recovery validation. |
| 5. First-scan button only navigates | The button launches the verified domain, disables during submission, displays errors, explains scan allowance usage and opens scan progress. | Guided first-result explanation and highest-priority finding walkthrough. |
| 6. Mobile setup is clipped or obstructed | Labeled mobile progress, stacked phone plans, shrinking OTP fields and reserved form space for the cookie notice. | Physical-device and virtual-keyboard checks. |

Additional recommendations have these statuses:

- **Implemented:** copyable DNS host, full record name, value, TTL and instructions
  for a DNS administrator; editable DNS-zone context for subdomains; manual-copy
  guidance when clipboard access fails; removal of the nonfunctional “keep me
  signed in” checkbox.
- **Partially implemented:** account switching is available on email verification,
  but secure in-place email correction is pending. Domain setup can be resumed,
  but completed scans, reviewed findings and teammate invitations are not yet a
  complete activation checklist.
- **Pending:** progressive business context and objective-specific onboarding
  for usable Compliance and Academy modules.

**Current flow:** signup → verify email → create or join a workspace → open the
dashboard. New workspace owners may add/verify a domain immediately or choose
“Do this later.” Scanning requires a verified domain; dashboard access does not.
Compliance and Academy should reuse account/workspace access when their real
workflows are implemented.

The sections below preserve the original findings and screenshots as historical
evidence. Use the table above to determine what is still open.

Reviewed signup, email verification, workspace creation, domain setup, DNS
verification, invitations, session restoration, and the first-scan handoff.
Seven local Chromium scenarios used mocked API responses; no real accounts,
email, DNS changes, payments, or scans were created. Production delivery and
latency were not tested. Existing scoring work was left unchanged.

## Original main finding — 10 October

The flow collects the basics, but it treats workspace setup, domain readiness,
and product activation as the same state. They need different outcomes:
workspace created; verification pending or deferred; scan ready; first scan
completed. Showing “all set” should not imply that an unverified domain can
be scanned.

Flow observed during the original review: signup → email verification → organization and plan → domain →
DNS verification or skip → “You're All Set!” → scans page. The final action
does not launch a scan.

## Original prioritized findings

### 1. High: advertised plans and granted entitlements disagree

Public pricing offers Starter (₦7,000/month) and Growth (₦15,000/month).
Organization setup instead offers Growth, Scale, and Sovereign, defaults to
Scale, and shows no price or trial terms. Starter is absent from the backend
plan allowlist. Both public plan buttons send users to the same `/signup`
URL without preserving their selection.

This also affects actual access: organization creation accepts the chosen
plan directly; without a subscription, entitlement resolution uses that
organization plan. Sovereign carries unlimited quotas. This is a confirmed
code path, not a live billing transaction tested in this review.

Use one canonical plan catalog for marketing, onboarding, billing, and quota
enforcement. Separate a desired plan from paid/trial entitlements. Clearly
state the trial or payment requirement; make enterprise provisioning an
assisted flow rather than a self-granted unlimited tier.

Evidence: [public plans](../../frontend/src/lib/publicPlans.ts),
[organization form](../../frontend/src/pages/onboarding/CreateOrganization.tsx),
[organization creation](../../backend/app/api/organizations.py),
[quota definitions](../../backend/app/core/plans.py),
[subscription fallback](../../backend/app/billing/subscriptions.py).

### 2. High: new invitees can lose their invitation during onboarding

Browser reproduction: an unverified account opens
`/onboarding?invite=local-review-invite`; it reaches
`/onboarding/verify-email` with an empty query string. Layout and app guards
redirect using pathname-only destinations. VerifyEmail preserves its query
on completion, but the invite has already been removed earlier.

Separately, successful invitation acceptance does not refresh memberships
or select the newly joined workspace. All non-403 failures, including
temporary server failures, discard the invite. Bootstrap always selects
the first membership rather than an explicitly requested workspace.

Persist a pending invitation through login and verification, distinguish
retryable errors from invalid invitations, refresh bootstrap after acceptance,
and select the organization returned by the acceptance API. Invitees should
join their existing organization without being asked to create another one.

Evidence: [layout redirects](../../frontend/src/pages/onboarding/OnboardingLayout.tsx),
[app guards](../../frontend/src/App.tsx),
[invitation handler](../../frontend/src/components/InviteAcceptance.tsx),
[bootstrap mapping](../../frontend/src/lib/auth.tsx).

### 3. High: skipping verification produces a false completion state

Browser reproduction: click “Skip for now” on a pending domain. The app shows
“You're All Set!” and “ready to start monitoring,” with the verification step
marked complete. Reload returns the user to DNS verification. The backend
correctly refuses scans of unverified domains.

Persist deferral separately from verification. Offer “Explore workspace —
verification pending,” show a resumable setup checklist, and make the next
action “Finish domain verification” while pending. Do not weaken the backend
ownership check. Make member onboarding role-aware: a normal member should
not be required to perform the owner/admin-only domain setup operation.

Evidence: [skip handler](../../frontend/src/pages/onboarding/VerifyDomain.tsx),
[completion state](../../frontend/src/lib/auth.tsx),
[completion page](../../frontend/src/pages/onboarding/OnboardingComplete.tsx),
[scan authorization](../../backend/app/api/scans.py).

### 4. High: a temporary bootstrap outage signs users out

Browser reproduction: returning-account bootstrap and refresh requests return
503. The stored session is deleted and onboarding redirects to `/login`.
The auth provider converts bootstrap failures into null, then clears the
session if recovery fails, without distinguishing outages from revoked or
invalid credentials.

Keep the account session on network/5xx failures, preserve setup progress,
and show a retry/offline state. Clear credentials only on confirmed auth
failure. This matters for interrupted mobile connections.

Evidence: [reloadState](../../frontend/src/lib/auth.tsx),
[observations](observations.json), [outage screenshot](bootstrap-outage.png).

### 5. Medium: “Start first scan” does not start a scan

Browser reproduction with a verified domain: clicking the button navigates
to `/scans`; zero `/scans/launch` requests occur. Users must find another
launch action and choose the domain again.

Either rename this to “Review and start your first scan” and open a populated
confirmation, or launch the verified domain on the explicit button click.
Show the selected domain, quota impact, queued/running state, and a path to
the result. Prevent duplicate submissions. Complete activation with a short
explanation of the first score and the highest-priority finding.

Evidence: [completion button](../../frontend/src/pages/onboarding/OnboardingComplete.tsx),
[browser observations](observations.json).

### 6. Medium: mobile progress and plan selection need simplification

At 320px the five-step indicator extends from x=-14 to x=334, clipping both
ends. At 390px and 1280px it fits. Step labels are hidden on small screens
without an equivalent accessible current-step label. Three plan columns are
cramped, and the fixed cookie banner covers lower form controls on first visit.

Use “Step 2 of 4 — Workspace” with a compact progress bar on mobile, expose
the current step to assistive technology, and stack plan options. Ensure
form actions remain reachable when the banner or mobile keyboard is present.

Evidence: [320px screenshot](create-org-320.png),
[390px screenshot](create-org-390.png),
[desktop screenshot](create-org-1280.png),
[stepper](../../frontend/src/pages/onboarding/OnboardingLayout.tsx).

## Original additional recommendations

- **Email correction and account switching.** The OTP screen supports paste,
  auto-submit, cooldown, and error messages, but provides no visible change-email
  or sign-out path for a mistyped address. Provide a safe correction flow that
  requires verification of the new address, plus an account-switch option.
- **Help for someone without DNS access.** Explain the prerequisite before
  domain entry. Offer copyable full instructions for an IT person, record
  name/value copy actions, TTL, propagation guidance, and a manual fallback
  if clipboard access fails. An explicit user action can open a share/email
  draft; do not silently send messages.
- **Correct subdomain instructions.** The form accepts names such as
  `www.example.com`, while verification always says to use `_cyphward` as the
  relative host. In an `example.com` zone the required host would be
  `_cyphward.www`. Show the exact full record name and account for the DNS
  zone being edited; do not assume the entered hostname is the zone apex.
- **Make “keep me signed in” work or remove it.** Signup and login track the
  checkbox locally, but do not pass it to authentication/session persistence.
  Sessions always go into localStorage. The current control does not affect
  persistence; the separate idle timeout does not implement that preference.
- **A resumable activation checklist.** Track domain verification, first scan
  completion, first finding reviewed, and an optional teammate invitation.
  Use existing audit events where possible to measure completion and time to
  first useful result. Record actual scan completion, not just button clicks.
- **Optional business context.** Country, industry, role, and objective can
  tailor guidance. Collect them progressively; avoid mandatory CAC details,
  phone numbers, or detailed compliance questionnaires before users see value.

## Compliance and Academy

Keep account verification and workspace membership shared. Once the modules
exist, ask optionally whether the user wants to monitor exposure, prepare
compliance evidence, or learn. Each objective should have its own readiness
checklist and first useful action:

| Objective | First useful action | DNS required? |
|---|---|---|
| Security monitoring | Verify a domain → scan → review the first finding | Yes, before scanning |
| Compliance | Choose a relevant checklist → assign an evidence owner | Only for domain-scanning features |
| Academy | Choose a learning goal → take the first lesson | No |

Domain verification must not become a universal gate that prevents learners
or compliance-only collaborators from entering the workspace. Avoid presenting
future modules as available until they are actually usable.

## Recommended implementation order

1. Complete the activation checklist using actual scan completion and finding-review events.
2. Add the guided first-result/first-finding handoff.
3. Add secure email correction with verification of the replacement address.
4. Verify deployed invitations, session recovery, trial entitlements, DNS and mobile keyboard behavior.
5. Add progressive business context and module-specific onboarding when Compliance and Academy workflows are usable.

## Verification evidence

[observations.json](observations.json) records seven browser scenarios,
requests, routes, and overflow measurements. Screenshots capture the tested
states from 10 October. At that time the review changed only documentation;
application fixes were subsequently implemented as recorded above.

Current regression checks are maintained in
[check-onboarding-flow.mjs](../../frontend/scripts/check-onboarding-flow.mjs).
Run `npm run test:onboarding-ui --workspace frontend`. It covers dashboard
access before domain verification, truthful zero counts, stale-workspace cache
replacement, subdomain DNS names and clipboard failures, tablet navigation and
focus/scroll behavior, 320px OTP sizing, bootstrap/refresh outage recovery,
invitation preservation, concurrent refresh and late account-switch responses.
The browser checks use mocked APIs and do not start real scans or send email.

Validation passed: frontend production build, onboarding and score browser
regressions, and **353 backend tests passed, 16 skipped**. These results do not
confirm deployed migrations, real PostgreSQL integration or production behavior.
