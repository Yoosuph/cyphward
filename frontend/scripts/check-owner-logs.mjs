// Owner console logs: expandable rows (docs/owner-logs-2026-10-29). Every API call is answered from fixtures;
// nothing reaches a server.
//   - a row opens on a click anywhere on the row and on its disclosure button; Enter and Space on the button open
//     and close it; aria-expanded flips and aria-controls names the panel row underneath; one entry open at a time
//   - the open entry shows the time in UTC and in the viewer's zone (pinned to Africa/Lagos here), the action, the
//     result and the reason, who did it, the target and the organization, the details as label and value pairs
//     (the first 8, then "Show all"), and a copy button for the row id
//   - customer events say the result is not recorded rather than inventing one
//   - error and empty states: a raw server body never reaches the screen
//   - the audit (no horizontal scroll, 44px targets on phones, labels, names, heading order, focus rings, contrast,
//     no claim wording) at 1440, 390 and 320 in both themes with an entry open, reduced motion on
// CAPTURE=1 also writes the "after" screenshots at 1440 and 390 to docs/owner-logs-2026-10-29/ (JPEG, each under 200 KB).
import assert from "node:assert/strict";
import { mkdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { WIDTHS, audit, frontend, settle, sleep, startHarness } from "./lib/ui-refine-harness.mjs";
import { CUSTOMER_ROWS, OWNER_ROWS, logsPayload } from "./lib/owner-logs-fixture.mjs";

const SHOTS = join(frontend, "..", "docs", "owner-logs-2026-10-29");
const CAPTURE = process.env.CAPTURE === "1";
const RAW = "Traceback (most recent call last): psycopg.errors.UndefinedColumn at owner_views.py line 366";

const h = await startHarness();
const problems = [];
let failLogs = null; // [status, body]
let emptyLogs = false;

h.state.route = (p, method, request) => {
  if (p !== "/api/v1/owner/logs") return undefined;
  if (failLogs) return failLogs;
  const body = logsPayload(new URL(request.url()));
  return [200, emptyLogs ? { ...body, items: [] } : body];
};

const check = (label, r) => {
  for (const key of ["small", "unlabelled", "nameless", "skips", "noRing", "lowContrast", "bannedHits", "landmarks"]) {
    if (r[key]?.length) problems.push(`${label}: ${key} ${JSON.stringify(r[key].slice(0, 6))}`);
  }
  if (r.overflow > 0) problems.push(`${label}: horizontal overflow ${r.overflow}px`);
  if (r.h1 !== 1) problems.push(`${label}: ${r.h1} h1 headings (want 1)`);
};

async function open(route, { width = 1440, height = 900, theme = "dark" } = {}) {
  const tab = await h.newPage({ theme });
  await tab.page.emulateTimezone("Africa/Lagos");
  await tab.page.setViewport({ width, height });
  await tab.page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
  await settle(tab.page, 500);
  return tab;
}

const cell = async (page, i, label) => (await page.$$('[data-testid="log-row"]'))[i].$(`td[data-label="${label}"]`);
// Scroll the element to the middle of its scroller first, so the sticky header never sits over it.
async function clickCentred(page, selector) {
  await page.$eval(selector, (e) => e.scrollIntoView({ block: "center" }));
  await sleep(50);
  await page.click(selector);
}
const toggles = (page) => page.$$('[data-testid="log-toggle"]');
const expanded = (page) => page.$$eval('[data-testid="log-toggle"]', (bs) => bs.map((b) => b.getAttribute("aria-expanded")));
const panelText = (page) => page.$eval('[data-testid="log-detail"]', (e) => e.innerText);
const openPanels = (page) => page.$$eval(".log-detail-row", (rows) => rows.filter((r) => !r.hidden && r.getBoundingClientRect().height > 0).length);

async function shot(page, name) {
  if (!CAPTURE) return;
  mkdirSync(SHOTS, { recursive: true });
  const path = join(SHOTS, `${name}.jpg`);
  await page.evaluate(() => { document.activeElement?.blur?.(); window.scrollTo(0, 0); });
  await page.mouse.move(0, 0);
  await sleep(150);
  await page.screenshot({ path, type: "jpeg", quality: 70 });
  const kb = statSync(path).size / 1024;
  assert.ok(kb < 200, `${name}.jpg is ${kb.toFixed(0)} KB (keep it under 200 KB)`);
}

try {
  // 1. Owner console entries: open by clicking the row, then the details.
  {
    const { page, errors, close } = await open("/admin/logs?source=owner");
    await page.waitForSelector('[data-testid="log-table"]');
    assert.equal((await toggles(page)).length, OWNER_ROWS.length);
    assert.deepEqual(await expanded(page), ["false", "false", "false", "false", "false"], "every entry starts closed");
    assert.equal(await openPanels(page), 0);
    // Each button names a panel row that exists, is the full width of the table and sits right under its row.
    const wiring = await page.$$eval('[data-testid="log-toggle"]', (bs) => bs.map((b) => {
      const panel = document.getElementById(b.getAttribute("aria-controls"));
      const td = panel?.querySelector("td");
      return { tag: b.tagName, type: b.type, panel: !!panel, next: b.closest("tr").nextElementSibling === panel,
        span: td?.colSpan, cols: b.closest("table").querySelectorAll("thead th").length };
    }));
    for (const w of wiring) {
      assert.equal(w.tag, "BUTTON"); assert.equal(w.type, "button");
      assert.ok(w.panel && w.next, "aria-controls names the row underneath");
      assert.equal(w.span, w.cols, "the panel spans every column");
    }
    const thead = await page.$eval('[data-testid="log-table"] thead th', (th) => getComputedStyle(th).position);
    assert.equal(thead, "sticky", "the header stays in view");

    // Click a plain cell of the first row (not the button).
    await (await cell(page, 0, "Action")).click();
    await sleep(150);
    assert.deepEqual(await expanded(page), ["true", "false", "false", "false", "false"], "a click on the row opens it");
    assert.equal(await openPanels(page), 1);
    const first = await panelText(page);
    assert.match(first, /owner\.action\.change_plan/, "action shown");
    assert.match(first, /SUCCESS/i, "result shown");
    assert.match(first, /Customer asked by email, ticket 42/, "reason shown");
    assert.match(first, /2026-10-29 08:14:07\.512 UTC/, "exact UTC time");
    assert.match(first, /09:14:07/, "local time (Africa/Lagos is UTC+1)");
    assert.match(first, /Africa\/Lagos/, "local zone named");
    assert.match(first, /Ada Owner/); assert.match(first, /owner@example\.test/);
    assert.match(first, /organization\s+0a000000-0000-4000-8000-000000000001/, "full target id");
    assert.match(first, /Acme Traders Ltd/, "organization name");
    assert.match(first, new RegExp(OWNER_ROWS[0].id), "row id");
    assert.ok(await page.$('[data-testid="log-detail"] [data-testid="log-copy-id"]'), "copy button present");
    await shot(page, "after-1440");
    // Details are label and value pairs, capped with a way to see the rest; no JSON dump on one line.
    const pairs = () => page.$$eval('[data-testid="log-details"] .log-pair', (ps) => ps.length);
    assert.equal(await pairs(), 8, "the first 8 details");
    assert.doesNotMatch(first, /\{"/, "no raw JSON");
    assert.match(first, /From plan\s+starter/i);
    await page.click('[data-testid="log-show-all"]');
    await sleep(100);
    assert.ok(await pairs() > 8, "Show all reveals the rest");
    assert.equal(await page.$eval('[data-testid="log-show-all"]', (b) => b.getAttribute("aria-expanded")), "true");
    // The long unbroken value wraps inside the panel.
    const wrap = await page.$eval('[data-testid="log-detail"]', (d) => {
      const vals = [...d.querySelectorAll(".log-value")];
      const box = d.getBoundingClientRect();
      return { widest: Math.max(...vals.map((v) => v.getBoundingClientRect().right)), right: box.right, page: document.documentElement.scrollWidth - innerWidth };
    });
    assert.ok(wrap.widest <= wrap.right + 1, `values stay inside the panel (${wrap.widest} > ${wrap.right})`);
    assert.equal(wrap.page, 0, "no horizontal page scroll");

    // Copy: the button hands the exact row id to the clipboard (headless Chromium has no real clipboard, so the
    // page's writeText is replaced with one that records what it was given), and a refusal is explained.
    await page.evaluate(() => {
      window.__copied = [];
      Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (t) => { if (window.__refuse) throw new Error("denied"); window.__copied.push(t); } } });
    });
    await clickCentred(page, '[data-testid="log-copy-id"]');
    await sleep(200);
    assert.deepEqual(await page.evaluate(() => window.__copied), [OWNER_ROWS[0].id], "row id copied");
    assert.match(await page.evaluate(() => document.body.innerText), /Row id copied\./);
    await page.evaluate(() => { window.__refuse = true; });
    await clickCentred(page, '[data-testid="log-copy-id"]');
    await sleep(200);
    assert.match(await page.evaluate(() => document.body.innerText), /Could not copy\. Select the id and copy it by hand\./);
    assert.deepEqual(await expanded(page), ["true", "false", "false", "false", "false"], "the copy button does not close the entry");

    // One entry at a time: opening the second closes the first. Its button flips once per click.
    const [, second] = await toggles(page);
    await second.click();
    await sleep(150);
    assert.deepEqual(await expanded(page), ["false", "true", "false", "false", "false"], "one entry open at a time");
    const rejected = await panelText(page);
    assert.match(rejected, /REJECTED/i);
    assert.match(rejected, /Repeated failed payments/);
    assert.match(rejected, /does not match/);
    await second.click();
    await sleep(150);
    assert.deepEqual(await expanded(page), ["false", "false", "false", "false", "false"], "a second click closes it");

    // Keyboard: Enter opens, Space closes.
    await (await toggles(page))[2].focus();
    await page.keyboard.press("Enter");
    await sleep(150);
    assert.deepEqual(await expanded(page), ["false", "false", "true", "false", "false"], "Enter opens");
    const third = await panelText(page);
    assert.match(third, /owner\.sign_in/); assert.match(third, /DENIED/i);
    assert.match(third, /No further details/, "an entry without details says so");
    await page.keyboard.press("Space");
    await sleep(150);
    assert.deepEqual(await expanded(page), ["false", "false", "false", "false", "false"], "Space closes");
    await page.keyboard.press("Space");
    await sleep(150);
    assert.deepEqual(await expanded(page), ["false", "false", "true", "false", "false"], "Space opens");

    // A short list with one very long value: the value is cut until "Show all", then shown in full and wrapped.
    const fifth = (await toggles(page))[4];
    await fifth.evaluate((e) => e.scrollIntoView({ block: "center" }));
    await sleep(50);
    await fifth.click();
    await sleep(150);
    const hostsPair = () => page.$$eval('[data-testid="log-details"] .log-pair', (ps) => ps.find((p) => /hosts/i.test(p.querySelector("dt").textContent))?.querySelector("dd").textContent || "");
    assert.equal(await page.$$eval('[data-testid="log-details"] .log-pair', (ps) => ps.length), 3);
    const cut = await hostsPair();
    assert.ok(cut.endsWith("…") && cut.length <= 302, `a long value is cut (${cut.length} characters)`);
    assert.doesNotMatch(cut, /host-60/);
    assert.equal(await page.$eval('[data-testid="log-show-all"]', (b) => b.textContent.trim()), "SHOW ALL");
    await clickCentred(page, '[data-testid="log-show-all"]');
    await sleep(100);
    const whole = await hostsPair();
    assert.match(whole, /host-60\.acme\.example$/, "Show all shows the whole value");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth), 0, "no horizontal page scroll");
    assert.deepEqual(errors, [], "no page errors");
    await close();
  }

  // 2. Customer events: names, organization, and a result that is not invented.
  {
    const { page, close } = await open("/admin/logs");
    await page.waitForSelector('[data-testid="log-table"]');
    assert.equal((await toggles(page)).length, CUSTOMER_ROWS.length);
    const [b] = await toggles(page);
    await b.click();
    await sleep(150);
    const text = await panelText(page);
    assert.match(text, /scan\.launched/);
    assert.match(text, /Not recorded/, "customer events carry no result");
    assert.match(text, /Chidi Okafor/); assert.match(text, /c1@example\.test/);
    assert.match(text, /Acme Traders Ltd/);
    assert.match(text, /Domain\s+acme\.example/i);
    // A link inside a row navigates instead of toggling.
    await (await (await cell(page, 1, "Organization")).$("a")).click();
    await settle(page, 300);
    assert.match(page.url(), /\/admin\/organizations\//, "the organization link still works");
    await close();
  }

  // 3. Error and empty states.
  {
    failLogs = [500, { detail: RAW }];
    const { page, close } = await open("/admin/logs?source=owner");
    await page.waitForSelector('[data-testid="state-error"]');
    const body = await page.evaluate(() => document.body.innerText);
    assert.doesNotMatch(body, /traceback|psycopg|owner_views\.py/i, "no raw server text");
    assert.match(body, /log entries did not load/i);
    failLogs = null;
    emptyLogs = true;
    await page.click('[data-testid="state-error"] button');
    await page.waitForSelector('[data-testid="state-empty"]');
    assert.match(await page.$eval('[data-testid="state-empty"]', (e) => e.innerText), /No log entries match/);
    check("empty 1440", await audit(page, { tabStops: 0 }));
    emptyLogs = false;
    await close();
  }

  // 4. Layout and accessibility audit with an entry open (details shown in full), at 1440, 390 and 320.
  for (const [label, width, height] of WIDTHS) {
    const mobile = width < 900;
    for (const [name, route] of [["owner", "/admin/logs?source=owner"], ["customer", "/admin/logs"]]) {
      for (const theme of ["dark", "light"]) {
        const { page, close } = await open(route, { width, height, theme });
        await page.waitForSelector('[data-testid="log-table"]');
        const [b] = await toggles(page);
        await b.click();
        await sleep(150);
        if (await page.$('[data-testid="log-show-all"]')) { await page.click('[data-testid="log-show-all"]'); await sleep(100); }
        check(`${name} ${label} ${theme}`, await audit(page, { mobile }));
        const stacked = await page.$eval('[data-testid="log-detail"] .log-pair', (p) => {
          const [dt, dd] = [p.querySelector("dt"), p.querySelector("dd")];
          return dd.getBoundingClientRect().top >= dt.getBoundingClientRect().bottom - 1;
        });
        if (width < 640) assert.ok(stacked, `${name} ${label}: label above value on phones`);
        if (theme === "dark" && label === "390" && name === "owner") {
          await page.$eval('[data-testid="log-row"]', (r) => r.scrollIntoView());
          await shot(page, "after-390");
        }
        await close();
      }
    }
  }

  assert.deepEqual(problems, [], `audit problems:\n${problems.join("\n")}`);
  console.log("owner logs: ok (row opens on click and on Enter/Space with aria-expanded and aria-controls, one entry at a time, " +
    "UTC and local time, action, result and reason, actor, target, organization, details as label/value pairs with Show all, " +
    "copy row id, customer result not invented, links still navigate, error and empty states without raw text, " +
    "sticky header, audit at 1440/390/320 in both themes with an entry open)");
} finally {
  await h.close();
}
