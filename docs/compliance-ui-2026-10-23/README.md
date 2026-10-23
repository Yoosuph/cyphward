# Compliance workspace UI — 23 October 2026

The readiness page now leads with evidence coverage and practical next actions: review gaps, answer questions and prepare an evidence pack. Coverage explicitly includes recorded gaps and is not presented as a compliance score. Existing source labels, pending clause reviews, exclusions and plan restrictions retain their meaning.

Navigation uses icon tabs, with a compact grid on phones so every available section is visible. Section URLs such as `/comply?section=questions` survive refresh and support browser Back and Forward. Keyboard navigation moves from the focused tab, including during rapid consecutive arrow presses. Each section has a short description. Detailed guidance is expandable; the legal disclaimer stays visible. Requirement rows show an expand indicator on mobile as well as desktop.

The register supports search and combined status/group filters, an announced visible count and an empty state with filter reset. Search runs only over already-authorized data. Locked groups remain gated. Empty applicable groups point to exclusions. A failed refresh with cached data now displays a retry error instead of silently retaining old results.

Validation:

- `npm run build` in `frontend` — type checking, production bundle and public prerender.
- `npm run test:compliance-ui` — existing questionnaire, incident, pack, document, evidence-file, timezone, permission, plan, dialog and keyboard checks at desktop/390/320px.
- `node frontend/scripts/check-compliance-layout.mjs` — new search, combined filters, empty/reset, keyboard tabs and page overflow checks at 1440/390/320px. Uses fixture data; no customer writes or model requests.

Reviewed screenshots: `/tmp/compliance-ui-before/comply-readiness-desktop.png` and `/tmp/compliance-after-{1440,390,320}.png`. No backend, compliance calculations or payment activation changes are included.


## Workspace follow-up

- A layout skeleton keeps the page title and the main evidence-card shapes visible while data loads.
- Evidence status totals are filter shortcuts with a pressed state. Selecting one clears unrelated filters and brings the register into view below the sticky top bar.
- Section headings explain the active workflow. The questionnaire tab and next-action card show actual expired-answer counts; the count also has a screen-reader description.
- A failed questionnaire refresh keeps existing answers visible and shows a retry message.
- Requirement details have associated expand controls and regions, with a visible mobile chevron. Members receive a View only label; existing plan and role restrictions continue to apply.
- Tab changes use the shared content entrance timing. Mobile status shortcuts retain 44px or larger targets without forcing the summary into four long rows.

The layout checks also cover visible navigation targets, status shortcuts, requirement expansion, section URLs after reload, Back/Forward, and failed refresh with existing questionnaire data.

Screenshots use synthetic API fixtures: [mobile](workspace-mobile.png), [desktop](workspace-desktop.png).
