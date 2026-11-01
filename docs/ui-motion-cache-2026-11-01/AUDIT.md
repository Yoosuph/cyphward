# Motion, skeletons, transitions and caching: audit and fixes (2026-11-01)

Scope: the customer app (`app.cyphward.com`, `frontend/src/App.tsx` and `pages/`) and the owner console
(`admin.cyphward.com`, `frontend/src/owner/`). Frontend only: no API contract, backend, scanner or infrastructure
change.

Method: every route and subroute was loaded cold in headless Chromium with its data held back 900 ms
(`scripts/capture-motion-cache.mjs`, fixtures only, nothing reaches a server), at 1440, 390 and 320 px (phones
emulated as touch devices). For each load the harness samples every animation frame of the content area (`main`)
and records whether it shows a skeleton, content or nothing, plus Chrome's cumulative layout shift (CLS) and where
the page's panels sit while the skeleton is up and after the data arrives. "Before" was measured on an untouched
checkout of `main` at 6438063 with the same harness and fixtures.

## Worst offenders (before), in order

1. **An organisation switch could show the previous organisation's data.** Pages were keyed by path only, so after
   an invitation moved the user into another organisation the same page stayed mounted with the old organisation's
   rows in React state until something refetched (Findings, Assets, Domains, Remediation, Reports, Settings and the
   compliance tabs never did). The page cache read the organisation id when a response *arrived*, so a request
   started for organisation A that resolved after the switch was stored under organisation B's key; the cache was
   not cleared on a switch.
2. **Owner console: one generic "Loading this view…" panel for 13 views** (overview, analytics, every list and every
   detail view). A 150 px panel was replaced by a full page of KPI tiles, panels and tables; panels jumped by up to
   520 px (scan detail), 484 px (user detail) and 453 px (organisation detail). No caching: every revisit started
   from that panel again. A failed refresh replaced data already on screen with an error panel.
3. **Settings flashed a full-page skeleton after every save** (`if (loading || !data) return <SettingsSkeleton/>`,
   and every save calls `loadSettings()`, which sets `loading`). Its skeleton ignored the tab, so Team,
   Authentication and Notifications loaded under a General-shaped skeleton. No caching.
4. **Skeletons drawn for an older layout.** The Overview, Findings, Domains and Settings skeletons still carried the
   old eyebrow header, a ticker row and different grids (panels moved 77–127 px). Compliance used a readiness-only
   skeleton for every section (137–193 px).
5. **Generic loaders on data pages:** Reports and every compliance tab used `LoadingPanel`; Remediation used the
   `Loading` tile block; Scans used three grey bars (437 px at 1440); Platform painted its page with "Loading…" in
   the health card (no skeleton at all); the reviewer area (`/reviews`) and Reviewer access showed plain "LOADING…"
   text; onboarding showed a pulsing icon instead of the shell's loading screen.
6. **A non-`main` frame on every cold deep link:** the chunk fallback (`PageFallback`) rendered outside `main#main`,
   a generic two-card shape unrelated to the page.
7. **Skeletons nearly invisible in dark mode:** the dark fill was a hard-coded `#171510` on raised panels of
   `#14130F`; and every `rounded`/`circle` prop on `Skeleton` was overridden by the `.skeleton` rule's 3 px radius.
8. **Motion had tokens but almost nothing used them:** `--motion-fast/base/page/enter` existed and six rules used
   them; 60+ rules hard-coded 0.12–0.4 s with three spellings of the same easing; every Tailwind `transition-*`
   utility ran at Tailwind's own 150 ms curve; data arriving translated content 6 px (`contentFadeIn`) and table
   rows replayed a 6 px rise whenever they remounted (Assets/Domains swapped rows for skeleton rows).
9. **Dead animation classes:** both mobile menu sheets and the board-report notice used `animate-in …` classes that
   need `tailwindcss-animate` (not installed): no enter motion at all.
10. **Two scroll-restoration rules:** the customer shell used `useLayoutEffect` keyed on navigation type; the owner
    shell used `useEffect` keyed on `location.key`, after paint, so a new console page could paint one frame at the
    old scroll position.

## Routes (before → after)

"Page skeleton" means the page's real header (the same `PageHead`, title and note) plus shapes in the page's own
grid and classes; the same component serves a cold deep link (route fallback) and the first data load.
"SWR" = the last data paints at once on a revisit and is refreshed in the background.

### Customer app (`App.tsx`, inside `AppShell` unless noted)

| Route | Before | After: skeleton | Motion | Cache key | Focus / revisit | Bugs fixed |
|---|---|---|---|---|---|---|
| `/` signed out | public landing, prerendered | unchanged | marketing reveal on `--motion-reveal` | none | — | — |
| `/` signed in | `LoadingScreen` → `/overview` | unchanged | — | — | — | — |
| `/overview` | outdated `OverviewSkeleton` | `OverviewSkeleton`: organisation-name header, score card, 4 KPI tiles, severity bar, two panels, recent-scans table | page enter; data fades | `overview`, `overview:domains` | 10 s poll, focus, online (kept) / SWR | panels 77 px off |
| `/assets` | inline rows, fixed px widths | `AssetsSkeleton` on first load; `AppTableRows` on a filter change | page enter; rows fade once | `assets:{type}:{search}` | focus (30 s throttle) / SWR | px-width rows |
| `/findings` | outdated full-page skeleton, also on any uncached filter change | `FindingsSkeleton` first load only; `FindingsListSkeleton` on a filter change (header and filters stay, focus kept) | page enter; cards fade once | `findings:{severity}:{category}:{search}` | focus / SWR | filter change swapped the whole page |
| `/scans` | three grey bars | `ScansBodySkeleton` in Scans.css classes (summary, metrics, checks, history) | page enter | none: live progress (by design) | 3 s poll while a scan runs (kept) / mount | 437 px at 1440 |
| `/domains` | outdated `DomainsSkeleton` | `DomainsSkeleton` | page enter; rows fade once | `domains` | focus / SWR | — |
| `/remediation` | `Loading` tile block | `RemediationSkeleton`; table skeleton on a filter change | page enter | `remediation:{status}` | focus / SWR | — |
| `/reports` | `LoadingPanel` | `ReportsSkeleton` (retention panel + table) | page enter | `reports` | focus / SWR | — |
| `/reports` preview dialog | `LoadingPanel` | unchanged (dialog) | dialog tokens | none | — | — |
| `/settings` (general) | tab-blind skeleton after every save | `SettingsSkeleton({tab})` only while nothing is loaded; billing and closure cards for owners | page enter | `settings` (organisation and members only) | mount only (forms) | flash after save; empty form fields on a cached revisit |
| `/settings?tab=team`, `auth`, `notifications` | General-shaped skeleton | tab-shaped skeleton; notification rows skeleton inside the panel | — | `settings`; billing, invoices, MFA and notification preferences never cached | mount | — |
| `/comply` (readiness) | readiness skeleton | `ComplianceSkeleton({section})`: header with register title, disclaimer, tab bar, section heading, panel | page enter | `comply:overview`, `comply:questionnaire` | focus (readiness only) / SWR | 193 px |
| `/comply?section=questions` | `LoadingPanel` | `CompliancePanelSkeleton('questions')` | — | `comply:questionnaire` | with the page (no focus: forms) | — |
| `/comply?section=incidents` | `LoadingPanel` | panel skeleton | — | `comply:incidents` | mount / SWR | — |
| `/comply?section=packs` | `LoadingPanel` | panel skeleton | — | `comply:packs` | mount / SWR | — |
| `/comply?section=documents` | `LoadingPanel` | panel skeleton | — | `comply:documents` | mount / SWR | — |
| `/comply?section=reviewers` | "LOADING REVIEWER ACCESS…" | panel skeleton | — | `comply:reviewers` | mount / SWR | 193 px |
| `/platform` (staff) | page painted with "Loading…" | `PlatformSkeleton` during the first health check | page enter | none (audited support reads) | mount | no skeleton |
| `/reviews` (outside shell) | "LOADING…" text | `LoadingScreen` for the session check; card skeleton per organisation | — | none (time-boxed reviewer grants) | mount | — |
| `/onboarding/*` (outside shell) | pulsing icon + text | `LoadingScreen` (same as the shell) | — | none | — | — |
| `/login`, `/signup`, `/forgot-password`, `/reset-password`, `/auth/callback` | `LoadingScreen` while the chunk loads | unchanged | — | none (auth is never cached) | — | — |
| Public pages (`/terms`, `/privacy`, `/pricing`, `/about`, `/scanner`, `/teams`, `/contact`, `/newsletter*`, `/health`) | eager, prerendered | unchanged | marketing reveal on `--motion-reveal` | none | — | — |
| Any app route whose code is still downloading | `PageFallback` outside `main` | `RouteSkeleton` for that path (and tab / section) inside `main` | — | — | — | non-`main` frame |

Drawers (asset, finding, scan detail) keep their purpose-built drawer skeletons (`components/Skeleton.tsx`);
dialogs (`ui/Dialog`, `ConfirmDialog`, `Modal`) keep their open/close animations, now on the tokens.

### Owner console (`owner/OwnerApp.tsx`, `owner/shell.tsx`)

| Route | Before | After: skeleton | Cache key (path + params) | Panels before → after (worst width) |
|---|---|---|---|---|
| sign-in, setup | `LoadingScreen` while the session is checked | unchanged | none (auth) | — |
| `/` overview | generic panel | 8 KPI tiles, sign-ups chart, invoices, activity table | `/overview?{}` | 170 → 8 px |
| `/analytics` | generic panel; charts "Loading…" | 2 KPI rows; chart areas in the chart's own box; count lines; a range change dims the current charts | `/analytics/summary?{range}`, `/analytics/timeseries?{range}` | 10 → 13 px |
| `/organizations` | generic panel | table skeleton with the real column names + pager; a filter / page change keeps rows dimmed until the new ones arrive | `/organizations?{filters,offset,limit}` | 0 → 0 px |
| `/organizations/:id` | generic panel | `DetailSkeleton` (summary, members, domains, billing, three wide tables) + subtitle placeholder | `/organizations/{id}?{}` | 453 → see table |
| `/users` | generic panel | table skeleton | `/users?{…}` | 0 → 0 px |
| `/users/:id` | generic panel | `DetailSkeleton` + subtitle and action placeholders | `/users/{id}?{}` | 484 → see table |
| `/subscriptions` | generic panel | table skeleton + invoices panel placeholder | `/subscriptions?{…}` | 407 → 81 px |
| `/scans` | generic panel | panel with table skeleton + pager; state chips dim the current rows | `/scans?{q,state,offset,limit}` | 0 → 0 px |
| `/scans/:id` | generic panel | `DetailSkeleton` + subtitle placeholder | `/scans/{id}?{}` | 520 → see table |
| `/newsletter` | generic panel | KPI row + drafts table | `newsletter:drafts` | 172 → 10 px |
| `/newsletter/:id` | generic panel | summary, sections and preview panels + subtitle placeholder | `newsletter:drafts` | 555 → see table |
| `/logs` | generic panel | table skeleton with the source's columns | `/logs?{source,q,offset,limit}` | 0 → 0 px |
| `/system` | generic panel | API/database, scanner and scheduled-runs panels | `/system?{}` | 509 → see table |

Owner views revalidate on mount only: console reads are audited and count as session activity, so focus or
interval refetching would write audit rows and keep an idle owner session alive (see `lib/notifications.ts`).

### Shared pieces

| Piece | Before | After |
|---|---|---|
| `components/ui/StatePanels.tsx` (`LoadingPanel`, `EmptyPanel`, `ErrorPanel`) | the loading/empty/error trio | unchanged; `LoadingPanel` remains for dialogs and as a fallback |
| `components/ui.tsx` `Loading` | tile-block loader (Remediation) | removed (no users left) |
| `components/ui.tsx` `LoadingScreen` | session hand-off | the one full-screen loader: app shell, owner console, onboarding, reviewer area, auth pages |
| `components/Skeleton.tsx` | 1,125 lines, mostly page skeletons for an older layout | primitives (`Skeleton` — whose `rounded`/`circle` now take effect — and `SkeletonText`), score ring, stat card, drawer and AI-report skeletons |
| `.skeleton` fill | `--inset` in light; `#171510` in dark (nearly the raised panel colour) | one `--skeleton` token: `--inset` in light, `--line` in dark; also used by the reduced-motion (no shimmer) rule |
| `components/ui/Skeleton.tsx` (new) | — | the shape set: `SkeletonRegion`, `SkLine`, `SkBlock`, `SkControl` (44 px on phones), `SkField`, `SkCard`, `SkKpi`, `SkChart`, `SkListItem`, `SkTableRows` (ledger markup with `table-stack`, so rows stack into cards below 640 px) |
| `components/skeletons/RouteSkeleton.tsx` (new) | — | one skeleton per customer route / tab / section, used by the pages and as the route fallback |
| `owner/skeletons.tsx` (new) | — | the console's panels, KPI rows, detail, list, chart and subtitle skeletons |
| Topbar, Sidebar, `NotificationBell`, `NotificationRow` | — | **not changed** (markup and classes stable; the bell and its phone sheet come from `notifications-mobile-swipe`, merged as #69). The bell keeps its own polling: 60 s while the tab is visible plus on focus; the owner bell polls the count only |
| Owner shell | `main` keyed by path; scroll reset after paint | same `main`; shared `useRouteScroll`; menu sheet uses `sheet-enter` |
| Customer shell | `PageFallback` outside `main`; `main` keyed by path | `main#main.page` keyed by **organisation id + path**, `Suspense` inside it with `RouteSkeleton`; the demo note and suspension banner stay outside the boundary |

## Motion

Tokens (`src/index.css :root`), honoured by every transition and one-shot animation in `index.css` and, through
`tailwind.config.js` (`transitionDuration.DEFAULT`, `transitionTimingFunction.DEFAULT`), by every Tailwind
`transition-*` utility:

| Token | Value | Use |
|---|---|---|
| `--motion-fast` | 120 ms | hover and focus colour changes, small toggles |
| `--motion-base` | 170 ms | buttons, chips, cards lifting, palette |
| `--motion-page` | 190 ms | page enter (`pageEnter`: fade + 4 px rise on `main.page`) |
| `--motion-enter` | 220 ms | data arriving (fade only), dialogs, toasts, scrims, sheets |
| `--motion-slow` | 320 ms | drawers, sidebar, dock |
| `--motion-reveal` | 700 ms | marketing scroll reveals only |
| `--motion-stagger` | 40 ms | step between items entering together (rows, stat strip) |
| `--motion-ease` / `--motion-ease-out` | `cubic-bezier(.2,.8,.2,1)` / `cubic-bezier(.16,1,.3,1)` | everything above |

Rules:
- Route change: the shell stays mounted; only `main.page` re-enters (customer app and owner console, same keyframe).
  No exit animation, so there is no frame of the previous page and no blank frame between pages. A new page opens
  at the top before it paints; back/forward keeps the position; a filter written to the query string never scrolls.
- Data arriving fades (`contentFadeIn`, opacity only); rows fade once when they first mount (`stagger-row`,
  opacity only). A refresh keeps rows mounted, so nothing replays and nothing moves.
- A background refresh changes nothing on screen; a filter or page change in the console dims the current rows
  until the new ones arrive.
- `prefers-reduced-motion: reduce`: no page, row, sheet, data or skeleton-shimmer animation (explicit rules plus
  the existing global near-zero duration rule), on desktop and phones alike.
- Left on purpose: the branded cursor's tracking, progress meters filling, the guided-tour spotlight and CyphBot's
  word animations keep their own timings (tracking or progress, not transitions); all stop under reduced motion.

## Caching

One store (`src/lib/queryCache.ts`), memory only, used by the customer app (through `lib/pageCache.ts` for pages
with their own loaders) and the owner console (`useOwnerView`, the newsletter hook).

**Keys.** Customer app: `app␀{user id}␀{organisation id}␀{key}`, with the page keys in the route table
(`overview`, `overview:domains`, `assets:{type}:{search}`, `findings:{severity}:{category}:{search}`, `domains`,
`remediation:{status}`, `reports`, `settings`, `comply:overview`, `comply:questionnaire`, `comply:incidents`,
`comply:packs`, `comply:documents`, `comply:reviewers`). Owner console: `owner␀{owner email}␀{path}?{params as
JSON}` and `newsletter:drafts`. Nothing is read or written without a full scope.

**Policy: stale-while-revalidate.** A page seen before paints its last data at once and asks again in the
background; a page never seen shows its skeleton. Customer list pages and compliance readiness also ask again when
the tab regains focus (30 s throttle); Overview keeps its 10 s poll; Scans keeps its 3 s poll while a scan runs;
pages with forms (Settings, compliance sections) and the owner console revalidate on mount only.

**Invalidation.**
- Any write in the customer app (`apiFetch` non-GET, except `/ai/*` reads and notification marks) and the evidence
  upload clear the cache; any console action (`ownerFetch` non-GET, except notification marks) clears the owner scope.
- Sign-in, sign-out, idle sign-out and a confirmed 401 clear everything (`auth.tsx`); a change of organisation
  (`persistTenant` with a different id: invitation accepted, workspace created) clears everything; the owner console
  clears its scope on sign-out and when its session ends (401).
- Every request takes a ticket (scope + generation) when it **starts**; clearing bumps the generation, and a write
  whose scope or generation changed is dropped. A response in flight across a switch, sign-out or write is never
  stored, and is never shown when the scope changed.
- The content area is keyed by organisation id, so no page state survives an organisation switch.

**Never cached.** Write responses; auth, MFA, billing and invoices; live scan progress (Scans list and detail);
platform support reads; reviewer-area reads; notification preferences and the bell. Nothing from the cache goes to
localStorage or sessionStorage (the test reads both after browsing and finds no cached data). What stays in Web
Storage is unchanged: session tokens, the active organisation id, theme, sidebar state and similar UI flags.

## Mobile (390 and 320, touch)

- Every skeleton uses the page's own responsive grid classes (`grid-cols-*`, `md:`, `lg:`), so phones get the
  stacked cards and rows the page shows; tables use `table-stack`, so skeleton rows stack into labelled cards below
  640 px like the real ones.
- Control placeholders (`SkControl`) are 44 px tall at 900 px and below, like the controls they stand for; the test
  counts any placeholder under 44 px on phones.
- No horizontal scroll in the skeleton state or the loaded state at 390 and 320 (tested on every route).
- Page enter is 190 ms with a 4 px rise and no exit; reduced motion is checked with a touch phone viewport too.
- Shell, Topbar and NotificationBell markup and classes are unchanged; the customer mobile menu sheet only gains
  the `sheet-enter` class (its dead `animate-in …` classes are left in place to keep its markup stable).

## Measurements

Measured with `scripts/capture-motion-cache.mjs` (same harness and fixtures for both runs: "before" on untouched
`main` 6438063, "after" on this branch), Vite dev server, headless Chromium, data held back 900 ms, phones emulated
as touch devices. Raw data: `cls-before.json`, `cls-after.json`; screenshots of the main pages in the skeleton and
loaded states at 1440 and 390: `before/`, `after/` (JPEG, all under 200 KB).

Two numbers per cell: **CLS** (Chrome's cumulative layout shift for the whole load) / **panel offset** (for each
outer bordered panel of the loaded page in the first screen, the distance to the nearest panel the skeleton drew;
the worst one). "no skeleton" = the page painted without one.

**Read the panel offset first.** CLS is near zero in most cells of both runs because Chrome only counts elements
that existed before and moved; a skeleton swapped out for new content is all new nodes, so CLS cannot see a
skeleton that does not match. It did catch two real shifts before (Reports at 320: 0.166; owner analytics at 1440:
0.048), both gone. The panel offset is what the eye sees: where the panels jump to when the data arrives.

| Route | 1440 before | 1440 after | 390 before | 390 after | 320 before | 320 after |
|---|---|---|---|---|---|---|
| `/overview` | 0.0000 / 77 px | 0.0000 / 0 px | 0.0001 / 48 px | 0.0001 / 1 px | 0.0002 / 26 px | 0.0002 / 0 px |
| `/assets` | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 4 px | 0.0000 / 0 px | 0.0000 / 4 px |
| `/findings` | 0.0000 / 91 px | 0.0000 / 1 px | 0.0000 / 79 px | 0.0000 / 44 px | 0.0000 / 113 px | 0.0000 / 49 px |
| `/scans` | 0.0004 / 437 px | 0.0000 / 66 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px |
| `/domains` | 0.0000 / 31 px | 0.0000 / 2 px | 0.0000 / 49 px | 0.0000 / 4 px | 0.0000 / 49 px | 0.0000 / 4 px |
| `/remediation` | 0.0000 / 50 px | 0.0000 / 5 px | 0.0000 / 49 px | 0.0000 / 0 px | 0.0000 / 49 px | 0.0000 / 0 px |
| `/reports` | 0.0000 / 115 px | 0.0000 / 1 px | 0.0000 / 129 px | 0.0000 / 1 px | 0.1659 / 201 px | 0.0000 / 21 px |
| `/settings` | 0.0000 / 127 px | 0.0000 / 0 px | 0.0000 / 201 px | 0.0000 / 0 px | 0.0000 / 4 px | 0.0000 / 0 px |
| `/comply` | 0.0000 / 193 px | 0.0000 / 23 px | 0.0000 / 137 px | 0.0000 / 0 px | 0.0000 / 137 px | 0.0000 / 19 px |
| `/platform` | 0.0000 / – (no skeleton) | 0.0000 / 1 px | 0.0000 / – (no skeleton) | 0.0000 / 1 px | 0.0000 / – (no skeleton) | 0.0000 / 1 px |
| `/comply?section=questions` | 0.0160 / 92 px | 0.0160 / 38 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px |
| `/comply?section=incidents` | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px |
| `/comply?section=packs` | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px |
| `/comply?section=documents` | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px |
| `/comply?section=reviewers` | 0.0000 / 193 px | 0.0000 / 0 px | 0.0000 / 137 px | 0.0000 / 0 px | 0.0000 / 137 px | 0.0000 / 0 px |
| `/settings?tab=team` | 0.0000 / 51 px | 0.0000 / 0 px | 0.0000 / 4 px | 0.0000 / 0 px | 0.0000 / 4 px | 0.0000 / 0 px |
| `/settings?tab=auth` | 0.0000 / 51 px | 0.0000 / 0 px | 0.0000 / 4 px | 0.0000 / 0 px | 0.0000 / 4 px | 0.0000 / 0 px |
| `/settings?tab=notifications` | 0.0000 / 51 px | 0.0000 / 0 px | 0.0000 / 4 px | 0.0000 / 0 px | 0.0000 / 4 px | 0.0000 / 0 px |
| `/admin` | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 170 px | 0.0000 / 8 px | 0.0000 / 170 px | 0.0000 / 8 px |
| `/admin/analytics` | 0.0478 / 0 px | 0.0000 / 0 px | 0.0000 / 7 px | 0.0000 / 13 px | 0.0000 / 10 px | 0.0000 / 0 px |
| `/admin/organizations` | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px |
| `/admin/organizations/o1` | 0.0000 / 219 px | 0.0000 / 24 px | 0.0000 / 453 px | 0.0000 / 18 px | 0.0000 / 453 px | 0.0000 / 18 px |
| `/admin/users` | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px |
| `/admin/users/u1` | 0.0000 / 484 px | 0.0000 / 7 px | 0.0000 / 432 px | 0.0000 / 35 px | 0.0000 / 388 px | 0.0000 / 14 px |
| `/admin/subscriptions` | 0.0000 / 407 px | 0.0000 / 81 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px |
| `/admin/scans` | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px |
| `/admin/scans/sc1` | 0.0000 / 520 px | 0.0000 / 15 px | 0.0000 / 506 px | 0.0000 / 6 px | 0.0000 / 506 px | 0.0000 / 6 px |
| `/admin/newsletter` | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 172 px | 0.0000 / 10 px | 0.0000 / 172 px | 0.0000 / 10 px |
| `/admin/newsletter/n1` | 0.0000 / 326 px | 0.0000 / 4 px | 0.0000 / 555 px | 0.0000 / 204 px | 0.0000 / 398 px | 0.0000 / 47 px |
| `/admin/logs` | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px | 0.0000 / 0 px |
| `/admin/system` | 0.0000 / 253 px | 0.0000 / 7 px | 0.0000 / 509 px | 0.0000 / 18 px | 0.0000 / 253 px | 0.0000 / 8 px |

| Width | customer app before (worst panel / worst CLS) | customer app after | owner console before | owner console after |
|---|---|---|---|---|
| 1440 | 437 px / 0.0160 | 66 px / 0.0160 | 520 px / 0.0478 | 81 px / 0.0000 |
| 390 | 201 px / 0.0001 | 44 px / 0.0001 | 555 px / 0.0000 | 204 px / 0.0000 |
| 320 | 201 px / 0.1659 | 49 px / 0.0002 | 506 px / 0.0000 | 47 px / 0.0000 |


Views still above 24 px after the change, and why. The test allows these explicitly (`DATA_DEPENDENT` in
`check-motion-cache.mjs`); every other route must stay within 48 px, and every route's first panel within 8 px:
- `/scans` 66 px at 1440: the coverage notice appears only for a scan with partial coverage (the fixture has one).
- `/findings` 44–49 px on phones: a finding's title and category wrap to two or three lines.
- `/admin/subscriptions` 81 px at 1440: the invoices panel grows with the number of invoices.
- `/admin/users/u1` 35 px at 390: memberships and sessions differ per user.
- `/admin/newsletter/n1` 204 px at 390: the title and subtitle are the draft's subject and preview line, which wrap
  to several lines on a phone; the skeleton cannot know their length. Its allowance is 240 px, so on phones this view
  is measured, not enforced.
- `/comply?section=questions` 38 px and CLS 0.016 at 1440 (same CLS as before): the "renewals due" count appears in
  the tab bar once the questionnaire arrives.

The thresholds were set after the first measurement: 24 px was the first target; it became 48 px plus the five
allowances above when the remaining offsets turned out to come from text length in the fixtures, not from the
skeleton's grid.

Bundle cost: the route skeletons are eager (they must render before a page's code arrives), so they and the
Scans/compliance stylesheets they use now ship in the entry bundle: entry JS 478.5 → 489.0 KB (+4.4 KB gzip),
entry CSS 139.6 → 158.7 KB (+3.3 KB gzip).


## Tests

All on this branch, headless Chromium, fixtures only (nothing reaches a server). The existing suites print one
"ok/passed" line per suite, so they are counted as suites.

| Suite | Result |
|---|---|
| `npm run build` (tsc, vite, prerender) | passes |
| `test:motion-cache` (new) | **pass: 907 checks, 93 route loads** (31 routes × 1440/390/320) plus route changes, motion, revisit, organisation switch, sign-out and cache-rule checks |
| `test:compliance-ui` | pass (after the date fix below) |
| `test:scans-ui`, `test:score-ui`, `test:onboarding-ui`, `test:ux-ui` | pass |
| `test:admin-phase1`, `test:admin-phase2`, `test:owner-logs`, `test:admin-newsletter`, `test:admin-delete-org` | pass |
| `test:notifications`, `test:notifications-mobile` | pass |
| `test:reviewer-ui`, `test:board-report-ui`, `test:datetime` (also in CI) | pass |
| `test:ui-refine` | everything passes except three social links on the landing page at 30×30 px on phones (`SocialFloat`, from #70); identical on untouched `main` |
| `test:product-tour` | not run: it needs a real local backend on 127.0.0.1:5173 (demo sign-in); it fails the same way on `main` without one |

Required list: 11 of 11 pass (`compliance-ui`, `scans-ui`, `score-ui`, `onboarding-ui`, `ux-ui`, `admin-phase1`,
`admin-phase2`, `owner-logs`, `admin-newsletter`, `admin-delete-org`, `notifications`), plus the new suite.

The new suite's organisation-switch test was checked against a deliberate regression (the content area keyed by
path only, as before): it fails with four findings, including frames that showed the previous organisation's data.

Test files changed outside the new suite:
- `check-compliance-page.mjs`: expected the incident form to say `UTC-04:00`; daylight saving ended in New York on
  1 November 2026, so it failed on untouched `main` today. It now computes today's offset.
- `check-ui-refine.mjs`: expected End to land on the Authentication tab; Settings has had a fourth tab
  (Notifications) since the notifications work, so it failed on untouched `main`. It now expects Notifications.

Other notes:
- The notification row's swipe and switch timings (`.notif-swipe`, `.notif-switch-*`) are left exactly as
  `notifications-mobile-swipe` set them (its suite asserts 0.18 s); everything else in `index.css` uses the tokens.

## What was not verified

- **Production build behaviour.** Every number and every browser test ran against the Vite dev server (unbundled
  modules) with fixtures. `npm run build` (TypeScript, Vite, prerender) passes, but transitions and chunk timing
  were not measured on the production bundle or on app.cyphward.com / admin.cyphward.com (no production access was
  used).
- **Real devices.** Phones were emulated in headless Chromium (390×844 and 320×720, touch, `isMobile`); no iOS Safari
  or Android Chrome device was used, so reduced motion on mobile browsers is verified through emulation only.
- **Real data shapes.** Skeleton geometry was calibrated against the suites' fixtures; panels whose height depends on
  text length or row counts (listed under Measurements) can still move on real accounts.
- **Cold chunk loads.** The route fallback is the same component a page uses for its first data load, but a slow
  chunk download was not simulated separately.
- **Organisation switching UI.** There is no organisation switcher in the app; the switch tested is the path that
  exists (an invitation accepted while signed in). A future switcher must go through `persistTenant` to inherit the
  cache clearing.
- **CI.** CI runs `npm run build` and `test:datetime` only; the browser suites were run locally.
