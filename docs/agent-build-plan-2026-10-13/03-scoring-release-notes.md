# Packet 03 scoring gate — review candidate, not deployed

## Contract

`cyphward-risk-v3` preserves the v2 severity weights and known-risk formula. It changes eligibility and presentation, so v1/v2 snapshots are not comparable history. Existing measurements remain untouched.

Authoritative completion derives version 1 assessment coverage from the producing observations and the hosts whose security checker completed. Conclusive apex TXT/DMARC policy checks, observed HTTP headers/certificates and confirmed template matches count as evaluated security-check groups. DNS/ports/TLS inventory or a successful tool process alone does not certify a security evaluation. A blocked HTTP redirect cannot certify header resolution. These groups are not an exhaustive count of all rules/requests.

Version 1 coverage was only ever partial, unassessed or unknown. Version 2, below, defines when coverage is complete.

## Declared-scope completeness (coverage version 2, check set `cyphward-checks-v1`)

The authoritative definition is the docstring of `backend/app/risk/check_set.py`. In summary:

- **Declared checks.** On the apex: `dns.spf` and `dns.dmarc` (conclusive exact DNS question plus a completed security checker). On each in-scope host: `ports.inventory` (port tool succeeded for the host), `http.headers` (usable HTTP response, no blocked redirect) and `tls.certificate` (certificate observed). Each security check also requires the security checker to have completed for that host.
- **Targets.** In scope means selected for DNS with a public address. A host whose A and AAAA answers are conclusive with no public address is omitted (`no_public_dns_address`). A host whose address lookup failed is missing (`dns_address_unknown`). A registered host dropped by selection blocks complete. Passive hosts dropped by the cap are reported but do not block.
- **Web applicability.** A conclusive port inventory with neither 80 nor 443 open omits `http.headers` and `tls.certificate` (`no_web_service`). With 80 open and 443 not open, `tls.certificate` is omitted (`no_https`) and `http.headers` stays required. Direct evidence wins over the inventory. A host with 80/443 open but no usable response stays missing.
- **States.** `complete` when nothing is missing and at least one host is in scope. Otherwise `partial` when anything was evaluated, else `unassessed`. Scans without a version-1 target selection keep the version-1 fallback and are never complete. `requested_checks` is an integer except in that fallback.
- **Nuclei** is a separate, non-gating line: "Known-CVE templates: matches reported; clean results not proven." Confirmed matches still count as evaluated evidence, as before. No-match handling stays inconclusive.

### Organisation grade gate

The score is organisation-wide, so a grade requires **every verified domain** in the organisation to have a complete latest assessment (`backend/app/risk/domain_coverage.py`). If any verified domain is partial, legacy/unknown or never scanned, the engine treats the result like partial coverage: a known-risk index without a grade when there is scored open risk, and no numeric score when there is none. The posture is "Not all domains assessed", and a per-domain line is shown, for example `example.com: complete · other.ng: not scanned`. A graded result carries `scope_label: "Within declared scope"`. The gate is re-evaluated at read time, so adding a new verified domain removes the grade until that domain is assessed.

Coverage version 2 is additive JSON in the existing `assessment_coverage` column and `stage_progress.scoring`; no new migration is required. Version-1 snapshots keep their meaning and never become complete.

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
