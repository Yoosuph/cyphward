// Screenshots and layout-shift numbers for the motion, skeleton and cache pass (docs/ui-motion-cache-2026-11-01).
//   PHASE=before|after node scripts/capture-motion-cache.mjs
// Every route loads cold with its data held back 900 ms. For each route and width (1440, 390, 320) it records the
// CLS of the whole load, the CLS from the first skeleton frame to settled, how far the panels moved when the data
// replaced the skeleton, and the frame sequence (skeleton, content, blank). The main pages are also captured in
// their skeleton and loaded states (JPEG, each under 200 KB).
// Writes docs/ui-motion-cache-2026-11-01/<phase>/*.jpg and cls-<phase>.json. Fixtures only; nothing reaches a server.
import { mkdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { WIDTHS, frontend, startHarness } from "./lib/ui-refine-harness.mjs";
import { APP_ROUTES, APP_SUBROUTES, OWNER_ROUTES, measureRoute } from "./lib/motion-cache-harness.mjs";

const PHASE = process.env.PHASE === "before" ? "before" : "after";
const DIR = join(frontend, "..", "docs", "ui-motion-cache-2026-11-01");
const SHOTS = join(DIR, PHASE);
mkdirSync(SHOTS, { recursive: true });
const MAIN = ["/overview", "/findings", "/scans", "/comply", "/settings", "/admin", "/admin/organizations", "/admin/analytics"];
const slug = (r) => r.replace(/^\//, "").replace(/[/?=]/g, "-") || "home";

const h = await startHarness();
const out = {};
try {
  for (const route of [...APP_ROUTES, ...APP_SUBROUTES, ...OWNER_ROUTES]) {
    out[route] = {};
    for (const [label, width, height] of WIDTHS) {
      const capture = MAIN.includes(route) && label !== "320";
      const r = await measureRoute(h, route, {
        width, height, motion: true,
        shot: capture ? join(SHOTS, `${slug(route)}-${label}-loaded.jpg`) : null,
        shotSkeleton: capture ? join(SHOTS, `${slug(route)}-${label}-skeleton.jpg`) : null,
      });
      out[route][label] = { cls: r.cls, clsAfterSkeleton: r.clsAfterSkeleton, frames: r.frames.map((f) => f.kind).join(">"), overflow: r.overflow, jump: r.jump,
        shifts: r.shifts, errors: r.errors };
      console.log(`${PHASE} ${route} @${label}: cls=${r.cls} afterSkeleton=${r.clsAfterSkeleton} jump=${JSON.stringify(r.jump)} frames=${out[route][label].frames} overflow=${r.overflow}${r.errors.length ? ` errors=${r.errors.length}` : ""}`);
    }
  }
} finally {
  await h.close();
}
writeFileSync(join(DIR, `cls-${PHASE}.json`), JSON.stringify(out, null, 1));
for (const route of MAIN) for (const label of ["1440", "390"]) for (const kind of ["skeleton", "loaded"]) {
  const file = join(SHOTS, `${slug(route)}-${label}-${kind}.jpg`);
  try {
    const kb = Math.round(statSync(file).size / 1024);
    if (kb >= 200) console.log(`WARNING ${file} is ${kb} KB`);
  } catch { console.log(`missing ${file}`); }
}
