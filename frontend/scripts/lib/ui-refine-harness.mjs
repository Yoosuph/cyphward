// Shared harness for the UI refinement pass (docs/ui-2026-10-25): serves the app with Vite, answers every API call
// with fixtures (no live account, no network) and audits a rendered page for the things the pass promised:
// no horizontal page scroll, 44px touch targets on phones, a label for every field, heading order, a visible
// focus ring on every Tab stop, WCAG AA text contrast and no claim wording.
import { createServer } from "vite";
import puppeteer from "puppeteer-core";
import { fileURLToPath } from "node:url";
import { BANNED, user, org, domain, overview as complianceOverview, members } from "./compliance-fixtures.mjs";

export const frontend = fileURLToPath(new URL("../..", import.meta.url));

/** Claim wording no rendered page may use: the compliance list plus the phrases named in the UI brief.
 *  ("certif" stays out: it would match "TLS certificate"; the Documents suite keeps that stricter list.) */
export const UI_BANNED = [...new Set([...BANNED, "compliance score", "meets the requirement", "passes audit"])];

const finding = (id, title, severity, category, extra = {}) => ({
  id, org_id: org.id, title, description: `${title}. Recorded from the last scan of acme.ng.`, severity, category,
  status: "open", hostname: "acme.ng", evidence: { record: "v=spf1 include:_spf.example ~all" }, remediation: "Review the record with the team that owns mail.",
  created_at: "2026-10-16T09:00:00Z", first_seen_at: "2026-10-09T09:00:00Z", last_seen_at: "2026-10-16T09:00:00Z", confidence: "confirmed", ...extra,
});
export const findings = [
  finding("f1", "Missing Email DMARC Authentication Policy", "critical", "DNS & Email Security"),
  finding("f2", "TLS certificate expires in 12 days", "high", "TLS & Certificates", { hostname: "shop.acme.ng" }),
  finding("f3", "Content-Security-Policy header not set", "medium", "HTTP Security Headers"),
  finding("f4", "Remote Desktop port 3389 reachable from the internet", "high", "Exposed Services", { hostname: "vpn.acme.ng" }),
  finding("f5", "Server banner reveals software version", "low", "HTTP Security Headers", { status: "acknowledged" }),
];
export const scans = [
  { id: "s1", domain: "acme.ng", status: "completed", score: 72, created_at: "2026-10-17T06:00:00Z", completed_at: "2026-10-17T06:18:00Z", findings_discovered: 9, current_stage: "completed",
    stage_progress: { discovery: { status: "completed", items: 5 }, dns: { status: "completed", items: 5 }, scoring: { status: "completed", scope: "organization" } } },
  { id: "s2", domain: "acme.ng", status: "failed", score: null, created_at: "2026-10-10T06:00:00Z", findings_discovered: 0, current_stage: "http",
    stage_progress: { http: { status: "failed", error: "Connection timed out" } } },
  { id: "s3", domain: "shop.acme.ng", status: "completed", score: 64, created_at: "2026-10-03T06:00:00Z", completed_at: "2026-10-03T06:22:00Z", findings_discovered: 6, current_stage: "completed",
    stage_progress: { scoring: { status: "completed", scope: "organization" } } },
];
const orgWithCounts = { ...org, plan: "growth", domains_count: 2, verified_domains_count: 1, display_timezone: "Africa/Lagos" };
export const overviewPayload = {
  organization: orgWithCounts, score: 72, max_score: 100, grade: "B", posture_label: "Fair", status_color: "warn", assessed: true,
  model: "cyphward-risk-v3", scope: "organization", risk_points: 84, trend: 7, trend_baseline_at: "2026-10-10T06:18:00Z",
  assessment: { scan_id: "s1", status: "completed", completed_at: "2026-10-17T06:18:00Z", coverage: { version: 1, state: "complete", evaluated_checks: 5 } },
  counts: { total_assets: 6, total_findings: 5, critical: 1, high: 2, medium: 1, low: 1, info: 0 },
  subscores: [], factors: [],
  recent_scans: scans.map((s) => ({ id: s.id, domain: s.domain, score: s.score, status: s.status, stage_progress: s.stage_progress, created_at: s.created_at })),
};
const reports = [
  { id: "r1", title: "Security report: acme.ng", status: "ready", summary: { score: 72 }, domain: "acme.ng", created_at: "2026-10-17T09:00:00Z", updated_at: "2026-10-17T09:00:00Z", html: null, integrity: "snapshot", integrity_label: "Frozen snapshot" },
  { id: "r2", title: "Security report: acme.ng", status: "ready", summary: { score: 65 }, domain: "acme.ng", created_at: "2026-10-03T09:00:00Z", updated_at: "2026-10-03T09:00:00Z", html: null, integrity: "legacy", integrity_label: "Legacy" },
];
const domains = [
  { ...domain, verified_at: "2026-10-02T00:00:00Z" },
  { id: "d2", org_id: org.id, domain: "shop.acme.ng", verification_status: "pending", verification_token: "cyphward-verify=abc123", created_at: "2026-10-12T00:00:00Z" },
];
const now = Math.floor(Date.parse("2026-10-25T09:00:00Z") / 1000);
const owner = {
  me: { email: "owner@example.test", expires_at: "2026-10-25T21:00:00Z", idle_minutes: 30 },
  overview: {
    as_of: now, queue_delay_seconds: 600,
    counts: { users_total: 128, users_7d: 9, users_30d: 31, orgs_total: 41, orgs_7d: 3, domains_verified: 52, domains_pending: 6, scans_24h: 37, scans_failed_24h: 2, scans_queued: 1, oldest_queued_seconds: 95, scans_running: 2, scans_lease_expired: 0 },
    signups_14d: [{ day: "2026-10-20", users: 3 }, { day: "2026-10-22", users: 5 }, { day: "2026-10-24", users: 1 }],
    subscriptions: [{ plan: "growth", status: "active", n: 12 }, { plan: "starter", status: "trialing", n: 7 }],
    invoices: [{ currency: "NGN", status: "paid", n: 14, amount_minor: 210000000 }],
    recent_activity: [
      { action: "scan.launch", org_name: "Acme Traders", user_email: "c1@example.test", created_at: "2026-10-25T08:40:00Z" },
      { action: "member.invite", org_name: "Kola Foods", user_email: "ops@kola.example", created_at: "2026-10-25T07:10:00Z" },
    ],
  },
  users: { total: 2, items: [
    { id: "u1", full_name: "Compliance Review", email: "c1@example.test", organizations: "Acme Traders", provider: "password", email_verified: true, authenticator: true, last_seen_at: "2026-10-25T08:00:00Z", active_sessions: 1, created_at: "2026-10-01T00:00:00Z" },
    { id: "u2", full_name: null, email: "ops@kola.example", organizations: "Kola Foods", provider: "google", email_verified: false, last_seen_at: null, created_at: "2026-10-20T00:00:00Z" },
  ] },
};

export const AUTH_PAGES = [
  ["overview", "/overview"], ["scans", "/scans"], ["findings", "/findings"], ["compliance", "/comply"],
  ["settings", "/settings"], ["reports", "/reports"],
];
export const PUBLIC_PAGES = [["landing", "/"], ["login", "/login"], ["signup", "/signup"]];
export const OWNER_PAGES = [["owner-console", "/admin"], ["owner-users", "/admin/users"]];
export const WIDTHS = [["1440", 1440, 900], ["390", 390, 844], ["320", 320, 720]];

/** Starts Vite and a headless Chromium. `state.failures` turns matching API paths into 500s to show error states;
 *  `state.empty` makes list endpoints return nothing to show empty states. */
export async function startHarness() {
  process.chdir(frontend);
  const server = await createServer({ root: frontend, server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  const browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || "/usr/bin/chromium", headless: true, args: ["--no-sandbox"] });
  const state = { failures: new Set(), empty: false, failStatus: 500, failDetail: "Internal Server Error", route: null };
  const json = (r, status, body) => void r.respond({ status, contentType: "application/json", body: JSON.stringify(body) });

  async function newPage({ theme = "dark", signedIn = true, reducedMotion = true } = {}) {
    const ctx = await browser.createBrowserContext();
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    if (reducedMotion) await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
    await page.setRequestInterception(true);
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (!url.pathname.startsWith("/api/")) return url.origin === origin ? void request.continue() : void request.abort();
      const p = url.pathname;
      const method = request.method();
      if ([...state.failures].some((k) => p.endsWith(k))) return json(request, state.failStatus, { detail: state.failDetail });
      // A suite can answer its own endpoints first: state.route(path, method, request) -> [status, body] or undefined.
      const own = state.route?.(p, method, request);
      if (own) return json(request, own[0], own[1]);
      if (p.startsWith("/api/v1/owner")) {
        if (p.endsWith("/me")) return json(request, 200, owner.me);
        if (p.endsWith("/overview")) return json(request, 200, owner.overview);
        if (p.endsWith("/users")) return json(request, 200, state.empty ? { total: 0, items: [] } : owner.users);
        return json(request, 200, { items: [], total: 0 });
      }
      if (p.endsWith("/auth/bootstrap")) {
        if (!signedIn) return json(request, 401, { detail: "Not signed in" });
        return json(request, 200, { user, email_verified: true, memberships: [{ org: orgWithCounts, role: "owner", domains }] });
      }
      if (p.endsWith("/auth/demo-login")) return json(request, 200, { enabled: true });
      if (p.endsWith("/auth/google/client-id")) return json(request, 200, { client_id: null });
      if (p.includes("/notifications")) return json(request, 200, { notifications: [], unread_count: 0 });
      if (p.includes("/platform/")) return json(request, 403, { detail: "no" });
      if (p.endsWith("/overview") && !p.includes("/compliance")) return json(request, 200, overviewPayload);
      if (p.endsWith("/compliance/overview")) return json(request, 200, complianceOverview("growth"));
      if (p.endsWith("/api/v1/members")) return json(request, 200, members);
      if (p.endsWith("/members/invites")) return json(request, 200, []);
      if (p.endsWith("/findings")) {
        const list = state.empty ? [] : findings;
        return json(request, 200, { findings: list, total: list.length, categories: list.reduce((m, f) => ({ ...m, [f.category]: (m[f.category] || 0) + 1 }), {}) });
      }
      if (/\/findings\/[^/]+$/.test(p)) return json(request, 200, findings.find((f) => p.endsWith(f.id)) || findings[0]);
      if (p.endsWith("/assets")) return json(request, 200, { assets: [], total: 0 });
      if (p.endsWith("/scans")) return json(request, 200, state.empty ? [] : scans);
      if (/\/scans\/[^/]+$/.test(p)) return json(request, 200, { scan: scans.find((s) => p.endsWith(s.id)) || scans[0], raw_results: [] });
      if (p.endsWith("/reports")) return json(request, 200, state.empty ? { reports: [], total: 0 } : { reports, total: reports.length });
      if (/\/domains\/[^/]+\/hosts$/.test(p)) return json(request, 200, { hosts: [{ id: "h1", hostname: "portal.acme.ng" }] });
      if (p.endsWith("/domains")) return json(request, 200, domains);
      if (p.endsWith("/settings")) return json(request, 200, { organization: { ...orgWithCounts, cac_rc: "RC 1234567", sector: "Retail" }, membership: { role: "owner", user_id: user.id }, members });
      if (p.endsWith("/billing/subscription")) return json(request, 200, { subscription: { plan: "growth", status: "active", current_period_end: "2026-12-01T00:00:00Z" }, effective_status: "active", entitlements: { plan: "growth" }, provider: "manual", billing_mode: "manual_confirmation" });
      if (p.endsWith("/billing/invoices")) return json(request, 200, { invoices: [] });
      if (p.endsWith("/auth/mfa/status")) return json(request, 200, { enrolled: true, email_verified: true, totp_enrolled: false });
      if (p.endsWith("/snapshots/retention")) return json(request, 200, { retention_months: 36, retention: "Issued records are kept for 36 months, then removed." });
      if (p.endsWith("/remediation")) return json(request, 200, { tasks: [], total: 0 });
      if (p.endsWith("/ai/explain")) return json(request, 200, { title: "Missing Email DMARC Authentication Policy", severity: "critical", category: "DNS & Email Security",
        what_is_this: "Your domain has no DMARC record.", why_it_matters: "Others can send mail that looks like yours.", evidence_analysis: "No _dmarc TXT record was found.", what_happens_if_ignored: "Spoofed mail is harder to spot." });
      if (p.endsWith("/ai/remediate")) return json(request, 200, { title: "Publish a DMARC record", target_stack: "nginx", summary: "Start with p=none and review reports.", prerequisites: ["Know every service that sends mail for you."],
        steps: ["Add a TXT record at _dmarc.acme.ng.", "Review aggregate reports for two weeks."], code_snippet: "v=DMARC1; p=none; rua=mailto:dmarc@acme.ng", verification_command: "dig +short TXT _dmarc.acme.ng", estimated_time_minutes: 20 });
      if (method !== "GET") return json(request, 200, {});
      return json(request, 200, {});
    });
    await page.evaluateOnNewDocument((u, t, si) => {
      try {
        localStorage.setItem(`cyphward-tour-v1:${u.id}`, "done");
        if (si) localStorage.setItem("cyphward-session", JSON.stringify({ access_token: "t", refresh_token: "r", user: u, _expires_at: Date.now() + 864000000 }));
        localStorage.setItem("cyphward-welcome-sent", u.id);
        localStorage.setItem("cyphward-theme", t);
        localStorage.setItem("cyphward-cookie-consent", "accepted");
      } catch { /* about:blank */ }
    }, user, theme, signedIn);
    return { page, errors, close: () => ctx.close() };
  }

  return {
    origin, state, newPage,
    async close() { await browser.close(); await server.close(); },
  };
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export async function settle(page, ms = 500) {
  await page.waitForNetworkIdle({ idleTime: 250, timeout: 8000 }).catch(() => {});
  await sleep(ms);
}

/**
 * Audits the page as rendered. Returns plain data (lists of offenders) so the caller can assert or report.
 * `tabStops` walks the Tab order (from the top, then from the start of the page content) and checks each stop
 * draws a ring that is actually visible: an opaque outline, or a box-shadow with colour and blur/spread.
 */
export async function audit(page, { mobile = false, tabStops = 40 } = {}) {
  const base = await page.evaluate((banned, mobile) => {
    const visible = (el) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return false;
      const s = getComputedStyle(el);
      return s.visibility !== "hidden" && s.display !== "none" && Number(s.opacity) > 0.05;
    };
    const describe = (el) => {
      const t = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.id || el.className || "").toString().replace(/\s+/g, " ").trim();
      return `${el.tagName.toLowerCase()}:${t.slice(0, 40)}`;
    };
    const overflow = document.documentElement.scrollWidth - window.innerWidth;
    const interactive = [...document.querySelectorAll('a[href], button, input:not([type="hidden"]), select, textarea, summary, [role="button"], [role="tab"], [role="menuitem"], [role="switch"], [role="checkbox"]')].filter(visible);
    const small = [];
    if (mobile) {
      for (const el of interactive) {
        if (el.closest('[aria-hidden="true"], [inert]')) continue;
        const r = el.getBoundingClientRect();
        // Inline links inside running text are exempt (WCAG 2.5.8).
        const inlineText = el.tagName === "A" && getComputedStyle(el).display === "inline" && el.closest("p, li, td, label, small");
        if (inlineText) continue;
        if (el.type === "checkbox" || el.type === "radio") { const lab = el.closest("label") || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)); if (lab && lab.getBoundingClientRect().height >= 44) continue; }
        if (r.height < 43.5 || r.width < 43.5) small.push(`${describe(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
      }
    }
    const fields = [...document.querySelectorAll('input:not([type="hidden"]), select, textarea')].filter((el) => visible(el) || el.type === "checkbox" || el.type === "radio");
    const unlabelled = fields.filter((el) => {
      if (el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || el.getAttribute("title")) return false;
      if (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) return false;
      if (el.closest("label")) return false;
      return true;
    }).map(describe);
    const nameless = interactive.filter((el) => !(el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || el.getAttribute("title") || el.textContent.trim() || el.querySelector("img[alt]:not([alt=''])") || ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName))).map(describe);
    const heads = [...document.querySelectorAll("h1, h2, h3, h4, h5, h6")].filter(visible).map((h) => Number(h.tagName[1]));
    const skips = [];
    for (let i = 1; i < heads.length; i++) if (heads[i] > heads[i - 1] + 1) skips.push(`h${heads[i - 1]}→h${heads[i]}`);
    const h1 = heads.filter((h) => h === 1).length;
    // Text contrast (WCAG AA: 4.5:1, or 3:1 for 24px+ / 18.66px+ bold).
    const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const [r, g, b, a = 1] = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r, g, b, a }; };
    const lum = ({ r, g, b }) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
    const blend = (top, bottom) => ({ r: top.r * top.a + bottom.r * (1 - top.a), g: top.g * top.a + bottom.g * (1 - top.a), b: top.b * top.a + bottom.b * (1 - top.a), a: 1 });
    const bgOf = (el) => {
      const layers = [];
      for (let n = el; n; n = n.parentElement) {
        const s = getComputedStyle(n);
        if (s.backgroundImage && s.backgroundImage !== "none" && !/gradient/.test(s.backgroundImage)) return null;
        const c = parse(s.backgroundColor);
        if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
      }
      let out = parse(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
      for (let i = layers.length - 1; i >= 0; i--) out = blend(layers[i], out);
      return out;
    };
    const lowContrast = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set();
    while (walker.nextNode()) {
      const el = walker.currentNode.parentElement;
      if (!el || seen.has(el) || !walker.currentNode.textContent.trim()) continue;
      seen.add(el);
      if (!visible(el) || el.closest('[aria-hidden="true"], svg, .sr-only, [inert]')) continue;
      const s = getComputedStyle(el);
      if (Number(s.opacity) < 1 || el.closest("[disabled], [aria-disabled='true']")) continue;
      let fg = parse(s.color);
      const bg = bgOf(el);
      if (!fg || !bg) continue;
      if (fg.a < 1) fg = blend(fg, bg);
      const [L1, L2] = [lum(fg), lum(bg)].sort((a, b) => b - a);
      const ratio = (L1 + 0.05) / (L2 + 0.05);
      const size = parseFloat(s.fontSize);
      const large = size >= 24 || (size >= 18.66 && Number(s.fontWeight) >= 700);
      if (ratio < (large ? 3 : 4.5)) lowContrast.push(`${describe(el)} ${ratio.toFixed(2)}`);
    }
    // Landmarks and references: one <main>, never nested; every aria-controls names an element that exists.
    const mains = document.querySelectorAll("main").length;
    const landmarks = [];
    if (document.querySelectorAll("main main").length) landmarks.push("nested <main>");
    if (mains > 1) landmarks.push(`${mains} <main> elements`);
    for (const el of document.querySelectorAll("[aria-controls]")) {
      const missing = el.getAttribute("aria-controls").split(/\s+/).filter((id) => id && !document.getElementById(id));
      if (missing.length) landmarks.push(`${describe(el)} aria-controls → missing #${missing.join(", #")}`);
    }
    const text = document.body.innerText.toLowerCase();
    const bannedHits = banned.filter((w) => text.includes(w));
    return { overflow, small, unlabelled, nameless, skips, h1, lowContrast, bannedHits, landmarks, interactive: interactive.length };
  }, UI_BANNED, mobile);

  const noRing = [];
  if (tabStops > 0) {
    const seen = new Set();
    for (const from of ["body", "main, .page"]) {
      const ok = await page.evaluate((sel) => {
        document.activeElement?.blur?.();
        window.scrollTo(0, 0);
        const start = document.querySelector(sel);
        if (!start) return false;
        const probe = document.createElement("span");
        probe.tabIndex = -1;
        probe.setAttribute("data-audit-probe", "");
        start.prepend(probe);
        probe.focus({ preventScroll: true });
        return true;
      }, from);
      if (!ok) continue;
      for (let i = 0; i < tabStops; i++) {
        await page.keyboard.press("Tab");
        const r = await page.evaluate(() => {
          document.querySelectorAll("[data-audit-probe]").forEach((n) => { if (n !== document.activeElement) n.remove(); });
          const el = document.activeElement;
          if (!el || el === document.body) return null;
          const key = el.outerHTML.slice(0, 160);
          const opaque = (c) => { const m = (c || "").match(/rgba?\(([^)]+)\)/); if (!m) return false; const v = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return v.length < 4 || v[3] > 0.2; };
          const ringOf = (s) => {
            const outline = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 1 && opaque(s.outlineColor);
            const layers = (s.boxShadow || "none") === "none" ? [] : s.boxShadow.split(/,(?![^(]*\))/);
            const shadow = layers.some((l) => { const col = (l.match(/rgba?\([^)]+\)/) || [""])[0]; const nums = l.replace(col, "").trim().split(/\s+/).map(parseFloat); return opaque(col) && ((nums[2] || 0) > 0 || (nums[3] || 0) > 0); });
            return outline || shadow;
          };
          const s = getComputedStyle(el);
          const pseudo = ["::after", "::before"].some((p) => { const ps = getComputedStyle(el, p); return ps.content !== "none" && ringOf(ps); });
          const wrap = el.parentElement && el.parentElement.matches(":focus-within") && ringOf(getComputedStyle(el.parentElement));
          const t = (el.getAttribute("aria-label") || el.textContent || el.id || "").replace(/\s+/g, " ").trim().slice(0, 40);
          return { key, ok: ringOf(s) || pseudo || wrap, label: `${el.tagName.toLowerCase()}:${t}` };
        });
        if (!r) continue;
        if (seen.has(r.key)) break;
        seen.add(r.key);
        if (!r.ok) noRing.push(r.label);
      }
    }
  }
  return { ...base, noRing };
}
