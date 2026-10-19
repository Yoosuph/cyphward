// Reports and Domains against a stubbed API (the shared dialog, confirmations, states, toasts, touch targets).
// Desktop, 390px and 320px: empty / loading / error states with a retry, report preview and email dialogs
// (focus in, Esc, focus back, ask before discarding), confirmations for removing a domain or a monitored host and
// for shortening retention (Cancel is the default focus, one sentence on what cannot be undone), toasts, no
// horizontal overflow, 44px touch targets on phones and no verdict language.
import assert from "node:assert/strict";
import { createServer } from "vite";
import puppeteer from "puppeteer-core";
import { fileURLToPath } from "node:url";
import { BANNED, user, org, domain } from "./lib/compliance-fixtures.mjs";

const frontend = fileURLToPath(new URL("..", import.meta.url));
process.chdir(frontend);

const REPORT_HTML = `<div style="padding:16px"><h2>Security report for acme.ng</h2><p>Score 72 out of 100.</p><table style="width:900px"><tr><td>A wide table that must scroll inside the dialog</td></tr></table></div>`;
const freshReports = () => [
  { id: "r1", title: "Security report: acme.ng", status: "ready", summary: { score: 72 }, domain: "acme.ng", created_at: "2026-10-17T09:00:00Z", updated_at: "2026-10-17T09:00:00Z", html: null, integrity: "snapshot", integrity_label: "Frozen snapshot" },
];
const freshDomains = () => [
  { ...domain, verified_at: "2026-10-02T00:00:00Z" },
  { id: "d2", org_id: org.id, domain: "shop.acme.ng", verification_status: "pending", verification_token: "abc123", created_at: "2026-10-12T00:00:00Z" },
];

const server = await createServer({ root: frontend, server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
let browser;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || "/usr/bin/chromium", headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let reports = freshReports();
  let domains = freshDomains();
  let hosts = [{ id: "h1", hostname: "portal.acme.ng" }];
  let retention = 36;
  const writes = [];
  const flags = { failReads: new Set(), failWrites: false, delayMs: 0 };
  const reset = () => { reports = freshReports(); domains = freshDomains(); hosts = [{ id: "h1", hostname: "portal.acme.ng" }]; retention = 36; writes.length = 0; flags.failReads.clear(); flags.failWrites = false; flags.delayMs = 0; };
  const json = (r, status, body) => void r.respond({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) return url.origin === origin ? void request.continue() : void request.abort();
    const p = url.pathname;
    const method = request.method();
    if (p.endsWith("/auth/bootstrap")) return json(request, 200, { user, email_verified: true, memberships: [{ org: { ...org, plan: "growth", display_timezone: "Africa/Lagos" }, role: "owner", domains }] });
    if (p.includes("/notifications")) return json(request, 200, { notifications: [], unread_count: 0 });
    if (p.includes("/platform/")) return json(request, 403, { detail: "no" });
    const respond = (status, body) => (flags.delayMs && method === "GET" ? setTimeout(() => json(request, status, body), flags.delayMs) : json(request, status, body));
    if ((flags.failWrites && method !== "GET") || (method === "GET" && [...flags.failReads].some((k) => p.endsWith(k)))) return respond(500, { detail: "Internal Server Error" });
    if (method !== "GET") writes.push({ method, path: p, body: JSON.parse(request.postData() || "{}") });
    if (p.endsWith("/snapshots/retention")) {
      if (method === "PUT") retention = JSON.parse(request.postData() || "{}").months;
      return respond(200, { retention_months: retention, retention: `Issued records are kept for ${retention} months, then removed.` });
    }
    if (p.endsWith("/reports/send-email")) return respond(200, { success: true, message: "Report sent to the address you gave." });
    if (/\/reports\/[^/]+$/.test(p)) return respond(200, { report: { ...reports[0], html: REPORT_HTML } });
    if (p.endsWith("/reports")) return respond(200, { reports, total: reports.length });
    if (/\/domains\/[^/]+\/hosts\/[^/]+$/.test(p)) { hosts = hosts.filter((h) => !p.endsWith(h.id)); return respond(200, { removed: true }); }
    if (/\/domains\/[^/]+\/hosts$/.test(p)) return respond(200, { hosts });
    if (/\/domains\/[^/]+\/verify$/.test(p)) return respond(200, { status: "pending", message: "not yet", details: {} });
    if (/\/domains\/[^/]+$/.test(p) && method === "DELETE") { domains = domains.filter((d) => !p.endsWith(d.id)); return respond(200, {}); }
    if (p.endsWith("/domains")) return respond(200, domains);
    return respond(200, {});
  });
  await page.evaluateOnNewDocument((u) => {
    localStorage.setItem(`cyphward-tour-v1:${u.id}`, "done");
    localStorage.setItem("cyphward-session", JSON.stringify({ access_token: "t", refresh_token: "r", user: u, _expires_at: Date.now() + 864000000 }));
    localStorage.setItem("cyphward-welcome-sent", u.id);
    localStorage.setItem("cyphward-theme", "light");
    localStorage.setItem("cyphward-cookie-consent", "accepted");
  }, user);

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const bodyText = () => page.evaluate(() => document.body.innerText);
  const overflowOf = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  const clickExact = (text, scope = "body") => page.evaluate((t, sc) => {
    const el = [...(document.querySelector(sc) || document).querySelectorAll("button, a")].find((b) => !b.closest("[inert]") && b.textContent.replace(/\s+/g, " ").trim() === t);
    if (el) el.click();
    return !!el;
  }, text, scope);
  const noVerdicts = async (where) => {
    const lowered = (await bodyText()).toLowerCase();
    for (const phrase of BANNED) assert.ok(!lowered.includes(phrase), `${where}: verdict language "${phrase}"`);
  };
  const closed = () => page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 3000 });
  const toasts = () => page.evaluate(() => document.querySelector(".toasts")?.innerText || "");
  const activeTestId = () => page.evaluate(() => document.activeElement?.getAttribute("data-testid"));
  const go = async (route, ready) => {
    await page.goto(`${origin}${route}`, { waitUntil: "networkidle0" });
    if (ready) await page.waitForSelector(ready, { timeout: 8000 });
  };
  const smallTargets = () => page.evaluate(() => [...document.querySelectorAll('button, [role="tab"], select, input:not([type="radio"]):not([type="hidden"]), textarea, summary')]
    .filter((el) => el.getClientRects().length > 0 && !el.closest("[inert]") && !el.closest("aside, nav, .sidebar, .topbar, header.topbar, [aria-label='Mobile navigation']") )
    .map((el) => ({ el: `${el.tagName}#${el.id || el.getAttribute("aria-label") || el.getAttribute("data-testid") || el.textContent.trim().slice(0, 24)}`, h: Math.round(el.getBoundingClientRect().height) }))
    .filter((x) => x.h < 43));

  for (const [name, width] of [["desktop", 1440], ["mobile", 390], ["small-mobile", 320]]) {
    const phone = width < 700;
    await page.setViewport({ width, height: 860, hasTouch: phone, isMobile: phone });

    // ---------------- Reports ----------------
    reset();
    await go("/reports", "table");
    const list = await bodyText();
    assert.ok(list.includes("17 Oct 2026"), `${name}: report dates are in the organisation's zone`);
    assert.ok(await overflowOf() <= 0, `${name}: reports overflow`);
    await noVerdicts(`${name} reports`);

    // View: opens in the shared dialog, wide content scrolls inside it, Esc closes, focus returns to the button.
    await page.focus("table button");
    const viewSelector = await page.evaluate(() => { const b = document.activeElement; b.setAttribute("data-ux-opener", "1"); return '[data-ux-opener="1"]'; });
    await page.keyboard.press("Enter");
    await page.waitForSelector('[role="dialog"] [data-testid="report-preview"]', { timeout: 5000 });
    await sleep(450);
    const pv = await page.evaluate(() => {
      const d = document.querySelector('[role="dialog"]');
      const body = d.querySelector(".dialog-body");
      const r = d.getBoundingClientRect();
      return { label: document.getElementById(d.getAttribute("aria-labelledby"))?.textContent, inside: d.contains(document.activeElement), w: r.width, h: r.height, page: document.documentElement.scrollWidth - innerWidth, bodyX: body.scrollWidth - body.clientWidth };
    });
    assert.equal(pv.label, "Security report: acme.ng", `${name}: the preview is named by its title`);
    assert.ok(pv.inside, `${name}: focus is inside the preview`);
    assert.ok(pv.page <= 0 && pv.bodyX <= 0, `${name}: a wide report scrolls inside the dialog, not the page`);
    if (phone) assert.ok(Math.abs(pv.w - width) < 1 && Math.abs(pv.h - 860) < 1, `${name}: the preview is full screen (${pv.w}x${pv.h})`);
    await page.keyboard.press("Escape");
    await closed();
    await sleep(50);
    assert.equal(await page.evaluate((s) => document.activeElement === document.querySelector(s), viewSelector), true, `${name}: focus returns to the View button`);

    // Email: native form in the dialog; leaving it with input asks first; a send gives a toast; a failure gives a plain one.
    assert.ok(await clickExact("Email report"));
    await page.waitForSelector("#report-to");
    assert.equal(await page.evaluate(() => document.activeElement.id), "report-to", `${name}: focus starts on the first field`);
    await page.keyboard.type("board@acme.ng");
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 2, { timeout: 3000 });
    assert.ok(/discard your changes\?/i.test(await bodyText()), `${name}: Esc with typed input asks first`);
    assert.equal(await page.evaluate(() => document.activeElement.textContent.trim()), "Keep editing", `${name}: Keep editing is the default`);
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 1, { timeout: 3000 });
    assert.equal(await page.evaluate(() => document.querySelector("#report-to").value), "board@acme.ng", `${name}: the input is kept`);
    flags.failWrites = true;
    await page.evaluate(() => document.querySelector('button[type="submit"][form="report-email-form"]').click());
    await page.waitForFunction(() => document.querySelector(".toasts")?.innerText.includes("was not sent"), { timeout: 5000 });
    assert.ok(!/500|internal server|failed to dispatch/i.test(await toasts()), `${name}: the failure toast is plain`);
    flags.failWrites = false;
    await page.evaluate(() => document.querySelector('button[type="submit"][form="report-email-form"]').click());
    await page.waitForFunction(() => document.querySelector(".toasts")?.innerText.includes("Report sent"), { timeout: 5000 });
    await closed();
    assert.equal(writes.filter((w) => w.path.endsWith("/send-email")).length, 1, `${name}: one email sent`);
    if (phone) assert.deepEqual(await smallTargets(), [], `${name}: reports touch targets under 44px`);

    // Retention: shortening it asks, Cancel is the default focus and names what cannot be undone.
    await page.select("#retention-months", "24");
    await page.evaluate(() => [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save").click());
    await page.waitForSelector('[data-testid="confirm-dialog"]');
    assert.equal(await activeTestId(), "confirm-cancel", `${name}: Cancel is the default focus for shortening retention`);
    const ask = await page.evaluate(() => document.querySelector('[data-testid="confirm-dialog"]').innerText);
    assert.ok(/cannot be brought back/i.test(ask) && /shorten retention/i.test(ask), `${name}: retention confirmation (${ask})`);
    await page.click('[data-testid="confirm-cancel"]');
    await closed();
    assert.equal(writes.filter((w) => w.method === "PUT").length, 0, `${name}: cancelling changes nothing`);
    await page.evaluate(() => [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save").click());
    await page.waitForSelector('[data-testid="confirm-dialog"]');
    await page.click('[data-testid="confirm-ok"]');
    await page.waitForFunction(() => document.querySelector(".toasts")?.innerText.includes("Retention saved"), { timeout: 5000 });
    assert.equal(writes.filter((w) => w.method === "PUT").length, 1, `${name}: confirming saves it`);

    // Reports states.
    reset();
    reports = [];
    await go("/reports", '[data-testid="state-empty"]');
    assert.ok(/No reports yet/.test(await page.evaluate(() => document.querySelector('[data-testid="state-empty"]').innerText)), `${name}: empty reports`);
    assert.ok(await clickExact("Generate your first report"), `${name}: the empty state offers the action`);
    reset();
    flags.failReads.add("/reports");
    await go("/reports", '[data-testid="state-error"]');
    const rerr = await page.evaluate(() => document.querySelector('[data-testid="state-error"]').innerText);
    assert.ok(!/500|internal server|status/i.test(rerr) && /try again/i.test(rerr), `${name}: reports error is plain with a retry (${rerr})`);
    flags.failReads.clear();
    assert.ok(await clickExact("Try again"));
    await page.waitForSelector("table", { timeout: 5000 });
    flags.delayMs = 1200;
    await page.goto(`${origin}/reports`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="state-loading"]', { timeout: 6000 });
    await page.waitForSelector("table", { timeout: 8000 });
    flags.delayMs = 0;

    // ---------------- Domains ----------------
    reset();
    await go("/domains", "table");
    assert.ok(await overflowOf() <= 0, `${name}: domains overflow`);
    await noVerdicts(`${name} domains`);
    if (phone) assert.deepEqual(await smallTargets(), [], `${name}: domains touch targets under 44px`);

    // Removing a domain: Cancel first, one sentence on what cannot be undone, a toast after.
    await page.evaluate(() => { const b = document.querySelector('button[aria-label="Remove acme.ng"]'); b.focus(); b.click(); });
    await page.waitForSelector('[data-testid="confirm-dialog"]');
    assert.equal(await activeTestId(), "confirm-cancel", `${name}: Cancel is the default focus for removing a domain`);
    const dask = await page.evaluate(() => document.querySelector('[role="dialog"]').innerText);
    assert.ok(/remove acme\.ng\?/i.test(dask) && /cannot be undone/i.test(dask) && /remove domain/i.test(dask), `${name}: remove-domain confirmation (${dask})`);
    await page.keyboard.press("Escape");
    await closed();
    assert.equal(writes.filter((w) => w.method === "DELETE").length, 0, `${name}: Esc removes nothing`);
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("aria-label")), "Remove acme.ng", `${name}: focus returns to the Remove button`);
    await page.evaluate(() => document.querySelector('button[aria-label="Remove acme.ng"]').click());
    await page.waitForSelector('[data-testid="confirm-dialog"]');
    await page.click('[data-testid="confirm-ok"]');
    await page.waitForFunction(() => document.querySelector(".toasts")?.innerText.includes("acme.ng removed"), { timeout: 5000 });
    assert.equal(writes.filter((w) => w.method === "DELETE").length, 1, `${name}: one domain removed`);

    // Extra hosts: removing one asks too.
    reset();
    await go("/domains", "table");
    assert.ok(await clickExact("Extra hosts"));
    await page.waitForSelector('button[aria-label="Stop monitoring portal.acme.ng"]');
    await page.evaluate(() => document.querySelector('button[aria-label="Stop monitoring portal.acme.ng"]').click());
    await page.waitForSelector('[data-testid="confirm-dialog"]');
    assert.equal(await activeTestId(), "confirm-cancel", `${name}: Cancel is the default focus for removing a host`);
    await page.click('[data-testid="confirm-ok"]');
    await page.waitForFunction(() => document.querySelector(".toasts")?.innerText.includes("removed from monitoring"), { timeout: 5000 });

    // Add domain: leaving it with input asks first; a failure gives a plain toast.
    reset();
    await go("/domains", "table");
    assert.ok(await clickExact("Add domain"));
    await page.waitForSelector("#add-domain-name");
    await page.keyboard.type("newshop.ng");
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 2, { timeout: 3000 });
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 1, { timeout: 3000 });
    flags.failWrites = true;
    await page.evaluate(() => document.querySelector('button[type="submit"][form="add-domain-form"]').click());
    await page.waitForFunction(() => document.querySelector(".toasts")?.innerText.includes("was not added"), { timeout: 5000 });
    assert.ok(!/500|internal server/i.test(await toasts()), `${name}: add-domain failure is plain`);
    flags.failWrites = false;
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 2, { timeout: 3000 });
    assert.ok(await clickExact("Discard changes"));
    await closed();

    // How to verify opens in the dialog and gives focus back.
    await page.evaluate(() => document.querySelector('button[aria-label="How to verify shop.acme.ng"]').focus());
    await page.keyboard.press("Enter");
    await page.waitForSelector('[role="dialog"]');
    assert.ok(/how to verify your domain/i.test(await bodyText()), `${name}: verification steps in a dialog`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow with the verification dialog`);
    await page.keyboard.press("Escape");
    await closed();
    await sleep(50);
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("aria-label")), "How to verify shop.acme.ng", `${name}: focus returns to the button`);

    // Domains states.
    reset();
    domains = [];
    await go("/domains", '[data-testid="state-empty"]');
    assert.ok(/No domains yet/.test(await page.evaluate(() => document.querySelector('[data-testid="state-empty"]').innerText)), `${name}: empty domains`);
    reset();
    flags.failReads.add("/domains");
    await go("/domains", '[data-testid="state-error"]');
    const derr = await page.evaluate(() => document.querySelector('[data-testid="state-error"]').innerText);
    assert.ok(!/500|internal server|status/i.test(derr) && /try again/i.test(derr), `${name}: domains error is plain with a retry (${derr})`);
    flags.failReads.clear();
    assert.ok(await clickExact("Try again"));
    await page.waitForSelector("table", { timeout: 5000 });
    assert.ok(await overflowOf() <= 0, `${name}: domains states overflow`);
  }

  assert.deepEqual(errors, [], "no page errors");
  console.log("reports and domains: dialogs, confirmations, states, toasts, touch targets: desktop/390/320 passed");
} finally {
  await browser?.close();
  await server.close();
}
