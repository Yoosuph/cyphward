// UI refinement regression (docs/ui-2026-10-25). Every API call is answered from fixtures; no live account.
// Main pages (landing, login, signup, overview, scans, findings, compliance, settings, reports, owner console) at
// 1440, 390 and 320 wide, dark theme, plus the light theme at 1440 and 390:
//   no horizontal page scroll, 44px touch targets on phones, a label for every field, a name for every control,
//   no skipped heading level, a visible focus ring on every Tab stop, WCAG AA text contrast, no claim wording.
// Then: error and empty states use the shared panels (never a blank screen or a false "no issues"), the skip link,
// Settings tabs by keyboard and the issue drawer's focus handling.
import assert from "node:assert/strict";
import { AUTH_PAGES, PUBLIC_PAGES, OWNER_PAGES, WIDTHS, UI_BANNED, startHarness, settle, audit } from "./lib/ui-refine-harness.mjs";

const h = await startHarness();
const problems = [];
const check = (label, r) => {
  for (const key of ["small", "unlabelled", "nameless", "skips", "noRing", "lowContrast", "bannedHits", "landmarks", "pageErrors"]) {
    if (r[key]?.length) problems.push(`${label}: ${key} ${JSON.stringify(r[key].slice(0, 6))}`);
  }
  if (r.overflow > 0) problems.push(`${label}: horizontal overflow ${r.overflow}px`);
  if (r.h1 !== 1) problems.push(`${label}: ${r.h1} h1 headings (want 1)`);
};

try {
  // 1. Audit every main page.
  for (const [pages, signedIn] of [[PUBLIC_PAGES, false], [AUTH_PAGES, true], [OWNER_PAGES, false]]) {
    for (const [name, route] of pages) {
      for (const theme of ["dark", "light"]) {
        const { page, errors, close } = await h.newPage({ theme, signedIn });
        for (const [label, width, height] of WIDTHS) {
          if (theme === "light" && label === "320") continue;
          await page.setViewport({ width, height });
          await page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
          await settle(page, 700);
          const r = await audit(page, { mobile: width < 768, tabStops: theme === "dark" ? 40 : 0 });
          check(`${name} ${theme} ${label}`, { ...r, pageErrors: errors.splice(0) });
        }
        await close();
      }
    }
  }

  // 2. Error states: the page's main read fails -> the shared error panel with a retry, never blank or "no issues".
  const failing = [
    ["/overview", "/overview"], ["/findings", "/findings"], ["/settings", "/settings"], ["/scans", "/scans"],
    ["/reports", "/reports"], ["/comply", "/compliance/overview"], ["/admin", "/owner/overview"],
  ];
  for (const [route, fail] of failing) {
    h.state.failures.clear();
    h.state.failures.add(fail);
    const { page, close } = await h.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
    await settle(page, 900);
    const s = await page.evaluate(() => ({
      error: !!document.querySelector('[data-testid="state-error"], [role="alert"]'),
      retry: [...document.querySelectorAll("button")].some((b) => /try again|retry/i.test(b.textContent)),
      h1: document.querySelectorAll("h1").length,
      text: document.body.innerText,
      overflow: document.documentElement.scrollWidth - innerWidth,
    }));
    assert.ok(s.error, `${route}: a failed load shows an error state`);
    assert.ok(s.retry, `${route}: the error state offers a retry`);
    assert.ok(!/no open issues|no issues recorded/i.test(s.text), `${route}: a failed load never claims there are no issues`);
    assert.ok(!/internal server error|traceback|status \d{3}/i.test(s.text), `${route}: no raw server wording`);
    assert.ok(s.overflow <= 0, `${route}: error state fits the phone width`);
    for (const w of UI_BANNED) assert.ok(!s.text.toLowerCase().includes(w), `${route}: error copy avoids "${w}"`);
    await close();
  }
  h.state.failures.clear();

  // 2b. A page-load error shows reviewed wording only: a 4xx detail from the API is not passed through.
  for (const [route, fail] of [["/findings", "/findings"], ["/settings", "/settings"], ["/admin", "/owner/overview"]]) {
    Object.assign(h.state, { failStatus: 422, failDetail: "Raw backend detail for review" });
    h.state.failures.clear();
    h.state.failures.add(fail);
    const { page, close } = await h.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
    await settle(page, 900);
    const text = await page.evaluate(() => document.body.innerText);
    assert.ok(await page.$('[data-testid="state-error"]'), `${route}: a 4xx load error shows the error state`);
    assert.ok(!text.includes("Raw backend detail"), `${route}: a 4xx detail is not shown on a page-load error`);
    await close();
  }
  Object.assign(h.state, { failStatus: 500, failDetail: "Internal Server Error" });
  h.state.failures.clear();

  // 2c. Pages outside the audited set that render inside the shell keep a single, un-nested <main>.
  for (const route of ["/remediation", "/assets", "/domains"]) {
    const { page, close } = await h.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
    for (let i = 0; i < 6; i++) {
      const n = await page.evaluate(() => ({ nested: document.querySelectorAll("main main").length, mains: document.querySelectorAll("main").length }));
      assert.equal(n.nested, 0, `${route}: no <main> inside <main> (sample ${i})`);
      assert.ok(n.mains <= 1, `${route}: at most one <main> (sample ${i})`);
      await new Promise((r) => setTimeout(r, 150));
    }
    await close();
  }

  // 3. Empty states use the shared panel.
  h.state.empty = true;
  for (const route of ["/findings", "/admin/users"]) {
    const { page, close } = await h.newPage();
    await page.setViewport({ width: 320, height: 720 });
    await page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
    await settle(page, 900);
    assert.ok(await page.$('[data-testid="state-empty"]'), `${route}: empty list shows the shared empty state`);
    await close();
  }
  h.state.empty = false;

  // 4. Keyboard: skip link, Settings tabs, issue drawer focus in and back.
  {
    const { page, close } = await h.newPage();
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(`${h.origin}/settings`, { waitUntil: "domcontentloaded" });
    await settle(page, 700);
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Skip to content", "first Tab stop is the skip link");
    await page.keyboard.press("Enter");
    assert.equal(await page.evaluate(() => document.activeElement?.id), "main", "skip link moves focus to the page content");

    await page.focus("#settings-tab-general");
    await page.keyboard.press("ArrowRight");
    assert.equal(await page.evaluate(() => document.activeElement?.id), "settings-tab-team", "ArrowRight moves to the next tab");
    assert.equal(await page.$eval("#settings-tab-team", (e) => e.getAttribute("aria-selected")), "true");
    assert.ok(await page.$('#settings-panel-team[role="tabpanel"]'), "the selected tab shows its panel");
    await page.keyboard.press("End");
    assert.equal(await page.evaluate(() => document.activeElement?.id), "settings-tab-notifications", "End moves to the last tab (Notifications, added after this suite)");

    await close();
  }

  // 5. Drawers and layered overlays, with normal motion and with reduced motion.
  //    Open focus: the same page opens and closes the issue drawer 15 times; each open must move focus inside
  //    (waiting at most 1s, never relying on a fresh page), each close must hand it back to the issue.
  //    A: issue drawer -> "Ask CyphBot" dialog on top. B: issue drawer -> "How to fix" drawer on top.
  for (const reducedMotion of [false, true]) {
    const mode = reducedMotion ? "reduced motion" : "normal motion";
    const { page, close } = await h.newPage({ reducedMotion });
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(`${h.origin}/findings`, { waitUntil: "domcontentloaded" });
    await settle(page, 700);
    const focusInside = (sel) => page.waitForFunction((sel) => { const d = document.querySelector(sel); return !!d && d.contains(document.activeElement); }, { timeout: 1000 }, sel).then(() => true, () => false);
    const focusOnIssue = () => page.waitForFunction(() => document.activeElement?.closest("main h2")?.textContent?.trim() === "Missing Email DMARC Authentication Policy", { timeout: 1000 }).then(() => true, () => false);
    const openIssue = async () => {
      await page.focus("main h2 button");
      await page.keyboard.press("Enter");
      await page.waitForFunction(() => document.querySelector("aside.drawer.open"));
      assert.ok(await focusInside("aside.drawer.open"), `${mode}: opening an issue moves focus into the drawer`);
      await settle(page, 400);
    };
    assert.equal(await page.evaluate(() => document.querySelector("aside.drawer")?.inert), true, `${mode}: a closed drawer is inert`);
    // A slower CPU widens the window in which an opening drawer is still hidden, so a focus call that is not
    // retried misses it reliably instead of now and then.
    await page.emulateCPUThrottling(4);
    let landed = 0;
    for (let i = 0; i < 15; i++) {
      await page.focus("main h2 button");
      await page.keyboard.press("Enter");
      if (await focusInside("aside.drawer.open")) landed++;
      const labelled = await page.evaluate(() => { const d = document.querySelector("aside.drawer.open"); return !!(d && document.getElementById(d.getAttribute("aria-labelledby") || "")?.textContent); });
      assert.ok(labelled, `${mode}: the drawer is labelled by its title`);
      await page.keyboard.press("Escape");
      assert.ok(await focusOnIssue(), `${mode}: closing returns focus to the issue (open ${i + 1})`);
      await page.waitForFunction(() => !document.querySelector("aside.drawer.open"));
    }
    assert.equal(landed, 15, `${mode}: focus moved into the drawer on ${landed} of 15 opens`);
    await page.emulateCPUThrottling(1);
    await settle(page, 400);
    /** Focus a button by its exact text inside the given drawer (the first open one by default) and press Enter. */
    const pressIn = async (scope, text) => {
      const ok = await page.evaluate((scope, text) => {
        const root = scope === "dialog" ? document.querySelector(".dialog-panel") : document.querySelector("aside.drawer.open");
        const b = root && [...root.querySelectorAll("button")].find((x) => x.textContent.replace(/\s+/g, " ").trim() === text);
        if (b) b.focus();
        return !!b && document.activeElement === b;
      }, scope, text);
      assert.ok(ok, `found and focused "${text}"`);
      await page.keyboard.press("Enter");
      await settle(page, 400);
    };
    const activeIn = (sel) => page.evaluate((sel) => { const n = document.querySelector(sel); return !!n && n.contains(document.activeElement) && document.activeElement !== document.body; }, sel);
    const activeText = () => page.evaluate(() => document.activeElement?.textContent?.replace(/\s+/g, " ").trim());
    const openDrawers = () => page.evaluate(() => [...document.querySelectorAll("aside.drawer.open")].map((d) => document.getElementById(d.getAttribute("aria-labelledby") || "")?.textContent?.trim()));

    // A: a dialog over a drawer keeps Tab and Shift+Tab inside the dialog; Escape closes the dialog first.
    await openIssue();
    await pressIn("drawer", "Ask CyphBot");
    await page.waitForSelector(".dialog-panel");
    await settle(page, 300);
    for (const shift of [false, false, false, false, false, false, true, true, true]) {
      if (shift) await page.keyboard.down("Shift");
      await page.keyboard.press("Tab");
      if (shift) await page.keyboard.up("Shift");
      assert.ok(await activeIn(".dialog-panel"), `${mode} A: Tab stays inside the dialog over the drawer (now on "${await activeText()}")`);
    }
    await page.keyboard.press("Escape");
    await settle(page, 400);
    assert.equal(await page.$(".dialog-panel"), null, `${mode} A: first Escape closes the dialog`);
    assert.deepEqual(await openDrawers(), ["Issue details"], `${mode} A: the issue drawer stays open under it`);
    assert.equal(await activeText(), "Ask CyphBot", `${mode} A: focus returns to the drawer button that opened the dialog`);
    await page.keyboard.press("Tab");
    assert.ok(await activeIn("aside.drawer.open"), `${mode} A: Tab then moves inside the issue drawer again`);
    await page.keyboard.press("Escape");
    await settle(page, 400);
    assert.deepEqual(await openDrawers(), [], `${mode} A: second Escape closes the issue drawer`);
    assert.equal(await activeText(), "Missing Email DMARC Authentication Policy", `${mode} A: focus returns to the issue`);

    // B: a drawer over a drawer: Tab reaches the top drawer's controls; Escape closes the top one first.
    await openIssue();
    await pressIn("drawer", "How to fix");
    await page.waitForFunction(() => document.querySelectorAll("aside.drawer.open").length === 2);
    assert.ok(await focusInside('aside.drawer.open:not([inert])'), `${mode} B: opening the fix drawer moves focus into it`);
    await settle(page, 400);
    const fixDrawer = 'aside.drawer.open[aria-labelledby]:not([inert])';
    const reached = new Set();
    for (let i = 0; i < 14; i++) {
      await page.keyboard.press("Tab");
      const where = await page.evaluate(() => {
        const a = document.activeElement;
        const d = a?.closest("aside.drawer");
        return { title: d && document.getElementById(d.getAttribute("aria-labelledby") || "")?.textContent?.trim(), text: a?.textContent?.replace(/\s+/g, " ").trim() };
      });
      assert.equal(where.title, "How to fix this", `${mode} B: Tab stays in the top drawer (step ${i}: "${where.text}" in "${where.title}")`);
      reached.add(where.text);
    }
    for (const want of ["nginx", "apache", "cloudflare", "aws"]) assert.ok(reached.has(want), `${mode} B: the setup choice "${want}" is reachable by Tab`);
    assert.ok(await page.$(fixDrawer), `${mode} B: the top drawer is not inert`);
    await page.keyboard.press("Escape");
    await settle(page, 400);
    assert.deepEqual(await openDrawers(), ["Issue details"], `${mode} B: first Escape closes only the top drawer`);
    assert.equal(await activeText(), "How to fix", `${mode} B: focus returns to the button that opened the top drawer`);
    await page.keyboard.press("Escape");
    await settle(page, 400);
    assert.deepEqual(await openDrawers(), [], `${mode} B: second Escape closes the issue drawer`);
    assert.equal(await activeText(), "Missing Email DMARC Authentication Policy", `${mode} B: focus returns to the issue`);
    await close();
  }
} finally {
  await h.close();
}
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log("ui-refine: 10 main pages at 1440/390/320 (dark) and 1440/390 (light) passed overflow, touch-target, label, name, heading, focus-ring, contrast and claim-wording checks; shared error/empty states; skip link, Settings tabs and issue drawer focus on 15/15 opens and dialog-over-drawer / drawer-over-drawer Tab and Escape order, each with normal and reduced motion");
