// Fixtures shared by the compliance browser suite and the screenshot capture script.
// Plain data builders only: no page or server state lives here.
export const DISCLAIMER =
  "Readiness evidence, not legal advice or a compliance determination. Filing of Compliance Audit Returns for UHL/EHL organisations must go through a licensed DPCO.";
// Words copy on these screens must never use (see the build plan). Matched case-insensitively against rendered text.
export const BANNED = [
  "compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit", "compliance score",
  "fully meets", "meets the requirement", "is met", "partial compliance", "fully compliant", "is compliant", "satisfy ndpa",
  "adequate", "adequacy", "guarantee",
];
// Added for the Documents tab (C5): claims a drafting assistant is most tempted to make.
export const DOC_BANNED = [...BANNED, "adequa", "legally sufficient", "certif", "complies", "in compliance"];
export const ORG_ZONE = "America/New_York"; // deliberately not Lagos, and not the browser's zone
export const BROWSER_ZONE = "Asia/Tokyo";
export const HOUR = 3600000;

export const user = { id: "c1-user", email: "c1@example.test", full_name: "Compliance Review" };
export const org = { id: "c1-org", name: "Acme Traders", slug: "acme", plan: "growth" };
export const domain = { id: "d1", org_id: org.id, domain: "acme.ng", verification_status: "verified", created_at: "2026-10-01T00:00:00Z" };

export const evidence = (status, extra = {}) => ({
  domain_id: "d1", domain: "acme.ng", status,
  status_label: { present: "Evidence present", gap: "Gap", not_assessed: "Not assessed" }[status],
  reason: "x", reason_text: { present: "Every requested check finished for this domain.", gap: "Open findings linked to this requirement.", not_assessed: "No scan with recorded coverage has finished for this domain yet." }[status],
  source: status === "not_assessed" ? null : "tool_observed",
  source_label: status === "not_assessed" ? null : "Tool observed",
  observed_at: status === "not_assessed" ? null : "2026-10-16T10:00:00Z",
  expires_at: status === "not_assessed" ? null : "2026-11-15T10:00:00Z",
  scan_id: "s1", finding_ids: [], details: {}, ...extra,
});
export const req = (key, group, title, status, extra = {}) => ({
  key, group, title, summary: `${title} — what the evidence shows.`, clause: "NDPA 2023 s.39(2)", clause_verified: false,
  clause_label: "NDPA 2023 s.39(2) · reference pending review", evidence_type_labels: ["Tool observed"],
  checks_performed: group === "security" ? "Certificate validity and expiry on each in-scope web host." : null,
  not_checked: group === "security" ? "Cipher strength and internal systems." : null,
  freshness_days: 30, remediation_hint: "Do the next sensible thing.",
  status, status_label: { present: "Evidence present", gap: "Gap", not_assessed: "Not assessed" }[status],
  reason: "x", reason_text: "Reason in plain words.",
  source: status === "not_assessed" && !extra.source ? null : "tool_observed",
  source_label: status === "not_assessed" && !extra.source ? null : "Tool observed",
  domains: [], findings: [], informational_findings: [], ...extra,
});
export const finding = { id: "f-dmarc", title: "Missing Email DMARC Authentication Policy", severity: "critical", status: "open" };

export function overview(plan) {
  const security = [
    req("ndpa.s39.encryption_in_transit", "security", "Personal data protected in transit", "present", { domains: [evidence("present")] }),
    req("ndpa.s39.exposed_services_inventoried", "security", "Internet-exposed services inventoried", "present",
      { domains: [evidence("present", { details: { open_ports: { "acme.ng": [80, 443, 3389] } } })] }),
    req("ndpa.s39.email_anti_spoofing", "security", "Email anti-spoofing records", "gap",
      { domains: [evidence("gap", { finding_ids: [finding.id] })], findings: [finding] }),
    req("ndpa.s39.known_vulnerability_testing", "security", "Testing for known vulnerabilities", "not_assessed",
      { domains: [evidence("not_assessed")] }),
  ];
  const external = (status, extra) => evidence(status, { source: "externally_observed", source_label: "Externally observed", ...extra });
  const notices = [
    req("gaid.notice.privacy_policy", "notices", "Privacy policy published", "present", {
      source: "externally_observed", source_label: "Externally observed",
      domains: [external("present", { details: { url: "https://acme.ng/privacy", changed_since_last_scan: true } })] }),
    req("gaid.consent.no_trackers_before_consent", "notices", "No non-essential cookies before consent", "gap", {
      source: "externally_observed", source_label: "Externally observed",
      domains: [external("gap", { details: { observed: [{ vendor: "google_analytics", how: "cookie_on_first_response", host: "acme.ng" }],
        cookies: [{ name: "_ga", category: "tracker" }, { name: "__cf_bm", category: "infrastructure" }] } })] }),
  ];
  const dpo = [req("gaid.dpo.designated", "dpo", "Data protection officer designated", "awaiting_input",
    { status_label: "Awaiting your input" })];
  const registration = [req("gaid.dpia.high_risk_processing", "registration", "Impact assessment for high-risk processing", "not_applicable",
    { status_label: "Not applicable", reason_text: "You told us you do not carry out high-risk processing, on 16 Oct 2026.", source: null, source_label: null })];
  const breach = [req("ndpa.s40.breach_response_plan", "breach", "Written breach response plan", "awaiting_input",
    { status_label: "Awaiting your input", reason_text: "Your answer has expired and is due for renewal.", source: "customer_attested", source_label: "Customer attested" })];
  const counts = (items) => ({
    with_evidence: 0, present: items.filter((r) => r.status === "present").length,
    gap: items.filter((r) => r.status === "gap").length,
    not_assessed: items.filter((r) => r.status === "not_assessed").length,
    awaiting_input: items.filter((r) => r.status === "awaiting_input").length, applicable: items.length,
  });
  return {
    disclaimer: DISCLAIMER,
    note: "Only the security measures group has an evidence source today.",
    register: { version: "ndpa-gaid-v1", title: "NDPA 2023 / GAID 2025 readiness register", references_pending_review: 11 },
    plan,
    readiness: { with_evidence: 3, present: 2, gap: 1, awaiting_input: 7, not_assessed: 1, applicable: 11 },
    domains: [{ id: "d1", domain: "acme.ng" }],
    groups: [
      { key: "registration", title: "Registration", locked: plan === "starter", counts: counts(registration), requirement_count: 1,
        requirements: plan === "starter" ? [] : registration },
      { key: "breach", title: "Breach readiness", locked: plan === "starter", counts: counts(breach), requirement_count: 1,
        requirements: plan === "starter" ? [] : breach },
      { key: "security", title: "Security measures", locked: false, counts: counts(security), requirement_count: 7, requirements: security },
      { key: "notices", title: "Notices", locked: plan === "starter", counts: counts(notices), requirement_count: 2,
        requirements: plan === "starter" ? [] : notices },
      { key: "dpo", title: "Data protection officer", locked: plan === "starter", counts: counts(dpo), requirement_count: 4,
        requirements: plan === "starter" ? [] : dpo },
    ],
  };
}


// ---- C3 mocks: members, a stateful questionnaire and an incident log ----
export const members = [
  { id: user.id, email: user.email, full_name: "Compliance Review", role: "owner" },
  { id: "m-ada", email: "ada@acme.ng", full_name: "Ada Obi", role: "admin" },
  { id: "m-tunde", email: "tunde@acme.ng", full_name: "Tunde Bello", role: "member" },
];
export const localIso = (iso, zone) => {
  if (!iso) return null;
  const at = new Date(iso);
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit" }).formatToParts(at).map((x) => [x.type, x.value]));
  const wall = `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}`;
  const off = Math.round((Date.parse(`${wall}Z`) - at.getTime()) / 60000);
  const sign = off < 0 ? "-" : "+";
  return `${wall}${sign}${String(Math.floor(Math.abs(off) / 60)).padStart(2, "0")}:${String(Math.abs(off) % 60).padStart(2, "0")}`;
};
export const qdef = (key, group, group_title, prompt, extra = {}) => ({
  key, group, group_title, prompt, type: "yes_no", shown: true, options: [], allow_not_applicable: false, allows_date: false, date_label: null,
  allows_text: false, text_label: null, text_max: null, expiry_days_from_date: null, show_if: null, evidences: [], applicability: [],
  answer_state: "unanswered", current: null, status: null, status_label: null, reason: null, reason_text: null, ...extra,
});
export const attested = (id, value, owner, extra = {}) => ({
  id, value, date: null, text: null, owner_user_id: owner.id, owner_name: owner.full_name, attested_at: "2026-10-16T23:30:00Z",
  expires_at: "2027-10-16T23:30:00Z", expired: false, evidence_link: null, notes: null, ...extra,
});
export function freshQuestions() {
  return [
    qdef("registration.major_importance", "registration", "Registration", "Are you a data controller or processor of major importance?",
      { applicability: [{ requirement_key: "gaid.registration.registered", when: "no" }] }),
    qdef("registration.tier", "registration", "Registration", "Which tier applies to you: UHL, EHL or OHL?",
      { type: "choice", options: ["uhl", "ehl", "ohl"], shown: false, applicability: [{ requirement_key: "gaid.registration.annual_car", when: "ohl" }], show_if: { question: "registration.major_importance", value: "yes" } }),
    qdef("dpia.high_risk_processing", "dpia", "Impact assessments", "Do you carry out processing likely to pose a high risk to people?",
      { applicability: [{ requirement_key: "gaid.dpia.high_risk_processing", when: "no" }], answer_state: "answered",
        current: attested("a-dpia", "no", members[1]) }),
    qdef("dpo.designated", "dpo", "Data protection officer", "Have you named a data protection officer?",
      { allows_text: true, text_label: "Name or role of the DPO (no personal ID numbers)", text_max: 120,
        evidences: [{ key: "gaid.dpo.designated", title: "Data protection officer designated" }], answer_state: "answered",
        current: attested("a-dpo", "yes", members[1], { text: "Ada Obi, Legal" }) }),
    qdef("dpo.six_monthly_report", "dpo", "Data protection officer", "What is the date of the DPO's latest six-monthly report?",
      { type: "date", allows_date: true, date_label: "Date of latest six-monthly report", expiry_days_from_date: 183,
        evidences: [{ key: "gaid.dpo.six_monthly_report", title: "DPO six-monthly report" }] }),
    qdef("breach.response_plan", "breach", "Breach readiness", "Do you have a written breach response plan?",
      { evidences: [{ key: "ndpa.s40.breach_response_plan", title: "Written breach response plan" }], answer_state: "expired",
        current: attested("a-plan", "yes", members[2], { attested_at: "2025-08-31T10:00:00Z", expires_at: "2026-08-31T10:00:00Z", expired: true }) }),
  ];
}
export const incidentView = (raw, zone, now) => {
  const aware = new Date(raw.became_aware_at).getTime();
  const deadline = new Date(aware + 72 * HOUR);
  const notified = raw.notified_commission_at ? new Date(raw.notified_commission_at).getTime() : null;
  const late = notified !== null && notified > deadline.getTime();
  const overdue = notified === null && now > deadline.getTime();
  const iso = (v) => (v ? new Date(v).toISOString() : null);
  const t = { detected_at: iso(raw.detected_at), became_aware_at: iso(raw.became_aware_at),
    notified_commission_at: iso(raw.notified_commission_at), notified_subjects_at: iso(raw.notified_subjects_at) };
  return {
    id: raw.id, title: raw.title, severity: raw.severity, status: raw.status, notes: raw.notes ?? null, ...t,
    deadline_at: deadline.toISOString(), hours_remaining: notified !== null ? null : Math.max(0, (deadline.getTime() - now) / HOUR),
    overdue, notified_late: late, notified_after_hours: notified === null ? null : (notified - aware) / HOUR,
    commission_state: notified === null ? (overdue ? "overdue" : "pending") : (late ? "notified_late" : "notified_on_time"),
    display_timezone: zone,
    local: { ...Object.fromEntries(Object.entries(t).map(([k, v]) => [k, localIso(v, zone)])), deadline_at: localIso(deadline.toISOString(), zone) },
  };
};
export const CHECKLIST = ["Contain", "Assess", "Record", "Notify the Commission", "Notify affected people", "Review"].map((title, i) => ({ key: `s${i}`, title, text: `${title} plainly.` }));
export const INCIDENT_DISCLAIMER = "A plain operational checklist, not legal advice. Whether a breach must be reported, and to whom, depends on your circumstances: ask your data protection officer or adviser.";
export function freshIncidents(now) {
  const ago = (h) => new Date(now - h * HOUR).toISOString();
  return [
    { id: "i-over", title: "Mailbox exposed to a former contractor", severity: "critical", status: "open", detected_at: ago(100), became_aware_at: ago(80), notified_commission_at: null, notified_subjects_at: null, notes: null },
    { id: "i-live", title: "Laptop lost on a site visit", severity: "medium", status: "contained", detected_at: ago(13), became_aware_at: ago(12.5), notified_commission_at: null, notified_subjects_at: ago(2), notes: "Disk was encrypted." },
    { id: "i-late", title: "Misdirected payroll file", severity: "high", status: "closed", detected_at: ago(300), became_aware_at: ago(290), notified_commission_at: ago(200), notified_subjects_at: null, notes: null },
  ];
}


// ---- C5 mocks: four AI-drafted documents, stateful ----
export const DOC_TITLES = { privacy_policy: "Privacy policy", cookie_notice: "Cookie notice", breach_response_plan: "Breach response plan", retention_schedule: "Retention schedule" };
export const DOC_LABEL = "Draft — not legal advice";
export const draftText = (kind, version) => [
  DOC_LABEL, "", `Version ${version} · Generated 2026-10-18 (UTC) · ${DOC_TITLES[kind]}`, "", `# ${DOC_TITLES[kind]} of Acme Traders`, "",
  "Data protection officer: [MISSING: name of your data protection officer].", "", "We keep records only as long as we need them. [MISSING: how long you keep each kind of personal data].", "",
  "---", "", DOC_LABEL + ". Have a qualified Nigerian data protection practitioner review it before you publish or rely on it.", "",
].join("\n");
export const docVersion = (kind, version, extra = {}) => ({
  id: `doc-${kind}-${version}`, kind, version, generated_at: "2026-10-18T09:00:00Z", generated_by: "Ada Obi", generator: "template", fallback_reason: null,
  placeholders: [{ key: "dpo_name", text: "[MISSING: name of your data protection officer]" }, { key: "retention", text: "[MISSING: how long you keep each kind of personal data]" }],
  open_placeholders: 2, approval: null, ...extra,
});
export const approved = (by, at) => ({ approved_by: by, approved_at: at, source: "customer_attested", open_placeholders: 2 });
export function freshDocuments() {
  return [
    docVersion("privacy_policy", 1, { approval: approved("Ada Obi", "2026-10-17T11:30:00Z") }),
    docVersion("privacy_policy", 2),
    docVersion("breach_response_plan", 1, { approval: approved("Compliance Review", "2026-10-18T10:00:00Z") }),
    docVersion("retention_schedule", 1),
  ];
}
export const docsListing = (all, usedToday) => ({
  label: DOC_LABEL, daily_cap: 10, generated_today: usedToday,
  documents: Object.keys(DOC_TITLES).map((kind) => {
    const history = all.filter((d) => d.kind === kind).sort((a, b) => b.version - a.version);
    const latest = history[0] ? { ...history[0], stale: kind === "privacy_policy" } : null;
    return { kind, title: DOC_TITLES[kind], status: !latest ? "not_generated" : latest.approval ? "approved" : "draft", latest, history };
  }),
});

