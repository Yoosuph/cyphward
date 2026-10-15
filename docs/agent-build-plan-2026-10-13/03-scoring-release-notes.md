# Packet 03 scoring gate — review candidate, not deployed

## Contract

`cyphward-risk-v3` preserves the v2 severity weights and known-risk formula. It changes eligibility and presentation, so v1/v2 snapshots are not comparable history. Existing measurements remain untouched.

Authoritative completion derives version 1 assessment coverage from the producing observations and the hosts whose security checker completed. Conclusive apex TXT/DMARC policy checks, observed HTTP headers/certificates and confirmed template matches count as evaluated security-check groups. DNS/ports/TLS inventory or a successful tool process alone does not certify a security evaluation. A blocked HTTP redirect cannot certify header resolution. These groups are not an exhaustive count of all rules/requests.

The current adapters emit only partial, unassessed or unknown coverage; they never emit complete coverage. The engine reserves complete coverage for a future validated adapter, exercised only as synthetic fixtures in the current tests.

- No evaluated security checks, failed assessment or unknown legacy evidence: score and grade are null. Recorded findings, risk points and negative drivers remain available when assessment metadata exists.
- Partial evaluation with scored open risk: a numeric known-risk index, no grade or unchecked category health ratings. It describes current unresolved organization risk, including retained/other-domain findings; it does not claim the selected domain scan assessed the whole organization.
- Partial evaluation with zero scored open risk: no numeric score, no positive health claim. Zero recorded risk points is not proof of complete security. Resolved findings remain visible through the existing workflow.
- The existing `assessed` boolean indicates a numeric index is available; it does not mean complete coverage. Read `assessment.coverage.state` and the accompanying label.

Coverage is persisted in `stage_progress.scoring.coverage` and in the score snapshot, in the same fenced terminal transaction as scan completion, completion notification and audit. Snapshot model/scope and coverage are retained; report summaries also carry model/scope/coverage. Latest current-risk APIs interpret legacy missing coverage as unknown; no fabricated historical backfill is performed. This can remove the current numeric score until a scan supplies sufficient evidence, while the historical scan values and open findings remain intact.

## Migration and compatibility

Apply **only** `20261015120000_assessment_score_coverage.sql` before deploying this Core/API. It drops the score snapshot's NOT NULL constraint and adds `assessment_coverage jsonb`. The fresh chain is now 26 migrations. No default score, rewrite of old records, reset or seed is part of this change.

Worker authority remains protocol v2. Deploy the updated Core/API after the migration and before the Packet 03 worker; old raw observations are accepted conservatively. Coordinate frontend deployment so null scores, unknown coverage and partial ratings render correctly. Primary-repository scanner deployment remains the only VPS operator.

Use the Packet 02 release mechanics for the eventual complete Packet 03 rollout: pause new claims, drain held recon/Core work, take private consistent backups and rehearse the migration on a restored application snapshot, apply only the new migration, release Core/API and the reviewed worker/frontend, verify health/authentication/claim compatibility, then resume allocation. Do not ship this incomplete packet by pushing worker paths to main accidentally. These notes are release preparation, not evidence that production changed.

Rollback must retain the nullable column and historical null measurements. Do not restore NOT NULL, replace null scores with zero/100 or drop evidence. An old Core rollback restores weaker score semantics: keep claims paused and prefer a forward fix over silently resuming false-clean scoring.

## Presentation and summaries

Dashboard, scan history/details, board summaries, reports and notification paths tolerate null scores. Partial coverage remains visible even if every stage process completed. AI summaries for partial/unknown evidence use the deterministic grounded path, without hardcoded TLS/clean-surface strengths or fabricated remediation priorities. This does not redesign immutable reports (Packet 04) or fix the separate general chat behavior.

## Remaining Packet 03 work

Actual per-template completion evidence, remaining requested/evaluated/failed/skipped tool/check identities and omissions, shared end-to-end deadlines, actual external-tool/egress boundary verification, final acceptance and coordinated rollout remain outstanding. Never describe this scoring gate as a complete scanner coverage implementation.
