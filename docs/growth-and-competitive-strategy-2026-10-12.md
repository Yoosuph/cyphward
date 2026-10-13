# Cyphward: growth and competitive strategy

**Founder execution document · 12 October 2026 · Version 1.0**

**Objective:** Build a durable cybersecurity business that wins a defined customer segment, delivers measurable improvements, and can expand with sustainable economics.

**Recommended direction:** Help Nigerian B2B software companies resolve externally visible security weaknesses and prepare credible evidence for customer security reviews. Validate that buyer and buying event before expanding into a broad compliance and training platform.

This is a proposed operating plan, not a revenue forecast or proof of competitive superiority. Commercial targets below are internal decision rules to test. Revenue, customer counts, retention, delivery costs, team capacity and available cash have not been supplied. Roadmap periods start when execution begins; progression depends on evidence. Payment-system activation remains deferred.

## 1. The decisions to make now

1. **Choose one initial buyer:** a founder or CTO at a Nigerian B2B software company with a real customer security request, renewal review or procurement deadline.
2. **Sell a bounded outcome:** assessed external exposures, an agreed remediation plan, verified fixes where supported, and an evidence package for one defined review.
3. **Recruit 3–5 paid pilot customers:** use the same scope and record delivery effort. Manual invoicing can support validation; establish collection and reconciliation procedures explicitly.
4. **Finish the existing customer workflow:** improve activation, remediation follow-through and trustworthy reports before expanding the product catalogue.
5. **Review pricing against actual costs:** current public prices are ₦7,000/month for Starter and ₦15,000/month for Growth. These prices are not evidence that substantial advisory work can be included profitably.
6. **Expand through demand:** build the first compliance workflow from repeated customer requirements; introduce Academy when customers will pay for assigned learning and training evidence.
7. **Use renewals and delivery economics to decide whether to scale:** registrations, scan volume and a larger interface do not establish a repeatable business.

The proposed customer promise is: **“Cyphward helps your team find important external security weaknesses, fix them, and show customers what you have addressed.”** Broader assurances require broader evidence and capabilities.

## 2. What already exists, and what still needs proving

The plan builds on the current product. It does not treat historical review findings as if every original defect remains unresolved.

| Area | Evidence available | Business work remaining |
| --- | --- | --- |
| External scanning | Verified-domain scanning, VPS worker, findings and scoring exist. Focused TLS and scanner memory corrections are documented. | Establish repeatable delivery within declared scope, measurable coverage and dependable turnaround under customer load. |
| Remediation | Tasks, assignee and due-date fields, workflow status and detector-aware rechecks already exist. | Make ownership, deadlines and follow-up easy to use; measure verified resolution and customer effort. |
| Reports | Executive reports exist; current report generation uses live findings and the latest assessment. | Produce consistent, versioned evidence packages with dates, scope, limitations and a traceable relationship to the assessment. |
| Onboarding and interface | Dashboard access can precede domain verification; scans require ownership verification. Scan desktop/mobile UX and scrollable history were improved. | Measure successful activation and make the first useful action obvious. |
| Administration | A small staff console already exists at `/platform`. | Extend support and operational visibility when it reduces recovery time or delivery cost. |
| Plans and adjacent modules | Plans and entitlement foundations exist. Compliance evidence workflows and assigned Academy learning remain proposed work. | Validate offers and economics; build real customer workflows before their administration screens. |

Source basis: [implementation status](implementation-status-2026-10-11.md), [scanner readiness review](scanner-feature-review-2026-10-11/README.md), [controlled scan follow-up](scanner-feature-review-2026-10-11/controlled-scan-validation-2026-10-12.md), and [scan UX implementation](scans-ui-review-2026-10-12/README.md). Current remediation fields are in [the remediation API](../backend/app/api/remediation.py); report behavior is in [the reports API](../backend/app/api/reports.py). Published pricing is in [the plan catalogue](../frontend/src/lib/publicPlans.ts) and [pricing page](../frontend/src/pages/Pricing.tsx).

The older October 3 review contains superseded prices and resolved findings. Use these more recent records and current source for decisions. This document does not constitute a new production security or capacity audit.

## 3. Define the first customer tightly

Start with Nigerian B2B software businesses that maintain internet-facing services and sell to larger organisations. The economic buyer is likely the founder or CTO; the engineering lead does the remediation. A compliance practitioner may influence the purchase.

Qualify each prospect against five questions:

- Is there an actual security questionnaire, customer review or renewal date within the next 90 days?
- Does the company control the relevant systems and have someone who can implement fixes?
- Can a named person approve the purchase?
- Do the requested deliverables fall within Cyphward's declared capabilities?
- Will monitoring, future reviews or evidence maintenance create a reason to continue paying?

Do not count general enthusiasm as qualified demand. Ask to inspect a redacted or permissioned review request. If the decisive requirement is a certification, internal assessment or specialist penetration test outside the offer, record that gap and determine whether a qualified partner can serve it.

**First 15–20 buyer conversations:** ask what happened in their last review, how long preparation took, what delayed it, what they paid, what tools or advisers they used, and who controlled the budget. Finish with a concrete scoped proposal. Record purchase decisions and objections alongside interview notes.

Nigeria is the initial market hypothesis. Earlier ideas about fintechs, healthtechs and agencies remain possible segments; test them separately if the first segment fails. Mixing them into one pilot cohort makes it harder to understand which problem and delivery process repeat.

## 4. How to compete against existing solutions

The following capabilities are described on vendors' own pages checked on 12 October 2026. They are advertised capabilities, not independent performance measurements. Feature availability, packages and pricing must be confirmed during an actual buying comparison. Absence from this table does not mean a competitor lacks a feature.

| Alternative | What its own material already offers | Cyphward's proposed way to earn a preference |
| --- | --- | --- |
| Intruder | Continuous vulnerability scanning, prioritisation, remediation guidance and workflow/compliance integrations. [Product source](https://www.intruder.io/platform/vulnerability-management) | Test whether a tightly scoped local delivery programme gets the chosen buyer to verified fixes with less total effort and sustainable cost. Scanning plus AI advice alone is not a distinctive position. |
| Detectify | External asset discovery and monitoring, with deeper application scanning including authenticated testing. [Product documentation](https://support.detectify.com/support/solutions/articles/48001061283-what-can-i-scan-using-detectify-) | Compete on the selected customer's workflow and outcome. Do not claim equivalent application testing depth without building and evaluating it. |
| Vanta | Security questionnaire automation, collaboration and approvals; a separate Trust Center product supports sharing security information. [Questionnaire product](https://www.vanta.com/products/questionnaire-automation), [Trust Center](https://www.vanta.com/products/trust-center) | Prove that a bounded evidence workflow fits the selected customer well. Offer useful exports or integrations where customers already use a larger platform. Questionnaire automation is already a competitive category. |
| Estreat | Nigeria-focused NDPA records, evidence and audit preparation, positioned around NDPA 2023 and GAID 2025. [Product source](https://estreat.ng/) | Test the value of linking actual external observations and verified fixes to evidence. Nigerian positioning and compliance checklists alone do not establish differentiation. |
| KnowBe4 | Security awareness content, simulations, automated training and reporting. [Product source](https://www.knowbe4.com/products/security-awareness-training) | Pilot a small employer-paid learning workflow tied to customers' documented needs. Measure usefulness and consider licensing content before building a large library. |
| The buyer's current process | May include spreadsheets, developer time, advisers and tools already purchased; determine the actual combination through interviews. | Measure total effort, delays and delivery cost against that real baseline. Make adoption easy and preserve exportability. |

**Define “beat” as a measured buying preference in the chosen segment.** For the first five comparable pilots, aim for at least three buyers to choose paid continuation and identify a specific advantage they experienced. Also aim to reduce median review-preparation effort by 30% against documented comparable work, without worse evidence quality. These are proposed learning targets with a tiny sample, not proof of market leadership.

Run three comparisons with customer permission:

1. **Resolution:** same authorised scope, agreed meaningful findings, time to triage and verified fix, disputed findings and staff hours. Raw finding counts are not a quality ranking.
2. **Evidence preparation:** comparable review requirements, preparation hours, unsupported answers, missing evidence and reviewer rework. Separate customer assertions from observed or independently reviewed facts.
3. **Commercial choice:** same deliverables, scope, support allowance and evaluation period; compare customer effort and total cost. Record which alternative won and why, including a decision to do nothing.

Only publish superiority claims after a fair, reproducible comparison with appropriate customer permission. Where another product meets a requirement better, an integration or qualified referral may preserve the customer relationship.

## 5. The first offer to sell

**Offer hypothesis: a 30-day external security improvement and review-preparation engagement.**

Specify the covered domains and asset limits, scan scope, customer contact, response hours, meeting allowance, number of rechecks and one defined customer review. Establish the baseline before delivery.

| Stage | Deliverable | Customer responsibility |
| --- | --- | --- |
| Start | Written scope, verified ownership, buying deadline and agreed success measures | Provide authorised access, the review request and a person responsible for fixes |
| Assess | Triaged results, coverage limitations and a short prioritised action plan | Confirm business context and agree which issues to address |
| Improve | Existing task workflow, guidance and supported verification evidence | Make or commission changes and record accepted risks |
| Demonstrate | Dated evidence index and management report for the agreed review | Review assertions and decide what to share with the requesting organisation |
| Continue | A priced monitoring/evidence-maintenance proposal based on actual recurring needs | Decide whether to continue, expand or stop |

A useful result can include a supported finding of no actionable issues within assessed scope. Never manufacture problems to justify the service. The engagement does not promise certification, breach prevention or acceptance by a customer's procurement team.

Keep software subscription, onboarding and optional advisory services separately identifiable in proposals and records. Cap advisory hours and charge explicitly for extra work. Implement a basic invoice, receipt, collection and reconciliation process while payment integration remains deferred.

## 6. Product work in commercial priority order

“Owner” denotes a responsibility; one person may initially hold several roles. These are proposed tasks, not features implemented by this document.

| Priority | Extend or build | Definition of done | Owner |
| --- | --- | --- | --- |
| P0 | Delivery reliability and coverage | Promised checks have recorded outcomes; failures cannot certify a fix; agreed pilot scope completes without repeated founder rescue. Validate recent fixes end to end. | Engineering + security |
| P0 | Activation measurement | Record verification, first usable result, review of findings and first agreed action. Track elapsed time and abandonment reasons. | Product |
| P0 | Remediation follow-through | Surface existing assignee/due-date support, overdue work and verification history; customers can identify the next action and its owner. | Product + engineering |
| P0 | Assessment evidence package | One versioned package states scope, assessment time, coverage, evidence source, findings and limitations; later changes do not silently rewrite it. | Engineering + security |
| P0 | Pilot and cost scorecard | Every pilot has a baseline, collected revenue, time log, outcome and renewal decision. | Founder + operations |
| P1 | Meaningful changes and follow-up | Notify appropriate users about new important exposures and overdue agreed work; measure action and notification usefulness. | Product |
| P1 | Narrow compliance workspace | One validated requirements set with evidence owners, source/date, review state, expiry and qualified review. | Compliance practitioner + product |
| P1 | One requested integration | Implement the ticketing or collaboration integration repeatedly requested by paying customers; measure reduced duplicate work. | Engineering |
| P1 | Support operations | Extend existing `/platform` with worker/queue health, failed-delivery visibility and audited support actions. Measure recovery time. | Engineering + operations |
| P2 | Academy pilot | Employer assignment, short lessons, assessment and versioned completion evidence work for a paying cohort. | Learning lead + product |
| P2 | Partner workflow | A proven partner can serve explicitly authorised client workspaces with clear permissions, commercial terms and attribution. | Partnerships + engineering |
| P2 | Broader administration | Add controls only for workflows that customers or staff actually use and need to manage. | Operations + product |

P0 work and buyer discovery run together. Progress does not require finishing every P1 item. Start a P1 module when at least three independent paying or committed pilot customers demonstrate substantially the same need, or a critical delivery requirement otherwise justifies it. Security and integrity corrections do not wait for a popularity threshold.

## 7. Compliance and Academy should strengthen one business

**Compliance first scope:** select one repeated customer review or Nigeria-specific evidence workflow. Include requirement references and applicability, responsible owner, evidence attachment or link, review date, expiry, exceptions and export. Record whether each item is observed by a tool, supplied by the customer, or reviewed by a qualified person. AI drafts require human approval and attributable sources.

External scanning supports only part of a security/privacy programme. Policies, processing records, staff responsibilities and training require other evidence. The NDPC describes this broader accountability context and maintains information about licensed DPCOs. Use a qualified practitioner to review the specific content and service boundaries. [NDPC annual report](https://ndpc.gov.ng/wp-content/uploads/2026/02/Print_NDPC-Annual-Report-2025-1.pdf), [NDPC services](https://www.ndpc.gov.ng/).

**Academy entry gate:** customers repeatedly need training evidence or cannot complete required actions because of a demonstrable skill gap. Pilot three short modules chosen from those needs, such as phishing/reporting, handling customer data, and the organisation's own security responsibilities. Make them usable on mobile and modest connections. Record assigned learners, version, assessment and completion; a completion record is not professional accreditation or proof of changed behaviour.

Use licensed content or a specialist partner where that is more economical. Measure learning with a short assessment and, where appropriate, an observed follow-up action. Continue only if an employer pays or renews and the delivery cost fits the package.

A consumer Academy, certification business and broad learning marketplace would each require separate commercial validation. Keep them outside the initial execution path.

## 8. Pricing and economics that can support growth

The current ₦7,000 and ₦15,000 monthly prices should be treated as published offers to assess, not validated optimal pricing. Retain existing customer commitments while testing clearly disclosed new pilot packages. This plan changes no live prices or subscriptions.

Use three commercial layers: a bounded software subscription; a fixed-scope onboarding or review-preparation engagement; and optional ongoing expert support. Define included assets, scan frequency, users, evidence retention and service allowance. Avoid unlimited resource-intensive work before measuring its cost.

For each account, calculate:

- **Delivery contribution:** net revenue for the period minus variable infrastructure, scanner, AI, storage, delivery, partner and direct service-labour costs. Include founder delivery time at a realistic replacement rate. Track collection separately.
- **Contribution margin:** delivery contribution divided by that period's net revenue. Separate one-time onboarding from steady-state service.
- **Acquisition cost:** attributable marketing, partner acquisition fees and sales labour divided by acquired paying customers. Classify each expense once; recurring partner commissions belong in delivery economics if they recur.
- **Payback:** acquisition cost divided by monthly steady-state contribution per customer, when that contribution is positive and sufficiently observed. Early results are estimates.

**Illustrative cost constraint:** at an 80% delivery contribution target, a ₦15,000 monthly account allows ₦3,000 in variable delivery costs, and a ₦7,000 account allows ₦1,400. This arithmetic assumes those prices are net revenue for the example and is not a claim about current costs or a universal margin requirement. It shows why human support needs explicit pricing and limits.

Track median and high-effort accounts. Stress-test a 30% increase in foreign-currency infrastructure/API costs, twice the expected scan usage and one additional support hour per account. These are planning scenarios, not forecasts. If the package fails, adjust scope, automation or price before acquiring more similar accounts.

Review alternative prices in real proposals and record conversion, reasons for refusal and delivery economics. Do not use hypothetical lifetime value to justify acquisition spending before meaningful retention evidence exists.

## 9. Build a repeatable sales and distribution process

**Founder-led sales first:** assemble a named list of 50 suitable accounts. Seek 15–20 qualified conversations over the first month and make scoped proposals where the buying event is real. Use warm introductions and individually relevant outreach. Measure the funnel: contacted, qualified, proposal, paid pilot, delivered, continued.

Create four sales assets: a one-page offer, a clearly labelled sample report, a short workflow demonstration and an honest security/data-handling overview. Add a customer-approved case study as soon as a measured outcome exists. Use customer language about their problem and buying decision.

**Partner experiment:** approach three relevant organisations such as development agencies, managed IT providers or licensed compliance practitioners. Agree lead ownership, customer consent, support responsibilities, fees and evidence access. The first milestone is qualified introductions and a paid customer from a partner. Build a partner portal after repeated use demonstrates its need.

**Content experiment:** publish practical material for the selected buying event: a security-review preparation guide, a sample evidence index and lessons from resolving common relevant exposures. Track qualified enquiries and paid conversions. Broad traffic and brand searches are secondary indicators.

For the first ten wins and losses, capture the trigger, budget owner, alternative, price, decisive objection, sales time and work required. When the same objection repeatedly explains losses, decide whether to fix the offer, product or segment. Avoid treating every lost deal as a request for a new feature.

## 10. Scale delivery before multiplying demand

A scalable business needs predictable delivery, controlled support effort and capacity that can grow. The earlier scanner review supplies the engineering detail; the commercial requirements are:

- Prevent duplicate/overlapping work from consuming allowances and capacity unexpectedly.
- Make worker ownership and result integrity dependable during retries, cancellation and recovery.
- Measure queue delay, scan duration, coverage and manual recovery within a declared scope.
- Bound history/evidence retrieval and define retention so growing accounts do not degrade the service.
- Demonstrate backup restoration, tenant isolation and operational access controls before expanding sensitive evidence handling.
- Make failures visible to support staff and customers with clear recovery expectations.

Preserve the current modular product architecture and separable scanner workers unless measurements justify another design. A microservices or Kubernetes migration is not a commercial milestone.

Before opening a substantially larger cohort, test the representative paid plan and scope at twice the forecast peak workload. Select provisional service targets from measured baselines; check high-percentile turnaround and failures, not only averages. Add capacity when queue time or reliability approaches the agreed limit. Do not advertise guaranteed turnaround before the operating evidence supports it.

Document onboarding, triage, evidence preparation and support so another trained person can deliver a pilot without the founder directing every step. This is a direct test of operational scalability.

## 11. The phased execution roadmap

| Period | Main work | Evidence required to advance | Accountable owner |
| --- | --- | --- | --- |
| Days 1–14 | Define buyer/offer; assemble prospects; interview buyers; inspect real requests; baseline product delivery and costs; prepare sample evidence pack. | Named budget owners and repeated, in-scope problems with actual deadlines. | Founder |
| Days 15–30 | Complete 15–20 qualified conversations; make bounded offers; secure 3–5 paid pilots from unrelated companies; prioritise delivery blockers. | Payments or separately identified binding commitments; common scope; recorded buying reasons. Commitments are not collected revenue. | Founder + product |
| Days 31–60 | Deliver pilots; complete critical workflow improvements; measure effort, fixes and evidence usefulness; test partner referrals. | Repeatable delivery, credible customer outcomes and a costed process. | Engineering + customer success |
| Days 61–90 | Seek paid continuation; compare alternatives fairly; have another person deliver from the playbook; select one repeated workflow to automate. | Aim for at least 3 of 5 comparable pilots continuing at a sustainable price, with documented reasons. Report actual counts if the sample differs. | Founder + operations |
| Months 4–6, if gates pass | Standardise onboarding, recurring monitoring and the first evidence workflow; build one demanded integration; expand one working channel. | Three months of cohort reporting, positive steady-state contribution and delivery that is increasingly independent of the founder. | Product + commercial leads |
| Months 7–12, if gates pass | Deepen successful accounts; pilot employer learning or partner workspaces when justified; test one adjacent segment or country. | Repeatable acquisition, retention and capacity; a costed local entry case with real buyers. | Founder + leadership |

**Day-90 decision:** expand recurring software if repeated demand, continuing paid use and improving economics are visible. Operate a clearly priced product-assisted service if expertise is the main value. Change the offer or segment if willingness to pay, useful outcomes or sustainable delivery remain weak.

If 15–20 genuinely qualified conversations and several concrete offers produce no paid pilot, pause adjacent-module development and examine the buying event, credibility, scope and price. If procurement decisions extend beyond day 90, record the pipeline and next decision date; do not relabel unresolved deals as wins or force an artificial result.

## 12. The weekly operating scorecard

Record a baseline in the first two weeks. Review small samples as customer-level evidence as well as percentages.

| Measure | Definition | Decision it supports |
| --- | --- | --- |
| Qualified-to-paid conversion | Paying customers divided by qualified prospects offered the comparable package, within a stated period | Does the offer sell? |
| Time to useful result | Time from required access/verification to a reviewed, usable assessment; show onboarding delay separately | Is activation delivering value quickly? |
| Assessment coverage | Successful required checks divided by required checks for the declared target/rule scope; expose unknowns | Can results support the promised claims? |
| Verified remediation | Time from agreed actionable finding to supported verification; retain unresolved age and accepted-risk counts | Are customers improving within scope? |
| Evidence preparation effort | Customer and delivery hours for comparable review requirements, before and after | Is the workflow saving work? |
| Reviewer rework | Missing or unsupported items returned for correction, with reason | Is the evidence useful and credible? |
| Paid continuation | Renewed/continued customers divided by customers actually eligible to make that decision | Is there recurring value? |
| Recurring revenue | Monthly value of active recurring contracts; track invoiced and collected amounts separately | What recurring business exists? |
| Account contribution | Period revenue less defined variable delivery costs; onboarding shown separately | Can each package scale economically? |
| Reliability and support | Partial/failed assessments, recovery interventions and support hours per account | Is growth increasing operational strain? |

When the recurring cohort is large and old enough to interpret, add gross revenue retention and net revenue retention. Gross retention excludes expansion; net retention includes expansion from the same starting cohort. Neither includes newly acquired customers. Exclude one-off pilot and advisory fees from recurring revenue. An annual prepayment is cash received; its monthly subscription equivalent is one-twelfth of the recurring annual price.

Link these measures to renewal conversations. Avoid making score increases, daily logins, report downloads or scanner volume the primary proof of value. A well-monitored customer may rarely need to log in.

## 13. Build advantages that compound

**Useful operational history:** connect assets, dated observations, verified fixes, evidence freshness and review responses. Customers should be able to retrieve and export that history. Its value is continuity and saved work.

**Repeatable delivery knowledge:** turn frequently successful remediation and evidence-preparation steps into reviewed templates, automation and integrations. Track which steps actually reduce effort and rework.

**Trusted distribution:** partners and customer referrals can reduce acquisition effort when they repeatedly bring the same buyer and problem. Measure economics and avoid excessive dependence on one partner.

**Credible local execution:** earn references for relevant support, pricing clarity, qualified Nigerian compliance input and dependable service. Local origin alone does not demonstrate quality or prevent competition.

**Customer-respecting learning:** use customer material only within agreed permissions. Develop reusable knowledge from approved, appropriately protected examples. Confidential questionnaires and vulnerability details are not automatically available for cross-customer training or marketing.

Expand inside an account through additional assets, business units, evidence workflows and assigned learning when there is demonstrated value. Test one new country at a time with named buyers, local expertise, workable collection and support arrangements. An “Africa” label does not establish one shared procurement process or regulatory regime.

## 14. Funding, team and investment readiness

Prepare a funding story around a specific repeatable business and the milestone that money will accelerate. Potential funding routes include customer-funded growth, grants, angels and venture capital; the right choice depends on the growth model and founder objectives. A profitable specialist service can be a sound business even if its expansion characteristics differ from venture-scale software.

Build a bottom-up market case: identify reachable qualified accounts in the first segment, observed conversion, expected annual contract value and delivery capacity. Expand the estimate only when another segment has evidence. For scale context, **1,000 active Growth accounts at the currently published ₦15,000/month would equal ₦15 million monthly recurring revenue and ₦180 million annualised recurring run rate**, before churn, discounts and costs. This is arithmetic, not a customer or revenue forecast. Use it to examine whether the expected acquisition and support model can sustain the required volume.

The investor evidence pack should contain:

- A precise buyer, buying event, alternative and reason customers choose Cyphward.
- Actual paid customer cohorts, invoices/collections and retention, with software and services separated.
- Permissioned case studies documenting verified improvements, effort saved and the limits of attribution to sales outcomes.
- Acquisition, delivery and account economics, including founder labour and high-effort customers.
- Product scope, reliability evidence, material dependencies and the operational improvement plan.
- A clear company ownership/capitalisation record, contributor/IP arrangements, financial records and customer commitments.
- A cash plan, proposed use of funds and milestones; distinguish funds already available from hoped-for investment.

Assign responsibilities before adding headcount: founder for selling and prioritisation; engineering/security for reliable delivery; customer success for activation and follow-through; a qualified compliance practitioner for regulatory content; and learning expertise when the Academy gate is met. Hire when a measured recurring bottleneck justifies the cost. Avoid expanding payroll from unsigned pipeline alone.

Investor discussions can start early. Represent the actual stage accurately; no customer-count target or calendar date guarantees investment. Evidence of retention is central to the quality of recurring revenue. [Y Combinator's business-model guidance](https://www.ycombinator.com/library/Gh-yc-guide-to-business-models).

## 15. Risks and explicit stop rules

| Risk | Early signal | Response |
| --- | --- | --- |
| Weak willingness to pay | Buyers praise demos but will not approve a scoped purchase | Revisit urgency, buyer and offer before expanding features |
| Offer mismatches procurement | Main blockers require capabilities or certification outside scope | Use a qualified partner where viable or choose a better-fitting segment |
| Service work overwhelms subscription revenue | Each account needs repeated unpriced expert intervention | Cap/reprice service, standardise delivery or adopt an explicit services model |
| Unreliable or overstated results | Customers cannot reproduce evidence; partial checks imply assurance | Correct claims and delivery before widening acquisition |
| One-off demand | Customers value a report but see no continuing need | Sell the engagement honestly; test a different recurring job |
| Customer-specific development dominates | One account controls most new work | Price custom work separately and protect the common product roadmap |
| Premature expansion | More segments, countries or modules appear before a repeatable cohort | Return to the next unproven commercial gate |

Keep payment activation, broad platform administration, a public Academy marketplace, unsupported residency/certification claims, and a major infrastructure rewrite outside the initial scope. Reconsider each only when a specific validated need and an economical delivery plan exist.

## 16. First-week execution checklist

- [ ] Assign a named owner to the business scorecard and each current P0 item.
- [ ] Write a one-page buyer definition and qualify 50 named prospect accounts.
- [ ] Book the first five buyer conversations around real upcoming reviews.
- [ ] Prepare the fixed-scope offer, sample report and clear support allowance.
- [ ] Start the delivery time log and per-account cost worksheet.
- [ ] Establish manual invoice, collection and reconciliation ownership without activating payment integration.
- [ ] Confirm a baseline for scan reliability, activation and report consistency within the proposed pilot scope.
- [ ] Review current product promises against what can be evidenced and delivered.
- [ ] Identify one qualified Nigerian compliance practitioner to review the proposed evidence workflow.
- [ ] Schedule a weekly 30-minute review of buyer decisions, delivery outcomes, economics and the next bottleneck.

The operating sequence is **qualify a buyer → sell a defined outcome → deliver and measure → earn paid continuation → standardise the work → expand a proven channel and product**. Revise this document monthly using customer evidence and actual delivery data.
