// Screenshots and an accessibility/layout audit for the UI refinement pass (docs/ui-2026-10-25). Not a test
// (the assertions live in check-ui-refine.mjs).
//   OUT_DIR=../docs/ui-2026-10-25/before node scripts/capture-ui-refine.mjs
// Serves the app with every API call answered from fixtures; saves one JPEG per page and width (dark theme, as the
// brand ships) and audit.json with the counts the README quotes. The same script runs on the old and new code.
import { mkdir, writeFile, stat } from "node:fs/promises";
import path from "node:path";
import { AUTH_PAGES, PUBLIC_PAGES, OWNER_PAGES, WIDTHS, startHarness, settle, audit } from "./lib/ui-refine-harness.mjs";

const outDir = path.resolve(process.env.OUT_DIR || "../docs/ui-2026-10-25/after");
await mkdir(outDir, { recursive: true });
const MAX_H = { 1440: 2400, 390: 3200, 320: 3200 };
const h = await startHarness();
const report = {};
try {
  const groups = [[PUBLIC_PAGES, false], [AUTH_PAGES, true], [OWNER_PAGES, false]];
  for (const [pages, signedIn] of groups) {
    for (const [name, route] of pages) {
      if (process.env.ONLY && !name.includes(process.env.ONLY)) continue;
      report[name] = {};
      for (const theme of ["dark", "light"]) {
        const { page, errors, close } = await h.newPage({ theme, signedIn });
        for (const [label, width, height] of WIDTHS) {
          if (theme === "light" && label !== "1440" && !process.env.ALL_THEMES) continue;
          await page.setViewport({ width, height });
          await page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
          await settle(page, 900);
          const result = await audit(page, { mobile: width < 768, tabStops: theme === "dark" ? 40 : 0 });
          report[name][`${theme}-${label}`] = { ...result, pageErrors: errors.splice(0) };
          if (theme === "dark") {
            await page.evaluate(() => { document.activeElement?.blur?.(); document.querySelectorAll("[data-audit-probe]").forEach((n) => n.remove()); window.scrollTo(0, 0); });
            await page.mouse.move(0, 0);
            const full = await page.evaluate(() => document.documentElement.scrollHeight);
            const file = path.join(outDir, `${name}-${label}.jpg`);
            const clip = { x: 0, y: 0, width, height: Math.min(full, MAX_H[label]) };
            await page.screenshot({ path: file, type: "jpeg", quality: 55, clip, captureBeyondViewport: true });
            if ((await stat(file)).size > 290 * 1024) await page.screenshot({ path: file, type: "jpeg", quality: 35, clip, captureBeyondViewport: true });
          }
        }
        await close();
      }
      const d = report[name];
      const sum = (k) => Object.values(d).reduce((n, r) => n + (Array.isArray(r[k]) ? r[k].length : r[k] > 0 ? 1 : 0), 0);
      console.log(`${name}: overflow ${sum("overflow")} small ${sum("small")} unlabelled ${sum("unlabelled")} nameless ${sum("nameless")} skips ${sum("skips")} noRing ${sum("noRing")} lowContrast ${sum("lowContrast")} banned ${sum("bannedHits")}`);
    }
  }
} finally {
  await h.close();
}
await writeFile(path.join(outDir, "audit.json"), JSON.stringify(report, null, 1));
