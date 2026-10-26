# UI refinement, 25 October 2026

Branch `ui-refine-2026-10-25`. Frontend only: nothing in `backend/`, `scanner/` or `shared/` changed, no API shapes
changed, and no dependencies were added.

The pass covers consistency, accessibility, mobile layout, copy and loading/empty/error states, in that priority
order. I made many small, targeted changes instead of a rewrite.

## How this was measured

`frontend/scripts/capture-ui-refine.mjs` serves the app with Vite and answers every API call from fixtures, so no
account, network or production system is involved. For each main page it saves a JPEG at 1440, 390 and 320 wide in
the dark theme, and it writes an audit (`audit.json`) covering four runs per page: dark at 1440, 390 and 320, and
light at 1440. The audit checks:

| Check | Rule |
|---|---|
| overflow | page wider than the viewport (horizontal page scroll) |
| small | touch target under 44 × 44 px at phone widths (inline links inside a sentence are exempt) |
| unlabelled | field with no `<label for>`, wrapping label, `aria-label` or `aria-labelledby` |
| nameless | control with no accessible name |
| skips | heading level skipped (for example h1 → h3) |
| noRing | Tab stop with no visible focus ring (an opaque outline, or a box-shadow with colour and blur or spread) |
| lowContrast | text under WCAG AA (4.5:1, or 3:1 for large text) against its real background |
| banned | claim wording rendered on the page (the compliance suite's list plus *compliance score*, *meets the requirement* and *passes audit*) |

Each number below is the total of offending items across the four runs. Before is commit `46a4ba0`, which is `main`
plus the harness only. After is the head of this branch.

| Page | small | unlabelled | skips | noRing | lowContrast | banned | → after |
|---|---|---|---|---|---|---|---|
| Landing `/` | 31 | 0 | 0 | 0 | 19 | 4 | all 0 |
| Login `/login` | 12 | 0 | 0 | 6 | 7 | 0 | all 0 |
| Sign-up `/signup` | 10 | 0 | 0 | 12 | 4 | 0 | all 0 |
| Overview `/overview` | 34 | 0 | 4 | 0 | 7 | 0 | all 0 |
| Scans `/scans` | 16 | 0 | 0 | 0 | 9 | 0 | all 0 |
| Findings `/findings` | 58 | 4 | 4 | 0 | 30 | 0 | all 0 |
| Compliance `/comply` | 20 | 0 | 0 | 0 | 1 | 0 | all 0 |
| Settings `/settings` | 40 | 16 | 4 | 0 | 3 | 0 | all 0 |
| Reports `/reports` | 16 | 0 | 0 | 0 | 3 | 0 | all 0 |
| Owner console `/admin` | 18 | 0 | 0 | 0 | 0 | 0 | all 0 |
| Owner console, users `/admin/users` | 22 | 0 | 0 | 1 | 0 | 0 | all 0 |

No page scrolled sideways before or after, at any width. Wide tables already scroll inside their own container
(`.ledger-wrap`, `.table-stack`) or turn into labelled cards below 640 px.

Screenshots are in `before/` and `after/`, named `<page>-<width>.jpg`. All of them are under 300 KB (the largest is
176 KB). The fixed bottom dock and the CyphBot button appear part-way down the tall phone captures because the
capture extends below the viewport. On a real phone they sit at the bottom of the screen.

## What changed

### Shared tokens and components

- **New colour tokens** in `frontend/src/index.css`, set for both themes:
  - `--accent-fill` and `--accent-fill-hover`: solid accent backgrounds
  - `--on-accent`: the label on a solid accent background
  - `--accent-ink`: accent used as text on a tinted panel

  `--accent` itself did not change, so the brand orange is untouched everywhere else. In the dark theme, the solid
  fill is a slightly deeper orange, `#C2441F`. With cream text it measures 4.8:1; the previous fill, `#E5532B`,
  measured 3.6:1.
- **One accent button.** `.btn-solid`, `.scan-button--primary` and the ~35 ad-hoc `bg-accent text-white` buttons
  and badges now all use `--accent-fill` and `--on-accent`. They share one fill and pass AA.
- **Light-theme `--warn`** went from `#A16A16` (4.3:1) to `#8A5A10` (5.5:1).
- **Danger text.** `.st.bad` and `.scan-badge--danger` use `--accent-ink`. "Failed" on its tinted badge had
  measured 4.3:1 in the dark theme.
- **New `components/ui/SeverityBadge.tsx`** provides `SeverityBadge` and `SeverityDot`, backed by the `.sev-badge`,
  `.sev-dot` and `.sev-bar` classes. Findings and Overview used to colour severity separately with Tailwind's amber,
  blue and emerald classes, and the issue drawer showed *low* and *info* in the *medium* colour. One severity now
  has one colour everywhere, and every badge is AA in both themes.
- **Shared state panels.** `components/ui/StatePanels.tsx` (`LoadingPanel`, `EmptyPanel`, `ErrorPanel`,
  `humanError`) already existed. These pages now use it instead of their own markup:
  - Overview error
  - Findings: error and empty
  - Settings: error (this page used to stay on its skeleton forever)
  - Owner console: `ViewState` loading and error, plus `Empty`

  The owner console also stops showing raw server text such as "Internal Server Error". Page-load errors on
  Findings, Settings and the owner console call `humanError(…, { passDetail: false })`, so a 4xx `detail` from the
  API is never shown there; only the reviewed wording is. The default for other callers is unchanged.
- **Client behaviour change in Findings.** The page now calls `getFindingsStrict` (new in `lib/api.ts`) instead of
  `getFindings`. A failed request now throws, and the page shows an error with a retry. Before, the failure was
  swallowed and the page showed an empty list, "No open issues". A failed refresh while issues are already on screen
  keeps them and shows a toast. `getFindings` itself still returns an empty list on failure, and Remediation still
  uses it. The API is unchanged.

### Accessibility

- **Focus rings.** Every text field, select and textarea now draws a 2 px accent ring on keyboard focus, even where
  a utility class removed the outline. Login and sign-up fields had no ring at all before. Composite fields that
  draw the ring on their wrapper (compliance search, command palette, CyphBot composer) keep their own.
- **Landmarks and skip link.** The app and owner-console shells now render the page inside
  `<main id="main" tabindex="-1">`; before, the app had no `<main>` landmark. Both shells start with a
  "Skip to content" link.
- **Drawer** (issue details, asset details):
  - It is a labelled dialog: `aria-labelledby` points at its `<h2>` title, which used to be an `<h3>`.
  - Focus moves into the drawer when it opens, Tab stays inside it, and Esc or Close hands focus back to whatever
    opened it.
  - A closed drawer is `inert`. Before, its off-screen controls were still in the Tab order.
  - The close button is now 44 px.
- **Settings tabs** follow the WAI-ARIA tabs pattern: `tablist`, `tab` and `tabpanel` roles, `aria-selected`,
  `aria-controls`, roving `tabindex`, and arrow, Home and End keys.
- **Labels.**
  - Every Settings field is labelled: the company profile, the invite dialog, the member role selects, the MFA and
    authenticator codes, close-workspace and delete-account.
  - "Your role" and "Your plan" were `<label>` elements with no field; they are now plain text.
  - Findings search, Assets search and the start-scan domain select are labelled.
  - The icon-only "Ask CyphBot" button has an `aria-label`.
- **Heading order.** Overview, Findings and Settings section headings moved from h3 to h2, and their sub-headings
  from h4 to h3. Each page has a single h1.
- **Keyboard access to issues.** A Findings card used to open only on a mouse click. Its title is now a button, so
  keyboard and screen-reader users can open the issue details too.
- **Toggles.** The severity filters, the landing preview tabs and the landing step buttons expose `aria-pressed`.
- **Decorative characters.** The "/" separators in the topbar, auth pages and mobile menu are now `aria-hidden`.
- **Reduced motion** was already handled globally (`@media (prefers-reduced-motion: reduce)` in `index.css`).
  Nothing new animates outside that rule.

- **Overlay stack.** Added after review of `d351d07`. Drawers now join the shared dialog's layer stack: Dialog.tsx
  exports `enterLayer`, `leaveLayer` and `isTopLayer`. As a result:
  - only the top overlay, whether a dialog or a drawer, handles Tab and Escape
  - the page and every layer underneath are `inert`
  - Escape closes the top layer first and focus goes back to the control that opened it

  Before this change, every open drawer ran its own window-level Tab trap. A drawer under the "Ask CyphBot" dialog
  pulled focus back to its own close button, and with two drawers open the fix guide's setup buttons could not be
  reached by keyboard.
- **Drawer focus on open.** Added after review of `d8b47ea`. With normal motion, the drawer was still hidden by its
  opening transition when `setTimeout(0)` tried to focus its close button. Focus fell to the inert page instead.
  Two changes fix it:
  - The open state now switches `visibility` at once (`.drawer.open { transition: …, visibility 0s }`, only under
    `prefers-reduced-motion: no-preference`). Closing still waits for the slide-out to finish.
  - The drawer retries focus once per animation frame until focus lands inside it, giving up after 30 frames. The
    panel itself (`tabindex="-1"`) is the fallback target.

  Measured on 15 opens in a row on the same page: 15/15 at 1440 and 390, with normal and with reduced motion.
  Focus landed within 48 ms every time.
- **One `<main>`.** `LoadingScreen` is now a plain status region instead of a `<main>`, so it never nests inside
  `main#main`.
- **`aria-controls`.** The Settings and Compliance tabs set it only on the selected tab, whose panel exists. Inactive
  panels are not rendered.

### Mobile (up to 900 px)

- The topbar icon buttons, logo link and bottom-dock items are now 44 px; the topbar is 56 px tall on phones.
  `test:score-ui` still passes its full-logo-at-320 check.
- Buttons, tabs, selects and inputs inside page content are at least 44 px, and summaries are 44 px tall.
- Other targets raised to 44 px:
  - landing preview tabs, step buttons and footer links
  - footer social icons
  - the password show/hide toggle
  - "View website", "Forgot password?", "Create account" and "Sign in"
  - the owner-console pager and "All logs"
- On Findings, the search box has its own full-width row on phones, and the severity filters scroll sideways in
  their own row. Before, the search box could be pushed out of view.

### Copy

These disclaimers used the word *certification* in negated form ("not a compliance certification"). They now use the
repo's existing wording, *legal advice or a compliance determination*:

- the landing page
- Pricing
- the footer
- the product tour
- the board report (two places)

### Demo login button (`Login.tsx`)

The button used ad-hoc classes, including `hover:bg-surface`, a colour token that does not exist, and a pulsing
"..." animation. It now uses the shared `.btn .btn-ghost` look and the same quiet spinner as the other busy buttons,
inside a `role="status"` message. Reduced motion stops the spinner. The text still reads "Try the demo" and
"Signing you into the demo…".

## Tests

`frontend/scripts/check-ui-refine.mjs` is a new suite, run with `npm run test:ui-refine`. It fails on any audit
finding above. It runs all ten main pages at 1440, 390 and 320 in the dark theme, and at 1440 and 390 in the light
theme. It also checks:

- **Error states.** When the main read on Overview, Findings, Settings, Scans, Reports, Compliance or the owner
  console fails, the page shows an error with a retry. It never goes blank, never shows "No open issues", never
  shows raw server text, and never uses banned wording.
- **Empty states.** Empty lists on Findings and owner users use the shared empty panel.
- **Reviewed error wording.** A 422 page-load error on Findings, Settings or the owner console does not show the
  API's detail text.
- **Landmarks and references.** Every audited page has at most one `<main>` and none is nested, including
  `/remediation`, `/assets` and `/domains` while they load. Every `aria-controls` names an element that exists.
- **Layered overlays.**
  - Dialog over drawer: Findings → issue → "Ask CyphBot". Tab and Shift+Tab stay inside the dialog. The first
    Escape closes only the dialog and returns focus to "Ask CyphBot" in the drawer; the second closes the drawer and
    returns focus to the issue.
  - Drawer over drawer: issue → "How to fix". Tab stays in the top drawer and reaches nginx, apache, cloudflare and
    aws. Escape closes the top drawer and then the issue drawer, each time returning focus to its opener.
  - Both scenarios run twice, once with normal motion and once with reduced motion. Each run first opens and
    closes the issue drawer 15 times on the same page, with a 4× CPU slowdown. Every open must move focus inside
    within 1 s, and every close must return focus to the issue. On `d8b47ea` this failed with normal motion
    (`focus moved into the drawer on 13 of 15 opens`; 14 of 15 on another run).
  - On `d351d07`, both scenarios failed: `A: Tab stays inside the dialog over the drawer` and
    `B: the setup choice "nginx" is reachable by Tab`.
- **Keyboard.**
  - The skip link is the first Tab stop and moves focus to `<main>`.
  - Settings tabs respond to the arrow and End keys.
  - The issue drawer is inert when closed. Opening it moves focus inside, it is labelled, and closing it returns
    focus to the issue.

The banned-phrase list is `UI_BANNED` in `scripts/lib/ui-refine-harness.mjs`. It extends the compliance suite's
`BANNED` list and applies to every rendered string on the ten pages, including every string this change added.
*certif* is left out on purpose because it would match "TLS certificate"; the Documents suite keeps that stricter
list.

To show the suite is not vacuous, I ran it against the old source (`git checkout 46a4ba0 -- frontend/src`). It
failed with `AssertionError: /overview: a failed load shows an error state`.

### Commands run and results

All commands ran from `frontend/` on Node 26.9.0 with Chromium at `/usr/bin/chromium`.

| Command | Before (main) | After (this branch) |
|---|---|---|
| `npm ci` | ok | ok |
| `npm run build` (tsc + vite + prerender) | exit 0 | exit 0 |
| `npm run test:compliance-ui` | pass | pass |
| `npm run test:scans-ui` | pass | pass |
| `npm run test:score-ui` | pass | pass |
| `npm run test:onboarding-ui` | pass | pass |
| `npm run test:ux-ui` | pass | pass |
| `npm run test:datetime` | 17 passed | 17 passed |
| `npm run test:reviewer-ui` | pass | pass |
| `npm run test:commercial-ui` | pass | pass |
| `node scripts/check-compliance-layout.mjs` | pass | pass |
| `node scripts/check-cyphbot-tables.mjs` | pass | pass |
| `npm run test:ui-refine` (new) | fails (see above) | pass |
| tour geometry from `check-product-tour.mjs`, re-run on fixtures (one-off, see below) | — | pass |
| `pytest backend/tests/test_scanner_identity.py backend/tests/test_evidence_files.py` (these read frontend files) | — | 71 passed |

`test:cyphbot-artifacts`, `test:cyphbot-custom`, `test:cyphbot-preview`, `test:cyphbot-resilience` and
`test:product-tour` need a running local backend (the "CyphBot lab" at `CYPHBOT_LAB_URL`, with a real demo login).
They fail the same way on `main` without one, so they were not run. Starting a backend was out of scope. The
`ECONNREFUSED` lines the browser suites print come from Vite's `/api` proxy before request interception is in place.
They are harmless and also appear on `main`.

These five suites are therefore checked only statically and partly:

- **Selectors.** I grepped them for selectors this change touched. They find the demo button by
  `textContent.includes('Try the demo')`, which still matches: the button now uses the uppercase `.btn` look, but
  its `textContent` is unchanged. None of them select `h3`/`h4`, `.page` or the drawer's close label.
- **Tour geometry.** The topbar, dock and icon-button sizes changed, so I re-ran `test:product-tour`'s geometry
  loop with this harness's fixtures instead of the demo backend, at 1280×900, 390×844 (menu open), 320×568 and
  844×390. At each size I checked that:
  - the tour card fits with an 8 px margin on every step
  - nothing covers the card
  - the page does not scroll sideways
  - the Next button is reachable
  - the spotlight covers the Domains target (the Menu button on phones)

  All of these passed. The suite's content assertions, which depend on the demo data, were not exercised.

## Known limitations

- The audit checks rendered text contrast, not non-text contrast such as icon-only borders or chart strokes.
- Contrast is checked in the light theme at 1440 and 390 only; the dark theme is checked at every width.
- The 44 px rule for page content uses a CSS selector scoped to `.page` below 900 px. A new control placed outside
  `.page`, for example in a portal dialog, needs `app-form-control`, `touch-target` or `tap-row` to get the same
  size.
- The rule makes some list rows a little taller on phones, for example the Findings title button.
- The Settings section tabs still scroll sideways at 320 px. They scroll inside their own row, not the page.
- The scans, compliance and reports pages already had their own audited states and suites. I changed only their
  colours and shared targets.
- Pages outside the brief were not audited: Assets, Domains, Remediation, Platform, the legal pages and onboarding.
  They share the CSS fixes but have no screenshots.

## Decisions for the founder

1. **Terms of Service wording.** `Terms.tsx` still says "compliance certification" (in "They are not a legal
   opinion, compliance certification …") and "guarantee" (in "we do not guarantee …"). Both are negated, and the
   Terms are a legal document, so I left them unchanged. Should they move to the same "compliance determination"
   wording?
2. **Dark-theme button orange.** In the dark theme, solid buttons now use `#C2441F` (4.8:1) instead of `#E5532B`
   (3.6:1) so the cream label passes AA. The alternative is to keep `#E5532B` and use a near-black label, which
   measures 5.5:1 but looks different from the light theme.
3. **Severity colours.** Overview and Findings now share one palette for severity:
   - critical: brand orange
   - high: amber `#94560D` badge, `#D97706` dot
   - medium: `#FBBF24`
   - low: blue
   - info: green

   Are these the colours you want for severity, including in exported reports?
4. **Mobile touch-target scope.** The 44 px minimum applies to every control in page content below 900 px. If some
   dense tables should stay compact on tablets, the breakpoint could drop to 640 px.
5. **Owner-console error text.** The console now shows a plain message instead of the server's text for 5xx
   errors, and passes short 4xx messages through. Platform owners might want the raw detail. That would need a
   "show details" toggle, which I did not add.
