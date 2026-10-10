# Risk score v2

The old four capped deductions hid both newly discovered risk and remediation
once a category reached zero. All Nuclei findings also fell into the same
15-point Exposure allowance.

V2 uses the total severity burden across **all unresolved organization
findings**. Critical findings contribute 60 risk points, high 20, medium 5,
low 1, and informational 0. The score is `10000 / (100 + risk points)`, rounded
to one decimal. These are product scoring weights, not a probability of breach
or an externally validated risk rating. One critical finding yields 62.5;
20 yield 7.7. Eight high findings yield 38.5; resolving three yields 50.0.

The formula has no category floor. Very small changes can still round to the
same displayed decimal at high risk burdens; the dashboard also shows exact
risk points and open finding counts. Unchanged findings produce unchanged
scores. Informational findings do not deduct points.

Each category now has an independent health score out of 100 using its own
burden. Category scores are diagnostic and do not add up to the overall score.
Nuclei categories are inferred from stored protocol/tags; HTTP and legacy
unclassified Nuclei results default to Web & Apps. Detector identity remains
unchanged so finding reconciliation and remediation verification still work.

Overview, the score API, reports, AI summaries, and newly completed scans use
all unresolved organization findings. A scan snapshot records organization
posture after reconciliation, including findings on other domains and findings
whose detectors failed or did not run. A later remediation can improve the
live score without rewriting a historical scan. Lack of findings is not proof
that every detector ran; the score is still gated on a completed scan.

Seven-day change compares the current score against the most recent snapshot
at or before seven days ago, with the same model and organization scope.
The API provides the baseline timestamp. Until comparable history exists,
the dashboard displays that limitation instead of a fabricated zero change.

## Deployment

1. Apply `supabase/migrations/20261009120000_risk_score_v2.sql` before deploying
   the API and workers. It preserves existing rows, changes score storage to
   one decimal, and adds model/scope/risk metadata to snapshots.
2. Deploy the API/worker and frontend together. New snapshots explicitly use
   `cyphward-risk-v2` and `organization`; old rows retain their legacy values.
3. Verify a completed scan's score matches Overview when findings have not
   changed since completion. Verify a resolved finding lowers risk points.

Historical v1 scores are not recalculated from today's findings. They remain
marked as legacy in scan details and are excluded from v2 trends. A formula
change may change the displayed current score even before another scan runs.
Rolling back application code does not require reverting the additive schema
changes; older inserts default to the legacy model and domain scope.

## Validation

Focused backend regressions cover saturation, severity, evidence categories,
tenant separation, history windows, score updates following remediation, and
scan/overview consistency with failed detectors. The frontend browser check
uses mocked API responses to exercise refresh failures and recovery.

Run the browser check with `npm run test:score-ui --workspace frontend`.
It requires Chromium (`CHROME_BIN` can override `/usr/bin/chromium`) and
starts/stops its own local Vite server. No live account is used.
