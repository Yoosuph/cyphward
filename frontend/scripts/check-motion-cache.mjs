// Motion, skeletons and the read cache (docs/ui-motion-cache-2026-11-01). Every API call is answered from fixtures;
// nothing reaches a server.
//   1. skeletons: every customer route and subpage and every owner-console view, loaded cold with its data held
//      back, paints its skeleton before its data and never a blank content frame; the skeleton state has no
//      sideways scroll and, on phones (touch emulated), 44px control placeholders; when the data arrives the
//      cumulative layout shift stays under CLS_MAX, the first panel stays where the skeleton drew it and the other
//      panels land within PANEL_MAX px of the skeleton's panels — at 1440, 390 and 320
//   2. route changes: client-side navigation in both apps never shows a blank content frame; the shell stays mounted
//   3. motion: the page enters with the shared pageEnter animation (190 ms); with prefers-reduced-motion it has no
//      animation at all and skeletons do not shimmer, in both apps, on desktop and on a phone
//   4. cache: a revisit paints the last data at once (no skeleton) and revalidates; after an organisation switch
//      (invitation accepted) no frame shows the previous organisation's data, even when its request lands late;
//      sign-out empties the cache; tickets taken before a switch, sign-out or write cannot store; the owner scope is
//      separate; nothing the cache holds reaches localStorage or sessionStorage
// ONLY=<regex> limits part 1 to matching routes and skips parts 2–4; SKIP_ROUTES=1 skips part 1.
import assert from "node:assert/strict";
import { WIDTHS, settle, sleep, startHarness } from "./lib/ui-refine-harness.mjs";
import { APP_ROUTES, APP_SUBROUTES, OWNER_ROUTES, measureRoute, installProbes, ownerRoute } from "./lib/motion-cache-harness.mjs";

const CLS_MAX = 0.02;
// How far a loaded panel may sit from the nearest panel the skeleton drew. The skeletons follow each page's grid;
// what is left is how much text the data brings (a long title wrapping on a phone, a second row of cards).
const PANEL_MAX = 48;
// Views whose layout depends on the data more than that, with the reason (also listed in the audit).
const DATA_DEPENDENT = {
  "/findings": [64, "a finding's title and category wrap to two or three lines on phones"],
  "/scans": [100, "the coverage notice appears only for a scan with partial coverage"],
  "/admin/subscriptions": [100, "the invoices panel grows with the number of invoices"],
  "/admin/users/u1": [100, "memberships and sessions differ per user"],
  "/admin/newsletter/n1": [240, "the title and subtitle are the draft's subject and preview, which wrap on phones"],
};
const ONLY = process.env.ONLY ? new RegExp(process.env.ONLY) : null;

const h = await startHarness();
const results = [];
let failures = 0;
let checks = 0;
const check = (cond, msg) => { checks++; if (!cond) { failures++; console.error(`FAIL ${msg}`); } };

try {
  // 1. Skeletons before data, no blank frame, small layout shift, mobile targets.
  for (const route of [...APP_ROUTES, ...APP_SUBROUTES, ...OWNER_ROUTES]) {
    if ((ONLY && !ONLY.test(route)) || process.env.SKIP_ROUTES) continue;
    for (const [label, width, height] of WIDTHS) {
      const r = await measureRoute(h, route, { width, height, motion: true });
      const kinds = r.frames.map((f) => f.kind);
      const firstSkeleton = kinds.indexOf("skeleton");
      const firstContent = kinds.indexOf("content");
      results.push({ route, label, cls: r.cls, panels: r.jump?.panels ?? null });
      const at = `${route} @${label}`;
      check(r.errors.length === 0, `${at}: page errors ${r.errors.join(" | ")}`);
      check(firstSkeleton >= 0 && (firstContent === -1 || firstSkeleton < firstContent), `${at}: a skeleton paints before the data (${kinds.join(">")})`);
      check(!kinds.includes("blank"), `${at}: no blank content frame (${kinds.join(">")})`);
      check(r.cls <= CLS_MAX, `${at}: CLS ${r.cls} > ${CLS_MAX} ${JSON.stringify(r.shifts)}`);
      const limit = DATA_DEPENDENT[route]?.[0] ?? PANEL_MAX;
      check(r.jump && r.jump.panels !== null && r.jump.panels <= limit, `${at}: panels moved ${r.jump?.panels}px, over ${limit} (skeleton ${r.jump?.skeletonPanels} vs ${r.jump?.contentPanels})`);
      // The data region starts where the skeleton started.
      check(r.jump && Math.abs((r.jump.contentPanels[0] ?? 0) - (r.jump.skeletonPanels[0] ?? 0)) <= (DATA_DEPENDENT[route] ? limit : 8), `${at}: the first panel moved (skeleton ${r.jump?.skeletonPanels} vs ${r.jump?.contentPanels})`);
      check(r.overflow <= 0, `${at}: horizontal scroll ${r.overflow}px when loaded`);
      check(r.skeleton && r.skeleton.overflow <= 0, `${at}: horizontal scroll ${r.skeleton?.overflow}px in the skeleton`);
      check(!r.skeleton || r.skeleton.smallControls === 0, `${at}: ${r.skeleton?.smallControls} control placeholders under 44px`);
    }
  }

  if (!ONLY) {
    // 2. Route changes keep the shell and never show a blank content frame (customer app and owner console).
    for (const [start, links] of [["/overview", ["/findings", "/scans", "/comply", "/settings", "/overview"]], ["/admin", ["/organizations", "/users", "/logs", "/system", "/"]]]) {
      for (const [label, width, height] of [WIDTHS[0], WIDTHS[1]]) {
        const tab = await h.newPage({ reducedMotion: false });
        await tab.page.setViewport({ width, height, isMobile: width < 768, hasTouch: width < 768 });
        h.state.route = (p) => ownerRoute(p);
        await tab.page.goto(`${h.origin}${start}`, { waitUntil: "domcontentloaded" });
        await settle(tab.page, 600);
        const shell = await tab.page.evaluate(() => { window.__shellNode = document.querySelector(".shell-main"); return !!window.__shellNode; });
        assert.ok(shell, `${start}: the shell is mounted`);
        for (const to of links) {
          await tab.page.evaluate(installProbes);
          // Client-side navigation through the router: a visible nav link where the layout shows one, else history.
          const href = start.startsWith("/admin") ? `/admin${to === "/" ? "" : to}` : to;
          const clicked = await tab.page.evaluate((href) => {
            const a = [...document.querySelectorAll("a[href]")].find((n) => (n.getAttribute("href") === href || n.getAttribute("href") === `${href}/`) && n.offsetParent);
            if (a) { a.click(); return true; }
            return false;
          }, href);
          if (!clicked) await tab.page.evaluate((href) => { history.pushState({}, "", href); dispatchEvent(new PopStateEvent("popstate")); }, href);
          await settle(tab.page, 400);
          const { frames, same } = await tab.page.evaluate(() => { window.__mcStop = true; return { frames: window.__mc.frames.map((f) => f.kind), same: document.querySelector(".shell-main") === window.__shellNode }; });
          check(!frames.includes("blank") && !frames.includes("none"), `route change ${start} -> ${to} @${label}: no blank frame (${frames.join(">")})`);
          check(same, `route change ${start} -> ${to} @${label}: the shell stays mounted`);
        }
        h.state.route = null;
        await tab.close();
      }
    }

    // 3. Page motion: the shared enter animation, none with reduced motion (desktop and phone, both apps).
    for (const reducedMotion of [false, true]) {
      for (const [label, width, height] of [WIDTHS[0], WIDTHS[2]]) {
        for (const route of ["/overview", "/admin/organizations"]) {
          const tab = await h.newPage({ reducedMotion });
          await tab.page.setViewport({ width, height, isMobile: width < 768, hasTouch: width < 768 });
          h.state.route = (p) => ownerRoute(p);
          await tab.page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
          await tab.page.waitForSelector("main.page");
          const m = await tab.page.evaluate(() => {
            const cs = getComputedStyle(document.querySelector("main.page"));
            const sk = document.querySelector(".skeleton");
            return { name: cs.animationName, duration: cs.animationDuration, skeleton: sk ? getComputedStyle(sk).animationName : "none" };
          });
          if (reducedMotion) {
            check(m.name === "none", `reduced motion ${route} @${label}: no page transition (${m.name})`);
            check(m.skeleton === "none", `reduced motion ${route} @${label}: skeletons do not shimmer (${m.skeleton})`);
          } else {
            check(m.name === "pageEnter" && m.duration === "0.19s", `motion ${route} @${label}: the shared page enter (${m.name} ${m.duration})`);
          }
          h.state.route = null;
          await tab.close();
        }
      }
    }

    // 4a. Revisit: the last data paints at once while a fresh request runs (customer app and owner console).
    for (const [first, other, text] of [["/findings", "/assets", "Missing Email DMARC"], ["/admin/organizations", "/admin/users", "Kola Foods"]]) {
      const tab = await h.newPage();
      await tab.page.setViewport({ width: 1440, height: 900 });
      let slow = false;
      h.state.route = async (p) => { if (slow && !p.endsWith("/bootstrap") && !p.endsWith("/me") && !p.includes("notifications")) await sleep(1500); return ownerRoute(p); };
      await tab.page.goto(`${h.origin}${first}`, { waitUntil: "domcontentloaded" });
      await tab.page.waitForFunction((t) => document.querySelector("main")?.innerText.includes(t), { timeout: 8000 }, text);
      // Through the router: a visible nav link with that address (the console's links carry its /admin base).
      const nav = (to) => tab.page.evaluate((to) => {
        const a = [...document.querySelectorAll("a[href]")].find((n) => n.getAttribute("href") === to && n.offsetParent);
        if (a) a.click(); else { history.pushState({}, "", to); dispatchEvent(new PopStateEvent("popstate")); }
      }, to);
      await nav(other);
      await settle(tab.page, 300);
      slow = true;
      await nav(first);
      await sleep(250);
      const shown = await tab.page.evaluate((t) => ({ has: document.querySelector("main").innerText.includes(t), skeleton: !!document.querySelector('main [data-testid="state-loading"]') }), text);
      check(shown.has && !shown.skeleton, `revisit ${first}: cached data painted at once without a skeleton (${JSON.stringify(shown)})`);
      slow = false;
      h.state.route = null;
      await tab.close();
    }

    // 4b. Organisation switch: never a frame of the previous organisation's data, even if its request lands late.
    {
      const A = { id: "org-a", name: "Alpha Traders", slug: "alpha", plan: "growth", domains_count: 1, verified_domains_count: 1 };
      const B = { id: "org-b", name: "Bravo Foods", slug: "bravo", plan: "growth", domains_count: 1, verified_domains_count: 1 };
      const user = { id: "c1-user", email: "c1@example.test", full_name: "Compliance Review" };
      let accepted = false;
      let slowA = 0;
      const finding = (org, title) => ({ id: `${org}-f1`, org_id: org, title, description: title, severity: "high", category: "DNS & Email Security", status: "open",
        hostname: "x.example.test", created_at: "2026-10-16T09:00:00Z", first_seen_at: "2026-10-16T09:00:00Z", last_seen_at: "2026-10-16T09:00:00Z", confidence: "confirmed" });
      h.state.route = async (p, method, request) => {
        const org = request.headers()["x-organization-id"];
        if (p.endsWith("/auth/bootstrap")) return [200, { user, email_verified: true, memberships: [{ org: A, role: "owner", domains: [] }, ...(accepted ? [{ org: B, role: "member", domains: [] }] : [])] }];
        if (p.endsWith("/members/invites/accept")) { accepted = true; return [200, { message: "Invitation accepted.", organization: { id: B.id, name: B.name } }]; }
        if (p.endsWith("/findings")) {
          if (org === A.id && slowA) await sleep(slowA);
          const f = org === A.id ? finding(A.id, "Alpha-only exposed admin panel") : finding(B.id, "Bravo open resolver");
          return [200, { findings: [f], total: 1, categories: { [f.category]: 1 } }];
        }
        return undefined;
      };
      const tab = await h.newPage();
      await tab.page.setViewport({ width: 1440, height: 900 });
      await tab.page.goto(`${h.origin}/findings`, { waitUntil: "domcontentloaded" });
      await tab.page.waitForFunction(() => document.querySelector("main")?.innerText.includes("Alpha-only"), { timeout: 8000 });
      // Watch every mutation: once the shell names organisation B, main must never contain A's data.
      await tab.page.evaluate(() => {
        window.__leaks = [];
        new MutationObserver(() => {
          const tenant = document.querySelector(".side-tenant")?.textContent || "";
          const main = document.querySelector("main")?.innerText || "";
          if (/Bravo/.test(tenant) && main.includes("Alpha-only")) window.__leaks.push(performance.now());
        }).observe(document.body, { subtree: true, childList: true, characterData: true });
      });
      // A's revalidation is in flight (slow, cached A on screen) when the invitation switches the workspace to B.
      const go = (url) => tab.page.evaluate((url) => { history.pushState({}, "", url); dispatchEvent(new PopStateEvent("popstate")); }, url);
      await go("/assets");
      await settle(tab.page, 300);
      slowA = 2500;
      await go("/findings");
      await sleep(100);
      check(await tab.page.evaluate(() => document.querySelector("main").innerText.includes("Alpha-only")), "organisation switch: A's cached findings show while A revalidates");
      await go("/findings?invite=tok-b");
      await tab.page.waitForFunction(() => /Bravo/.test(document.querySelector(".side-tenant")?.textContent || ""), { timeout: 8000 });
      await tab.page.waitForFunction(() => document.querySelector("main")?.innerText.includes("Bravo open resolver"), { timeout: 8000 })
        .catch(() => check(false, "organisation switch: the page reloads for the new organisation (it still shows the old one)"));
      await sleep(3000); // A's late response lands
      const leaks = await tab.page.evaluate(() => window.__leaks.length);
      check(leaks === 0, `organisation switch: ${leaks} frames showed the previous organisation's findings`);
      check(!(await tab.page.evaluate(() => document.querySelector("main").innerText.includes("Alpha-only"))), "organisation switch: A's late response is not shown");
      // Leave and come back: the cache has nothing from A.
      await go("/assets");
      await settle(tab.page, 300);
      await go("/findings");
      await sleep(150);
      check(!(await tab.page.evaluate(() => document.querySelector("main").innerText.includes("Alpha-only"))), "organisation switch: a revisit never paints A's cached findings");
      check((await tab.page.evaluate(() => window.__leaks.length)) === 0, "organisation switch: no leak on revisit");
      // Nothing from the cache reaches Web Storage.
      const stored = await tab.page.evaluate(() => [localStorage, sessionStorage].flatMap((s) => Object.keys(s).map((k) => s.getItem(k) || "")).join("\n"));
      check(!/Alpha-only|Bravo open resolver/.test(stored), "no cached customer data in localStorage or sessionStorage");
      // Sign-out empties the cache (same module instance the app uses).
      await tab.page.evaluate(() => [...document.querySelectorAll("button.side-out")].find((b) => b.offsetParent)?.click());
      await tab.page.waitForFunction(() => location.pathname.startsWith("/login"), { timeout: 8000 });
      const size = await tab.page.evaluate(async () => (await import("/src/lib/queryCache.ts")).queryCacheSize());
      check(size === 0, `sign-out: the cache is empty (${size} entries)`);
      h.state.route = null;
      await tab.close();
    }

    // 4c. The cache rules themselves, in the browser against the module the app loads.
    {
      const tab = await h.newPage();
      await tab.page.goto(`${h.origin}/overview`, { waitUntil: "domcontentloaded" });
      await settle(tab.page, 300);
      const r = await tab.page.evaluate(async () => {
        const q = await import("/src/lib/queryCache.ts");
        const session = JSON.parse(localStorage.getItem("cyphward-session"));
        const setUser = (id) => localStorage.setItem("cyphward-session", JSON.stringify({ ...session, user: { ...session.user, id } }));
        const setOrg = (id) => { localStorage.setItem("cyphward-org-id", id); sessionStorage.setItem("cyphward-org-id", id); };
        const out = {};
        q.clearQueryCache();
        setOrg("org-1"); setUser("user-1");
        out.stored = q.writeQueryCache("k", "org-1 data", q.cacheTicket());
        setOrg("org-2");
        out.otherOrgRead = q.readQueryCache("k")?.data ?? null;
        setOrg("org-1");
        out.backRead = q.readQueryCache("k")?.data ?? null;
        setUser("user-2");
        out.otherUserRead = q.readQueryCache("k")?.data ?? null;
        setUser("user-1");
        let t = q.cacheTicket(); setOrg("org-2");
        out.lateWriteAfterSwitch = q.writeQueryCache("k2", "x", t); setOrg("org-1");
        t = q.cacheTicket(); q.clearQueryCache();
        out.lateWriteAfterClear = q.writeQueryCache("k3", "x", t);
        q.setOwnerScope("owner-a@example.test");
        out.ownerStored = q.writeQueryCache("v", "owner view", q.cacheTicket("owner"));
        out.appSeesOwner = q.readQueryCache("v")?.data ?? null;
        q.setOwnerScope("owner-b@example.test");
        out.otherOwnerRead = q.readQueryCache("v", "owner")?.data ?? null;
        q.setOwnerScope(null);
        q.clearQueryCache();
        out.sizeAfterClear = q.queryCacheSize();
        return out;
      });
      check(r.stored === true, "cache: a read result is stored for its scope");
      check(r.otherOrgRead === null, "cache: another organisation never reads it");
      check(r.backRead === "org-1 data", "cache: its own organisation reads it");
      check(r.otherUserRead === null, "cache: another user never reads it");
      check(r.lateWriteAfterSwitch === false, "cache: a request started before an organisation switch cannot store");
      check(r.lateWriteAfterClear === false, "cache: a request started before sign-out or a write cannot store");
      check(r.ownerStored === true && r.appSeesOwner === null, "cache: the owner console has its own scope");
      check(r.otherOwnerRead === null, "cache: another owner never reads it");
      check(r.sizeAfterClear === 0, "cache: clearing empties it");
      await tab.close();
    }
  }
} finally {
  await h.close();
}

const worst = (filter) => results.filter(filter).reduce((m, r) => ({ cls: Math.max(m.cls, r.cls), panels: Math.max(m.panels, r.panels ?? 0) }), { cls: 0, panels: 0 });
for (const label of ["1440", "390", "320"]) {
  const app = worst((r) => r.label === label && !r.route.startsWith("/admin"));
  const owner = worst((r) => r.label === label && r.route.startsWith("/admin"));
  console.log(`worst @${label}: customer CLS ${app.cls} panels ${app.panels}px · owner CLS ${owner.cls} panels ${owner.panels}px`);
}
if (failures) {
  console.error(`motion/cache: ${failures} of ${checks} checks failed`);
  process.exit(1);
}
console.log(`motion/cache: ok (${checks} checks, ${results.length} route loads at 1440/390/320: skeleton before data, no blank frame, CLS <= ${CLS_MAX}, panels within ${PANEL_MAX}px (data-dependent views listed), no sideways scroll, 44px placeholders on phones; route changes keep the shell with no blank frame; pageEnter and reduced motion in both apps; revisit paints cached data; organisation switch, sign-out, tickets and owner scope)`);
