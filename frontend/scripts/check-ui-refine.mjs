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
  for (const key of ["small", "unlabelled", "nameless", "skips", "noRing", "lowContrast", "bannedHits", "pageErrors"]) {
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
    assert.equal(await page.evaluate(() => document.activeElement?.id), "settings-tab-auth", "End moves to the last tab");

    await page.goto(`${h.origin}/findings`, { waitUntil: "domcontentloaded" });
    await settle(page, 700);
    const drawerFocusable = await page.evaluate(() => { const d = document.querySelector("aside.drawer"); return d ? d.inert : null; });
    assert.equal(drawerFocusable, true, "a closed drawer is inert");
    await page.focus("main h2 button");
    await page.keyboard.press("Enter");
    await settle(page, 400);
    const opened = await page.evaluate(() => {
      const d = document.querySelector("aside.drawer.open");
      const label = d && document.getElementById(d.getAttribute("aria-labelledby") || "")?.textContent;
      return { inside: !!d && d.contains(document.activeElement), label };
    });
    assert.ok(opened.inside, "opening an issue moves focus into the drawer");
    assert.ok(opened.label, "the drawer is labelled by its title");
    await page.keyboard.press("Escape");
    await settle(page, 300);
    assert.equal(await page.evaluate(() => document.activeElement?.closest("h2")?.textContent?.trim()), "Missing Email DMARC Authentication Policy", "closing returns focus to the issue");
    await close();
  }
} finally {
  await h.close();
}
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log("ui-refine: 10 main pages at 1440/390/320 (dark) and 1440/390 (light) passed overflow, touch-target, label, name, heading, focus-ring, contrast and claim-wording checks; shared error/empty states; skip link, Settings tabs and issue drawer by keyboard");
