# Cyphward: focused offer and paid-pilot operating pack

Prepared 21 October 2026 against `origin/main` `9795bd5`. This package accompanies the commercial-copy, remediation-safety and manual-billing changes. Implementation and local checks do not establish deployment, legal validation, customer demand or collected revenue.

## The offer

**Cyphward helps Nigerian software teams find external security weaknesses, verify supported fixes, and prepare evidence for customer security and data-protection reviews.**

Start with founders/technical leads at Nigerian B2B software businesses facing an actual customer review, procurement request or contract deadline. Ask to see the request with permission and agree which parts Cyphward can support. A general interest in security is insufficient qualification. A customer needing a specialist penetration test or formal audit may need a partner and a different scope.

Lead with the workflow: **verified domain → scoped assessment → explained findings → assigned work → supported recheck → dated evidence**. Explain Growth's Nigerian evidence workflows after establishing this need. Country positioning does not imply a special network-scanning capability or regulatory approval.

## What changed in this implementation

- Homepage: specific buyer and outcome, five workflow steps, Growth Compliance capabilities and source/evidence limitations. Retired the assumed-turnover fine calculator and “African networks”/“six defence layers” claims.
- Pricing: existing ₦15,000 Starter / ₦25,000 Growth amounts, explicit 30-day paid periods, actual 30/300 calendar-month scan allowances, shared scheduled/manual usage, domain/member/report limits, trial and manual payment conditions.
- Remediation: staged DMARC/SPF deployment and reporting prerequisites; HSTS subdomain/preload cautions; CSP report-only/staging; legitimate embed checks before clickjacking restrictions. Detector identities/severity weights/history remain unchanged. This is not a validation of every detector or finding priority.
- AI guidance: recognized email/transport/browser-policy configuration findings use curated guides even when a cloud model is configured. Sensitive chat topics and recent configuration follow-ups use the conservative path in both streaming and non-streaming calls. No invented organization-derived mailbox, assumed missing DMARC/HSTS, fabricated board-report strength or 15-minute enforcement estimate. This is a bounded routing policy, not proof that every possible model response is correct.
- Findings UI: guide prerequisites are visible; failed explanation/guide requests show an error, without synthetic advice or a previous finding's guide. The setup selector now works when a guide is opened directly from the list.
- Register `ndpa-gaid-v1.2` / questionnaire `ndpa-gaid-questionnaire-v1.1`: safer email-authentication guidance and the matching register reference. Requirement keys, legal references, applicability and all 29 false verification flags are preserved. Stored snapshots and issued pack bytes are not rebuilt.
- Customer billing: selecting a plan, renewing, or editing `organization.plan` cannot create paid access or restart a trial. New organizations retain their original 30-day trial. Expired/canceled subscriptions have zero new scan/report/domain/member allowance; existing workspace reads and privacy exports retain their existing permissions.
- Manual settlement: [operator runbook](MANUAL-PAYMENT-RUNBOOK.md) and a dry-run-first reconciliation script. Only independently confirmed receipts create an active standard paid period. No payment processor or automatic charging is enabled.
- Professional review: a [29-row checklist](professional-review-register.csv) for a qualified reviewer. All current verification flags remain false; no professional approval has been invented.

Legacy organizations without subscription rows retain their existing compatibility behavior. Existing active manual periods are not retroactively described as verified payments or revoked. Audit them privately before treating them as paid customers. This patch closes new self-service activation paths; it is not a financial audit of earlier records.

## The five-customer pilot

**Target:** five paying organizations from the same initial segment. Payment, supported customer outcome and renewal are separate facts. Do not fill the scorecard with invented prospects or demo data.

Suggested initial written offer, confirmed individually before collection:

> **30-day Growth pilot — ₦25,000.** We will help your team assess one primary domain you own, understand the findings, coordinate a selected fix where needed, recheck it where supported, and prepare a dated evidence pack for one agreed customer review. Your standard Growth limits apply (up to 10 domains, 25 members, 300 accepted scan jobs and 300 report/evidence units per UTC calendar month). We focus the pilot outcome on the agreed primary domain; other domains still use the same shared allowance. The pilot includes one onboarding session of up to 30 minutes and one handover of up to 15 minutes. Additional hands-on engineering, legal review, audit filing and ongoing managed remediation require a separate quote. No automatic renewal. We ask whether you want to continue when the paid period ends.

This limited assisted pilot is a proposed commercial agreement, not an automatic benefit added to every self-service account. Use the public 30-day no-card trial when a prospect wants evaluation first; it creates no obligation and does not count as paid demand. An operator may start the agreed paid pilot immediately after confirming payment, ending the unused trial; explain the new paid start/end before recording it.

Before taking payment, record buyer, review deadline, domain/authorized scope, plan, exact paid dates, included assistance, relevant deliverables, exclusions and refund/cancellation terms. Use the current Terms and get advice on tax/invoicing obligations; this document is not an accounting or legal opinion. Do not promise a clean score, a particular number of findings, audit acceptance, certification or prevented breaches.

## Observe each pilot

1. Record how the customer handled the same review previously and the time spent. Save only permitted, minimized information; a prospect's questionnaire may contain confidential material.
2. Observe email verification, workspace creation, domain verification and first useful assessment. Measure elapsed time, waiting time and actual staff minutes separately.
3. Select one meaningful next action with the customer. If a scoped assessment finds no actionable issue, record that supported result; do not manufacture a remediation task.
4. Let the customer's engineer make production changes. Provide provider-specific guidance, staging/rollback prerequisites and a supported recheck. Separate manual closure, risk acceptance, inconclusive recheck and evidence-supported resolution.
5. Build the evidence record and ask the actual reviewer what is useful or missing. A source-labelled PDF is useful only if its claims and scope can withstand review.
6. Ask for renewal before the agreed period ends and record money actually received and the customer's reason. Customers whose period has not ended are pending, not failed renewals.

Use [pilot-scorecard.csv](pilot-scorecard.csv) as the schema for a **private** operating sheet. It is intentionally empty. Never commit real contact details, bank references, customer evidence or review questionnaires to Git. Retain only necessary records under the applicable policy.

Prepared [outreach and interview drafts](OUTREACH-DRAFTS.md) can support founder-led recruitment and professional review. They have no recipients and have not been sent.

## Professional validation assignment

Give a qualified Nigerian adviser/licensed DPCO the current register, questionnaire, one synthetic pack, one draft of each document type, applicability rules and the 29-row CSV. Request:

- Exact primary-source references and current clause text, with amendments/date checked.
- Applicability, exemptions and the effect of a customer's own answers; no sector/country-only determination.
- What each evidence item can support, what it cannot establish, and whether the copy is misleading.
- Review of incident timing/notifications, evidence freshness, generated drafts and terminology.
- A written correction/approval record naming the reviewer and scope. Customer-specific reviewer notes are separate from validation of the platform register.

Apply corrections in a versioned register release. A `clause_verified` flag changes only with attributable review; do not bulk-switch flags as an implementation shortcut. Preserve frozen historical snapshots/packs and make their original version visible.

The [NDPC FAQ](https://ndpc.gov.ng/faqs/) describes filing Compliance Audit Returns through licensed DPCOs. Cyphward's evidence packs are supporting preparation, not a replacement filing or professional verification statement. The Commission's [licensed-DPCO directory](https://ndpc.gov.ng/licensed-dpcos/) is a starting point for identifying a reviewer; inclusion does not itself establish a commercial agreement with Cyphward.

## Thirty-day operating sequence

| Window | Work | Evidence |
| --- | --- | --- |
| Days 1–5 | Release tested copy/safety/billing changes; arrange professional review; agree the one-segment offer. | Actual deployment receipts, review scope, corrected drafts and a usable demonstration. |
| Days 3–12 | Founder-led conversations and five qualified pilot offers. Outreach requires a real prospect list and an authorized sender; no messages are sent by this implementation. | Actual review need/deadline and signed scope; collected money recorded separately from offers. |
| Days 7–24 | Observe onboarding and first outcome; cap assistance and record exceptions. | Assessment provenance, supported fixes or clean scoped outcomes, customer feedback and time/cost entries. |
| Days 21–30 and each paid period's end | Ask about continuation; compare useful outcomes and delivery effort. | Collected renewals/refusals and reasons. Later-starting cohorts remain pending. |

Founder owns qualification, offers, collection and renewal conversations. Engineering owns safe outputs, clear product limits and incident handling. A named qualified reviewer owns professional validation. No dashboard can substitute for those responsibilities.

## The learning gate

Proposed early target: at least **three of five eligible pilots** pay to continue and identify an outcome they value, with delivery effort that fits the price. Report the tiny sample honestly; this is not proof of product-market fit.

For each paid period, record scanner/AI/storage/delivery usage, actual cash costs and staff minutes valued at an explicit internal rate. Report cloud credits separately from underlying consumption. Keep NGN and foreign-currency costs separate unless a dated conversion source is recorded. Compare the period's revenue and attributable delivery costs; collections/prepayments and recognized revenue are different measures.

If customers only renew when the founder performs extensive engineering, price that service separately and test a repeatable delivery process. If they repeatedly need a missing integration or evidence workflow, prioritize that specific gap. Broader admin features and Academy wait for that evidence; browser-worker security work already in review remains a separate technical release.

## Sources for the safety changes

- [Google: recommended DMARC rollout](https://support.google.com/a/answer/10032473).
- [Google: set up SPF](https://support.google.com/a/answer/33786).
- [MDN: HSTS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Strict-Transport-Security).
- [MDN: CSP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP).

The guidance reduces unsafe one-line instructions. It does not certify production changes, validate the customer's mail streams, or retrospectively rewrite issued reports.
