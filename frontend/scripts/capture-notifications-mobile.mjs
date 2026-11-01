// Screenshots of the bell's panel on phones (docs/notifications-mobile-2026-11-01). Every API call is answered from
// fixtures; nothing reaches a server.
//   node scripts/capture-notifications-mobile.mjs <before|after> [out-dir]
// Writes <label>-390.jpg and <label>-320.jpg (panel open) and, for "after", <label>-390-swipe.jpg (a row swiped to
// show Clear). Prints the panel's box and the page's horizontal overflow for each width.
import { mkdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { settle, sleep, startHarness } from "./lib/ui-refine-harness.mjs";

const label = process.argv[2] || "after";
const out = resolve(process.argv[3] || "../docs/notifications-mobile-2026-11-01");
mkdirSync(out, { recursive: true });

const hoursAgo = (h) => new Date(Date.now() - h * 3600_000).toISOString();
const daysAgo = (d) => { const x = new Date(); x.setDate(x.getDate() - d); x.setHours(9, 0, 0, 0); return x.toISOString(); };
const items = [
  { id: "n1", kind: "finding_critical", category: "findings", severity: "critical", title: "Critical finding on shop.acme.ng",
    body: "A finding rated critical was recorded. Open Findings to see what each one is and how to fix it.", link: "/findings", count: 1, read_at: null, created_at: hoursAgo(0.2) },
  { id: "n2", kind: "asset_discovered", category: "scans", severity: "info", title: "3 new hosts found",
    body: "It was found on acme.ng during the latest scan. Review it on the Assets page.", link: "/assets", count: 3, read_at: null, created_at: hoursAgo(0.5) },
  { id: "n3", kind: "scan_failed", category: "scans", severity: "warning", title: "Scan did not finish for acme.ng",
    body: "The check ran out of time.", link: "/scans", count: 1, read_at: null, created_at: daysAgo(1) },
  { id: "n4", kind: "member_joined", category: "members", severity: "info", title: "Ada Bello joined the workspace",
    body: "Members and their roles are listed on the Team tab in Settings.", link: "/settings?tab=team", count: 1, read_at: daysAgo(2), created_at: daysAgo(3) },
];

const h = await startHarness();
h.state.route = (p, method) => {
  if (p === "/api/v1/notifications" && method === "GET") return [200, { notifications: items, unread_count: 3, has_more: false }];
  if (/^\/api\/v1\/notifications\/[^/]+\/read$/.test(p)) return [200, {}];
  return undefined;
};

try {
  for (const [width, height] of [[390, 844], [320, 720]]) {
    const { page, close } = await h.newPage({ theme: "dark", reducedMotion: false });
    await page.setViewport({ width, height, hasTouch: true, isMobile: true, deviceScaleFactor: 1 });
    await page.goto(`${h.origin}/overview`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="notif-bell"]');
    await settle(page, 400);
    await page.click('[data-testid="notif-bell"]');
    await page.waitForSelector('[data-testid="notif-item"]');
    await sleep(300);
    const box = await page.$eval('[data-testid="notif-panel"]', (e) => {
      const b = e.getBoundingClientRect();
      return { left: Math.round(b.left), right: Math.round(window.innerWidth - b.right), top: Math.round(b.top), width: Math.round(b.width),
        overflow: document.documentElement.scrollWidth - window.innerWidth };
    });
    console.log(`${label} ${width}: ${JSON.stringify(box)}`);
    const file = `${out}/${label}-${width}.jpg`;
    await page.screenshot({ path: file, type: "jpeg", quality: 72 });
    console.log(`  ${file} ${Math.round(statSync(file).size / 1024)} KB`);

    if (label === "after" && width === 390) {
      const row = await page.$('[data-testid="notif-item"][data-id="n2"] .notif-swipe');
      const b = await row.boundingBox();
      const y = b.y + b.height / 2;
      await page.touchscreen.touchStart(b.x + b.width - 20, y);
      for (let i = 1; i <= 8; i++) { await page.touchscreen.touchMove(b.x + b.width - 20 - i * 12, y); await sleep(16); }
      await page.touchscreen.touchEnd();
      await sleep(350);
      const swipe = `${out}/${label}-390-swipe.jpg`;
      await page.screenshot({ path: swipe, type: "jpeg", quality: 72 });
      console.log(`  ${swipe} ${Math.round(statSync(swipe).size / 1024)} KB`);
    }
    await close();
  }
} finally {
  await h.close();
}
