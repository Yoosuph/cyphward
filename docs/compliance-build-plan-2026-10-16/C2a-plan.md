# C2a plan — static privacy checks (no browser)

**Branch:** `codex/compliance-c2a`. One PR. **Worker change**: the release follows the runbook (section 8).
**Governing rule:** README section 0. Every privacy observation is `externally_observed` and heuristic where marked. The output is "found / mentioned / not found", never "adequate". Missing or unrun checks are never shown as present.
**Status:** plan for founder review. No code yet.

## 1. What C2a observes

On the scanned domain's **apex homepage plus up to 4 other in-scope web hosts** (those whose HTTP stage returned a usable response, apex and `www.` first), with one unauthenticated GET per page, no forms submitted and no JavaScript run:

| Signal | How | Stored |
|---|---|---|
| Privacy policy | `<a>` links whose text or href matches `privacy`, `privacy-policy`, `data-protection`, `privacy-notice`; then the fixed paths `/privacy`, `/privacy-policy`, `/privacy-notice`, `/data-protection` | URL, how it was found (link / fixed path), HTTP status, final URL. An off-domain link (for example a hosted policy service) is recorded as **linked off-domain, not fetched**. |
| Cookie notice | links matching `cookie`; fixed paths `/cookie-policy`, `/cookies` | as above |
| Policy content signals (heuristic) | case-insensitive phrase sets on the fetched policy text: lawful basis; data subject rights; DPO/contact (an email near "data protection officer"/"DPO"); NDPA/NDPR/GAID/Nigeria Data Protection | `mentioned` / `not_found` per signal plus the matched phrase. **Labelled heuristic; never "adequate".** |
| Cookies on first response | `Set-Cookie` on the homepage GET | Cookie **names and attributes only** (Secure, HttpOnly, SameSite, Domain, Max-Age). **Never values.** Each name is classified against a known tracker list (`_ga`, `_gid`, `_fbp`, `_hjSession*`, `_ttp`, `_clck`, …). |
| Tracker scripts in HTML | `<script src>` hosts and inline snippets against a known list: Google Analytics/GTM, Meta Pixel, Hotjar, TikTok, LinkedIn, Microsoft Clarity, Snap | the vendor, plus whether the tag is **blocked until consent** (`type="text/plain"` with a consent-manager attribute) |
| Consent manager | a known consent-manager script or attribute: Cookiebot, OneTrust/CookieLaw, Osano, Termly, iubenda, CookieYes, Usercentrics, Complianz, Quantcast Choice | the vendor |
| `security.txt` | `/.well-known/security.txt` | present / absent, and whether a `Contact:` line exists (stored for C4; no requirement in C1's register uses it) |

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
| `gaid.notice.privacy_policy` | A policy page returned 200 on an in-scope host, or is linked off-domain (recorded as such) | Homepage fetched fine **and** no link **and** every fixed path 404/410 (D8) | Stage not run / failed / old worker / homepage not usable | — |
| `gaid.notice.cookie_notice` | Same rule for the cookie notice | Same as above (D8) | Same | — |
| `gaid.consent.no_trackers_before_consent` | **Never in C2a.** Static fetching can't prove no tracker loads later; the browser test (C2b) may. | A known tracker cookie set on the first response, **or** a known tracker script not blocked for consent while no consent manager is present | Everything else, including trackers present behind a consent manager (reason: needs the browser test) | — |
| `gaid.dpo.contact_published` | A DPO contact is mentioned in a fetched policy | — | — | `awaiting_input` (the customer can attest in C3), with "not found in the published policy" in the detail |
| `gaid.consent.banner_visible`, `accept_and_reject`, `purpose_and_withdrawal` | — | — | — | Stay **Upcoming check** (C2b). The detail shows any consent manager detected. |
| Lawful basis, rights, DPO and others (attested) | — | — | — | Status unchanged (`awaiting_input`). The policy signals appear as **informational** "mentioned in your published policy (heuristic)". |

**Read side:** the same live rules as C1. Evidence expires after the requirement's `freshness_days`; an old worker or a missing stage reads not assessed with its reason.

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
- **Contract and compatibility:**
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

## 8. Release (worker change; runbook `02-release-runbook.md`)

1. **Prepare:** CI green; scanner image and API built from the same revision; no migration in this packet.
2. **Pause new claims:** set `SCANNER_CLAIMS_ENABLED=false` on Render and redeploy. Verify the worker gets 204 on claim. *(Production write: needs your OK at release.)*
3. **Drain:** wait until no scan is `running` (read-only check on your domains' scans; for other organisations' scans I'd ask first). Queued scans wait safely.
4. **Back up:** encrypted dump. Not strictly needed (no schema change), but cheap.
5. **Merge:** API deploys on Render; scanner CD rebuilds and restarts the VPS worker. Verify:
   - the API is live at the merge commit;
   - `/scanner/protocol` advertises `privacy_v1`;
   - the scanner CD job succeeded;
   - the container's revision matches;
   - the worker's negotiation succeeds while claims are paused (204, no errors).
6. **Resume claims:** set `SCANNER_CLAIMS_ENABLED=true` and redeploy.
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
