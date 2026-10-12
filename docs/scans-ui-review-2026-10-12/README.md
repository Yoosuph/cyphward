# Scans page design proposal — 12 October 2026

**Status: user approved the design; implementation and validation follow below.**
The implemented route is `/scans`; the user referred to it as `/scan`.

## Inspection

Rendered current local application source in Chromium at 1440×1000 desktop,
390×844 mobile and 320×844 small mobile. All API calls were intercepted with
synthetic demo-account responses; external requests were blocked. This was a
visual inspection of existing source, not an authenticated production session
or a new live scan. No customer data was used and no scan was launched.

- [Current desktop](current-desktop.png)
- [Current mobile](current-mobile.png)
- [Current small mobile](current-small-mobile.png)
- [Mobile scan history](current-mobile-history.png)
- [Mobile launch dialog](current-mobile-launch.png)
- [Measured layout](inspection-metrics.json)
- [Maintained browser regression](../../frontend/scripts/check-scans-layout.mjs)

At 390px, history starts approximately **2,181px** below the page top, and its
table is **826px** wide. Page-level horizontal overflow is contained, but users
must scroll the table to reach offscreen fields/actions. The primary start
button is **32px** high on mobile. At desktop width, history starts at about
987px, near the first viewport's bottom. Ten equal-weight stage cards emphasize
execution detail ahead of outcomes and history.

Source review also found that selecting a row opens a drawer, while its Select
button changes the main tracker. These separate ways to inspect the same scan
create an avoidable distinction. The drawer's stage rendering also does not
give failed/skipped states the same explicit treatment as the main tracker.

## Proposed design

[Desktop and mobile proposal](proposed-desktop-mobile.png), generated with the
built-in image generation tool. The exact [generation prompt](design-prompt.txt)
is saved alongside it. This is a design image with illustrative values, not
a working page or production evidence.

1. Start with scan identity, lifecycle, coverage and useful results. Keep
   “Scan completed” separate from “Limited coverage”; retain the organization
   score's historical scope and never fabricate a score for an unassessed run.
2. Give the coverage warning a plain explanation and an explicit path to the
   affected check. Distinguish findings recorded from new findings.
3. Replace large stage tiles with compact check rows. Group normalization,
   scoring and AI under expandable result processing; retain their individual
   statuses, failures and evidence inside. Technical evidence is an inspection
   action, not a security pass/fail result; do not implement the generated
   image's decorative green “Completed” evidence badge.
4. Desktop uses adjacent checks and history panels. Mobile prioritizes history
   cards with visible actions, then collapsible check details. No horizontally
   scrolling history table is required on phones.
5. Use consistent View actions, at least 44px touch targets, readable type,
   labelled statuses and safe spacing around the existing mobile navigation.
6. Keep role-aware launch and verified-domain requirements, loading/error/empty
   states, polling, stored score semantics, and the actual Cyphward logo. The
   mockup simplifies the surrounding shell; a page redesign does not authorize
   changes to unrelated navigation, authentication or scanner behavior.

Filters in the proposed history panel would operate on the loaded data unless
server pagination/filter support is separately implemented. “View findings”
must use supported scope rather than claim a scan-only result set if the API
does not provide one. No unsupported retry-failed-only, cancel, export,
payment or compliance controls are introduced by this proposal.

## Approval boundary

The user explicitly requested a design preview and approval **before** UI
implementation, and subsequently replied “yes, approved.” The image was
reviewable before page/component changes began.

## Implementation

- A result summary replaces the ten large stage tiles at the top. Historical
  selection is explicit and can return to the latest scan. Coverage and job
  lifecycle remain distinct; unassessed scans have no invented numerical score.
- Desktop places compact checks beside history. Mobile places history cards
  before the collapsed checks, with no sideways table scrolling. Domain and
  status filters operate on the loaded scan list.
- History entries scroll within a bounded panel on desktop and mobile. The
  section heading and filters stay outside the scrolling area, desktop column
  headings remain sticky, and the entry region supports keyboard scrolling.
- A single selection drives both the summary and detail drawer. Request guards
  prevent an older detail response from overwriting a newer selection. The
  list retains previous results and shows a retry notice during an outage.
- Queued/running scans continue polling. Launch retains verified-domain and
  owner/admin requirements, displays errors within the dialog, and explains
  the existing allowance. These are presentation changes, not transactional
  launch/quota protection or a scanner-policy change.
- Processing and raw evidence remain inspectable. Failed/skipped results are
  explicit in the drawer as well as the main page. Existing AI summaries remain
  available in scan details.
- Mobile uses 44px primary/action controls. On `/scans`, CyphBot moves from
  its overlapping floating trigger into the topbar. The actual existing logo,
  navigation and other pages' floating trigger remain in use.
- Scan overlays receive initial focus, contain Tab/Shift+Tab navigation and
  restore focus on close. Closed scan drawers are not mounted as offscreen
  keyboard targets.

[Implemented desktop](implemented-desktop.png),
[implemented mobile](implemented-mobile.png),
[small mobile](implemented-small-mobile.png),
[mobile history](implemented-mobile-history.png),
[launch dialog](implemented-mobile-launch.png), and
[empty account](implemented-empty-mobile.png) are screenshots with mocked APIs.
The approved illustration is retained separately as a design reference.

At 390px, history now starts at approximately **890px**, versus **2,181px** in
the baseline. History fits the **362px** content area instead of requiring an
826px table. The start button increased from **32px to 44px**. Desktop history
starts around **617px**, versus 987px previously. The summary can still require
scrolling on a short phone viewport; no constant percentage of assessed scope
or estimated finishing time is fabricated.

## Validation and rollout

The production frontend build, existing score regression and onboarding
regression were checked. The maintained `npm run test:scans-ui --workspace
frontend` checks responsive bounds, history filters, stale detail responses,
refresh failure recovery, roles, verified-domain launch, empty accounts,
launch errors/success, queued-scan polling and keyboard containment.
Polling is also checked with responses slower than its three-second interval:
background refreshes do not overlap, and a selected queued/running scan keeps
polling until its detail record is terminal. Set `CYPHWARD_SCANS_SCREENSHOTS=1`
when running this script to intentionally regenerate review images and metrics;
normal regression runs leave the committed artifacts untouched.
The browser fixtures do not launch a real scan or test production authentication.

No backend or database changes are required. GitHub CI passed, but pushing did
not start a Vercel release. Rollout therefore uses the existing authenticated
`vercel deploy --prod --yes` workflow, with readiness checked through Vercel
and the deployed JavaScript assets. Both repository `main` references are
verified after push. This change does not complete the scanner workload protections discussed
before the design work, and payment activation remains deferred.
