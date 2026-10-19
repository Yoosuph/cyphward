// Screenshot capture for the UX review (docs/ux-2026-10-19). Not a test: it serves the app, answers the API
// with fixtures and saves one PNG per screen at desktop and 390 wide.
//   OUT_DIR=../docs/ux-2026-10-19/before node scripts/capture-ux-screens.mjs
// Steps that cannot find their control are logged and skipped, so the same script runs against old and new code.
import { createServer } from "vite";
import puppeteer from "puppeteer-core";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  user, org, domain, overview, members, freshQuestions, freshIncidents, incidentView, CHECKLIST, INCIDENT_DISCLAIMER,
  freshDocuments, docsListing, draftText, DOC_TITLES, DOC_LABEL, DISCLAIMER, ORG_ZONE,
} from "./lib/compliance-fixtures.mjs";

const frontend = fileURLToPath(new URL("..", import.meta.url));
process.chdir(frontend);
const outDir = path.resolve(process.env.OUT_DIR || "../docs/ux-2026-10-19/after");
await mkdir(outDir, { recursive: true });

const HOUR = 3600000;
const REPORT_HTML = `<div style="font-family:sans-serif;padding:16px"><h2>Security report for acme.ng</h2><p>Score 72 out of 100. Three open findings.</p>
<table style="width:900px"><tr><td>A wide table cell that should scroll inside the dialog, not the page</td></tr></table></div>`;
const reports = [
  { id: "r1", title: "Security report: acme.ng", status: "ready", summary: { score: 72 }, domain: "acme.ng", created_at: "2026-10-17T09:00:00Z", updated_at: "2026-10-17T09:00:00Z",
    html: REPORT_HTML, integrity: "snapshot", integrity_label: "Frozen snapshot" },
  { id: "r2", title: "Security report: acme.ng", status: "ready", summary: { score: 65 }, domain: "acme.ng", created_at: "2026-10-03T09:00:00Z", updated_at: "2026-10-03T09:00:00Z",
    html: REPORT_HTML, integrity: "legacy", integrity_label: "Legacy" },
];
const scans = [
  { id: "s1", domain: "acme.ng", status: "completed", score: 72, created_at: "2026-10-17T06:00:00Z", completed_at: "2026-10-17T06:18:00Z", findings_discovered: 9, current_stage: "completed",
    stage_progress: { discovery: { status: "completed", items: 5 }, dns: { status: "completed", items: 5 } } },
  { id: "s2", domain: "acme.ng", status: "failed", score: null, created_at: "2026-10-10T06:00:00Z", findings_discovered: 0, current_stage: "http",
    stage_progress: { http: { status: "failed", error: "Connection timed out" } } },
];

const server = await createServer({ root: frontend, server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
let browser;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || "/usr/bin/chromium", headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage();
  page.on("pageerror", (e) => console.log("  pageerror:", (e.stack||e.message).slice(0, 600)));
  const state = { overviewFails: false, packsEmpty: false, reportsEmpty: false, domainsEmpty: false, incidentsEmpty: false };
  const json = (r, status, body) => void r.respond({ status, contentType: "application/json", body: JSON.stringify(body) });
  const incidents = freshIncidents(Date.now());
  const documents = freshDocuments();
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) return url.origin === origin ? void request.continue() : void request.abort();
    const p = url.pathname;
    const method = request.method();
    if (p.endsWith("/auth/bootstrap")) return json(request, 200, { user, email_verified: true, memberships: [{ org: { ...org, plan: "growth" }, role: "owner", domains: [domain] }] });
    if (p.endsWith("/compliance/overview")) return state.overviewFails ? json(request, 500, { detail: "Internal Server Error" }) : json(request, 200, overview("growth"));
    if (p.endsWith("/compliance/questionnaire")) {
      const questions = freshQuestions();
      return json(request, 200, { disclaimer: DISCLAIMER, version: "v1", register_version: "x", display_timezone: "Africa/Lagos", answered: 1, questions });
    }
    if (p.includes("/compliance/documents")) {
      const one = p.match(/\/documents\/([^/]+)$/);
      if (one) {
        const d = documents.find((x) => x.id === one[1]);
        return json(request, 200, { ...d, title: DOC_TITLES[d.kind], label: DOC_LABEL, text: draftText(d.kind, d.version), is_latest: d.version === 2 });
      }
      return json(request, 200, docsListing(documents, 3));
    }
    if (p.includes("/compliance/incidents")) {
      const list = state.incidentsEmpty ? [] : incidents;
      return json(request, 200, { disclaimer: INCIDENT_DISCLAIMER, checklist: CHECKLIST, deadline_hours: 72, display_timezone: "Africa/Lagos", incidents: list.map((i) => incidentView(i, "Africa/Lagos", Date.now())) });
    }
    if (p.includes("/api/v1/packs")) {
      const packs = state.packsEmpty ? [] : [{ id: "p-old00000000", snapshot_id: "s-old00000000", kind: "readiness_pack", pack_version: "v1",
        issued_at: "2026-10-10T09:00:00Z", retain_until: "2029-10-10T09:00:00Z", issued_by: user.id, window_start: null, window_end: null, html_sha256: "a".repeat(64), pdf_sha256: "d".repeat(64) }];
      return json(request, 200, { packs, total: packs.length, notice: "Supporting evidence only.", retention_months: 36,
        retention: "Kept for 36 months from the day it is issued, and removed with your organisation. Names of answer owners recorded at the time stay in issued snapshots and packs." });
    }
    if (p.endsWith("/api/v1/members")) return json(request, 200, members);
    if (p.endsWith("/snapshots/retention")) return json(request, 200, { retention_months: 36, retention: "Issued records are kept for 36 months, then removed." });
    if (/\/reports\/[^/]+$/.test(p)) return json(request, 200, { report: reports.find((r) => p.endsWith(r.id)) });
    if (p.endsWith("/reports")) return json(request, 200, { reports: state.reportsEmpty ? [] : reports.map(({ html, ...r }) => ({ ...r, html: null })), total: 2 });
    if (p.endsWith("/domains")) return json(request, 200, state.domainsEmpty ? [] : [{ ...domain, verified_at: "2026-10-02T00:00:00Z" },
      { id: "d2", org_id: org.id, domain: "shop.acme.ng", verification_status: "pending", verification_token: "cyphward-verify=abc123", created_at: "2026-10-12T00:00:00Z" }]);
    if (p.endsWith("/scans")) return json(request, 200, scans);
    if (p.includes("/scans/")) return json(request, 200, { scan: scans[0], raw_results: [] });
    if (p.includes("/notifications")) return json(request, 200, { notifications: [], unread_count: 0 });
    if (p.includes("/platform/")) return json(request, 403, { detail: "no" });
    return json(request, 200, {});
  });
  await page.evaluateOnNewDocument((u) => {
    localStorage.setItem(`cyphward-tour-v1:${u.id}`, "done");
    localStorage.setItem("cyphward-session", JSON.stringify({ access_token: "t", refresh_token: "r", user: u, _expires_at: Date.now() + 864000000 }));
    localStorage.setItem("cyphward-welcome-sent", u.id);
    localStorage.setItem("cyphward-theme", "light");
    localStorage.setItem("cyphward-cookie-consent", "accepted");
  }, user);

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  /** Click the first button or link whose text matches, optionally inside a selector. */
  const click = (re, scope = "body") => page.evaluate((src, sc) => {
    const rx = new RegExp(src, "i");
    const root = document.querySelector(sc) || document;
    const el = [...root.querySelectorAll("button, a, [role=tab]")].find((b) => rx.test(b.textContent.replace(/\s+/g, " ").trim()));
    if (el) el.click();
    return !!el;
  }, re.source, scope);
  const settle = async (ms = 450) => { await page.waitForNetworkIdle({ idleTime: 250, timeout: 8000 }).catch(() => {}); await sleep(ms); };
  const tab = (label) => click(new RegExp(`^${label}$`, "i"), '[role="tablist"]');

  const screens = [
    ["comply-readiness", "/comply", async () => true],
    ["comply-readiness-expanded", "/comply", async () => click(/Email anti-spoofing records/), true],
    ["comply-error", "/comply", async () => true, false, { overviewFails: true }],
    ["comply-questions", "/comply", async () => { await tab("Answer questions"); await settle(); return click(/^ANSWER$/, '[data-testid="question-registration.major_importance"]'); }],
    ["comply-incidents", "/comply", async () => { await tab("Incidents"); return true; }],
    ["comply-incidents-empty", "/comply", async () => { await tab("Incidents"); return true; }, false, { incidentsEmpty: true }],
    ["comply-incident-new", "/comply", async () => { await tab("Incidents"); await settle(); return click(/RECORD AN INCIDENT|RECORD AN INCIDENT/); }],
    ["comply-incident-edit", "/comply", async () => { await tab("Incidents"); await settle(); return click(/^EDIT$|Edit/, '[data-testid="incident-i-live"]'); }],
    ["comply-packs", "/comply", async () => { await tab("Packs"); return true; }],
    ["comply-packs-empty", "/comply", async () => { await tab("Packs"); return true; }, false, { packsEmpty: true }],
    ["comply-documents", "/comply", async () => { await tab("Documents"); return true; }],
    ["comply-document-view", "/comply", async () => { await tab("Documents"); await settle(); return click(/^VIEW$|View/, '[data-testid="doc-privacy_policy"]'); }],
    ["reports-list", "/reports", async () => true],
    ["reports-empty", "/reports", async () => true, false, { reportsEmpty: true }],
    ["reports-preview", "/reports", async () => click(/^VIEW$/i, "main")],
    ["reports-email", "/reports", async () => click(/EMAIL REPORT|Email report/i)],
    ["scans-list", "/scans", async () => true],
    ["domains-list", "/domains", async () => true],
    ["domains-empty", "/domains", async () => true, false, { domainsEmpty: true }],
    ["domains-add", "/domains", async () => click(/ADD DOMAIN|Add a domain|ADD/i)],
  ];

  for (const [name, route, act, , flags] of screens) {
    if (process.env.ONLY && !name.includes(process.env.ONLY)) continue;
    Object.assign(state, { overviewFails: false, packsEmpty: false, reportsEmpty: false, domainsEmpty: false, incidentsEmpty: false }, flags || {});
    for (const [size, width, height] of [["desktop", 1440, 900], ["mobile", 390, 844]]) {
      await page.setViewport({ width, height });
      await page.goto(`${origin}${route}`, { waitUntil: "domcontentloaded" });
      await settle(700);
      const done = await act().catch((e) => { console.log(`  ! ${name}: ${e.message}`); return false; });
      await settle();
      if (!done) console.log(`  ! ${name} ${size}: control not found, saved the page as it is`);
      const isModal = await page.evaluate(() => !!document.querySelector('[role="dialog"], .modal-backdrop'));
      await page.screenshot({ path: path.join(outDir, `${name}-${size}.png`), fullPage: !isModal });
    }
    console.log(`captured ${name}`);
  }
} finally {
  await browser?.close();
  await server.close();
}
