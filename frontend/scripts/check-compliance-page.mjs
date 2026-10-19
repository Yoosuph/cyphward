// Compliance readiness page (packet C1) against a stubbed API.
// Desktop, 390px and 320px: disclaimer, readiness counts, status chips with
// source labels, "reference pending review", gap → findings and Create task
// (no duplicate when a task exists), locked groups on Starter, no verdict
// language in rendered text and no horizontal overflow.
import assert from "node:assert/strict";
import { createServer } from "vite";
import puppeteer from "puppeteer-core";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const frontend = fileURLToPath(new URL("..", import.meta.url));
process.chdir(frontend);
const DISCLAIMER =
  "Readiness evidence, not legal advice or a compliance determination. Filing of Compliance Audit Returns for UHL/EHL organisations must go through a licensed DPCO.";
const BANNED = ["compliant", "certified", "satisfies", "satisfied", "passes audit", "pass the audit", "compliance score", "fully meets", "meets the requirement", "is met"];
// Added for the Documents tab (C5): claims a drafting assistant is most tempted to make.
const DOC_BANNED = [...BANNED, "guarantee", "adequa", "legally sufficient", "certif", "complies", "in compliance"];
const ORG_ZONE = "America/New_York"; // deliberately not Lagos, and not the browser's zone
const BROWSER_ZONE = "Asia/Tokyo";
const HOUR = 3600000;

const user = { id: "c1-user", email: "c1@example.test", full_name: "Compliance Review" };
const org = { id: "c1-org", name: "Acme Traders", slug: "acme", plan: "growth" };
const domain = { id: "d1", org_id: org.id, domain: "acme.ng", verification_status: "verified", created_at: "2026-10-01T00:00:00Z" };

const evidence = (status, extra = {}) => ({
  domain_id: "d1", domain: "acme.ng", status,
  status_label: { present: "Evidence present", gap: "Gap", not_assessed: "Not assessed" }[status],
  reason: "x", reason_text: { present: "Every requested check finished for this domain.", gap: "Open findings linked to this requirement.", not_assessed: "No scan with recorded coverage has finished for this domain yet." }[status],
  source: status === "not_assessed" ? null : "tool_observed",
  source_label: status === "not_assessed" ? null : "Tool observed",
  observed_at: status === "not_assessed" ? null : "2026-10-16T10:00:00Z",
  expires_at: status === "not_assessed" ? null : "2026-11-15T10:00:00Z",
  scan_id: "s1", finding_ids: [], details: {}, ...extra,
});
const req = (key, group, title, status, extra = {}) => ({
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
const finding = { id: "f-dmarc", title: "Missing Email DMARC Authentication Policy", severity: "critical", status: "open" };

function overview(plan) {
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
const members = [
  { id: user.id, email: user.email, full_name: "Compliance Review", role: "owner" },
  { id: "m-ada", email: "ada@acme.ng", full_name: "Ada Obi", role: "admin" },
  { id: "m-tunde", email: "tunde@acme.ng", full_name: "Tunde Bello", role: "member" },
];
const localIso = (iso, zone) => {
  if (!iso) return null;
  const at = new Date(iso);
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit" }).formatToParts(at).map((x) => [x.type, x.value]));
  const wall = `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}`;
  const off = Math.round((Date.parse(`${wall}Z`) - at.getTime()) / 60000);
  const sign = off < 0 ? "-" : "+";
  return `${wall}${sign}${String(Math.floor(Math.abs(off) / 60)).padStart(2, "0")}:${String(Math.abs(off) % 60).padStart(2, "0")}`;
};
const qdef = (key, group, group_title, prompt, extra = {}) => ({
  key, group, group_title, prompt, type: "yes_no", shown: true, options: [], allow_not_applicable: false, allows_date: false, date_label: null,
  allows_text: false, text_label: null, text_max: null, expiry_days_from_date: null, show_if: null, evidences: [], applicability: [],
  answer_state: "unanswered", current: null, status: null, status_label: null, reason: null, reason_text: null, ...extra,
});
const attested = (id, value, owner, extra = {}) => ({
  id, value, date: null, text: null, owner_user_id: owner.id, owner_name: owner.full_name, attested_at: "2026-10-16T23:30:00Z",
  expires_at: "2027-10-16T23:30:00Z", expired: false, evidence_link: null, notes: null, ...extra,
});
function freshQuestions() {
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
const incidentView = (raw, zone, now) => {
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
const CHECKLIST = ["Contain", "Assess", "Record", "Notify the Commission", "Notify affected people", "Review"].map((title, i) => ({ key: `s${i}`, title, text: `${title} plainly.` }));
const INCIDENT_DISCLAIMER = "A plain operational checklist, not legal advice. Whether a breach must be reported, and to whom, depends on your circumstances: ask your data protection officer or adviser.";
function freshIncidents(now) {
  const ago = (h) => new Date(now - h * HOUR).toISOString();
  return [
    { id: "i-over", title: "Mailbox exposed to a former contractor", severity: "critical", status: "open", detected_at: ago(100), became_aware_at: ago(80), notified_commission_at: null, notified_subjects_at: null, notes: null },
    { id: "i-live", title: "Laptop lost on a site visit", severity: "medium", status: "contained", detected_at: ago(13), became_aware_at: ago(12.5), notified_commission_at: null, notified_subjects_at: ago(2), notes: "Disk was encrypted." },
    { id: "i-late", title: "Misdirected payroll file", severity: "high", status: "closed", detected_at: ago(300), became_aware_at: ago(290), notified_commission_at: ago(200), notified_subjects_at: null, notes: null },
  ];
}


// ---- C5 mocks: four AI-drafted documents, stateful ----
const DOC_TITLES = { privacy_policy: "Privacy policy", cookie_notice: "Cookie notice", breach_response_plan: "Breach response plan", retention_schedule: "Retention schedule" };
const DOC_LABEL = "Draft — not legal advice";
const draftText = (kind, version) => [
  DOC_LABEL, "", `Version ${version} · Generated 2026-10-18 (UTC) · ${DOC_TITLES[kind]}`, "", `# ${DOC_TITLES[kind]} of Acme Traders`, "",
  "Data protection officer: [MISSING: name of your data protection officer].", "", "We keep records only as long as we need them. [MISSING: how long you keep each kind of personal data].", "",
  "---", "", DOC_LABEL + ". Have a qualified Nigerian data protection practitioner review it before you publish or rely on it.", "",
].join("\n");
const docVersion = (kind, version, extra = {}) => ({
  id: `doc-${kind}-${version}`, kind, version, generated_at: "2026-10-18T09:00:00Z", generated_by: "Ada Obi", generator: "template", fallback_reason: null,
  placeholders: [{ key: "dpo_name", text: "[MISSING: name of your data protection officer]" }, { key: "retention", text: "[MISSING: how long you keep each kind of personal data]" }],
  open_placeholders: 2, approval: null, ...extra,
});
const approved = (by, at) => ({ approved_by: by, approved_at: at, source: "customer_attested", open_placeholders: 2 });
function freshDocuments() {
  return [
    docVersion("privacy_policy", 1, { approval: approved("Ada Obi", "2026-10-17T11:30:00Z") }),
    docVersion("privacy_policy", 2),
    docVersion("breach_response_plan", 1, { approval: approved("Compliance Review", "2026-10-18T10:00:00Z") }),
    docVersion("retention_schedule", 1),
  ];
}
const docsListing = (all, usedToday) => ({
  label: DOC_LABEL, daily_cap: 10, generated_today: usedToday,
  documents: Object.keys(DOC_TITLES).map((kind) => {
    const history = all.filter((d) => d.kind === kind).sort((a, b) => b.version - a.version);
    const latest = history[0] ? { ...history[0], stale: kind === "privacy_policy" } : null;
    return { kind, title: DOC_TITLES[kind], status: !latest ? "not_generated" : latest.approval ? "approved" : "draft", latest, history };
  }),
});

const server = await createServer({ root: frontend, server: { host: "127.0.0.1", port: 0 } });
let browser;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || "/usr/bin/chromium", headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let plan = "growth";
  let role = "member";
  let existingTasks = [];
  const posts = [];
  const writes = [];
  let questions = freshQuestions();
  let incidents = freshIncidents(Date.now());
  const downloads = [];
  const freshPacks = () => [{ id: "p-old00000000", snapshot_id: "s-old00000000", kind: "readiness_pack", pack_version: "cyphward-ndpa-pack-v1",
    issued_at: "2026-10-10T09:00:00Z", retain_until: "2029-10-10T09:00:00Z", issued_by: user.id, window_start: null, window_end: null, html_sha256: "a".repeat(64), pdf_sha256: "d".repeat(64) }];
  let packs = freshPacks();
  let documents = freshDocuments();
  const freshFiles = () => [{ id: "ef-old", question_key: "dpo.designated", attestation_id: "a-dpo", display_name: "dpo-appointment-letter.pdf",
    content_type: "application/pdf", type_label: "PDF", size_bytes: 52341, sha256: "e".repeat(64), uploaded_at: "2026-10-17T09:00:00Z", uploaded_by: "Ada Obi" }];
  let evidenceFiles = freshFiles();
  const fileEvents = [];
  const reset = () => { questions = freshQuestions(); incidents = freshIncidents(Date.now()); packs = freshPacks(); documents = freshDocuments(); evidenceFiles = freshFiles(); fileEvents.length = 0; writes.length = 0; posts.length = 0; downloads.length = 0; };
  const json = (request, status, body) => void request.respond({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      return url.origin === origin ? void request.continue() : void request.abort();
    }
    const method = request.method();
    const path = url.pathname;
    const growth = plan !== "starter";
    if (path.endsWith("/auth/bootstrap")) return json(request, 200, { user, email_verified: true, memberships: [{ org: { ...org, plan }, role, domains: [domain] }] });
    if (path.endsWith("/compliance/overview")) return json(request, 200, overview(plan));
    if (path.endsWith("/compliance/questionnaire")) {
      if (!growth) return json(request, 403, { detail: "This part of the compliance pages is part of the Growth plan." });
      const shown = questions.filter((q) => q.shown);
      return json(request, 200, { disclaimer: DISCLAIMER, version: "ndpa-gaid-questionnaire-v1", register_version: "x", display_timezone: ORG_ZONE,
        answered: shown.filter((q) => q.answer_state !== "unanswered").length, questions });
    }
    if (path.endsWith("/compliance/attestations") && method === "POST") {
      const body = JSON.parse(request.postData() || "{}");
      writes.push({ method, path, body });
      const q = questions.find((x) => x.key === body.question_key);
      const owner = members.find((m) => m.id === body.owner_user_id);
      q.current = attested(`a-${writes.length}`, body.answer.value, owner, { date: body.answer.date || null, text: body.answer.text || null,
        evidence_link: body.evidence_link || null, notes: body.notes || null, attested_at: new Date().toISOString(),
        expires_at: body.expires_at || new Date(Date.now() + 365 * 24 * HOUR).toISOString() });
      q.answer_state = body.answer.value === "not_sure" ? "not_sure" : "answered";
      const tier = questions.find((x) => x.key === "registration.tier");
      const major = questions.find((x) => x.key === "registration.major_importance");
      tier.shown = major.current?.value === "yes";
      return json(request, 201, q.current);
    }
    if (path.includes("/compliance/evidence-files")) {
      if (!growth) return json(request, 403, { detail: "This part of the compliance pages is part of the Growth plan." });
      const one = path.match(/\/evidence-files\/([^/]+)(\/download)?$/);
      if (!one && method === "GET") {
        return json(request, 200, { files: evidenceFiles, usage: { files: evidenceFiles.length, bytes: 1 }, uploads_available: true,
          limits: { max_bytes: 10 * 1024 * 1024, max_files: 100, max_total_bytes: 500 * 1024 * 1024, extensions: ["docx", "jpeg", "jpg", "pdf", "png"], label: "x" } });
      }
      if (!one && method === "POST") {
        const key = url.searchParams.get("question_key");
        const name = decodeURIComponent(request.headers()["x-file-name"] || "");
        fileEvents.push({ method, key, name, type: request.headers()["content-type"], auth: request.headers().authorization });
        if (name.startsWith("refused")) return setTimeout(() => json(request, 422, { detail: "The file's contents do not match its PDF name. Check the file and try again." }), 100);
        return setTimeout(() => {
          evidenceFiles.push({ id: `ef-new-${fileEvents.length}`, question_key: key, attestation_id: null, display_name: name, content_type: "application/pdf",
            type_label: "PDF", size_bytes: 20, sha256: "f".repeat(64), uploaded_at: new Date().toISOString(), uploaded_by: "Compliance Review" });
          json(request, 201, evidenceFiles.at(-1));
        }, 600);
      }
      if (one && one[2] && method === "GET") {
        fileEvents.push({ method, id: one[1] });
        return json(request, 200, { url: `https://files.example.test/object/sign/${one[1]}?token=t&download=x`, expires_in: 60, display_name: "dpo-appointment-letter.pdf" });
      }
      if (one && method === "DELETE") {
        fileEvents.push({ method, id: one[1] });
        evidenceFiles = evidenceFiles.filter((f) => f.id !== one[1]);
        return json(request, 200, { id: one[1], removed: true, object_deleted: true });
      }
    }
    if (path.includes("/compliance/documents")) {
      if (!growth) return json(request, 403, { detail: "This part of the compliance pages is part of the Growth plan." });
      const generatedToday = 3 + writes.filter((w) => w.path.endsWith("/generate")).length;
      const generate = path.match(/\/documents\/([a-z_]+)\/generate$/);
      const approve = path.match(/\/documents\/([^/]+)\/approve$/);
      if (generate && method === "POST") {
        writes.push({ method, path });
        const version = documents.filter((d) => d.kind === generate[1]).length + 1;
        const made = docVersion(generate[1], version, { generated_at: new Date().toISOString() });
        documents.push(made);
        return json(request, 201, { id: made.id, version });
      }
      if (approve && method === "POST") {
        writes.push({ method, path });
        const target = documents.find((d) => d.id === approve[1]);
        target.approval = approved("Compliance Review", new Date().toISOString());
        return json(request, 201, { id: "ap-1", approved_at: target.approval.approved_at });
      }
      const one = path.match(/\/documents\/([^/]+)$/);
      if (one) {
        const d = documents.find((x) => x.id === one[1]);
        const latestVersion = Math.max(...documents.filter((x) => x.kind === d.kind).map((x) => x.version));
        return json(request, 200, { ...d, title: DOC_TITLES[d.kind], label: DOC_LABEL, text: draftText(d.kind, d.version), is_latest: d.version === latestVersion });
      }
      return json(request, 200, docsListing(documents, generatedToday));
    }
    if (path.includes("/compliance/incidents")) {
      if (!growth) return json(request, 403, { detail: "This part of the compliance pages is part of the Growth plan." });
      const now = Date.now();
      if (method === "GET") {
        return json(request, 200, { disclaimer: INCIDENT_DISCLAIMER, checklist: CHECKLIST, deadline_hours: 72, display_timezone: ORG_ZONE,
          incidents: incidents.map((i) => incidentView(i, ORG_ZONE, now)) });
      }
      const body = JSON.parse(request.postData() || "{}");
      writes.push({ method, path, body });
      if (method === "POST") {
        const wall = (v) => (v ? new Date(Date.parse(`${v}Z`) + 4 * HOUR).toISOString() : null); // mock zone: UTC-4 on this date
        const created = { id: `i-new-${writes.length}`, ...body, detected_at: wall(body.detected_at), became_aware_at: wall(body.became_aware_at),
          notified_commission_at: wall(body.notified_commission_at), notified_subjects_at: wall(body.notified_subjects_at) };
        incidents.unshift(created);
        return json(request, 201, incidentView(created, ORG_ZONE, now));
      }
      const target = incidents.find((i) => path.endsWith(`/${i.id}`));
      for (const [k, v] of Object.entries(body)) target[k] = k.startsWith("notified_") && v ? new Date(Date.parse(`${v}Z`) + 4 * HOUR).toISOString() : v;
      return json(request, 200, incidentView(target, ORG_ZONE, now));
    }
    if (path.includes("/api/v1/packs")) {
      if (!growth) return json(request, 403, { detail: "Evidence packs are part of the Growth plan." });
      if (/\/packs\/[^/]+\/(html|pdf)$/.test(path)) {
        downloads.push(path);
        return void request.respond({ status: 200, contentType: path.endsWith("pdf") ? "application/pdf" : "text/html", body: "stored bytes" });
      }
      if (method === "POST") {
        const body = JSON.parse(request.postData() || "{}");
        writes.push({ method, path, body });
        packs.unshift({ id: `p-new-${writes.length}000000`, snapshot_id: "s-new0000000", kind: body.kind, pack_version: "cyphward-ndpa-pack-v1",
          issued_at: new Date().toISOString(), retain_until: "2029-10-18T09:00:00Z", issued_by: user.id, window_start: null, window_end: null,
          html_sha256: "b".repeat(64), pdf_sha256: "c".repeat(64) });
        return json(request, 201, { pack: packs[0], created: true });
      }
      return json(request, 200, { packs, total: packs.length, notice: "Supporting evidence only. Not a Compliance Audit Return.", retention_months: 36,
        retention: "Kept for 36 months from the day it is issued (the default is 36 months, 3 years), and removed with your organisation. Names of answer owners recorded at the time stay in issued snapshots and packs." });
    }
    if (path.endsWith("/api/v1/members")) return json(request, 200, members);
    let body = {};
    if (path.endsWith("/remediation") && method === "GET") body = { tasks: existingTasks, total: existingTasks.length };
    else if (path.endsWith("/remediation") && method === "POST") {
      posts.push(JSON.parse(request.postData() || "{}"));
      body = { task: { id: "t-new", title: "Fix", status: "open" } };
    } else if (path.endsWith("/domains")) body = [domain];
    else if (path.includes("/notifications")) body = { notifications: [], unread_count: 0 };
    else if (path.includes("/platform/")) return void request.respond({ status: 403, contentType: "application/json", body: '{"detail":"no"}' });
    json(request, 200, body);
  });
  await page.emulateTimezone(BROWSER_ZONE);
  // Run the page's slow timers (the countdown tick) quickly so the live behaviour can be asserted.
  await page.evaluateOnNewDocument(() => {
    const original = window.setInterval.bind(window);
    window.setInterval = (fn, ms, ...rest) => original(fn, ms >= 10000 && ms <= 30000 ? 150 : ms, ...rest);
  });
  await page.evaluateOnNewDocument((u) => {
    localStorage.setItem(`cyphward-tour-v1:${u.id}`, "done");
    localStorage.setItem("cyphward-session", JSON.stringify({ access_token: "t", refresh_token: "r", user: u, _expires_at: Date.now() + 864000000 }));
    localStorage.setItem("cyphward-welcome-sent", u.id);
    localStorage.setItem("cyphward-theme", "light");
    localStorage.setItem("cyphward-cookie-consent", "accepted");
  }, user);

  const clickExact = (text, within = "body") => page.evaluate((t, scope) => {
    const root = document.querySelector(scope);
    const el = [...(root || document).querySelectorAll("button, a")].find((b) => b.textContent.replace(/\s+/g, " ").trim() === t);
    if (el) el.click();
    return !!el;
  }, text, within);
  const setVal = (selector, value) => page.evaluate((sel, v) => {
    const el = document.querySelector(sel);
    if (!el) throw new Error(`missing ${sel}`);
    const proto = el.tagName === "SELECT" ? HTMLSelectElement.prototype : el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  }, selector, value);
  const chooseRadio = (scope, label) => page.evaluate((sc, text) => {
    const l = [...document.querySelector(sc).querySelectorAll("label")].find((x) => x.textContent.trim() === text);
    if (!l) return false;
    l.querySelector("input").click();
    return true;
  }, scope, label);
  const bodyText = () => page.evaluate(() => document.body.innerText);
  const overflowOf = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  const openTab = async (label) => {
    assert.ok(await clickExact(label.toUpperCase(), '[role="tablist"]'), `tab ${label}`);
  };
  const noVerdicts = async (where) => {
    const lowered = (await bodyText()).toLowerCase();
    for (const phrase of where.includes("documents") ? DOC_BANNED : BANNED) assert.ok(!lowered.includes(phrase), `${where}: verdict language "${phrase}"`);
  };
  const qsel = (key) => `[data-testid="question-${key}"]`;
  const gotoComply = async () => {
    await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
    await page.waitForSelector('[data-testid="compliance-disclaimer"]', { timeout: 10000 });
  };

  const clickText = (text) => page.evaluate((t) => {
    const el = [...document.querySelectorAll("button, a")].find((b) => b.textContent.includes(t));
    if (el) el.click();
    return !!el;
  }, text);

  for (const [name, width] of [["desktop", 1440], ["mobile", 390], ["small-mobile", 320]]) {
    plan = "growth";
    existingTasks = [];
    posts.length = 0;
    await page.setViewport({ width, height: 900 });
    await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
    await page.waitForSelector('[data-testid="compliance-disclaimer"]', { timeout: 10000 });

    const view = await page.evaluate(() => ({
      disclaimer: document.querySelector('[data-testid="compliance-disclaimer"]').textContent.trim(),
      line: document.querySelector('[data-testid="readiness-line"]').textContent.replace(/\s+/g, " ").trim(),
      text: document.body.innerText,
      overflow: document.documentElement.scrollWidth - window.innerWidth,
      nav: !!document.querySelector('a[href="/comply"]'),
    }));
    assert.equal(view.disclaimer, DISCLAIMER, `${name}: disclaimer`);
    assert.equal(view.line, "3 of 11 have evidence · 7 awaiting input or upcoming checks", `${name}: readiness line`);
    assert.ok(!/\d%/.test(view.text), `${name}: no bare percentage`);
    for (const label of ["2 PRESENT", "1 GAPS", "1 NOT ASSESSED", "7 AWAITING INPUT", "Awaiting your input", "reference pending review", "No evidence yet"]) {
      assert.ok(view.text.includes(label) || view.text.toUpperCase().includes(label.toUpperCase()), `${name}: ${label}`);
    }
    assert.ok(view.text.toUpperCase().includes("TOOL OBSERVED"), `${name}: source label`);
    assert.ok(view.overflow <= 0, `${name}: horizontal overflow ${view.overflow}px`);
    if (width === 1440) assert.ok(view.nav, "sidebar has the Compliance entry");

    // Expand the ports requirement: the open ports are listed with "present".
    assert.ok(await clickText("Internet-exposed services inventoried"));
    await page.waitForFunction(() => document.body.innerText.includes("Open ports:"), { timeout: 5000 });
    assert.ok((await page.evaluate(() => document.body.innerText)).includes("acme.ng 80, 443, 3389"), `${name}: ports listed`);

    // Expand the gap: its finding and Create task.
    assert.ok(await clickText("Email anti-spoofing records"));
    await page.waitForFunction(() => document.body.innerText.includes("OPEN FINDINGS BEHIND THIS GAP"), { timeout: 5000 });
    assert.ok(await clickText("CREATE TASK"));
    await page.waitForFunction(() => document.body.innerText.includes("TASK CREATED"), { timeout: 5000 });
    assert.equal(posts.length, 1, `${name}: one task created`);
    assert.equal(posts[0].finding_id, "f-dmarc");

    // Externally observed evidence: source label, page found and change flag, tracker gap and cookie categories.
    assert.ok(view.text.toUpperCase().includes("EXTERNALLY OBSERVED"), `${name}: external source label`);
    assert.ok(await clickText("Privacy policy published"));
    await page.waitForFunction(() => document.body.innerText.includes("changed since last scan"), { timeout: 5000 });
    assert.ok(await clickText("No non-essential cookies before consent"));
    await page.waitForFunction(() => document.body.innerText.includes("Observed: google analytics"), { timeout: 5000 });
    assert.ok((await page.evaluate(() => document.body.innerText)).includes("__cf_bm (infrastructure)"), `${name}: cookie categories`);

    const lowered = (await page.evaluate(() => document.body.innerText)).toLowerCase();
    for (const phrase of BANNED) assert.ok(!lowered.includes(phrase), `${name}: verdict language "${phrase}"`);
    const expandedOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(expandedOverflow <= 0, `${name}: overflow after expanding ${expandedOverflow}px`);
    if (process.env.CYPHWARD_COMPLIANCE_SCREENSHOTS === "1") await page.screenshot({ path: `/tmp/compliance-${name}.png`, fullPage: true });
  }

  // An existing task for the finding is shown instead of creating a duplicate.
  existingTasks = [{ id: "t-old", finding_id: "f-dmarc", title: "Fix DMARC", status: "open" }];
  posts.length = 0;
  await page.setViewport({ width: 1440, height: 900 });
  await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
  await page.waitForSelector('[data-testid="compliance-disclaimer"]');
  await clickText("Email anti-spoofing records");
  await page.waitForFunction(() => document.body.innerText.includes("CREATE TASK"));
  await clickText("CREATE TASK");
  await page.waitForFunction(() => document.body.innerText.includes("VIEW TASK"), { timeout: 5000 });
  assert.equal(posts.length, 0, "no duplicate task");

  // Starter: other groups locked, readiness still shown.
  plan = "starter";
  await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
  await page.waitForSelector('[data-testid="compliance-disclaimer"]');
  const starter = await page.evaluate(() => document.body.innerText);
  assert.ok(starter.toUpperCase().includes("GROWTH PLAN") && starter.includes("SEE PLANS"), "locked group prompt");
  assert.ok(!starter.includes("Data protection officer designated"), "locked requirements hidden");
  assert.ok(starter.includes("Email anti-spoofing records"), "security group open on Starter");


  // ---------------- C3: owners and admins (all three widths) ----------------
  role = "admin";
  plan = "growth";
  for (const [name, width] of [["desktop", 1440], ["mobile", 390], ["small-mobile", 320]]) {
    reset();
    await page.setViewport({ width, height: 900 });
    await gotoComply();

    // Readiness: attested answers, renewal due and the Excluded section, in the organisation's zone.
    await clickText("Data protection officer designated");
    await page.waitForSelector('[data-testid="told-us"]', { timeout: 5000 });
    const told = await page.evaluate(() => document.querySelector('[data-testid="told-us"]').textContent.replace(/\s+/g, " ").trim());
    assert.match(told, /^You told us: Yes · Ada Obi, Legal on 16 Oct 2026 \(owner Ada Obi, renews 16 Oct 2027\)/, `${name}: told-us line (org zone, not the browser's)`);
    const readiness = await bodyText();
    assert.ok(readiness.toUpperCase().includes("RENEWAL DUE"), `${name}: renewal due on the expired answer`);
    assert.ok(readiness.includes("CUSTOMER ATTESTED"), `${name}: answer labelled customer attested`);
    const excluded = await page.evaluate(() => document.querySelector('[data-testid="excluded-section"]')?.innerText || "");
    assert.ok(excluded.includes("Impact assessment for high-risk processing") && excluded.includes("do not carry out high-risk processing"), `${name}: excluded section with reason`);
    assert.ok(!(await page.evaluate(() => document.querySelector('section[aria-label="Registration"]').innerText)).includes("Impact assessment for high-risk processing"),
      `${name}: excluded requirement is not listed as a requirement`);
    await noVerdicts(`${name} readiness`);

    // Questionnaire: applicability first, follow-ups only when shown.
    await openTab("Answer questions");
    await page.waitForSelector('[data-testid="questionnaire"]');
    let text = await bodyText();
    assert.ok(text.includes("What applies to you") && text.includes("major importance"), `${name}: applicability step first`);
    assert.ok(!text.includes("Which tier"), `${name}: follow-up hidden until shown`);
    assert.ok(text.includes("times shown in America/New_York"), `${name}: zone named`);
    const told2 = await page.evaluate(() => document.querySelector('[data-testid="question-dpia.high_risk_processing"] [data-testid="told-us"]').textContent);
    assert.ok(told2.includes("on 16 Oct 2026") && told2.includes("renews 16 Oct 2027"), `${name}: answered applicability question`);

    assert.ok(await clickExact("ANSWER", qsel("registration.major_importance")));
    const form = `[data-testid="form-registration.major_importance"]`;
    await page.waitForSelector(form);
    assert.deepEqual(await page.evaluate((f) => [...document.querySelectorAll(`${f} select`)[0].options].map((o) => o.textContent), form),
      ["Choose a member", "Compliance Review", "Ada Obi", "Tunde Bello"], `${name}: owner picker is the members`);
    assert.equal(await page.evaluate((f) => document.querySelectorAll(`${f} select`)[0].value, form), user.id, `${name}: owner defaults to the viewer`);
    const longest = await page.evaluate((f) => [...document.querySelectorAll(`${f} select`)[1].options].map((o) => o.textContent), form);
    assert.ok(longest.includes("24 months (longest)") && !longest.some((o) => /36|48/.test(o)), `${name}: expiry capped at 24 months`);
    assert.ok(await chooseRadio(form, "Yes"));
    await setVal(`${form} input[type="url"]`, "http://insecure.example");
    assert.ok(await overflowOf() <= 0, `${name}: overflow with the form open`);
    await clickExact("SAVE ANSWER", form);
    await page.waitForFunction(() => document.querySelector('[data-testid="form-error"]')?.textContent.includes("https"), { timeout: 5000 });
    assert.equal(writes.length, 0, `${name}: an http link is not sent`);
    await setVal(`${form} input[type="url"]`, "https://example.com/registration-proof");
    await setVal(`${form} textarea`, "Certificate is in the shared drive.");
    await clickExact("SAVE ANSWER", form);
    await page.waitForFunction(() => document.body.innerText.includes("Which tier"), { timeout: 5000 });
    assert.equal(writes.length, 1, `${name}: one attestation sent`);
    const sent = writes[0].body;
    assert.equal(sent.question_key, "registration.major_importance");
    assert.deepEqual(sent.answer, { value: "yes" });
    assert.equal(sent.evidence_link, "https://example.com/registration-proof");
    assert.equal(sent.notes, "Certificate is in the shared drive.");
    assert.ok(members.some((m) => m.id === sent.owner_user_id), `${name}: owner is a member`);
    assert.equal(sent.expires_at, undefined, `${name}: default expiry is left to the server`);

    // A 24-month expiry stays inside the API's 730-day cap.
    assert.ok(await clickExact("UPDATE ANSWER", qsel("registration.major_importance")));
    await chooseRadio(form, "Yes");
    const expirySelect = await page.evaluateHandle((f) => [...document.querySelectorAll(`${f} select`)].find((x) => x.id.endsWith("-expiry")), form);
    await page.evaluate((el) => { el.value = "729"; el.dispatchEvent(new Event("change", { bubbles: true })); }, expirySelect);
    await clickExact("SAVE ANSWER", form);
    await page.waitForFunction(() => !document.querySelector('[data-testid="form-registration.major_importance"]'), { timeout: 5000 });
    const days = (Date.parse(writes[1].body.expires_at) - Date.now()) / (24 * HOUR);
    assert.ok(days > 700 && days < 730, `${name}: 24-month expiry is ${days} days, inside the cap`);

    // Digits in a text answer are refused before sending; a date question takes no expiry.
    assert.ok(await clickExact("2. Data protection officer", 'nav[aria-label="Question groups"]'));
    await page.waitForSelector(qsel("dpo.six_monthly_report"));
    assert.ok(await clickExact("UPDATE ANSWER", qsel("dpo.designated")));
    const dform = `[data-testid="form-dpo.designated"]`;
    await setVal(`${dform} input[type="text"]`, "Ada 12345678");
    await clickExact("SAVE ANSWER", dform);
    await page.waitForFunction(() => document.querySelector('[data-testid="form-dpo.designated"] [data-testid="form-error"]')?.textContent.includes("ID numbers"), { timeout: 5000 });
    assert.equal(writes.length, 2, `${name}: digits not sent`);
    await clickExact("CANCEL", dform);
    assert.ok(await clickExact("ANSWER", qsel("dpo.six_monthly_report")));
    const sform = `[data-testid="form-dpo.six_monthly_report"]`;
    await page.waitForSelector(sform);
    assert.ok(await chooseRadio(sform, "I have the date"));
    await page.waitForSelector('[data-testid="expiry-follows-date"]');
    assert.ok(!(await page.evaluate((f) => [...document.querySelectorAll(`${f} select`)].some((x) => x.id.endsWith("-expiry")), sform)), `${name}: no expiry control on a date answer`);
    assert.equal(await page.evaluate((f) => document.querySelector(`${f} input[type="date"]`).max.length, sform), 10, `${name}: date capped at today`);
    await setVal(`${sform} input[type="date"]`, "2026-09-30");
    await clickExact("SAVE ANSWER", sform);
    await page.waitForFunction(() => !document.querySelector('[data-testid="form-dpo.six_monthly_report"]'), { timeout: 5000 });
    assert.deepEqual(writes[2].body.answer, { value: "date", date: "2026-09-30" }, `${name}: date answer`);
    assert.equal(writes[2].body.expires_at, undefined, `${name}: date answers send no expiry`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow in the questionnaire`);
    await noVerdicts(`${name} questionnaire`);

    // Evidence files (C6): list, checks mirroring the server, progress, upload, download link, confirm-then-remove.
    assert.ok(await clickExact("2. Data protection officer", 'nav[aria-label="Question groups"]'));
    const fq = qsel("dpo.designated");
    await page.waitForSelector(`${fq} [data-testid="file-ef-old"]`);
    const listed = await page.evaluate((q) => document.querySelector(`${q} [data-testid="file-ef-old"]`).innerText.replace(/\s+/g, " "), fq);
    assert.match(listed, /dpo-appointment-letter\.pdf PDF · 51 KB · 17 Oct 2026 · Ada Obi/, `${name}: file row shows name, type, size, date, uploader (${listed})`);
    assert.ok(await page.evaluate((q) => /Cyphward does not read or review it/.test(document.querySelector(q).innerText), fq), `${name}: attach area says it is not reviewed`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow with files listed`);
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cyph-files-"));
    const make = (file, bytes) => { const full = path.join(tmp, file); fs.writeFileSync(full, bytes); return full; };
    const fileInput = await page.$(`${fq} [data-testid="file-input-dpo.designated"]`);
    for (const [bad, bytes, pattern] of [["tool.exe", "MZ", /Only PDF, PNG, JPG\/JPEG or DOCX files up to 10 MB/], ["report.exe.pdf", "%PDF-1", /second extension/],
      ["empty.pdf", "", /empty/], ["big.pdf", Buffer.alloc(10 * 1024 * 1024 + 1), /limit is 10\.0 MB/]]) {
      await fileInput.uploadFile(make(bad, bytes));
      await page.waitForFunction((q) => document.querySelector(`${q} [data-testid="file-error"]`), { timeout: 5000 }, fq);
      const msg = await page.evaluate((q) => document.querySelector(`${q} [data-testid="file-error"]`).textContent, fq);
      assert.match(msg, pattern, `${name}: ${bad} refused before sending (${msg})`);
    }
    assert.equal(fileEvents.filter((e) => e.method === "POST").length, 0, `${name}: refused files are never sent`);
    await fileInput.uploadFile(make("refused-mismatch.pdf", "%PDF-1"));
    await page.waitForFunction((q) => document.querySelector(`${q} [data-testid="upload-progress"]`), { timeout: 5000 }, fq);
    assert.ok(await page.evaluate((q) => /Uploading refused-mismatch\.pdf/.test(document.querySelector(`${q} [data-testid="upload-progress"]`).innerText), fq), `${name}: progress shown`);
    await page.waitForFunction((q) => /do not match/.test(document.querySelector(`${q} [data-testid="file-error"]`)?.textContent || ""), { timeout: 5000 }, fq);
    assert.equal(await page.evaluate((q) => !!document.querySelector(`${q} [data-testid="upload-progress"]`), fq), false, `${name}: progress ends on a server refusal`);
    await fileInput.uploadFile(make("new-minutes.pdf", "%PDF-1.4 hello"));
    await page.waitForFunction((q) => document.body.innerText.includes("new-minutes.pdf") && !document.querySelector(`${q} [data-testid="upload-progress"]`), { timeout: 5000 }, fq);
    const sentUpload = fileEvents.filter((e) => e.method === "POST").at(-1);
    assert.deepEqual([sentUpload.key, sentUpload.name, sentUpload.type, sentUpload.auth], ["dpo.designated", "new-minutes.pdf", "application/octet-stream", "Bearer t"], `${name}: raw upload with the session`);
    // Download: the API is called, then the signed link is followed as a download.
    await page.evaluate(() => { window.__followed = []; HTMLAnchorElement.prototype.click = function () { window.__followed.push([this.href, this.getAttribute("download")]); }; });
    assert.ok(await page.evaluate((q) => { document.querySelector(`${q} [data-testid="file-ef-old"] button[aria-label^="Download"]`).click(); return true; }, fq));
    await page.waitForFunction(() => window.__followed.length === 1, { timeout: 5000 });
    const followed = await page.evaluate(() => window.__followed[0]);
    assert.ok(followed[0].startsWith("https://files.example.test/object/sign/ef-old?token=") && followed[0].includes("download="), `${name}: the signed link is followed`);
    assert.equal(followed[1], "dpo-appointment-letter.pdf", `${name}: saved under the display name`);
    // Remove asks first; cancel keeps the file, confirm removes it.
    const removeBtn = `${fq} [data-testid="file-ef-old"] button[aria-label^="Remove"]`;
    await page.evaluate((b) => document.querySelector(b).click(), removeBtn);
    await page.waitForFunction(() => /remove this file\?/i.test(document.body.innerText), { timeout: 5000 });
    assert.equal(fileEvents.filter((e) => e.method === "DELETE").length, 0, `${name}: nothing removed before the confirm step`);
    assert.ok(await clickExact("CANCEL", '[role="dialog"]'));
    await page.waitForFunction(() => !/remove this file\?/i.test(document.body.innerText), { timeout: 5000 });
    assert.equal(fileEvents.filter((e) => e.method === "DELETE").length, 0, `${name}: cancel keeps the file`);
    await page.evaluate((b) => document.querySelector(b).click(), removeBtn);
    await page.waitForFunction(() => /remove this file\?/i.test(document.body.innerText), { timeout: 5000 });
    assert.ok(await clickExact("REMOVE", '[role="dialog"]'));
    await page.waitForFunction(() => !document.body.innerText.includes("dpo-appointment-letter.pdf"), { timeout: 5000 });
    assert.equal(fileEvents.filter((e) => e.method === "DELETE").length, 1, `${name}: one removal after the confirm`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow with the attach area`);
    // Keyboard: the attach button is reachable and its label is plain text.
    assert.ok(await page.evaluate((q) => [...document.querySelectorAll(`${q} button`)].some((b) => b.textContent.trim() === "ATTACH EVIDENCE" && b.tabIndex === 0), fq), `${name}: attach button is focusable`);
    await noVerdicts(`${name} evidence files`);
    fs.rmSync(tmp, { recursive: true, force: true });
    if (process.env.CYPHWARD_COMPLIANCE_SCREENSHOTS === "1") await page.screenshot({ path: `/tmp/compliance-files-${name}.png`, fullPage: true });

    // Incidents: list, badges, countdown, zone and the checklist.
    await openTab("Incidents");
    await page.waitForSelector('[data-testid="incidents"]');
    const inc = await page.evaluate(() => ({
      text: document.body.innerText,
      overdue: document.querySelector('[data-testid="incident-i-over"] [data-testid="badge-overdue"]')?.textContent.trim(),
      live: document.querySelector('[data-testid="incident-i-live"] [data-testid="countdown"]')?.textContent.trim(),
      late: document.querySelector('[data-testid="incident-i-late"] [data-testid="badge-notified-late"]')?.textContent.trim(),
      overdueOnLive: !!document.querySelector('[data-testid="incident-i-live"] [data-testid="badge-overdue"]'),
      steps: [...document.querySelectorAll('[data-testid="incident-checklist"] li')].length,
      disclaimer: document.querySelector('[data-testid="incident-disclaimer"]').textContent.trim(),
    }));
    assert.equal(inc.overdue, "Overdue", `${name}: overdue badge`);
    assert.match(inc.live, /^59h (29|30|28)m left$/, `${name}: countdown in hours and minutes (${inc.live})`);
    assert.equal(inc.late, "Notified late", `${name}: notified late`);
    assert.ok(!inc.overdueOnLive, `${name}: a running countdown is not overdue`);
    assert.equal(inc.steps, 6, `${name}: six checklist steps`);
    assert.equal(inc.disclaimer, INCIDENT_DISCLAIMER, `${name}: incident disclaimer`);
    assert.ok(inc.text.includes("All times shown in America/New_York"), `${name}: zone named`);
    assert.ok(inc.text.includes("Disk was encrypted."), `${name}: notes shown`);

    // Create: a time typed without an offset goes out as typed, with the zone beside the field.
    assert.ok(await clickExact("RECORD AN INCIDENT"));
    await page.waitForSelector('[data-testid="incident-form"]');
    assert.ok((await bodyText()).includes("Time in America/New_York"), `${name}: zone beside the time field`);
    await setVal("#inc-title", "Shared drive link left public");
    await setVal("#inc-severity", "high");
    await setVal("#inc-detected", "2026-10-15T09:30");
    await setVal("#inc-aware", "2026-10-15T10:45");
    assert.ok(await overflowOf() <= 0, `${name}: overflow with the incident form open`);
    const writesBefore = writes.length;
    await clickExact("RECORD INCIDENT", '[data-testid="incident-form"]');
    await page.waitForFunction(() => document.body.innerText.includes("Shared drive link left public"), { timeout: 5000 });
    const created = writes[writesBefore].body;
    assert.equal(created.detected_at, "2026-10-15T09:30:00", `${name}: sent as typed, no offset`);
    assert.equal(created.became_aware_at, "2026-10-15T10:45:00");
    assert.equal(created.title, "Shared drive link left public");
    assert.ok(!("notified_commission_at" in created), `${name}: unset times are not sent`);
    const shown = await page.evaluate(() => document.querySelector('[data-testid^="incident-i-new"]').innerText);
    assert.ok(shown.includes("15 Oct 2026 10:45"), `${name}: shown in the organisation's zone (${shown})`);

    // Edit: only changed fields go out; title and the awareness times are read-only; clearing sends null.
    assert.ok(await clickExact("EDIT", '[data-testid="incident-i-live"]'));
    await page.waitForSelector('[data-testid="incident-form"]');
    assert.equal(await page.evaluate(() => !!document.querySelector("#inc-title, #inc-detected, #inc-aware")), false, `${name}: immutable fields are not editable`);
    assert.equal(await page.evaluate(() => document.querySelector("#inc-subjects").value.length), 16, `${name}: prefilled from the zone's wall time`);
    await setVal("#inc-subjects", "");
    await setVal("#inc-commission", "2026-10-16T08:00");
    const before = writes.length;
    await clickExact("SAVE CHANGES", '[data-testid="incident-form"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="incident-i-live"] [data-testid="badge-notified"], [data-testid="incident-i-live"] [data-testid="badge-notified-late"]'), { timeout: 5000 });
    assert.deepEqual(writes[before].body, { notified_commission_at: "2026-10-16T08:00:00", notified_subjects_at: null }, `${name}: PATCH carries only the changes`);
    assert.match(writes[before].path, /\/compliance\/incidents\/i-live$/);
    assert.ok(await overflowOf() <= 0, `${name}: overflow in incidents`);
    await noVerdicts(`${name} incidents`);
    if (process.env.CYPHWARD_COMPLIANCE_SCREENSHOTS === "1") await page.screenshot({ path: `/tmp/compliance-incidents-${name}.png`, fullPage: true });

    // Packs: list, issue, download; supporting-evidence notice; no verdict language.
    await openTab("Packs");
    await page.waitForSelector('[data-testid="packs"]');
    const pk = await page.evaluate(() => ({ rows: document.querySelectorAll('[data-testid="pack-list"] li').length,
      notice: document.querySelector('[data-testid="packs-notice"]')?.textContent || "",
      retention: document.querySelector('[data-testid="packs-retention"]')?.textContent || "",
      row: document.querySelector('[data-testid="pack-list"] li')?.textContent || "" }));
    assert.equal(pk.rows, 1, `${name}: the issued pack is listed`);
    assert.ok(/36 months/.test(pk.retention) && /names of answer owners/i.test(pk.retention), `${name}: packs show the retention period and the owner-name disclosure`);
    assert.ok(/kept until/i.test(pk.row), `${name}: each pack shows when it becomes eligible for removal`);
    assert.ok(/not a compliance audit return/i.test(pk.notice), `${name}: packs say they are not a Compliance Audit Return`);
    const beforePack = writes.length;
    await page.evaluate(() => document.querySelector('[data-testid="issue-dpo_section"]').click());
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="pack-list"] li').length === 2, { timeout: 5000 });
    assert.equal(writes[beforePack].body.kind, "dpo_section", `${name}: issue sends the kind`);
    assert.ok(/^ui-/.test(writes[beforePack].body.request_key || ""), `${name}: each click carries its own request key`);
    assert.deepEqual(Object.keys(writes[beforePack].body).sort(), ["kind", "request_key"], `${name}: issue sends only the kind and the key`);
    await page.evaluate(() => document.querySelector('[data-testid="download-pdf"]').click());
    for (let waited = 0; waited < 3000 && !downloads.some((d) => d.endsWith("/pdf")); waited += 100) await new Promise((r) => setTimeout(r, 100));
    assert.ok(downloads.some((d) => d.endsWith("/pdf")), `${name}: the PDF is fetched with the session`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow in packs`);
    await noVerdicts(`${name} packs`);
  }

  // The countdown runs on its own and flips to Overdue when the deadline passes.
  reset();
  await page.setViewport({ width: 1440, height: 900 });
  await gotoComply();
  await openTab("Incidents");
  await page.waitForSelector('[data-testid="incident-i-live"] [data-testid="countdown"]');
  await page.evaluate(() => { const real = Date.now.bind(Date); window.__skew = 0; Date.now = () => real() + window.__skew; });
  await page.evaluate((h) => { window.__skew = h; }, 2 * HOUR);
  await page.waitForFunction(() => /^57h (2\d|30)m left$/.test(document.querySelector('[data-testid="incident-i-live"] [data-testid="countdown"]')?.textContent.trim() || ""), { timeout: 5000 });
  await page.evaluate((h) => { window.__skew = h; }, 61 * HOUR);
  await page.waitForFunction(() => document.querySelector('[data-testid="incident-i-live"] [data-testid="badge-overdue"]'), { timeout: 5000 });
  await page.evaluate(() => { window.__skew = 0; });

  // ---------------- C3: members see everything and can change nothing ----------------
  role = "member";
  for (const [name, width] of [["desktop", 1440], ["small-mobile", 320]]) {
    reset();
    await page.setViewport({ width, height: 900 });
    await gotoComply();
    await openTab("Answer questions");
    await page.waitForSelector('[data-testid="questionnaire"]');
    const q = await page.evaluate(() => ({
      buttons: [...document.querySelectorAll("button")].map((b) => b.textContent.trim()),
      forms: document.querySelectorAll("form, input, select, textarea").length,
      note: !!document.querySelector('[data-testid="read-only-note"]'),
      told: document.querySelectorAll('[data-testid="told-us"]').length,
    }));
    assert.ok(q.note && q.told >= 1, `${name}: members see the answers read-only`);
    assert.equal(q.forms, 0, `${name}: no form controls rendered for a member (questions)`);
    assert.ok(!q.buttons.some((b) => /^(ANSWER|UPDATE ANSWER|SAVE ANSWER)$/.test(b)), `${name}: no answer buttons`);
    // Evidence files: a member sees the list and can download, but can neither attach nor remove.
    assert.ok(await clickExact("2. Data protection officer", 'nav[aria-label="Question groups"]'));
    await page.waitForSelector('[data-testid="file-ef-old"]');
    const mf = await page.evaluate(() => ({
      buttons: [...document.querySelectorAll('[data-testid="file-ef-old"] button')].map((b) => b.textContent.trim()),
      inputs: document.querySelectorAll('input[type="file"], [data-testid^="file-input-"]').length,
      attach: [...document.querySelectorAll("button")].some((b) => /ATTACH EVIDENCE|REMOVE/.test(b.textContent)),
    }));
    assert.deepEqual(mf.buttons, ["DOWNLOAD"], `${name}: members can only download`);
    assert.equal(mf.inputs, 0, `${name}: no file input for a member`);
    assert.equal(mf.attach, false, `${name}: no attach or remove for a member`);
    assert.ok(await clickExact("1. What applies to you", 'nav[aria-label="Question groups"]'));
    await openTab("Incidents");
    await page.waitForSelector('[data-testid="incidents"]');
    const i = await page.evaluate(() => ({
      buttons: [...document.querySelectorAll("button")].map((b) => b.textContent.trim()),
      forms: document.querySelectorAll("form, input, select, textarea").length,
      rows: document.querySelectorAll('[data-testid^="incident-i-"]').length,
      overdue: !!document.querySelector('[data-testid="badge-overdue"]'),
    }));
    assert.equal(i.rows, 3, `${name}: members see the incidents`);
    assert.ok(i.overdue, `${name}: members see the overdue badge`);
    assert.equal(i.forms, 0, `${name}: no form controls rendered for a member (incidents)`);
    assert.ok(!i.buttons.some((b) => /EDIT|RECORD/.test(b)), `${name}: no incident write buttons`);
    await openTab("Packs");
    await page.waitForSelector('[data-testid="packs"]');
    const mp = await page.evaluate(() => ({ rows: document.querySelectorAll('[data-testid="pack-list"] li').length,
      issue: [...document.querySelectorAll("button")].some((b) => /ISSUE/.test(b.textContent)),
      note: !!document.querySelector('[data-testid="read-only-note"]'),
      download: !!document.querySelector('[data-testid="download-pdf"]') }));
    assert.ok(mp.rows === 1 && mp.download && mp.note && !mp.issue, `${name}: members download packs but cannot issue`);
    await noVerdicts(`${name} member packs`);
    assert.equal(writes.length, 0, `${name}: members send no writes`);
    assert.ok(await overflowOf() <= 0, `${name}: member overflow`);
    await noVerdicts(`${name} member`);
  }


  // ---------------- C5: documents (owners/admins, then members, then Starter) ----------------
  const docKinds = ["privacy_policy", "cookie_notice", "breach_response_plan", "retention_schedule"];
  const docCard = (kind) => `[data-testid="doc-${kind}"]`;
  const statusOf = (kind) => page.evaluate((k) => document.querySelector(`[data-testid="doc-status-${k}"]`)?.textContent.trim().toUpperCase(), kind);
  const stubClipboard = () => page.evaluate(() => {
    window.__copied = [];
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (t) => { window.__copied.push(t); } } });
  });
  role = "admin";
  plan = "growth";
  for (const [name, width] of [["desktop", 1440], ["mobile", 390], ["small-mobile", 320]]) {
    reset();
    await page.setViewport({ width, height: 900 });
    await gotoComply();
    await openTab("Documents");
    await page.waitForSelector('[data-testid="documents"]');
    const d = await page.evaluate(() => ({
      disclaimer: document.querySelector('[data-testid="documents-disclaimer"]').textContent,
      quota: document.querySelector('[data-testid="doc-quota"]').textContent,
      cards: document.querySelectorAll('section[aria-label="Documents"] > ul > li').length,
    }));
    assert.ok(d.disclaimer.startsWith(DOC_LABEL), `${name}: documents disclaimer leads with the label`);
    assert.ok(d.disclaimer.includes("does not change your readiness page"), `${name}: approval does not touch readiness`);
    assert.equal(d.quota, "3 of 10 drafts used today", `${name}: quota line`);
    assert.equal(d.cards, 4, `${name}: four documents`);
    assert.deepEqual(await Promise.all(docKinds.map(statusOf)), ["DRAFT", "NOT GENERATED", "APPROVED", "DRAFT"], `${name}: statuses`);
    assert.ok((await bodyText()).includes("Your answers have changed since this version"), `${name}: stale note`);
    assert.ok(await overflowOf() <= 0, `${name}: documents overflow`);

    // View: banner, highlighted placeholders, label as the first line, copy and download.
    assert.ok(await clickExact("VIEW", docCard("privacy_policy")));
    await page.waitForSelector('[data-testid="doc-viewer"]');
    const v = await page.evaluate(() => ({
      banner: document.querySelector('[data-testid="doc-banner"]').textContent,
      text: document.querySelector('[data-testid="doc-text"]').textContent,
      marks: [...document.querySelectorAll('[data-testid="placeholder"]')].map((m) => m.textContent),
      buttons: [...document.querySelectorAll('[data-testid="doc-viewer"] button')].map((b) => b.textContent.trim()),
    }));
    assert.ok(v.banner.startsWith(DOC_LABEL), `${name}: banner`);
    assert.ok(v.text.startsWith(DOC_LABEL), `${name}: label is the first line of the text`);
    assert.deepEqual(v.marks, ["[MISSING: name of your data protection officer]", "[MISSING: how long you keep each kind of personal data]"], `${name}: placeholders highlighted`);
    for (const b of ["COPY TEXT", "COPY MARKDOWN", "DOWNLOAD TEXT", "DOWNLOAD MARKDOWN", "APPROVE THIS VERSION"]) assert.ok(v.buttons.includes(b), `${name}: ${b}`);
    await stubClipboard();
    await clickExact("COPY TEXT", '[data-testid="doc-viewer"]');
    await clickExact("COPY MARKDOWN", '[data-testid="doc-viewer"]');
    const copied = await page.evaluate(() => window.__copied);
    assert.ok(copied[0].startsWith(DOC_LABEL) && !copied[0].includes("# "), `${name}: text copy keeps the label, drops heading marks`);
    assert.ok(copied[1].startsWith(DOC_LABEL) && copied[1].includes("# Privacy policy of Acme Traders"), `${name}: markdown copy`);
    assert.ok(await overflowOf() <= 0, `${name}: viewer overflow`);
    await noVerdicts(`${name} documents`);

    // Approve: confirmation says what it does not mean, then the approver and date show.
    assert.ok(await clickExact("APPROVE THIS VERSION", '[data-testid="doc-viewer"]'));
    await page.waitForSelector('[data-testid="approve-confirm"]');
    assert.ok((await bodyText()).includes("does not mean the document is published or in force"), `${name}: approval wording`);
    assert.ok(await clickExact("CONFIRM APPROVAL"));
    await page.waitForSelector('[data-testid="doc-approval"]', { timeout: 5000 });
    assert.match(await page.evaluate(() => document.querySelector('[data-testid="doc-approval"]').textContent), /^Approved by Compliance Review on \d/, `${name}: approver shown`);
    assert.equal(writes.filter((w) => w.path.endsWith("/approve")).length, 1, `${name}: one approval sent`);
    assert.equal(await statusOf("privacy_policy"), "APPROVED", `${name}: status moves to approved`);

    // Version history keeps the older approved version, which has no approve button.
    await page.evaluate(() => document.querySelector('[data-testid="doc-history-privacy_policy"]').setAttribute("open", ""));
    const history = await page.evaluate(() => document.querySelector('[data-testid="doc-history-privacy_policy"]').innerText);
    assert.ok(history.includes("Version 2") && history.includes("Version 1") && history.includes("approved by Ada Obi"), `${name}: history`);
    assert.ok(await clickExact("VIEW", '[data-testid="doc-history-privacy_policy"] li:last-child'));
    await page.waitForFunction(() => document.querySelector('[data-testid="doc-viewer"]')?.innerText.includes("an older version"), { timeout: 5000 });
    assert.ok(!(await page.evaluate(() => [...document.querySelectorAll('[data-testid="doc-viewer"] button')].some((b) => /APPROVE/.test(b.textContent)))), `${name}: no approve on an older version`);

    // Generate a new document: it appears as a draft and opens.
    assert.ok(await clickExact("GENERATE", docCard("cookie_notice")));
    await page.waitForFunction(() => document.querySelector('[data-testid="doc-status-cookie_notice"]')?.textContent.trim().toUpperCase() === "DRAFT", { timeout: 5000 });
    assert.equal(writes.filter((w) => w.path.endsWith("/generate")).length, 1, `${name}: one generate sent`);
    assert.equal(await page.evaluate(() => document.querySelector('[data-testid="doc-quota"]').textContent), "4 of 10 drafts used today", `${name}: quota moves`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow after generating`);
    await noVerdicts(`${name} documents after actions`);
  }

  role = "member";
  for (const [name, width] of [["desktop", 1440], ["mobile", 390], ["small-mobile", 320]]) {
    reset();
    await page.setViewport({ width, height: 900 });
    await gotoComply();
    await openTab("Documents");
    await page.waitForSelector('[data-testid="documents"]');
    assert.ok(await clickExact("VIEW", docCard("privacy_policy")));
    await page.waitForSelector('[data-testid="doc-viewer"]');
    const m = await page.evaluate(() => ({
      buttons: [...document.querySelectorAll("button")].map((b) => b.textContent.trim()),
      note: !!document.querySelector('[data-testid="read-only-note"]'),
      banner: !!document.querySelector('[data-testid="doc-banner"]'),
    }));
    assert.ok(m.note && m.banner, `${name}: members see the banner and the read-only note`);
    assert.ok(!m.buttons.some((b) => /^(GENERATE|GENERATE NEW VERSION|APPROVE THIS VERSION|CONFIRM APPROVAL)$/.test(b)), `${name}: no generate or approve buttons for a member`);
    assert.ok(m.buttons.includes("COPY TEXT") && m.buttons.includes("DOWNLOAD MARKDOWN"), `${name}: members can copy and download`);
    assert.equal(writes.length, 0, `${name}: members send no writes`);
    assert.ok(await overflowOf() <= 0, `${name}: member documents overflow`);
    await noVerdicts(`${name} member documents`);
  }

  role = "owner";
  plan = "starter";
  reset();
  await page.setViewport({ width: 390, height: 900 });
  await gotoComply();
  await openTab("Documents");
  await page.waitForSelector('[data-testid="growth-gate"]', { timeout: 5000 });
  assert.ok((await bodyText()).toUpperCase().includes("GROWTH PLAN"), "starter documents: upgrade prompt");
  assert.equal(writes.length, 0);
  plan = "growth";

  // ---------------- C3: Starter organisations get the upgrade treatment, not an error ----------------
  role = "owner";
  plan = "starter";
  reset();
  await page.setViewport({ width: 390, height: 900 });
  await gotoComply();
  for (const tabName of ["Answer questions", "Incidents", "Packs"]) {
    await openTab(tabName);
    await page.waitForSelector('[data-testid="growth-gate"]', { timeout: 5000 });
    const gate = await bodyText();
    assert.ok(gate.toUpperCase().includes("GROWTH PLAN") && gate.includes("SEE PLANS"), `starter ${tabName}: upgrade prompt`);
    assert.ok(!gate.includes("We couldn't load"), `starter ${tabName}: not an error`);
    assert.ok(await overflowOf() <= 0, `starter ${tabName}: overflow`);
  }
  assert.equal(writes.length, 0);

  assert.deepEqual(errors, [], "no page errors");
  console.log("compliance page, questionnaire, incidents, documents, read-only members and the Starter gate: desktop/390/320 passed");
} finally {
  await browser?.close();
  await server.close();
}
