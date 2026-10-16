# C2a plan — static privacy checks (no browser)

**Branch:** `codex/compliance-c2a`. One PR. **Worker change**: the release follows the runbook (section 8).
**Governing rule:** README section 0. Every privacy observation is `externally_observed` and heuristic where marked. The output is "found / mentioned / not found", never "adequate". Missing or unrun checks are never shown as present.
**Status:** **approved by the founder on 16 October 2026**, with D8–D10 as proposed plus the three additions below. The release OKs are also given: pause claims, a count-only all-organisation queued/running query, resume claims.

**Founder additions (binding):**
1. **Policy change tracking:** store a SHA-256 of the **normalised** policy text (never the text itself) and flag "policy changed since last scan" when it differs from the previous privacy observation for that URL.
   - Normalisation: strip tags/scripts/styles, collapse whitespace, lowercase.
   - Shown as informational; it never changes a status.
2. **Cookies:** only **known-tracker** cookies can contribute to a gap. Necessary, infrastructure (for example `__cf_bm`, `__cfruid`, load-balancer cookies) and unknown cookies are listed, with their classification, and are **never** a gap. Tests include `__cf_bm` and typical session cookies (`sessionid`, `PHPSESSID`, `connect.sid`).
3. **Newest observation wins:** for each privacy requirement the latest row replaces older privacy evidence (present → gap or gap → present at the next scan). `expires_at` only marks staleness; it never revives an older status.

## 1. What C2a observes

On the scanned domain's **apex homepage plus up to 4 other in-scope web hosts** (those whose HTTP stage returned a usable response, apex and `www.` first), with one unauthenticated GET per page, no forms submitted and no JavaScript run:

| Signal | How | Stored |
|---|---|---|
| Privacy policy | `<a>` links whose text or href matches `privacy`, `privacy-policy`, `data-protection`, `privacy-notice`; then the fixed paths `/privacy`, `/privacy-policy`, `/privacy-notice`, `/data-protection` | URL, how it was found (link / fixed path), HTTP status, final URL. An off-domain link (for example a hosted policy service) is recorded as **linked off-domain, not fetched**. |
| Cookie notice | links matching `cookie`; fixed paths `/cookie-policy`, `/cookies` | as above |
| Policy content signals (heuristic) | case-insensitive phrase sets on the fetched policy text: lawful basis; data subject rights; DPO/contact (an email near "data protection officer"/"DPO"); NDPA/NDPR/GAID/Nigeria Data Protection | `mentioned` / `not_found` per signal plus the matched phrase. **Labelled heuristic; never "adequate".** |
| Cookies on first response | `Set-Cookie` on the homepage GET | Cookie **names and attributes only** (Secure, HttpOnly, SameSite, Domain, Max-Age). **Never values.** Each name is classified `tracker` (known list: `_ga`, `_gid`, `_fbp`, `_hjSession*`, `_ttp`, `_clck`, …), `infrastructure` (`__cf_bm`, `__cfruid`, `AWSALB*`, …), `necessary` (session/CSRF names) or `unknown`. **Only `tracker` can contribute to a gap.** |
| Policy fingerprint | the fetched policy page | SHA-256 of the normalised text (no text stored); "changed since last scan" when it differs for the same URL |
| Tracker scripts in HTML | `<script src>` hosts and inline snippets against a known list: Google Analytics/GTM, Meta Pixel, Hotjar, TikTok, LinkedIn, Microsoft Clarity, Snap | the vendor, plus whether the tag is **blocked until consent** (`type="text/plain"` with a consent-manager attribute) |
| Consent manager | a known consent-manager script or attribute: Cookiebot, OneTrust/CookieLaw, Osano, Termly, iubenda, CookieYes, Usercentrics, Complianz, Quantcast Choice | the vendor |
| `security.txt` | `/.well-known/security.txt` | present / absent, and whether a `Contact:` line exists (stored for C4; no requirement in C1's register uses it) |

**Catch-all sites (single-page apps on Vercel, Netlify and similar):**
- Before trusting fixed paths, each host gets one request for a random path that cannot exist (`/cyphward-<random>`).
- If that returns 200, or the same title and body hash as the homepage, the host is **catch-all**. On a catch-all host a fixed-path 200 proves nothing.
- On any host, a fetched page only counts as a policy or notice when its title or first heading names privacy/data protection (or cookies) **and** its body differs from the homepage.

**Tracker strength:**
- A tag-manager loader on its own (GTM, Google Consent Mode) is recorded but does not prove anything loads before consent.
- Only a **direct** tracker script, or a tracker **cookie** on the first response, can support a gap (section 4).

**Limits** (job limits, configurable):
- 5 hosts;
- 6 fetches per host;
- 512 KB per body;
- 4 s per request;
- one request at a time per host, 2 hosts in parallel;
- the whole stage stays inside the existing stage/recon budget (`ReconBudget`).

**Safety:** the fetcher reuses `http_probe`'s rules:
- in-scope redirects only;
- every hop re-resolved and pinned to a public IP through `ip_guard` (DNS-rebinding safe);
- an off-scope redirect stops there and is recorded;
- unverified domains never run (claims already require verified).

## 2. Contract and capability flag (old workers keep working)

- `shared/contracts.py`:
  - add `STAGE_PRIVACY = "privacy"` to `RECON_STAGES`, after `http`;
  - add `privacy_max_hosts` / `privacy_max_pages` to `ScanJobLimits`, with defaults;
  - add `PRIVACY_CAPABILITY = "privacy_v1"`.
- `GET /scanner/protocol` returns `"capabilities": ["privacy_v1"]`. A new worker runs the privacy stage **only if** the API it talks to advertises the capability. Against an old API (which would 422 an unknown stage), it skips the stage. So **either deploy order is safe**.
- The worker sends `X-Scanner-Capabilities: privacy_v1` on claim. At claim time the API writes `stage_progress.privacy`:
  - `pending` when the worker advertised the capability;
  - otherwise `skipped` with reason `worker_without_privacy_capability`.
- An old worker never reports the stage, so evidence and UI read "not assessed: worker update pending". It is never present.
- Local mode (`_execute_recon_local_owned`) runs the same stage function.
- **The stage is optional**, like ports/TLS/Nuclei: a crash or timeout records failed hosts, reports the stage `failed`, and the scan continues and completes.
- **Checked against the deployed worker (`c043223`)**:
  - its `ScanJob`/`ScanJobLimits` ignore unknown fields, so the new limit fields can't break its claims (verified by validating the new payload against that revision's contract);
  - the Packet 02 stage-order guard only moves forward and never reopens a finished stage, so `skipped` privacy is never regressed and an old worker's http → ports jump is accepted.

## 3. Observation contract `privacy_observations` v1

The `scan_results` stage `privacy` uses the existing attempt identity (`attempt_generation`) and the same fenced writes as every recon stage. There is **no migration**.

```json
{"privacy_observations": {"version": 1, "heuristic": true,
   "hosts": {"<host>": {"homepage": {"url", "status", "final_url"},
                        "pages": [{"kind": "privacy_policy|cookie_notice|security_txt", "url", "found_by", "status", "off_domain": false}],
                        "policy_signals": {"lawful_basis": {"state": "mentioned|not_found", "phrase"}, ...},
                        "first_response_cookies": [{"name", "secure", "httponly", "samesite", "tracker": "google_analytics|null"}],
                        "trackers": [{"vendor", "source": "script_src|inline", "consent_blocked": false}],
                        "consent_manager": "cookiebot|null"}}},
 "attempted_hosts": [], "successful_hosts": [], "failed_hosts": {}, "omitted_hosts": {}}
```

**Privacy is not a declared check.** `cyphward-checks-v1` and assessment coverage (and therefore grades) are unchanged. Privacy keeps its own summary.

## 4. Mapping to the register (Core, at finalisation)

Rows go in the same savepoint-protected insert as C1, with source `externally_observed`, for the scanned domain only. The register gains a `privacy` mapping type, and its version goes to `ndpa-gaid-v1.1` (requirement text unchanged).

| Requirement | Present | Gap | Not assessed | Otherwise |
|---|---|---|---|---|
| `gaid.notice.privacy_policy` | A page that **passes the content test** (title/heading names privacy; body differs from the homepage), reached by a link or fixed path on an in-scope host; or a link to an off-domain policy (recorded "linked off-domain, not fetched") | Host is **not catch-all**, homepage fetched fine, no matching link, **and** every fixed path returned a real 404/410 (D8). The reason names exactly what was checked. | Stage not run / failed / old worker / homepage unusable / **catch-all host with no linked policy** (reason: "site serves every path") | — |
| `gaid.notice.cookie_notice` | Same rule for the cookie notice | Same (D8) | Same | — |
| `gaid.consent.no_trackers_before_consent` | **Never in C2a.** Static fetching can't prove that no tracker loads later; the browser test (C2b) may. | A **direct** known tracker script not blocked for consent while **no** consent manager is present, **or** a known tracker cookie set on the first response. The reason names the vendor and how it was seen. | Everything else: tag-manager loaders only, trackers behind a consent manager, nothing found (reason: "needs the browser test") | — |
| `gaid.dpo.contact_published` | A DPO contact is mentioned in a fetched policy (a present row exists) | — | — | `awaiting_input` **only when there is no present row**; the detail says "not found in the published policy" |
| `gaid.consent.banner_visible`, `accept_and_reject`, `purpose_and_withdrawal` | — | — | — | Stay **Upcoming check** (C2b). The detail shows any consent manager detected. |
| Lawful basis, rights, DPO and others (attested) | — | — | — | Status unchanged (`awaiting_input`). The policy signals appear as **informational** "mentioned in your published policy (heuristic)". |

**Read side — a separate path for `externally_observed` rows.** C1's tool path turns a stored gap without open findings into "not assessed (findings resolved)", which would hide every privacy gap, because privacy gaps have no findings. So:
- **gap:** stands until the row expires, then reads `not_assessed` (`evidence_expired`);
- **present:** stands until the row expires, then reads `not_assessed` (`evidence_expired`);
- **no row:** `not_assessed`, with the stage reason (old worker / failed / not yet scanned). For requirements that a customer can also attest, it reads `awaiting_input`.

The register validator gains rules for the `privacy` mapping type: it must name a known signal, requires `externally_observed`, and is allowed alongside `customer_attested`. The truth-table tests cover each case, including "DPO present row is not overridden by awaiting input".

## 5. Files

| Area | Files |
|---|---|
| Worker/shared | `shared/contracts.py`; `backend/app/scanner/privacy_probe.py` (new: fetcher + parsers, pure parsing split from I/O); `backend/app/scanner/http_probe.py` (extract the in-scope pinned fetch for reuse, no behaviour change); `backend/app/scanner/recon_policy.py` (privacy stage plan); `scanner/runner.py` (stage after http, behind the capability); `scanner/client.py` (read capabilities, send header) |
| API/Core | `backend/app/api/scanner_jobs.py` (advertise; record the capability at claim); `backend/app/core/scan_execution.py` (claim writes the stage state); `backend/app/workflows/inngest_workflow.py` (local mode; pass the privacy observation to evidence); `backend/app/compliance/{mapping,scan_evidence,register}.py` + register JSON |
| Frontend | `pages/Scans.tsx` (new "Privacy" stage card: pages found, cookies by name, trackers, consent manager, "heuristic" label, "worker update pending"); `pages/Compliance.tsx` ("Externally observed" source label) |
| Docs | this plan; `PROGRESS.md` (**C1 release record** + C2a); `02-release-runbook.md` (C2a steps + backup retention/encryption note) |

## 6. Tests (no live sites; fixtures only)

- **Parser unit tests** on static HTML fixtures:
  - no policy;
  - policy linked in footer;
  - policy only at `/privacy`;
  - off-domain hosted policy;
  - cookie notice;
  - tracker before consent (GA script + `_ga` cookie);
  - tracker blocked by a consent manager;
  - inline Meta Pixel;
  - consent manager present;
  - `security.txt` with/without Contact;
  - policy text signals (each mentioned / not found);
  - cookie values never stored.
- **Fetcher tests** through an injected `httpx.MockTransport`:
  - in-scope redirect followed;
  - off-scope redirect stopped and recorded;
  - private IP refused (real `ip_guard`);
  - DNS answer changing between hops;
  - body cap;
  - page cap;
  - timeout → host failed, not "not found".
- **Catch-all fixtures:** catch-all with no policy → not assessed; catch-all with a footer-linked policy → present; a 200 page whose title isn't a policy → not counted.
- **Optional stage:** a privacy crash or timeout → the scan completes, with coverage, grade and score unchanged.
- **Contract and compatibility:**
  - the new claim payload validates against the deployed worker's contract (`c043223`);
  - new worker + old API (no capability) → stage skipped, no 422;
  - old worker + new API → claim marks `skipped`, finalisation succeeds, requirements not assessed;
  - unknown capabilities are ignored.
- **Mapping truth table** for every row in section 4, plus D8.
- **PostgreSQL** (real role, fenced):
  - privacy observation stored under the current attempt; a stale attempt can't write it;
  - evidence rows `externally_observed` written in the completion savepoint;
  - coverage, grade and score unchanged when privacy data is added.
- **Banned phrases** extended to the new copy; the scans and compliance browser suites at desktop/390/320.
- Full backend suite on a fresh bootstrap; `git diff --check`.

## 7. Decisions for the founder

| # | Question | Proposed default |
|---|---|---|
| D8 | When the static check finds no privacy policy or cookie notice, is that a **gap** or **not assessed**? | **Gap**, but only when the homepage was fetched successfully, no matching link exists and every fixed path returned 404/410. The copy says "not found by Cyphward's static check; pages built by JavaScript may not be seen". Any fetch failure → not assessed. |
| D9 | Hosts checked | Apex + up to 4 in-scope web hosts with a usable response. |
| D10 | Store the policy text? | **No.** Store URLs, statuses and matched phrases only; the text stays on the customer's site. |

**Release approvals I will ask for at release time** (beyond your standing read permission):
1. the Render env change pausing claims;
2. the all-organisation count of queued/running scans (count only);
3. the Render env change resuming claims.
The merge itself needs your "merge".

## 8. Release (worker change; runbook `02-release-runbook.md`)

1. **Prepare:** CI green; scanner image and API built from the same revision; no migration in this packet.
2. **Pause new claims:** set `SCANNER_CLAIMS_ENABLED=false` on Render and redeploy. Verify the worker gets 204 on claim. **OK needed (Render write).**
3. **Drain:** the worker is shared, so the check is a **count of queued/running scans across all organisations, with no other fields**. **OK needed** (it goes beyond your domains). Wait until running = 0; queued scans wait safely.
4. **Back up:** encrypted dump. Not strictly needed (no schema change), but cheap.
5. **Merge:** API deploys on Render; scanner CD rebuilds and restarts the VPS worker. Verify:
   - the API is live at the merge commit;
   - `/scanner/protocol` advertises `privacy_v1`;
   - the scanner CD job succeeded;
   - the container's revision matches;
   - the worker's negotiation succeeds while claims are paused (204, no errors).
6. **Resume claims:** set `SCANNER_CLAIMS_ENABLED=true` and redeploy. **OK needed (Render write).**
7. **Controlled scan:** one scan of `cyphward.com`. Verify:
   - a privacy observation is stored under the current attempt;
   - coverage, grade and score behave as before;
   - privacy evidence rows exist with `externally_observed`;
   - the scan page shows the Privacy card.
8. **Rollback:** revert the worker first (the API tolerates both), then the API. Observations are additive JSON; nothing to undo in the schema.

**Order safety:** a new worker only runs privacy when the API advertises it, and the API tolerates workers without it. A mis-ordered deploy therefore degrades to "privacy not assessed", never to failed scans.

## 9. Out of scope (C2b and later)

- Running JavaScript, banner visibility, clicking accept/reject, cookies after interaction (C2b, after measuring memory).
- Customer attestations (C3).
- Judging policy quality.

## 10. Implementation notes (deviations from the plan text, recorded at build)

- **Fetch budget 10 per host** (plan: 6). D8 needs the homepage, the catch-all probe and all 6 fixed paths; with 6 a gap could never be proven. Running out of budget reads "not assessed", never "not found".
- **Stage results without an observation:**
  - a scan whose privacy stage did not run (older worker) writes **no** privacy rows, so the newest real observation stands;
  - a stage that ran but could fetch no host writes `not_assessed` (`privacy_check_failed`), so an old "present" is not kept alive by a failed check.
- **Policy mentions** of lawful basis and data subject rights appear on those attested requirements as informational notes ("your published policy mentions this", heuristic). They never change status.
- **Catch-all hosts** still try the fixed paths, because a prerendered `/privacy` page passes the content test (title names privacy, body differs from the shell).

