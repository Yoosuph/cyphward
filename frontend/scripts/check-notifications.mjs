// Notifications phase 1 (components/NotificationBell.tsx, components/NotificationSettings.tsx). Every API call is
// answered from fixtures; nothing reaches a server.
//   - the bell: the unread count in the badge and in the accessible name; a 60-second poll is registered and a
//     focus or visibility change asks again
//   - the panel: newest first, grouped by day, read and unread states, mark read (one, then all), a link opens
//   - keyboard: Enter opens and moves focus into the panel, Tab reaches the items, Escape closes and returns focus
//   - Settings › Notifications: each category's in-app and email switches, saved at once; a failed save puts the
//     switch back with reviewed wording; ?tab=notifications&category= opens it at the row
//   - errors: a raw server body (500 traceback, 422 array) never reaches the screen, on the list, a mark or a save
//   - the owner console bell: count-only poll, list, mark read, the item opens the organisation
//   - the audit (no horizontal scroll, 44px targets on phones, labels, names, contrast, no claim wording) with the
//     panel open at 1440, 390 and 320
import assert from "node:assert/strict";
import { WIDTHS, audit, settle, sleep, startHarness } from "./lib/ui-refine-harness.mjs";

const RAW = "Traceback (most recent call last): psycopg.errors.UniqueViolation at notifications.py line 120";
const ORG_ID = "0a000000-0000-4000-8000-0000000000aa";
const hoursAgo = (h) => new Date(Date.now() - h * 3600_000).toISOString();
const daysAgo = (d) => { const x = new Date(); x.setDate(x.getDate() - d); x.setHours(9, 0, 0, 0); return x.toISOString(); };

function fixtures() {
  return [
    { id: "n1", kind: "finding_critical", category: "findings", severity: "critical", title: "Critical finding on shop.acme.ng",
      body: "A finding rated critical was recorded. Open Findings to see what each one is and how to fix it.", link: "/findings",
      count: 1, read_at: null, created_at: hoursAgo(0.2) },
    { id: "n2", kind: "asset_discovered", category: "scans", severity: "info", title: "3 new hosts found",
      body: "It was found on acme.ng during the latest scan. Review it on the Assets page.", link: "/assets", count: 3,
      read_at: null, created_at: hoursAgo(0.5) },
    { id: "n3", kind: "scan_failed", category: "scans", severity: "warning", title: "Scan did not finish for acme.ng",
      body: "The check ran out of time.", link: "/scans", count: 1, read_at: null, created_at: daysAgo(1) },
    { id: "n4", kind: "member_joined", category: "members", severity: "info", title: "Ada Bello joined the workspace",
      body: "Members and their roles are listed on the Team tab in Settings.", link: "/settings?tab=team", count: 1,
      read_at: daysAgo(2), created_at: daysAgo(3) },
  ];
}
const PREFS = [
  ["scans", "Scans", "A scan finished, did not finish, or found a new host."],
  ["findings", "Findings", "A finding was rated critical or high, came back, or was resolved."],
  ["billing", "Plan and trial", "Your trial or plan period ends in 7 days, and again the day before."],
  ["members", "Team members", "Someone was invited, joined or was removed."],
  ["organisation", "Organisation status", "Cyphward suspended this organisation or lifted the suspension."],
  ["compliance", "Compliance reminders", "A recorded answer expires within 30 days, or a report is due."],
].map(([category, label, hint]) => ({ category, label, hint, in_app: true, email: true }));

const h = await startHarness();
const problems = [];
let items = fixtures();
let prefs = PREFS.map((p) => ({ ...p }));
const net = { lists: 0, reads: [], readAll: 0, puts: [], ownerCounts: 0, ownerLists: 0, ownerReads: [] };
const fail = { list: null, read: null, put: null };
let countDelayMs = 0;  // the owner count route answers this much later (the busy-poll probe)
const page = (list) => ({ notifications: list, unread_count: list.filter((n) => !n.read_at).length, limit: 50, offset: 0, has_more: false });
let ownerItems = [{ ...fixtures()[0], id: "o1", org_id: ORG_ID, org_name: "Acme Traders", title: "Acme Traders: Critical finding on shop.acme.ng" }];

h.state.route = (p, method, request) => {
  if (p === "/api/v1/notifications" && method === "GET") { net.lists += 1; return fail.list || [200, page(items)]; }
  if (p === "/api/v1/notifications/read-all" && method === "POST") {
    net.readAll += 1; items = items.map((n) => ({ ...n, read_at: n.read_at || new Date().toISOString() }));
    return [200, { message: "All notifications marked as read.", marked: 1 }];
  }
  let m = p.match(/^\/api\/v1\/notifications\/([^/]+)\/read$/);
  if (m && method === "PATCH") {
    net.reads.push(m[1]);
    if (fail.read) return fail.read;
    items = items.map((n) => (n.id === m[1] ? { ...n, read_at: n.read_at || new Date().toISOString() } : n));
    return [200, { notification: items.find((n) => n.id === m[1]) }];
  }
  if (p === "/api/v1/notifications/preferences" && method === "GET") return [200, { preferences: prefs }];
  m = p.match(/^\/api\/v1\/notifications\/preferences\/([a-z_]+)$/);
  if (m && method === "PUT") {
    const body = JSON.parse(request.postData() || "{}");
    net.puts.push({ category: m[1], body });
    if (fail.put) return fail.put;
    prefs = prefs.map((x) => (x.category === m[1] ? { ...x, ...body } : x));
    return [200, { preference: prefs.find((x) => x.category === m[1]) }];
  }
  if (p === "/api/v1/owner/notifications/unread-count") {
    net.ownerCounts += 1;
    const answer = [200, { unread_count: ownerItems.filter((n) => !n.read_at).length }];
    return countDelayMs ? new Promise((resolve) => setTimeout(() => resolve(answer), countDelayMs)) : answer;
  }
  if (p === "/api/v1/owner/notifications" && method === "GET") { net.ownerLists += 1; return [200, page(ownerItems)]; }
  m = p.match(/^\/api\/v1\/owner\/notifications\/([^/]+)\/read$/);
  if (m && method === "POST") {
    net.ownerReads.push(m[1]);
    ownerItems = ownerItems.map((n) => (n.id === m[1] ? { ...n, read_at: new Date().toISOString() } : n));
    return [200, { notification: ownerItems[0] }];
  }
  if (p === `/api/v1/owner/organizations/${ORG_ID}`) return [200, { organization: { id: ORG_ID, name: "Acme Traders", plan: "growth", suspended: false }, members: [], domains: [], subscriptions: [], invoices: [], scans: [], open_findings: [], activity: [], owner_actions: [], plans: [] }];
  return undefined;
};

const check = (label, r) => {
  for (const key of ["small", "unlabelled", "nameless", "noRing", "lowContrast", "bannedHits"]) {
    if (r[key]?.length) problems.push(`${label}: ${key} ${JSON.stringify(r[key].slice(0, 6))}`);
  }
  if (r.overflow > 0) problems.push(`${label}: horizontal overflow ${r.overflow}px`);
};

async function open(route, { width = 1440, height = 900, theme = "dark" } = {}) {
  const tab = await h.newPage({ theme });
  await tab.page.evaluateOnNewDocument(() => {
    window.__intervals = [];
    window.__ticks = [];
    const orig = window.setInterval.bind(window);
    window.setInterval = (fn, ms, ...rest) => {
      window.__intervals.push(ms);
      if (ms === 60000) window.__ticks.push(fn);  // the bell's poll, run on demand below
      return orig(fn, ms, ...rest);
    };
  });
  await tab.page.setViewport({ width, height });
  await tab.page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
  await settle(tab.page, 500);
  return tab;
}
const text = (pg) => pg.evaluate(() => document.body.innerText);
const badge = (pg) => pg.$eval('[data-testid="notif-count"]', (e) => e.textContent).catch(() => null);
const bellLabel = (pg) => pg.$eval('[data-testid="notif-bell"]', (e) => e.getAttribute("aria-label"));
const tick = (pg) => pg.evaluate(() => { for (const fn of window.__ticks) fn(); });
const states = (pg) => pg.$$eval('[data-testid="notif-item"]', (els) => els.map((e) => `${e.dataset.id}:${e.dataset.read}`));

try {
  // 1. The bell: count, accessible name, polling.
  {
    const { page: pg, close } = await open("/overview");
    await pg.waitForSelector('[data-testid="notif-bell"]');
    await settle(pg, 300);
    assert.equal(await badge(pg), "3", "three unread");
    assert.equal(await bellLabel(pg), "Notifications, 3 unread");
    assert.ok((await pg.evaluate(() => window.__intervals)).includes(60000), "a 60-second poll is registered");
    const before = net.lists;
    await pg.evaluate(() => window.dispatchEvent(new Event("focus")));
    await settle(pg, 300);
    assert.ok(net.lists > before, "focus asks again");
    const afterFocus = net.lists;
    await pg.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await settle(pg, 300);
    assert.ok(net.lists > afterFocus, "coming back to the tab asks again");
    const beforeTick = net.lists;
    await tick(pg);
    await settle(pg, 300);
    assert.ok(net.lists > beforeTick, "the 60-second poll asks for the newest page and its count");

    // 2. The panel: grouped by day, read and unread states, mark read, mark all read.
    await pg.click('[data-testid="notif-bell"]');
    await pg.waitForSelector('[data-testid="notif-panel"]');
    await settle(pg, 300);
    assert.equal(await pg.$eval('[data-testid="notif-bell"]', (b) => b.getAttribute("aria-expanded")), "true");
    const days = await pg.$$eval('[data-testid="notif-panel"] .notif-day', (d) => d.map((x) => x.textContent));
    assert.deepEqual(days.slice(0, 2), ["Today", "Yesterday"], "grouped by day, newest first");
    assert.equal(days.length, 3);
    assert.deepEqual(await states(pg), ["n1:false", "n2:false", "n3:false", "n4:true"]);
    assert.match(await pg.$eval('[data-testid="notif-panel"]', (e) => e.innerText), /3 events/, "a grouped row shows its count");
    await pg.click('[data-testid="notif-item"][data-id="n2"] [data-testid="notif-mark"]');
    await settle(pg, 400);
    assert.deepEqual(net.reads, ["n2"]);
    assert.deepEqual(await states(pg), ["n1:false", "n2:true", "n3:false", "n4:true"]);
    assert.equal(await badge(pg), "2");
    await pg.click('[data-testid="notif-read-all"]');
    await settle(pg, 400);
    assert.equal(net.readAll, 1);
    assert.equal(await badge(pg), null, "no badge when nothing is unread");
    assert.equal(await bellLabel(pg), "Notifications, none unread");
    // Opening an item follows its in-app link.
    await pg.click('[data-testid="notif-item"][data-id="n3"] .notif-open');
    await settle(pg, 400);
    assert.equal(new URL(pg.url()).pathname, "/scans");
    assert.equal(await pg.$('[data-testid="notif-panel"]'), null, "the panel closes when an item opens");
    await close();
  }

  // 3. Keyboard only.
  {
    items = fixtures();
    const { page: pg, close } = await open("/overview");
    await pg.waitForSelector('[data-testid="notif-bell"]');
    await pg.focus('[data-testid="notif-bell"]');
    await pg.keyboard.press("Enter");
    await pg.waitForSelector('[data-testid="notif-panel"]');
    await settle(pg, 200);
    assert.equal(await pg.evaluate(() => document.activeElement?.className), "notif-title", "focus moves into the panel");
    const stops = [];
    for (let i = 0; i < 5; i++) {
      await pg.keyboard.press("Tab");
      stops.push(await pg.evaluate(() => document.activeElement?.closest('[data-testid="notif-panel"]') ? document.activeElement.className.split(" ")[0] || document.activeElement.tagName : "outside"));
    }
    assert.ok(stops.includes("notif-open") && stops.includes("notif-tool"), `Tab reaches the items and their marks: ${stops}`);
    // Focus stays inside the open panel: many Tabs, then Shift+Tab from the heading, never leave it.
    for (let i = 0; i < 25; i++) {
      await pg.keyboard.press("Tab");
      assert.ok(await pg.evaluate(() => Boolean(document.activeElement?.closest('[data-testid="notif-panel"]'))), `Tab ${i} stayed inside`);
    }
    await pg.focus('[data-testid="notif-panel"] .notif-title');
    await pg.keyboard.down("Shift"); await pg.keyboard.press("Tab"); await pg.keyboard.up("Shift");
    assert.ok(await pg.evaluate(() => Boolean(document.activeElement?.closest('[data-testid="notif-panel"]'))), "Shift+Tab wraps inside");
    await pg.keyboard.press("Escape");
    await settle(pg, 200);
    assert.equal(await pg.$('[data-testid="notif-panel"]'), null, "Escape closes");
    assert.equal(await pg.evaluate(() => document.activeElement?.dataset.testid), "notif-bell", "focus returns to the bell");
    await close();
  }

  // 4. Settings › Notifications: the switches.
  {
    const { page: pg, close } = await open("/settings?tab=notifications&category=findings");
    await pg.waitForSelector('[data-testid="notif-settings-panel"]');
    await settle(pg, 300);
    assert.equal(await pg.$eval("#settings-tab-notifications", (t) => t.getAttribute("aria-selected")), "true", "the link opens the tab");
    assert.equal(await pg.$$eval('[data-testid="notif-pref"]', (r) => r.length), 6);
    assert.ok(await pg.$('[data-testid="notif-pref"][data-category="findings"].is-focus'), "the linked category is highlighted");
    const note = await pg.$eval('[data-testid="notif-settings-panel"]', (e) => e.innerText);
    assert.match(note, /critical alerts, such as a critical finding or a suspension, and for compliance reminders/);
    assert.ok(!/only for critical/i.test(note), "the email note does not overstate what is emailed");
    const sw = (cat, ch) => `[data-testid="notif-pref"][data-category="${cat}"] [data-testid="notif-switch-${ch}"]`;
    await pg.click(sw("findings", "in_app"));
    await settle(pg, 300);
    assert.deepEqual(net.puts.at(-1), { category: "findings", body: { in_app: false } });
    assert.equal(await pg.$eval(sw("findings", "in_app"), (b) => b.getAttribute("aria-checked")), "false");
    // Keyboard: Space toggles a focused switch.
    await pg.focus(sw("scans", "email"));
    await pg.keyboard.press("Space");
    await settle(pg, 300);
    assert.deepEqual(net.puts.at(-1), { category: "scans", body: { email: false } });
    // A failed save puts the switch back and shows reviewed wording only.
    fail.put = [500, { detail: RAW }];
    await pg.click(sw("members", "in_app"));
    await settle(pg, 400);
    assert.equal(await pg.$eval(sw("members", "in_app"), (b) => b.getAttribute("aria-checked")), "true", "reverted");
    const t = await text(pg);
    assert.match(t, /That setting could not be saved\. Nothing was changed\./);
    assert.ok(!t.includes("Traceback") && !t.includes("psycopg"), "no raw text");
    fail.put = null;
    await close();
  }

  // 5. Errors never show raw text.
  {
    items = fixtures();
    fail.list = [500, { detail: RAW }];
    const { page: pg, close } = await open("/overview");
    await pg.waitForSelector('[data-testid="notif-bell"]');
    await pg.click('[data-testid="notif-bell"]');
    await pg.waitForSelector('[data-testid="notif-error"]');
    let t = await text(pg);
    assert.match(t, /Notifications could not be loaded\. Try again in a moment\./);
    assert.ok(!t.includes("Traceback") && !t.includes("psycopg"));
    fail.list = [422, { detail: [{ loc: ["query", "limit"], msg: RAW, type: "value_error" }] }];
    await pg.click('[data-testid="notif-error"] button');
    await settle(pg, 300);
    t = await text(pg);
    assert.ok(!t.includes("Traceback") && !t.includes("value_error"));
    fail.list = null;
    await pg.click('[data-testid="notif-error"] button');
    await pg.waitForSelector('[data-testid="notif-item"]');
    fail.read = [500, { detail: RAW }];
    await pg.click('[data-testid="notif-item"][data-id="n1"] [data-testid="notif-mark"]');
    await settle(pg, 400);
    t = await text(pg);
    assert.match(t, /That could not be marked as read\. Try again in a moment\./);
    assert.ok(!t.includes("Traceback"));
    fail.read = null;
    await close();
  }

  // 6. The owner console bell.
  {
    const { page: pg, close } = await open("/admin");
    await pg.waitForSelector('[data-testid="notif-bell"]');
    await settle(pg, 300);
    assert.ok(net.ownerCounts >= 1 && net.ownerLists === 0, "closed, the console polls a count only");
    assert.equal(await badge(pg), "1");
    await pg.click('[data-testid="notif-bell"]');
    await pg.waitForSelector('[data-testid="notif-item"]');
    assert.equal(net.ownerLists, 1);
    assert.match(await pg.$eval('[data-testid="notif-panel"]', (e) => e.innerText), /Acme Traders: Critical finding/);
    // With the panel open, the poll, a focus and a visibility change ask for the count only, never the list
    // (the list is audited and counts as activity; the count route does neither).
    const counts = net.ownerCounts;
    for (let i = 0; i < 3; i++) {
      await tick(pg);
      await pg.evaluate(() => { window.dispatchEvent(new Event("focus")); document.dispatchEvent(new Event("visibilitychange")); });
      await settle(pg, 200);
    }
    assert.equal(net.ownerLists, 1, "the list is not polled while the panel is open");
    assert.ok(net.ownerCounts > counts, "the count is");
    await pg.click('[data-testid="notif-item"] .notif-open');
    await settle(pg, 400);
    assert.deepEqual(net.ownerReads, ["o1"]);
    assert.match(new URL(pg.url()).pathname, new RegExp(`/admin/organizations/${ORG_ID}$`), "opens the organisation");
    await close();
  }

  // 6b. Opening the owner panel while a count poll is still in flight still loads the list (it is queued, not
  //     dropped): the count route answers 1.2 s late, a focus starts a poll, then the bell is clicked at once.
  {
    ownerItems = [{ ...fixtures()[0], id: "o2", org_id: ORG_ID, org_name: "Acme Traders", title: "Acme Traders: Critical finding on shop.acme.ng" }];
    const { page: pg, close } = await open("/admin");
    await pg.waitForSelector('[data-testid="notif-bell"]');
    await settle(pg, 300);
    countDelayMs = 1200;
    const lists = net.ownerLists;
    await pg.evaluate(() => window.dispatchEvent(new Event("focus")));
    await sleep(100);
    await pg.click('[data-testid="notif-bell"]');
    await pg.waitForSelector('[data-testid="notif-item"]', { timeout: 6000 });
    assert.equal(net.ownerLists, lists + 1, "the list loaded once, after the in-flight poll");
    assert.ok(!(await text(pg)).includes("Loading…"), "the panel is not left loading");
    countDelayMs = 0;
    await close();
  }

  // 7. The audit with the panel open, at every width, both themes for the phone sizes.
  for (const [name, width, height] of WIDTHS) {
    for (const theme of name === "1440" ? ["dark"] : ["dark", "light"]) {
      items = fixtures();
      for (const route of ["/overview", "/admin"]) {
        const { page: pg, close } = await open(route, { width, height, theme });
        await pg.waitForSelector('[data-testid="notif-bell"]');
        await pg.click('[data-testid="notif-bell"]');
        await pg.waitForSelector('[data-testid="notif-item"]');
        await sleep(200);
        const r = await audit(pg, { mobile: width < 900, tabStops: 0 });
        check(`${route} ${name} ${theme} (panel open)`, r);
        const rect = await pg.$eval('[data-testid="notif-panel"]', (e) => { const b = e.getBoundingClientRect(); return { left: b.left, right: b.right, vw: window.innerWidth }; });
        if (rect.left < 0 || rect.right > rect.vw) problems.push(`${route} ${name}: panel outside the viewport ${JSON.stringify(rect)}`);
        await close();
      }
      const { page: pg, close } = await open("/settings?tab=notifications", { width, height, theme });
      await pg.waitForSelector('[data-testid="notif-pref"]');
      check(`settings notifications ${name} ${theme}`, await audit(pg, { mobile: width < 900, tabStops: 0 }));
      await close();
    }
  }

  assert.deepEqual(problems, []);
  console.log("notifications: bell count, polling, panel (days, read states, mark read, mark all), keyboard, settings switches, owner bell, raw-text errors, 1440/390/320 audits passed");
} finally {
  await h.close();
}
