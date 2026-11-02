// Shared pieces for the motion, skeleton and cache pass (docs/ui-motion-cache-2026-11-01): fixtures so every route
// has data to show, the route lists, and the measurement of one page load (did a skeleton paint before the data,
// was any frame blank, how much did the layout move when the data arrived).
// Synthetic data only: example.test addresses, made-up ids.
import { sleep } from "./ui-refine-harness.mjs";
import { OWNER_ROWS, CUSTOMER_ROWS } from "./owner-logs-fixture.mjs";
import { CHECKLIST, DISCLAIMER, INCIDENT_DISCLAIMER, ORG_ZONE, docsListing, freshDocuments, freshIncidents, freshQuestions, incidentView } from "./compliance-fixtures.mjs";

export const APP_ROUTES = [
  "/overview", "/assets", "/findings", "/scans", "/domains", "/remediation", "/reports", "/settings", "/comply", "/platform",
];
/** Compliance and settings subpages (tabs) reached by query string. */
export const APP_SUBROUTES = [
  "/comply?section=questions", "/comply?section=incidents", "/comply?section=packs", "/comply?section=documents", "/comply?section=reviewers",
  "/settings?tab=team", "/settings?tab=auth", "/settings?tab=notifications",
];
export const OWNER_ROUTES = [
  "/admin", "/admin/analytics", "/admin/organizations", "/admin/organizations/o1", "/admin/users", "/admin/users/u1",
  "/admin/subscriptions", "/admin/scans", "/admin/scans/sc1", "/admin/newsletter", "/admin/newsletter/n1", "/admin/logs", "/admin/system",
];

const ORG = { id: "o1", name: "Acme Traders Ltd", slug: "acme", plan: "growth", sector: "Retail", created_at: "2026-09-01T00:00:00Z", suspended: false };
const orgRow = (i) => ({ id: `o${i}`, name: ["Acme Traders Ltd", "Kola Foods", "Bello Logistics", "Delta Clinics"][i % 4], slug: `org${i}`, plan: i % 2 ? "starter" : "growth",
  billing: ["paid", "trialing", "free"][i % 3], subscription_status: "active", suspended: false, members: 1 + (i % 5), owner_email: `owner${i}@example.test`,
  domains: 2, domains_verified: 1, last_scan_at: "2026-10-28T09:00:00Z", last_scan_status: "completed", created_at: "2026-09-01T00:00:00Z" });
const userRow = (i) => ({ id: `u${i}`, email: `person${i}@example.test`, full_name: `Person ${i}`, memberships: [{ org_id: "o1", org_name: ORG.name, role: "owner" }],
  mfa: "authenticator", email_verified: true, last_sign_in_at: "2026-10-30T09:00:00Z", active_sessions: 1, created_at: "2026-09-01T00:00:00Z" });
const scanRow = (i) => ({ id: `sc${i}`, domain: `site${i}.example.test`, org_id: "o1", org_name: ORG.name, state: i % 4 ? "completed" : "failed",
  coverage_state: "complete", score: 60 + i, duration_seconds: 300 + i, created_at: "2026-10-30T09:00:00Z" });
const days = (n) => Array.from({ length: n }, (_, i) => new Date(Date.UTC(2026, 9, 31 - (n - 1) + i)).toISOString().slice(0, 10));
const issue = (id, status) => ({ id, subject: `Cyphward notes ${id}`, preview: "A product change and one security tip.", status, sendable: status === "draft",
  created_at: "2026-10-28T09:00:00Z", sent_at: status === "sent" ? "2026-10-29T09:00:00Z" : null, recipients: status === "sent" ? 120 : null,
  preview_html: "<!doctype html><html><body><p>Preview</p></body></html>", preview_text: "Preview", sources: [], sections: [], warnings: [] });

const ago = (d) => new Date(Date.UTC(2026, 9, 30 - d, 9)).toISOString();
/** Enough rows to fill a first screen, so the skeleton-to-content comparison is like for like. */
export const APP_FIXTURES = {
  assets: Array.from({ length: 10 }, (_, i) => ({ id: `a${i}`, org_id: "c1-org", hostname: `host${i}.acme.ng`, parent_domain: "acme.ng", ip_address: `203.0.113.${i + 10}`,
    asset_type: "Web Endpoint", status: "active", first_seen: ago(20), last_seen: ago(1), http_status: 200, technologies: [{ name: "nginx", version: "1.25" }],
    tls_info: { valid: true, issuer: "Let's Encrypt", days_remaining: 60 }, findings_count: i % 3, critical_findings_count: i % 5 === 0 ? 1 : 0 })),
  tasks: Array.from({ length: 8 }, (_, i) => ({ id: `t${i}`, finding_id: `f${i}`, finding_title: "Missing Email DMARC Authentication Policy", severity: "high",
    title: `Fix item ${i + 1}`, priority: "high", status: i % 2 ? "open" : "in_progress", due_date: "2026-11-20", created_at: ago(5), updated_at: ago(2), assignee_name: "Ada Obi" })),
  reports: Array.from({ length: 8 }, (_, i) => ({ id: `r${i}`, title: "Security report: acme.ng", status: "ready", summary: { score: 70 + i }, domain: "acme.ng",
    created_at: ago(i * 3), updated_at: ago(i * 3), html: null, integrity: "snapshot", integrity_label: "Frozen snapshot" })),
};

/** Answers the app lists, compliance tabs and owner endpoints the base harness leaves empty or short. */
export function ownerRoute(p) {
  // A platform-staff account (the only one that sees /platform in the navigation).
  if (p.endsWith("/platform/health")) return [200, { database: { connected: true, roundtrip_ms: 4 }, daily_scans_last_completed: "2026-10-31", scans_active: 2 }];
  if (p.endsWith("/api/v1/assets")) return [200, { assets: APP_FIXTURES.assets, total: APP_FIXTURES.assets.length }];
  if (p.endsWith("/api/v1/remediation")) return [200, { tasks: APP_FIXTURES.tasks, total: APP_FIXTURES.tasks.length }];
  if (p.endsWith("/api/v1/reports")) return [200, { reports: APP_FIXTURES.reports, total: APP_FIXTURES.reports.length }];
  if (p.endsWith("/compliance/questionnaire")) {
    const questions = freshQuestions();
    return [200, { disclaimer: DISCLAIMER, version: "ndpa-gaid-questionnaire-v1", register_version: "x", display_timezone: ORG_ZONE,
      answered: questions.filter((q) => q.answer_state !== "unanswered").length, questions }];
  }
  if (p.endsWith("/compliance/incidents")) return [200, { disclaimer: INCIDENT_DISCLAIMER, checklist: CHECKLIST, deadline_hours: 72, display_timezone: ORG_ZONE,
    incidents: freshIncidents(Date.now()).map((i) => incidentView(i, ORG_ZONE, Date.now())) }];
  if (p.endsWith("/compliance/documents")) return [200, docsListing(freshDocuments(), 1)];
  if (p.endsWith("/compliance/evidence-files")) return [200, { files: [], usage: { files: 0, bytes: 0 }, uploads_available: true,
    limits: { max_bytes: 10485760, max_files: 100, max_total_bytes: 524288000, extensions: ["pdf"], label: "x" } }];
  if (p.endsWith("/compliance/reviewer-grants")) return [200, { grants: [], activity: [], audit: [], note: "Reviewers see readiness evidence only.", can_grant: true,
    limits: { min_days: 1, default_days: 30, max_days: 90, purpose_max: 200 } }];
  if (p.endsWith("/api/v1/packs")) return [200, { packs: [], total: 0, notice: "Supporting evidence only. Not a Compliance Audit Return.", retention_months: 36, retention: "Kept for 36 months." }];
  if (!p.startsWith("/api/v1/owner") && !p.startsWith("/api/v1/newsletter")) return undefined;
  if (p.endsWith("/organizations")) return [200, { total: 12, items: Array.from({ length: 12 }, (_, i) => orgRow(i + 1)) }];
  if (/\/organizations\/[^/]+$/.test(p)) return [200, { organization: ORG, plans: ["starter", "growth"], removed_members: [],
    members: [{ id: "u1", email: "owner@acme.example.test", full_name: "Ada Owner", role: "owner", last_seen_at: "2026-10-28T09:00:00Z" }],
    domains: [{ id: "d1", domain: "acme.example.test", verification_status: "verified", verified_at: "2026-09-02T00:00:00Z" }],
    subscriptions: [{ plan: "growth", status: "active", current_period_end: "2026-11-30T00:00:00Z", provider: "manual" }], invoices: [],
    scans: [scanRow(1)], owner_actions: [], activity: [{ action: "scan.launched", user_email: "owner@acme.example.test", created_at: "2026-10-30T09:00:00Z" }],
    open_findings: [{ severity: "high", n: 2 }] }];
  if (p.endsWith("/users")) return [200, { total: 12, items: Array.from({ length: 12 }, (_, i) => userRow(i + 1)) }];
  if (/\/users\/[^/]+$/.test(p)) return [200, { user: { id: "u1", email: "person1@example.test", full_name: "Person 1", provider: "password",
    email_verified_at: "2026-09-01T00:00:00Z", created_at: "2026-09-01T00:00:00Z" }, remembered_browsers: 1,
    memberships: [{ org_id: "o1", org_name: ORG.name, role: "owner" }], sessions: [], activity: [] }];
  if (p.endsWith("/subscriptions")) return [200, { total: 6, invoices: [], items: Array.from({ length: 6 }, (_, i) => ({ id: `sub${i}`, org_id: "o1", org_name: orgRow(i).name,
    plan: "growth", status: "active", effective_status: "active", current_period_end: "2026-11-30T00:00:00Z", created_at: "2026-09-01T00:00:00Z" })) }];
  if (p.endsWith("/scans")) return [200, { queue_delay_seconds: 600, items: Array.from({ length: 10 }, (_, i) => scanRow(i + 1)) }];
  if (/\/scans\/[^/]+$/.test(p)) return [200, { scan: { ...scanRow(1), coverage: { state: "complete", evaluated_checks: 5, requested_checks: 5, missing: [] } },
    stages: [{ stage: "dns", status: "completed", duration_ms: 2000, items: 5 }, { stage: "http", status: "completed", duration_ms: 4000, items: 3 }], hosts: [] }];
  if (p.endsWith("/system")) return [200, { database: { ok: true, latency_ms: 4 }, deploy: { commit: "abc1234", service: "api" }, background: { scheduler: "running" },
    integrations: { email: true, ai: false }, scanner: { running: 1, queued: 0, last_scan_started_at: "2026-10-31T09:00:00Z", last_scan_completed_at: "2026-10-31T09:10:00Z" },
    scheduled_runs: [{ cron_name: "daily-scan", run_day: "2026-10-31", status: "completed", claimed_at: "2026-10-31T01:00:00Z", finished_at: "2026-10-31T01:20:00Z" }] }];
  if (p.endsWith("/analytics/summary")) return [200, { as_of: 1793000000, range_days: 30, since: "2026-10-01T00:00:00+00:00",
    organizations: { total: 41, new_in_range: 9, suspended: 1 }, billing: { paid: 12, trialing: 7, free: 22 },
    subscription_status: [{ status: "active", count: 12 }, { status: "trialing", count: 7 }],
    scans: { total: 120, queued: 1, running: 2, completed: 100, failed: 15, cancelled: 2, success_rate: 0.87, failure_rate: 0.13 }, users: { total: 128, new_in_range: 11 } }];
  if (p.endsWith("/analytics/timeseries")) return [200, { as_of: 1793000000, range_days: 30, truncated: false,
    scans_per_day: days(30).map((day, i) => ({ day, total: i % 3, completed: i % 3 === 2 ? 1 : 0, failed: i % 3 === 1 ? 1 : 0, cancelled: 0, queued: 0, running: 0 })),
    findings_per_day: days(30).map((day, i) => ({ day, critical: i % 5 === 0 ? 1 : 0, high: i % 4 === 0 ? 2 : 0, medium: 1, low: 0, info: 0 })) }];
  if (p.endsWith("/logs")) return [200, { source: "customer", items: CUSTOMER_ROWS.concat(OWNER_ROWS.slice(0, 0)), limit: 100, offset: 0 }];
  if (p.endsWith("/newsletter/drafts")) return [200, { confirmed_subscribers: 120, issues: [issue("n1", "draft"), issue("n2", "sent")] }];
  if (p.endsWith("/newsletter/stats")) return [200, { confirmed: 120, pending: 3, unsubscribed: 4 }];
  return undefined;
}

/** Installed before any page script: a buffered layout-shift observer and a frame sampler that records, for each
 *  animation frame until `window.__mcStop`, whether the content area showed real content, a skeleton, or nothing. */
export function installProbes() {
  window.__mc = { cls: 0, shifts: [], frames: [], start: performance.now() };
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (e.hadRecentInput) continue;
        window.__mc.cls += e.value;
        window.__mc.shifts.push({ t: Math.round(e.startTime), v: Number(e.value.toFixed(4)),
          nodes: (e.sources || []).map((s) => (s.node && s.node.nodeType === 1 ? `${s.node.tagName.toLowerCase()}.${String(s.node.className || "").split(" ").slice(0, 2).join(".")}` : "#text")).slice(0, 3) });
      }
    }).observe({ type: "layout-shift", buffered: true });
  } catch { /* unsupported */ }
  // Geometry of the content area: its height inside the first screen, where its first heading sits and the tops of
  // its outer bordered panels (a bordered box inside another bordered box is part of that panel).
  window.__mcGeom = (main) => {
    const r = main.getBoundingClientRect();
    const y = (n) => Math.round(n.getBoundingClientRect().top + window.scrollY);
    const h1 = main.querySelector("h1");
    const boxes = [];
    for (const n of main.querySelectorAll("div, section, article, table, aside, header")) {
      const b = n.getBoundingClientRect();
      if (b.height < 40 || b.width < 120 || b.top > window.innerHeight || b.bottom < 0) continue;
      const cs = getComputedStyle(n);
      if (parseFloat(cs.borderTopWidth) === 0 || cs.borderTopStyle === "none" || cs.display === "contents") continue;
      let inner = false;
      for (let a = n.parentElement; a && a !== main; a = a.parentElement) {
        const as = getComputedStyle(a);
        if (parseFloat(as.borderTopWidth) > 0 && as.borderTopStyle !== "none" && a.getBoundingClientRect().height >= 40) { inner = true; break; }
      }
      if (inner) continue;
      boxes.push(y(n));
      if (boxes.length >= 4) break;
    }
    return { fold: Math.round(Math.min(r.bottom, window.innerHeight) - Math.max(r.top, 0)), h1: h1 ? y(h1) : null, boxes: [...new Set(boxes)].sort((p, q) => p - q).slice(0, 3) };
  };
  const sample = () => {
    if (window.__mcStop) return;
    const main = document.querySelector("main#main") || document.querySelector("main");
    let kind = "none";
    if (main) {
      const busy = main.querySelector('[aria-busy="true"], [data-testid="state-loading"], .skeleton');
      const text = (main.innerText || "").replace(/\s+/g, " ").trim();
      kind = busy ? "skeleton" : text.length > 0 ? "content" : "blank";
    } else if (document.querySelector('.loading-screen, [role="status"][aria-busy="true"]')) {
      kind = "loader";
    }
    if (kind === "skeleton") window.__mc.skeleton = window.__mcGeom(main);
    const last = window.__mc.frames[window.__mc.frames.length - 1];
    if (!last || last.kind !== kind) window.__mc.frames.push({ t: Math.round(performance.now() - window.__mc.start), kind });
    requestAnimationFrame(sample);
  };
  requestAnimationFrame(sample);
}

/**
 * Loads one route cold with every data request held back by `delay` ms, and returns what the visitor saw:
 * the frame sequence, the CLS for the whole load and from the first skeleton frame, how far the panels moved when
 * the data replaced the skeleton, and the skeleton state itself (sideways scroll, control placeholders under 44px).
 */
export async function measureRoute(h, route, { width = 1440, height = 900, delay = 900, motion = false, shot = null, shotSkeleton = null } = {}) {
  const tab = await h.newPage({ reducedMotion: !motion });
  // Phones are emulated as touch devices (hover: none, coarse pointer), as on a real phone.
  await tab.page.setViewport({ width, height, isMobile: width < 768, hasTouch: width < 768 });
  await tab.page.evaluateOnNewDocument(installProbes);
  h.state.route = async (p) => {
    const own = ownerRoute(p);
    if (p.endsWith("/auth/bootstrap") || p.endsWith("/owner/me") || p.includes("/notifications")) return own;
    await sleep(delay);
    return own;
  };
  await tab.page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
  const seen = await tab.page.waitForSelector('main [aria-busy="true"], main .skeleton, main [data-testid="state-loading"]', { timeout: 6000 }).then(() => true, () => false);
  const skeleton = seen ? await tab.page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    smallControls: window.innerWidth <= 900
      ? [...document.querySelectorAll("main .sk-control")].map((n) => n.getBoundingClientRect()).filter((r) => r.width > 0 && r.height < 43.5).length : 0,
  })) : null;
  if (shotSkeleton && seen) {
    await sleep(250); // past the page-enter fade, so the picture shows the skeleton itself
    await tab.page.screenshot({ path: shotSkeleton, type: "jpeg", quality: 70 });
  }
  await tab.page.waitForNetworkIdle({ idleTime: 400, timeout: 15000 }).catch(() => {});
  await sleep(700);
  if (shot) await tab.page.screenshot({ path: shot, type: "jpeg", quality: 70 });
  const result = await tab.page.evaluate(() => {
    window.__mcStop = true;
    const m = window.__mc;
    const firstSkeleton = m.frames.find((f) => f.kind === "skeleton");
    const afterSkeleton = firstSkeleton ? m.shifts.filter((s) => s.t >= firstSkeleton.t).reduce((n, s) => n + s.v, 0) : m.cls;
    const main = document.querySelector("main#main") || document.querySelector("main");
    const done = main ? window.__mcGeom(main) : null;
    // For each of the first loaded panels, the distance to the nearest panel the skeleton drew: a skeleton with the
    // page's grid scores 0; one generic block standing in for several panels scores the distance to the next one.
    const near = (c) => Math.min(...m.skeleton.boxes.map((k) => Math.abs(c - k)));
    const jump = m.skeleton && done ? { h1: m.skeleton.h1 !== null && done.h1 !== null ? Math.abs(done.h1 - m.skeleton.h1) : null,
      fold: Math.abs(done.fold - m.skeleton.fold),
      panels: m.skeleton.boxes.length && done.boxes.length ? Math.max(...done.boxes.map(near)) : null,
      skeletonPanels: m.skeleton.boxes, contentPanels: done.boxes } : null;
    return { frames: m.frames, cls: Number(m.cls.toFixed(4)), clsAfterSkeleton: Number(afterSkeleton.toFixed(4)), shifts: m.shifts.slice(0, 8), jump,
      overflow: document.documentElement.scrollWidth - window.innerWidth };
  });
  h.state.route = null;
  await tab.close();
  return { ...result, skeleton, errors: tab.errors };
}
