# C1 plan — register, s.39 mapping, Compliance page

**Branch:** `codex/compliance-c1`, stacked on `codex/compliance-c0`. One PR. API + frontend + one additive migration; **no worker or scanner change**.
**Governing rule:** section 0 of `README.md`. No compliance verdicts; every piece of evidence is labelled by source; unassessed is never shown as satisfied. Decisions D1–D7 are in `PROGRESS.md`.
**Approval:** reviewed and approved by the agent on 16 October 2026 under the founder's delegation, with the review changes in section 0 folded in. That approval covers this plan only. Applying the production migration and merging each wait for the founder's explicit OK.

## 0. Review changes (folded into the sections below)

1. **A compliance failure never fails a scan.** Rows are computed as pure code before the completion transaction, inside a try/except that re-raises `ClaimLost`. They are inserted under a SAVEPOINT inside `owned_transaction`. On any error the savepoint rolls back, no rows are written (they read as `not_assessed`) and the `scan.completed` audit metadata records `compliance_evidence: "error"`. The snapshot and completion still commit.
2. **Gaps are live.** Production check (read-only, 16 Oct): every real open finding links to an asset with a `domain_id`, and apex DMARC/SPF findings sit on apex assets. Even so, on read **any currently open mapped issue finding** makes its domain (or, when unlinked, the organization) a `gap`, whatever the stored row says. "Open" means `status != 'resolved'`, exactly as the scorer reads it, so `acknowledged` and `in_progress` still count as gaps. No customer-set status can make a requirement present.
3. **"Present" states its limits.** Every tool-backed register entry carries a fixed `checks_performed` line and a `not_checked` line, shown next to the status. The ports requirement records the observed open ports in `details` and the page lists them. Nuclei reuses "matches reported; clean results not proven". A source tag appears only when an evidence row exists; otherwise the page says "No evidence yet".
4. Rows are written for the **scanned** domain only; other domains keep their latest rows. Scan history joins `scans.domain_id`, since snapshots store `domain_id` NULL. `scan_id` uses `ON DELETE SET NULL` so history survives. "Create task" is open to every member (the existing endpoint's rule); it shows an existing task for that finding instead of creating a duplicate. The README disclaimer is used word for word and asserted. The page explains that the C1 ceiling is 6 of 29 (Nuclei can never be present).
5. Checked: the scanner image copies `backend/` but the worker imports only scanner/shared modules; the register JSON is not git-ignored. Production has 4 partial and 0 complete v2 snapshots in 90 days, so both scan-history requirements will start as not assessed for every customer.


## 1. Files

| File | Purpose |
|---|---|
| `backend/app/compliance/registers/ndpa_gaid_v1.json` | Versioned register, 29 requirements in 11 groups (section 2). All `clause_verified: false`. |
| `backend/app/compliance/register.py` | Loads and validates the register once at startup (fails startup if invalid); exposes `REGISTER`, `requirement(key)` and `groups()`. Validation is plain code, no new dependency. |
| `backend/app/compliance/mapping.py` | Pure functions. `domain_evidence(register, coverage, domain_findings, observed_at, scan_id)` returns the rows to write; `aggregate(...)` derives each requirement's status on read; `scan_history_evidence(...)` handles the two scan-history requirements. |
| `backend/app/compliance/status.py` | Read path: loads verified domains, latest rows, linked findings and complete-scan history, then calls `mapping.aggregate`. Applies D1 gating. |
| `backend/app/api/compliance.py` | `GET /api/v1/compliance/overview` and `GET /api/v1/compliance/requirements/{key}`. Uses `get_current_org`, so any member can read it, scoped to their organization. |
| `backend/app/workflows/inngest_workflow.py` | The finaliser computes evidence rows from the coverage it already builds plus the domain's open findings after reconciliation, then passes them to `finish_assessment`. |
| `backend/app/core/scan_execution.py` | `finish_assessment(..., compliance_evidence=None)` inserts the rows inside the existing `owned_transaction` (claim fence). The existing `scan.completed` audit row gains `compliance_evidence: <count>`. |
| `backend/app/main.py` | Registers the router and loads the register at import. |
| `supabase/migrations/20261017090000_compliance_evidence.sql` | Table, indexes, RLS, grants (section 3). |
| `frontend/src/pages/Compliance.tsx` | The page (section 6). |
| `frontend/src/lib/api.ts` | `complianceOverview()` and `complianceRequirement(key)`. |
| `frontend/src/App.tsx`, `components/Sidebar.tsx`, `components/MobileMenuSheet.tsx` | `/comply` renders the page instead of redirecting; nav entry "COMPLIANCE"; section label. `lib/hosts.ts` already lists `/comply` as an app path. |
| `frontend/scripts/check-compliance-page.mjs` + `package.json` `test:compliance-ui` | Browser suite with a stubbed API at desktop/390/320. |
| Tests | Section 5. |

## 2. Register v1

Entry fields (from README §2): `key`, `group`, `title`, `clause`, `clause_verified`, `summary`, `applies_to` (`all|dcpmi|uhl_ehl|conditional`), `applicability_question` (optional), `evidence_types`, `tool_mapping` (`{"checks": [...], "rules": [...]}` or `{"scan_history": {"min_complete_scans": 1}}`), `freshness_days`, `remediation_hint`.

Tool-backed in C1 (Security measures group, source `tool_observed`):

| Key | Declared checks | Issue rules (gap when open) | Fresh |
|---|---|---|---|
| `ndpa.s39.encryption_in_transit` | `tls.certificate`, `http.headers` | `tls.certificate.invalid`, `tls.certificate.expiring`, `http.hsts.missing`, `http.hsts.no_subdomains` | 30 d |
| `ndpa.s39.web_security_headers` | `http.headers` | `http.csp.missing`, `http.frame_options.missing`, `http.content_type_options.missing`, `http.server_version_disclosed`, `http.powered_by_disclosed` (+ informational `http.robots_paths_disclosed`) | 30 d |
| `ndpa.s39.exposed_services_inventoried` | `ports.inventory` | none | 30 d |
| `ndpa.s39.known_vulnerability_testing` | none | `nuclei:*` | 30 d |
| `ndpa.s39.email_anti_spoofing` | `dns.spf`, `dns.dmarc` | `dns.spf.missing`, `dns.spf.softfail`, `dns.dmarc.missing`, `dns.dmarc.policy_none` | 30 d |
| `ndpa.s39.periodic_risk_assessment` | scan history | — | 90 d |
| `ndpa.s39.regular_testing` | scan history | — | 30 d |

**Not tool-backed in C1.** These are 22 requirements across Notices (2), Cookie consent (4), DPO (4), Registration/CAR (3), Breach (3), DPIA (1), Lawful basis/consent (2), Data subject rights (1), Cross-border transfer (1) and Training (1). They show `not_assessed` with "evidence collection not available yet", per D7. Their `evidence_types` name the future source (`externally_observed` for C2, `customer_attested` for C3).

The register's titles and summaries describe what evidence shows. None of them states a conclusion.

## 3. Migration `20261017090000_compliance_evidence.sql` (additive)

```sql
CREATE TABLE compliance_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  domain_id uuid REFERENCES domains(id) ON DELETE CASCADE,
  requirement_key text NOT NULL,
  register_version text NOT NULL,
  source text NOT NULL CHECK (source IN ('tool_observed','externally_observed','customer_attested','practitioner_reviewed')),
  status text NOT NULL CHECK (status IN ('present','gap','not_assessed','not_applicable')),
  observed_at timestamptz NOT NULL,
  expires_at timestamptz,
  scan_id uuid REFERENCES scans(id) ON DELETE SET NULL,
  finding_ids uuid[] NOT NULL DEFAULT '{}',
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by uuid REFERENCES profiles(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_compliance_evidence_latest ON compliance_evidence (org_id, requirement_key, domain_id, observed_at DESC);
CREATE UNIQUE INDEX uq_compliance_evidence_scan ON compliance_evidence (scan_id, requirement_key) WHERE scan_id IS NOT NULL;
-- RLS enabled, policy cyphward_app_all (same pattern as every app table).
-- Append-only: GRANT SELECT, INSERT only. No UPDATE or DELETE for cyphward_app.
```

Replay of the same finalisation inserts with `ON CONFLICT (scan_id, requirement_key) WHERE scan_id IS NOT NULL DO NOTHING`. No backfill: domains without a v2 assessment simply have no rows and read as `not_assessed`.

## 4. Mapping truth table

**Written for the scanned domain at finalisation** (other domains keep their latest rows). One row per tool-backed requirement (not the two scan-history ones), source `tool_observed`, `observed_at` = completion time, `expires_at` = `observed_at + freshness_days`.

Domain findings are open findings whose `assets.domain_id` is this domain, after this scan's reconciliation. Only mapped rules count; unmapped findings are ignored.

| # | Condition (checked in order) | Status | Recorded |
|---|---|---|---|
| 1 | An open finding whose rule is one of R's **issue** rules | `gap` | `finding_ids`, rule keys |
| 2 | Coverage absent, not version 2, or `requested_checks` is null (legacy/older worker) | `not_assessed` | reason `legacy_coverage` / `no_coverage` |
| 3 | R declares no checks (Nuclei) | `not_assessed` | reason `clean_result_not_provable` |
| 4 | Any requested group for R's checks is in `missing` | `not_assessed` | missing hosts and reasons |
| 5 | No requested group at all (every group omitted, e.g. `no_web_service`) | `not_assessed` | omission reasons (D6: never `not_applicable`) |
| 6 | Otherwise: every requested group evaluated, at least one evaluated | `present` | evaluated groups, informational findings |

Positive findings never affect status. A gap is written even with legacy coverage, because an open finding is a direct observation.

**Derived on read, per requirement, across the organization's current verified (not revoked) domains:**

| Condition | Status |
|---|---|
| No verified domain | `not_assessed` (`no_verified_domain`) |
| Domain has no row | `not_assessed` (`no_assessment`) for that domain |
| Latest row expired, status `present` | `not_assessed` (`evidence_expired`), last observation shown |
| Latest row expired, status `gap`, a linked finding still open | `gap` |
| Latest row expired, status `gap`, no linked finding open | `not_assessed` (`evidence_expired`) |
| A currently open mapped issue finding on the domain (live, whatever the row says) | `gap` for that domain |
| An open mapped issue finding with no domain link | requirement `gap` (reason `unlinked_finding`) |
| Any domain `gap` | requirement `gap` |
| Else any domain `not_assessed` | requirement `not_assessed` |
| All domains `present` | requirement `present` |

**Scan history** (`periodic_risk_assessment`, `regular_testing`): a requirement is `present` only if **every** verified domain has at least one completed scan whose stored `assessment_coverage.state` is `complete` within `freshness_days`. Otherwise it is `not_assessed`. It lists, per domain, the count and dates of complete scans in the window, and the latest partial or legacy scans as "not counted". It is never `gap`.

**Readiness** (D5, revised 16 Oct) is shown as counts, never a percentage: "N of 29 have evidence · M awaiting input or upcoming checks", where N = present + gap, plus separate present / gap / not assessed / awaiting counts. Requirements without an evidence source read `awaiting_input` (read-only, never stored), not `not_assessed`.

## 5. Tests

- `test_compliance_register.py`:
  - the register loads;
  - each validation failure is rejected (missing field, duplicate key, unknown group/`applies_to`/evidence type, unknown declared check, unknown rule key, a `clause_verified: true` without a reviewer note);
  - every `tool_mapping` check is in `DECLARED_CHECKS`, and every rule is in `RULES` or is `nuclei:*`.
- `test_compliance_mapping.py`, the pure truth table (each row of §4):
  - evaluated clean → present;
  - open issue → gap with ids;
  - informational only → present;
  - positive only → no effect;
  - missing check → not assessed with reason;
  - all omitted → not assessed, never not_applicable;
  - legacy v1 and no coverage → not assessed;
  - Nuclei never present, gap on match;
  - findings on another domain, resolved findings and unmapped findings are ignored;
  - aggregation: no rows, expired present, expired gap with/without an open finding, zero domains, mixed domains;
  - scan history: complete in window, one stale domain, partial scans don't count;
  - readiness % counts present only.
- `test_compliance_postgres.py` (real `cyphward_app`, independent connections; added to the CI Postgres job):
  - `finish_assessment` writes the rows in the same transaction as the snapshot;
  - a stale or expired claim writes no evidence and no snapshot;
  - replay doesn't duplicate;
  - the app role cannot UPDATE or DELETE `compliance_evidence`;
  - overview/requirement responses are tenant-isolated: org B never sees A's rows, and A's requirement key in B's context shows B's state;
  - a member can read, a non-member can't;
  - Starter sees locked groups (D1);
  - end to end, a synthetic complete scan → present; an open HSTS finding → gap linked to it; an apex DMARC-missing finding → `email_anti_spoofing` gap;
  - a forced mapping exception still completes the scan with its snapshot and zero evidence rows, and the audit records the error;
  - a finding reopened after the row was written (status back to `open`) turns a stored `present` into `gap` on read.
- `test_compliance_claims.py`, extended. The banned phrases are "compliant", "non-compliant", "certified", "satisfies", "satisfied", "passes audit", "compliance score", "fully meets". They are checked over:
  - the register file;
  - every string in the overview/requirement responses, across all statuses;
  - the frontend page source;
  - API field names.
  It also checks that the disclaimer is present in both responses and on the page.
- `test:compliance-ui` (stubbed API) at desktop, 390 and 320:
  - readiness % with counts;
  - status chips with source labels;
  - "reference pending review";
  - gap → findings link and "Create task" (admins only);
  - locked groups for Starter;
  - not-assessed text;
  - disclaimer visible;
  - no horizontal overflow.
- Full backend suite, Postgres modules, frontend build, existing UI suites, `git diff --check`.

## 6. API and page

- **Overview** returns:
  - `disclaimer`, plus `register: {version, clauses_pending_review: n}`;
  - `readiness: {with_evidence, present, gap, awaiting_input, not_assessed, applicable}`;
  - `groups[]`, each with counts, `locked`, and `requirements[]`. Each requirement has `key, title, clause, clause_verified, summary, status, source, reason, domains[], findings[], remediation_hint, freshness_days`.
- **Requirement** returns the same requirement plus `history[]`: the newest 50 rows, each with domain, status, source, observed/expires and scan id. A Starter locked group returns 403 with an upgrade message.
- **Page:**
  - header "Compliance readiness";
  - the readiness % stat with counts beside it;
  - the disclaimer banner, always visible;
  - groups as panels, with a row per requirement: the app's status dot chip ("Evidence present" / "Gap" / "Not assessed") plus a source tag ("TOOL OBSERVED"), the clause, and "reference pending review" when unverified;
  - an expandable row with per-domain detail and reasons in plain words, gap findings linking to `/findings`, and "Create task" calling the existing `POST /api/v1/remediation/tasks` with `finding_id`;
  - locked groups with an upgrade prompt.
  It uses the app's existing classes; no new design system.

## 7. Release

1. Apply the migration to production as `postgres` first. Verify the table, RLS, the append-only grants via the `cyphward_app` connection, and that existing row counts are unchanged.
2. Merge → Render API deploy (evidence starts being written at the next scan completion) and Vercel frontend.
3. Verify `/health`, that `GET /api/v1/compliance/overview` returns 401 without auth, and that the page loads.

No scanner deploy (scanner paths are unchanged). Rollback: revert the API/frontend; the table can stay (additive, unused).

## 8. Compatibility and limits

- Old scans and legacy coverage read as `not_assessed`; there is no backfill.
- Evidence appears only after a domain's next completed scan.
- Nuclei can show gaps only.
- The 22 non-tool requirements stay not assessed until C2/C3.
- No snapshot immutability yet (C4/Packet 04). The page reads live state.
