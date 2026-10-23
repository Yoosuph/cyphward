# Report and motion review — 23 October 2026

The review found functional problems in the initial improvements, which are now corrected:

- Full HTML reports were inserted into the dashboard document. Their `body` and `table` styles could change the surrounding application. The preview now uses a separate, automatically sized document with scripts disabled. Escape, Tab and Shift+Tab continue to work inside the dialog.
- Reduced-motion settings shortened animation durations but retained stagger delays. Both animation and transition delays now become zero; the loading indicator stays visible without moving.
- Score panel padding was applied to a collapsed table and did not reliably inset its content. Padding now belongs to the cells, with a stacked mobile layout.
- Zero scores displayed a minimum 2% progress bar. The bar now represents the supplied value, including zero.
- Reports with nonzero finding counts but no detail rows could claim there were no open findings. They now direct the reader to review the recorded findings.
- Zero counts and the assessment availability badge used reassuring green styling. They now use neutral colours. Positive resolution counts retain green.
- Long domains, finding descriptions and the footer now fit phone widths. Finding labels stack above the text on phones. Printed reports omit dashboard action buttons.

## Evidence

- `python -m pytest backend/tests/test_mailer.py backend/tests/test_declared_scope_copy.py backend/tests/test_reports_tenant.py -q --disable-warnings`: 32 passed.
- `CHROME_BIN=/usr/sbin/chromium npm run test:ux-ui` in `frontend`: desktop, 390px and 320px passed. Includes report CSS isolation, disabled report scripts, Escape inside the report, Tab/Shift+Tab boundaries, reduced-motion delays, and existing dialog and domain workflows.
- `npm run build` in `frontend`: passed, including TypeScript and public-page prerendering. Vite still reports the existing large CyphBot chart-renderer chunk.
- Generated reports with regular content, long company/domain names and no assessment: nine combinations at 320px, 390px and 1440px, all without horizontal page overflow.

The sample uses synthetic data. [Open sample HTML](sample-report.html), [mobile screenshot](report-390.png), [desktop screenshot](report-1440.png).

Browser checks used Chromium. Rendering in individual mail applications was not tested. Existing issued reports keep their stored HTML; template changes apply when generating a new report.
