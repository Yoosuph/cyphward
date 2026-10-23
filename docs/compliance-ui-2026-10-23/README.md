# Compliance workspace UI — 23 October 2026

The readiness page now leads with evidence coverage and practical next actions: review gaps, answer questions and prepare an evidence pack. Coverage explicitly includes recorded gaps and is not presented as a compliance score. Existing source labels, pending clause reviews, exclusions and plan restrictions retain their meaning.

Navigation uses icon tabs that scroll horizontally on small screens and bring keyboard-selected tabs into view. Each section has a short description. Detailed guidance is expandable; the legal disclaimer stays visible. Requirement rows show an expand indicator on mobile as well as desktop.

The register supports search and combined status/group filters, an announced visible count and an empty state with filter reset. Search runs only over already-authorized data. Locked groups remain gated. Empty applicable groups point to exclusions. A failed refresh with cached data now displays a retry error instead of silently retaining old results.

Validation:

- `npm run build` in `frontend` — type checking, production bundle and public prerender.
- `npm run test:compliance-ui` — existing questionnaire, incident, pack, document, evidence-file, timezone, permission, plan, dialog and keyboard checks at desktop/390/320px.
- `node frontend/scripts/check-compliance-layout.mjs` — new search, combined filters, empty/reset, keyboard tabs and page overflow checks at 1440/390/320px. Uses fixture data; no customer writes or model requests.

Reviewed screenshots: `/tmp/compliance-ui-before/comply-readiness-desktop.png` and `/tmp/compliance-after-{1440,390,320}.png`. No backend, compliance calculations or payment activation changes are included.
