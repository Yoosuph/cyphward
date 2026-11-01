// The bell's panel on phones and swipe to clear (docs/notifications-mobile-2026-11-01; components/NotificationBell.tsx,
// components/NotificationRow.tsx). Every API call is answered from fixtures; nothing reaches a server. Touches are
// real touch input sent through the DevTools protocol, so the page sees pointer events of type "touch".
//   - the sheet at 390 and 320 (customer and owner console): 16px gutter, no horizontal scroll, under the top bar,
//     header and close control visible and on top, list scrolls inside while the header stays, safe-area insets in
//     the rule; 1440 keeps the popover under the bell
//   - keyboard on a phone: focus enters the panel, Tab stays inside, Escape and the close control return to the bell
//   - swipe past the threshold clears the row, calls mark-read exactly once, announces "Notification cleared", and
//     the row stays gone after closing and reopening; a short swipe opens the row on Clear, and tapping it clears
//   - the Clear button with no gesture (keyboard and mouse); focus moves to the next row; a double press sends one
//   - the unread count drops only for an unread row; a failed mark puts the row back with reviewed wording
//   - reduced motion: the row does not slide and nothing animates, Clear shows at once
//   - a vertical gesture on a row scrolls the list and clears nothing
//   - the owner console bell does the same through its own route
//   - the audit (44px targets, labels, contrast, no claim wording, no overflow) mid-swipe and after a clear
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { UI_BANNED, audit, frontend, settle, sleep, startHarness } from "./lib/ui-refine-harness.mjs";

const RAW = "Traceback (most recent call last): psycopg.errors.UniqueViolation at notifications.py line 120";
const ORG_ID = "0a000000-0000-4000-8000-0000000000aa";
const hoursAgo = (h) => new Date(Date.now() - h * 3600_000).toISOString();
const daysAgo = (d) => { const x = new Date(); x.setDate(x.getDate() - d); x.setHours(9, 0, 0, 0); return x.toISOString(); };

// The new wording, read from the source it ships in, never uses claim language.
{
  const src = readFileSync(`${frontend}/src/lib/notifications.ts`, "utf8");
  const words = ["NOTIFY_CLEAR", "NOTIFY_CLEARED", "NOTIFY_CLOSE"].map((k) => {
    const m = src.match(new RegExp(`export const ${k} = '([^']+)'`));
    assert.ok(m, `${k} is defined`);
    return m[1];
  });
  assert.deepEqual(words, ["Clear", "Notification cleared", "Close notifications"]);
  for (const w of words) for (const b of UI_BANNED) assert.ok(!w.toLowerCase().includes(b), `"${w}" uses "${b}"`);
}

function fixtures(extra = 0) {
  const base = [
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
  for (let i = 0; i < extra; i++) {
    base.push({ id: `x${i}`, kind: "scan_completed", category: "scans", severity: "info", title: `Scan finished for host ${i + 1}.acme.ng`,
      body: "The results are on the Scans page.", link: "/scans", count: 1, read_at: daysAgo(4), created_at: daysAgo(4 + i) });
  }
  return base;
}
const ownerFixtures = () => [
  { ...fixtures()[0], id: "o1", org_id: ORG_ID, org_name: "Acme Traders", title: "Acme Traders: Critical finding on shop.acme.ng" },
  { ...fixtures()[2], id: "o2", org_id: ORG_ID, org_name: "Acme Traders", title: "Acme Traders: Scan did not finish" },
  { ...fixtures()[3], id: "o3", org_id: ORG_ID, org_name: "Acme Traders", title: "Acme Traders: a member joined" },
];

const h = await startHarness();
let items = fixtures();
let ownerItems = ownerFixtures();
const net = { reads: [], ownerReads: [] };
const fail = { read: null };
const page = (list) => ({ notifications: list, unread_count: list.filter((n) => !n.read_at).length, limit: 50, offset: 0, has_more: false });
const markIn = (list, id) => list.map((n) => (n.id === id ? { ...n, read_at: n.read_at || new Date().toISOString() } : n));

h.state.route = (p, method) => {
  if (p === "/api/v1/notifications" && method === "GET") return [200, page(items)];
  let m = p.match(/^\/api\/v1\/notifications\/([^/]+)\/read$/);
  if (m && method === "PATCH") {
    net.reads.push(m[1]);
    if (fail.read) return fail.read;
    items = markIn(items, m[1]);
    return [200, { notification: items.find((n) => n.id === m[1]) }];
  }
  if (p === "/api/v1/owner/notifications/unread-count") return [200, { unread_count: ownerItems.filter((n) => !n.read_at).length }];
  if (p === "/api/v1/owner/notifications" && method === "GET") return [200, page(ownerItems)];
  m = p.match(/^\/api\/v1\/owner\/notifications\/([^/]+)\/read$/);
  if (m && method === "POST") {
    net.ownerReads.push(m[1]);
    ownerItems = markIn(ownerItems, m[1]);
    return [200, { notification: ownerItems.find((n) => n.id === m[1]), changed: true }];
  }
  return undefined;
};

const problems = [];
const check = (label, r) => {
  for (const key of ["small", "unlabelled", "nameless", "lowContrast", "bannedHits"]) {
    if (r[key]?.length) problems.push(`${label}: ${key} ${JSON.stringify(r[key].slice(0, 6))}`);
  }
  if (r.overflow > 0) problems.push(`${label}: horizontal overflow ${r.overflow}px`);
};

async function open(route, { width = 390, height = 844, theme = "dark", reducedMotion = false, touch = true } = {}) {
  const tab = await h.newPage({ theme, reducedMotion });
  await tab.page.setViewport({ width, height, hasTouch: touch, isMobile: touch && width < 900 });
  await tab.page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
  await tab.page.waitForSelector('[data-testid="notif-bell"]');
  await settle(tab.page, 300);
  return tab;
}
async function openPanel(pg) {
  await pg.click('[data-testid="notif-bell"]');
  await pg.waitForSelector('[data-testid="notif-item"]');
  await sleep(200);
}
const ids = (pg) => pg.$$eval('[data-testid="notif-item"]', (els) => els.map((e) => e.dataset.id));
const badge = (pg) => pg.$eval('[data-testid="notif-count"]', (e) => e.textContent).catch(() => null);
const announced = (pg) => pg.$eval('[data-testid="notif-announce"]', (e) => e.textContent.trim()).catch(() => null);
const active = (pg) => pg.evaluate(() => {
  const el = document.activeElement;
  return { testid: el?.dataset?.testid || null, cls: el?.className || "", row: el?.closest('[data-testid="notif-item"]')?.dataset.id || null,
    inPanel: Boolean(el?.closest('[data-testid="notif-panel"]')) };
});
const row = (id) => `[data-testid="notif-item"][data-id="${id}"]`;

/** A one-finger drag that starts near the row's right end. `hold` leaves the finger down. */
async function drag(pg, id, dx, dy = 0, { steps = 10, hold = false } = {}) {
  const el = await pg.$(`${row(id)} .notif-swipe`);
  const b = await el.boundingBox();
  const x0 = b.x + b.width - 30;
  const y0 = b.y + Math.min(b.height / 2, 40);
  await pg.touchscreen.touchStart(x0, y0);
  for (let i = 1; i <= steps; i++) { await pg.touchscreen.touchMove(x0 + (dx * i) / steps, y0 + (dy * i) / steps); await sleep(16); }
  if (!hold) await pg.touchscreen.touchEnd();
}
const swipeState = (pg, id) => pg.$eval(row(id), (li) => {
  const s = getComputedStyle(li.querySelector(".notif-swipe"));
  return { state: li.dataset.swipe, transform: s.transform, duration: s.transitionDuration,
    action: Boolean(li.querySelector('[data-testid="notif-swipe-clear"]')) };
});

/** The sheet's geometry and what is drawn on top of its header and bottom edge. */
const sheetBox = (pg) => pg.$eval('[data-testid="notif-panel"]', (panel) => {
  const r = panel.getBoundingClientRect();
  const close = panel.querySelector('[data-testid="notif-close"]').getBoundingClientRect();
  const head = panel.querySelector(".notif-head");
  const body = panel.querySelector(".notif-body");
  const bar = document.querySelector("header.topbar").getBoundingClientRect();
  const at = (x, y) => document.elementFromPoint(x, y);
  return {
    left: r.left, right: window.innerWidth - r.right, top: r.top, bottom: r.bottom, vw: window.innerWidth, vh: window.innerHeight,
    barBottom: bar.bottom, overflow: document.documentElement.scrollWidth - window.innerWidth,
    sheet: panel.classList.contains("is-sheet"), inBody: panel.parentElement === document.body,
    position: getComputedStyle(panel).position,
    close: { left: close.left, right: close.right, top: close.top, bottom: close.bottom, w: close.width, h: close.height },
    closeOnTop: panel.querySelector('[data-testid="notif-close"]').contains(at(close.left + close.width / 2, close.top + close.height / 2)),
    bottomOnTop: panel.contains(at(r.left + r.width / 2, r.bottom - 4)),
    headFits: head.scrollWidth <= head.clientWidth,
    bodyScrolls: body.scrollHeight > body.clientHeight + 1, bodyOverflowY: getComputedStyle(body).overflowY,
  };
});

try {
  // 0. The sheet rule carries the safe-area insets on every side.
  {
    const { page: pg, close } = await open("/overview");
    const rule = await pg.evaluate(() => {
      for (const sheet of document.styleSheets) {
        let rules; try { rules = sheet.cssRules; } catch { continue; }
        for (const r of rules) if (r.selectorText === ".notif-panel.is-sheet") return r.cssText;
      }
      return "";
    });
    for (const side of ["top", "left", "right", "bottom"]) assert.ok(rule.includes(`env(safe-area-inset-${side}`), `the sheet respects safe-area-inset-${side}: ${rule}`);
    await close();
  }

  // 1. Geometry at 390 and 320, customer and owner, both themes at 320; 1440 keeps the popover.
  for (const [width, height, themes] of [[390, 844, ["dark"]], [320, 720, ["dark", "light"]]]) {
    for (const theme of themes) {
      for (const route of ["/overview", "/admin"]) {
        items = fixtures(10);
        ownerItems = [...ownerFixtures(), ...fixtures(10).slice(4).map((n) => ({ ...n, id: `o${n.id}`, org_id: ORG_ID, org_name: "Acme Traders" }))];
        const { page: pg, close } = await open(route, { width, height, theme });
        await openPanel(pg);
        const box = await sheetBox(pg);
        const where = `${route} ${width} ${theme}`;
        assert.ok(box.sheet && box.inBody && box.position === "fixed", `${where}: a fixed sheet in <body> ${JSON.stringify(box)}`);
        assert.ok(Math.abs(box.left - 16) <= 1 && Math.abs(box.right - 16) <= 1, `${where}: 16px gutter ${box.left}/${box.right}`);
        assert.equal(box.overflow, 0, `${where}: no horizontal scroll`);
        assert.ok(box.top >= box.barBottom && box.top - box.barBottom <= 12, `${where}: anchored under the top bar ${box.top} vs ${box.barBottom}`);
        assert.ok(box.bottom <= box.vh - 15, `${where}: ends 16px above the bottom ${box.bottom}/${box.vh}`);
        assert.ok(box.close.left >= box.left && box.close.right <= box.vw - 16 && box.close.top >= box.top, `${where}: close inside the sheet`);
        assert.ok(box.close.w >= 44 && box.close.h >= 44, `${where}: 44px close`);
        assert.ok(box.closeOnTop, `${where}: nothing covers the close control`);
        assert.ok(box.bottomOnTop, `${where}: nothing (dock, chat button) covers the sheet's bottom edge`);
        assert.ok(box.headFits, `${where}: the header fits its width`);
        assert.ok(box.bodyScrolls && box.bodyOverflowY === "auto", `${where}: the list scrolls inside the sheet`);
        // Scroll the list to its end: the header and close control stay where they were.
        await pg.$eval('[data-testid="notif-panel"] .notif-body', (b) => { b.scrollTop = b.scrollHeight; });
        await sleep(100);
        const after = await sheetBox(pg);
        assert.equal(after.close.top, box.close.top, `${where}: the close control stays put`);
        assert.ok(after.closeOnTop && after.overflow === 0, `${where}: still visible after scrolling the list`);
        assert.equal(await pg.evaluate(() => window.scrollY), 0, `${where}: the page itself did not scroll`);
        check(`${where} sheet`, await audit(pg, { mobile: true, tabStops: 0 }));
        await close();
      }
    }
  }
  {
    items = fixtures();
    const { page: pg, close } = await open("/overview", { width: 1440, height: 900, touch: false });
    await openPanel(pg);
    const box = await pg.$eval('[data-testid="notif-panel"]', (p) => ({ sheet: p.classList.contains("is-sheet"), inWrap: Boolean(p.closest(".notif-wrap")), position: getComputedStyle(p).position }));
    assert.deepEqual(box, { sheet: false, inWrap: true, position: "absolute" }, "1440 keeps the popover under the bell");
    // The Clear button works with a mouse too.
    await pg.click(`${row("n3")} [data-testid="notif-clear"]`);
    await settle(pg, 300);
    assert.ok(!(await ids(pg)).includes("n3"), "a mouse click on Clear clears");
    assert.deepEqual(net.reads, ["n3"]);
    net.reads = [];
    await close();
  }

  // 2. Keyboard on a phone: focus enters, Tab stays inside, Escape and the close control return to the bell.
  {
    items = fixtures();
    const { page: pg, close } = await open("/overview", { width: 320, height: 720 });
    await pg.focus('[data-testid="notif-bell"]');
    await pg.keyboard.press("Enter");
    await pg.waitForSelector('[data-testid="notif-item"]');
    await sleep(150);
    assert.equal((await active(pg)).cls, "notif-title", "focus moves into the sheet");
    for (let i = 0; i < 30; i++) {
      await pg.keyboard.press("Tab");
      assert.ok((await active(pg)).inPanel, `Tab ${i} stayed inside the sheet`);
    }
    await pg.keyboard.press("Escape");
    await sleep(150);
    assert.equal(await pg.$('[data-testid="notif-panel"]'), null, "Escape closes");
    assert.equal((await active(pg)).testid, "notif-bell", "focus returns to the bell");
    await pg.keyboard.press("Enter");
    await pg.waitForSelector('[data-testid="notif-close"]');
    await pg.focus('[data-testid="notif-close"]');
    await pg.keyboard.press("Enter");
    await sleep(150);
    assert.equal(await pg.$('[data-testid="notif-panel"]'), null, "the close control closes");
    assert.equal((await active(pg)).testid, "notif-bell", "and focus returns to the bell");
    // A tap inside the sheet (rendered outside the bell's wrapper) does not close it; a tap outside does.
    await openPanel(pg);
    await pg.click('[data-testid="notif-panel"] .notif-title');
    await sleep(150);
    assert.ok(await pg.$('[data-testid="notif-panel"]'), "a press inside the sheet keeps it open");
    await pg.mouse.click(160, 700);
    await sleep(150);
    assert.equal(await pg.$('[data-testid="notif-panel"]'), null, "a press outside closes it");
    await close();
  }

  // 3. Swipe to clear (motion allowed).
  {
    items = fixtures();
    net.reads = [];
    const { page: pg, close } = await open("/overview", { width: 390, height: 844 });
    assert.equal(await badge(pg), "3");
    await openPanel(pg);
    assert.equal(await pg.$eval(row("n2"), (li) => getComputedStyle(li).touchAction), "pan-y", "rows leave vertical panning to the browser");
    // Mid-swipe the row follows the finger and Clear shows behind it; the audit holds.
    await drag(pg, "n2", -60, 0, { hold: true });
    let s = await swipeState(pg, "n2");
    assert.equal(s.state, "dragging");
    assert.ok(s.action, "Clear is uncovered");
    assert.match(s.transform, /matrix\(1, 0, 0, 1, -(5\d|60)/, `the row slides with the finger: ${s.transform}`);
    check("390 mid-swipe", await audit(pg, { mobile: true, tabStops: 0 }));
    await pg.touchscreen.touchEnd();
    await sleep(300);
    s = await swipeState(pg, "n2");
    assert.equal(s.state, "revealed", "a short swipe leaves the row open on Clear");
    assert.equal(s.duration, "0.18s", "the row animates when motion is allowed");
    assert.deepEqual(net.reads, [], "opening on Clear marks nothing");
    // Tapping the open row closes it again rather than opening the item.
    await pg.tap(`${row("n2")} .notif-item-title`);
    await sleep(300);
    assert.equal((await swipeState(pg, "n2")).state, "idle", "a tap on the open row closes it");
    assert.equal(new URL(pg.url()).pathname, "/overview", "and does not open the item");
    // A full swipe clears it: gone, marked read once, count down by one, announced.
    await drag(pg, "n2", -240);
    await settle(pg, 300);
    assert.deepEqual(await ids(pg), ["n1", "n3", "n4"], "the swiped row is gone");
    assert.deepEqual(net.reads, ["n2"], "mark-read was called exactly once");
    assert.equal(await badge(pg), "2", "the unread count dropped by one");
    assert.equal(await announced(pg), "Notification cleared");
    assert.equal(new URL(pg.url()).pathname, "/overview", "the swipe did not open the item");
    // A short swipe then a tap on the uncovered Clear.
    await drag(pg, "n1", -70);
    await sleep(300);
    await pg.tap(`${row("n1")} [data-testid="notif-swipe-clear"]`);
    await settle(pg, 300);
    assert.deepEqual(await ids(pg), ["n3", "n4"]);
    assert.deepEqual(net.reads, ["n2", "n1"]);
    assert.equal(await badge(pg), "1");
    // Clearing a row that was already read leaves the unread count alone (the call is harmless).
    await drag(pg, "n4", -240);
    await settle(pg, 300);
    assert.deepEqual(await ids(pg), ["n3"]);
    assert.equal(await badge(pg), "1", "a read row does not change the count");
    assert.equal(net.reads.filter((x) => x === "n4").length, 1);
    check("390 after clears", await audit(pg, { mobile: true, tabStops: 0 }));
    // Close and reopen: cleared rows stay gone, and nothing more is sent.
    await pg.click('[data-testid="notif-close"]');
    await sleep(150);
    await openPanel(pg);
    assert.deepEqual(await ids(pg), ["n3"], "cleared rows stay hidden after the panel reopens");
    assert.equal(net.reads.length, 3, "no extra mark-read calls");
    assert.equal(await announced(pg), "", "a reopened panel has nothing stale to announce");
    await close();
  }

  // 4. The Clear button with no gesture: keyboard, focus, double press, failure.
  {
    items = fixtures();
    net.reads = [];
    const { page: pg, close } = await open("/overview", { width: 320, height: 720 });
    await openPanel(pg);
    await pg.focus(`${row("n1")} [data-testid="notif-clear"]`);
    await pg.keyboard.press("Enter");
    await settle(pg, 300);
    assert.deepEqual(await ids(pg), ["n2", "n3", "n4"], "Enter on Clear clears");
    assert.deepEqual(net.reads, ["n1"]);
    assert.equal(await badge(pg), "2");
    assert.equal(await announced(pg), "Notification cleared");
    const f = await active(pg);
    assert.ok(f.row === "n2" && f.cls === "notif-open", `focus moves to the next row: ${JSON.stringify(f)}`);
    assert.equal(await pg.$eval(`${row("n2")} [data-testid="notif-clear"]`, (b) => b.getAttribute("aria-label")), "Clear: 3 new hosts found");
    // Two presses in the same moment send one call.
    await pg.$eval(`${row("n2")} [data-testid="notif-clear"]`, (b) => { b.click(); b.click(); });
    await settle(pg, 300);
    assert.equal(net.reads.filter((x) => x === "n2").length, 1, "a double press marks read once");
    assert.equal(await badge(pg), "1");
    // A failed mark puts the row back, keeps the count and shows reviewed wording only.
    fail.read = [500, { detail: RAW }];
    await pg.click(`${row("n3")} [data-testid="notif-clear"]`);
    await settle(pg, 400);
    assert.ok((await ids(pg)).includes("n3"), "the row is back");
    assert.equal(await badge(pg), "1", "the count is unchanged");
    const t = await pg.evaluate(() => document.body.innerText);
    assert.match(t, /That could not be marked as read\. Try again in a moment\./);
    assert.ok(!t.includes("Traceback") && !t.includes("psycopg"), "no raw text");
    fail.read = null;
    // Clearing the last rows leaves the empty state and focus on the heading.
    await pg.click(`${row("n3")} [data-testid="notif-clear"]`);
    await settle(pg, 300);
    await pg.focus(`${row("n4")} [data-testid="notif-clear"]`);
    await pg.keyboard.press("Enter");
    await settle(pg, 300);
    assert.ok(await pg.$('[data-testid="notif-empty"]'), "the empty state shows");
    assert.equal((await active(pg)).cls, "notif-title", "focus goes to the heading when nothing is left");
    await close();
  }

  // 5. Reduced motion: no slide, no animation, Clear shows at once.
  {
    items = fixtures();
    net.reads = [];
    const { page: pg, close } = await open("/overview", { width: 390, height: 844, reducedMotion: true });
    await openPanel(pg);
    await drag(pg, "n2", -40, 0, { hold: true });
    let s = await swipeState(pg, "n2");
    assert.equal(s.transform, "none", "the row does not follow the finger");
    // (the app-wide reduced-motion rule sets every transition to 0.01ms, which reads back as 1e-05s)
    assert.ok(parseFloat(s.duration) <= 0.001, `no transition: ${s.duration}`);
    assert.ok(s.action, "Clear shows at once");
    await pg.touchscreen.touchEnd();
    await sleep(50);
    s = await swipeState(pg, "n2");
    assert.ok(s.state === "idle" && s.transform === "none", "a short swipe under reduced motion still does not slide");
    await drag(pg, "n2", -70);
    await sleep(50);
    s = await swipeState(pg, "n2");
    assert.ok(s.state === "revealed" && s.transform === "none" && s.action, `open on Clear without sliding: ${JSON.stringify(s)}`);
    check("390 reduced motion revealed", await audit(pg, { mobile: true, tabStops: 0 }));
    await drag(pg, "n2", -240);
    await settle(pg, 300);
    assert.ok(!(await ids(pg)).includes("n2"), "a full swipe still clears");
    assert.deepEqual(net.reads, ["n2"]);
    await close();
  }

  // 6. A vertical gesture on a row scrolls the list and clears nothing.
  {
    items = fixtures(10);
    net.reads = [];
    const { page: pg, close } = await open("/overview", { width: 320, height: 720 });
    await openPanel(pg);
    const before = await pg.$eval('[data-testid="notif-panel"] .notif-body', (b) => b.scrollTop);
    await drag(pg, "n2", -14, -220, { steps: 12 });
    await settle(pg, 300);
    const afterTop = await pg.$eval('[data-testid="notif-panel"] .notif-body', (b) => b.scrollTop);
    assert.ok(afterTop > before + 40, `the list scrolled (${before} -> ${afterTop})`);
    assert.ok((await ids(pg)).includes("n2"), "the row is still there");
    const s = await swipeState(pg, "n2");
    assert.ok(s.state === "idle" && !s.action, `nothing was uncovered: ${JSON.stringify(s)}`);
    assert.deepEqual(net.reads, [], "no mark-read call");
    await close();
  }

  // 7. The owner console bell: the same sheet and gestures, through its own route.
  {
    ownerItems = ownerFixtures();
    net.ownerReads = [];
    const { page: pg, close } = await open("/admin", { width: 320, height: 720 });
    assert.equal(await badge(pg), "2");
    await openPanel(pg);
    await drag(pg, "o1", -240);
    await settle(pg, 300);
    assert.deepEqual(await ids(pg), ["o2", "o3"], "the swiped owner row is gone");
    assert.deepEqual(net.ownerReads, ["o1"], "the owner mark-read route was called exactly once");
    assert.deepEqual(net.reads, [], "the customer route was not");
    assert.equal(await badge(pg), "1");
    assert.equal(await announced(pg), "Notification cleared");
    await pg.focus(`${row("o3")} [data-testid="notif-clear"]`);
    await pg.keyboard.press("Enter");
    await settle(pg, 300);
    assert.deepEqual(await ids(pg), ["o2"]);
    assert.deepEqual(net.ownerReads, ["o1", "o3"]);
    assert.equal(await badge(pg), "1", "clearing a read owner row leaves the count");
    await drag(pg, "o2", -14, -220, { steps: 12 });
    await settle(pg, 200);
    assert.deepEqual(await ids(pg), ["o2"], "a vertical gesture clears nothing");
    await pg.keyboard.press("Escape");
    await sleep(150);
    assert.equal((await active(pg)).testid, "notif-bell", "Escape returns focus to the owner bell");
    await close();
  }

  assert.deepEqual(problems, []);
  console.log("notifications mobile: sheet geometry at 390/320 (customer and owner, dark and light), 1440 popover, safe-area rule, keyboard and close, swipe clear (once, announced, persists), reveal and tap, Clear button (keyboard, mouse, double press, failure), reduced motion, vertical scroll, owner bell, audits passed");
} finally {
  await h.close();
}
