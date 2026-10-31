// Owner console phase 1 (docs/admin-2026-10-29): analytics, management lists and the typed-name gate. Every API call
// is answered from fixtures; nothing reaches a server.
//   - analytics: the KPI strip (values from the summary), the time-range selector (7/30/90 sent as range=), both
//     charts, subscription status counts and newsletter counts
//   - organizations: sorting by header button (pointer and keyboard) with aria-sort and the server sort parameters,
//     the Sort control, a filter (billing) sent to the server, the CSV export carrying the same filters
//   - suspend: the confirm button stays disabled until the reason is written and the organization's exact name is
//     typed (case and trailing space refused); nothing is sent before that; the body carries confirm_name
//   - errors: a raw server body (500 traceback, 422 validation array, 503) never reaches the screen, on a list or in
//     an action dialog; reviewed wording is shown instead
//   - the audit (no horizontal scroll, 44px targets on phones, labels, names, heading order, focus rings, contrast,
//     no claim wording) at 1440, 390 and 320, reduced motion on
// CAPTURE=1 also writes screenshots at 1440 and 390 to docs/admin-2026-10-29/ (JPEG, each under 250 KB).
import assert from "node:assert/strict";
import { mkdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { WIDTHS, audit, frontend, settle, sleep, startHarness } from "./lib/ui-refine-harness.mjs";

const SHOTS = join(frontend, "..", "docs", "admin-2026-10-29");
const CAPTURE = process.env.CAPTURE === "1";
const RAW = "Traceback (most recent call last): psycopg.errors.QueryCanceled at owner_reads.py line 40";

const ORG_ID = "0a000000-0000-4000-8000-000000000001";
const ORG_NAME = "Acme Traders Ltd";
const orgs = [
  { id: ORG_ID, name: ORG_NAME, slug: "acme", plan: "growth", billing: "paid", subscription_status: "active", suspended: false,
    members: 4, owner_email: "owner@acme.example", domains: 3, domains_verified: 2, last_scan_at: "2026-10-28T09:00:00Z",
    last_scan_status: "completed", created_at: "2026-09-01T00:00:00Z" },
  { id: "0a000000-0000-4000-8000-000000000002", name: "Kola Foods", slug: "kola", plan: "starter", billing: "trialing",
    subscription_status: "trialing", suspended: false, members: 1, owner_email: "ops@kola.example", domains: 1, domains_verified: 1,
    last_scan_at: null, last_scan_status: null, created_at: "2026-10-20T00:00:00Z" },
  { id: "0a000000-0000-4000-8000-000000000003", name: "Bello Logistics", slug: "bello", plan: "growth", billing: "free",
    subscription_status: null, suspended: true, members: 2, owner_email: "it@bello.example", domains: 0, domains_verified: 0,
    last_scan_at: "2026-10-01T09:00:00Z", last_scan_status: "failed", created_at: "2026-08-15T00:00:00Z" },
];
const SORTERS = {
  name: (o) => o.name.toLowerCase(), members: (o) => o.members, created: (o) => o.created_at, plan: (o) => o.plan,
  domains: (o) => o.domains, last_scan: (o) => o.last_scan_at || "",
};
const days = (n) => Array.from({ length: n }, (_, i) => new Date(Date.UTC(2026, 9, 29 - (n - 1) + i)).toISOString().slice(0, 10));
const summary = (n) => ({
  as_of: 1793000000, range_days: n, since: `${days(n)[0]}T00:00:00+00:00`,
  organizations: { total: 41, new_in_range: n === 7 ? 3 : 9, suspended: 1 },
  billing: { paid: 12, trialing: 7, free: 22 },
  subscription_status: [{ status: "active", count: 12 }, { status: "lapsed", count: 2 }, { status: "trialing", count: 7 }],
  scans: { total: 120, queued: 1, running: 2, completed: 100, failed: 15, cancelled: 2, success_rate: 0.8696, failure_rate: 0.1304 },
  users: { total: 128, new_in_range: 11 },
});
const series = (n) => ({
  as_of: 1793000000, range_days: n, truncated: false,
  scans_per_day: days(n).map((day, i) => ({ day, total: i % 3, completed: i % 3 === 2 ? 1 : 0, failed: i % 3 === 1 ? 1 : 0, cancelled: i % 3 === 2 ? 1 : 0, queued: 0, running: 0 })),
  findings_per_day: days(n).map((day, i) => ({ day, critical: i % 5 === 0 ? 1 : 0, high: i % 4 === 0 ? 2 : 0, medium: 1, low: 0, info: 0 })),
});
const detail = (suspended) => ({
  organization: { id: ORG_ID, name: ORG_NAME, slug: "acme", plan: "growth", sector: "Retail", created_at: "2026-09-01T00:00:00Z", suspended, suspension_changed_at: suspended ? "2026-10-29T08:00:00Z" : null },
  members: [
    { id: "u1", email: "owner@acme.example", full_name: "Ada Owner", role: "owner", last_seen_at: "2026-10-28T09:00:00Z" },
    { id: "u2", email: "dev@acme.example", full_name: null, role: "member", last_seen_at: null },
  ],
  domains: [{ id: "d1", domain: "acme.example", verification_status: "verified", verified_at: "2026-09-02T00:00:00Z" }],
  subscriptions: [{ plan: "growth", status: "active", current_period_end: "2026-11-20T00:00:00Z" }],
  invoices: [], scans: [], open_findings: [{ severity: "high", n: 2 }], activity: [],
  owner_actions: [{ created_at: "2026-10-27T10:00:00Z", action: "owner.action.change_plan", outcome: "success", actor_email: "owner@example.test", reason: "Customer asked by email" }],
  plans: [{ slug: "starter", label: "Starter" }, { slug: "growth", label: "Growth" }],
});

const h = await startHarness();
const problems = [];
const net = { orgLists: [], exports: [], posts: [], analytics: [] };
let suspended = false;
let failList = null; // [status, body] for GET /owner/organizations
let failAction = null; // [status, body] for POST .../suspend

h.state.route = (p, method, request) => {
  const url = new URL(request.url());
  if (p === "/api/v1/owner/analytics/summary") { net.analytics.push(url.search); return [200, summary(Number(url.searchParams.get("range") || 30))]; }
  if (p === "/api/v1/owner/analytics/timeseries") return [200, series(Number(url.searchParams.get("range") || 30))];
  if (p === "/api/v1/newsletter/stats") return [200, { confirmed: 340, unsubscribed: 12, pending: 3 }];
  if (p === "/api/v1/owner/organizations" && method === "GET") {
    net.orgLists.push(Object.fromEntries(url.searchParams));
    if (failList) return failList;
    const sp = url.searchParams;
    let items = orgs.filter((o) => !sp.get("billing") || o.billing === sp.get("billing"));
    const key = SORTERS[sp.get("sort") || "created"];
    items = [...items].sort((a, b) => (key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0));
    if ((sp.get("dir") || "desc") === "desc") items.reverse();
    return [200, { items, total: items.length, limit: 50, offset: 0, sort: sp.get("sort") || "created", dir: sp.get("dir") || "desc" }];
  }
  if (p === `/api/v1/owner/organizations/${ORG_ID}` && method === "GET") return [200, detail(suspended)];
  if (p === "/api/v1/owner/users" && method === "GET") {
    return [200, { total: 2, limit: 50, offset: 0, items: [
      { id: "u1", email: "owner@acme.example", full_name: "Ada Owner", mfa: "authenticator", email_verified: true, memberships: [{ org_id: ORG_ID, name: ORG_NAME, role: "owner" }], last_sign_in_at: "2026-10-28T09:00:00Z", active_sessions: 1, created_at: "2026-09-01T00:00:00Z" },
      { id: "u2", email: "dev@acme.example", full_name: null, mfa: "none", email_verified: false, memberships: [{ org_id: ORG_ID, name: ORG_NAME, role: "member" }], last_sign_in_at: null, created_at: "2026-10-02T00:00:00Z" },
    ] }];
  }
  if (p === "/api/v1/owner/subscriptions" && method === "GET") {
    return [200, { total: 1, limit: 50, offset: 0, invoices: [], items: [
      { id: "s1", org_id: ORG_ID, org_name: ORG_NAME, plan: "growth", status: "active", effective_status: "active", provider: "manual", current_period_end: "2026-11-20T00:00:00Z", trial_ends_at: null, created_at: "2026-09-01T00:00:00Z" },
    ] }];
  }
  if (p.startsWith("/api/v1/owner/exports/")) {
    net.exports.push({ path: p, params: Object.fromEntries(url.searchParams) });
    return undefined; // answered below as CSV
  }
  if (method === "POST" && p.startsWith(`/api/v1/owner/organizations/${ORG_ID}/`)) {
    const body = JSON.parse(request.postData() || "{}");
    net.posts.push({ path: p, body });
    if (failAction) return failAction;
    if (p.endsWith("/suspend")) { suspended = true; return [200, { organization_id: ORG_ID, suspended: true, changed_at: "2026-10-29T08:00:00Z" }]; }
    if (p.endsWith("/unsuspend")) { suspended = false; return [200, { organization_id: ORG_ID, suspended: false, changed_at: "2026-10-29T08:05:00Z" }]; }
  }
  return undefined;
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
  await tab.page.setViewport({ width, height });
  await tab.page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
  await settle(tab.page, 500);
  return tab;
}

const text = (page) => page.evaluate(() => document.body.innerText);
const rowIds = (page) => page.$$eval('[data-testid="org-table-row"]', (rows) => rows.map((r) => r.dataset.id));
const ariaSort = (page) => page.$$eval('[data-testid="org-table"] thead th', (ths) => Object.fromEntries(ths.filter((t) => t.hasAttribute("aria-sort")).map((t) => [t.textContent.trim(), t.getAttribute("aria-sort")])));
const okDisabled = (page) => page.$eval('[role="dialog"] [data-testid="confirm-ok"]', (b) => b.disabled);
const lastList = () => net.orgLists[net.orgLists.length - 1];

async function shot(page, name) {
  if (!CAPTURE) return;
  mkdirSync(SHOTS, { recursive: true });
  const path = join(SHOTS, `${name}.jpg`);
  await page.evaluate(() => { if (!document.activeElement?.closest('[role="dialog"]')) document.activeElement?.blur?.(); window.scrollTo(0, 0); });
  await page.mouse.move(0, 0);
  await sleep(150);
  await page.screenshot({ path, type: "jpeg", quality: 70 });
  const kb = statSync(path).size / 1024;
  assert.ok(kb < 250, `${name}.jpg is ${kb.toFixed(0)} KB (keep it under 250 KB)`);
}

async function typeInto(page, selector, value) {
  await page.$eval(selector, (el) => { el.focus(); el.select?.(); });
  await page.keyboard.down("Control"); await page.keyboard.press("a"); await page.keyboard.up("Control");
  await page.keyboard.press("Backspace");
  if (value) await page.keyboard.type(value);
}

try {
  // 1. Analytics: KPI strip, range selector, charts, subscription and newsletter counts.
  {
    const { page, close } = await open("/admin/analytics");
    await page.waitForSelector('[data-testid="kpi-strip"]');
    const kpi = await page.$$eval('[data-testid="kpi-strip"]', (s) => s.map((x) => x.innerText.replace(/\s+/g, " ")).join(" | "));
    for (const want of [/ORGANIZATIONS 41/i, /PAID 12/i, /TRIALING 7/i, /FREE 22/i, /COMPLETED SHARE 87%/, /FAILED SHARE 13%/, /USERS 128/i]) assert.match(kpi, want, `KPI strip shows ${want}`);
    assert.equal(net.analytics.at(-1), "?range=30", "30 days by default");
    assert.ok(await page.$('[data-testid="scans-chart"]') && await page.$('[data-testid="findings-chart"]'), "both charts drawn");
    assert.match(await page.$eval('[data-testid="newsletter-counts"]', (e) => e.innerText), /340/, "newsletter counts shown");
    assert.match(await page.$eval('[data-testid="subscription-status-counts"]', (e) => e.innerText), /lapsed/i);
    const pressed = () => page.$$eval('[data-testid="range-selector"] button', (bs) => bs.map((b) => `${b.textContent.trim()}:${b.getAttribute("aria-pressed")}`));
    assert.deepEqual(await pressed(), ["7 DAYS:false", "30 DAYS:true", "90 DAYS:false"]);
    const [b90] = await page.$$('[data-testid="range-selector"] button').then((bs) => bs.slice(2));
    await b90.click();
    await settle(page, 300);
    assert.equal(net.analytics.at(-1), "?range=90", "the range is sent to the server");
    assert.equal(await page.$$eval('[data-testid="scans-chart"] [role="img"] > div', (d) => d.length), 90, "90 bars for 90 days");
    assert.match(await text(page), /\+9 in 90 days/);
    await page.focus('[data-testid="range-selector"] button');
    await page.keyboard.press("Enter");
    await settle(page, 300);
    assert.equal(net.analytics.at(-1), "?range=7", "keyboard selects a range");
    await shot(page, "analytics-1440");
    await close();
  }

  // 2. Organizations: sorting by header (pointer and keyboard) with aria-sort, the sort control, a filter, export.
  {
    const { page, close } = await open("/admin/organizations");
    await page.waitForSelector('[data-testid="org-table"]');
    assert.deepEqual(await rowIds(page), [orgs[1].id, orgs[0].id, orgs[2].id], "created, newest first by default");
    assert.equal((await ariaSort(page))["CREATED"], "descending");
    assert.equal((await ariaSort(page))["MEMBERS"], "none");
    await page.click('[data-testid="org-table"] [data-sort-key="members"]');
    await settle(page, 300);
    assert.equal(lastList().sort, "members"); assert.equal(lastList().dir, "desc", "counts start largest first");
    assert.deepEqual(await rowIds(page), [orgs[0].id, orgs[2].id, orgs[1].id]);
    assert.equal((await ariaSort(page))["MEMBERS"], "descending");
    assert.equal((await ariaSort(page))["CREATED"], "none");
    await page.click('[data-testid="org-table"] [data-sort-key="members"]');
    await settle(page, 300);
    assert.equal(lastList().dir, "asc"); assert.equal((await ariaSort(page))["MEMBERS"], "ascending");
    // Keyboard: Tab to the Organization header button and press Enter, then Space.
    await page.focus('[data-testid="org-table"] [data-sort-key="name"]');
    await page.keyboard.press("Enter");
    await settle(page, 300);
    assert.equal(lastList().sort, "name"); assert.equal(lastList().dir, "asc");
    assert.equal((await ariaSort(page))["ORGANIZATION"], "ascending");
    assert.deepEqual(await rowIds(page), [orgs[0].id, orgs[2].id, orgs[1].id], "name A to Z");
    await page.focus('[data-testid="org-table"] [data-sort-key="name"]');
    await page.keyboard.press("Space");
    await settle(page, 300);
    assert.equal((await ariaSort(page))["ORGANIZATION"], "descending", "Space reverses");
    // The Sort control (the phone layout's way to sort) drives the same parameters.
    await page.select("#org-sort", "created:asc");
    await settle(page, 300);
    assert.equal(lastList().sort, "created"); assert.equal(lastList().dir, "asc");
    // A filter goes to the server and the table shows its answer.
    await page.select("#org-billing", "paid");
    await settle(page, 300);
    assert.equal(lastList().billing, "paid");
    assert.deepEqual(await rowIds(page), [ORG_ID]);
    assert.match(await page.$eval("h1", (e) => e.closest(".mb-6")?.innerText || ""), /1 workspace match/);
    await shot(page, "organizations-1440");
    await close();
  }

  // 3. Suspend: the typed-name gate.
  {
    suspended = false;
    const { page, close } = await open(`/admin/organizations/${ORG_ID}`);
    await page.click('[data-testid="org-suspend-open"]');
    await page.waitForSelector('[role="dialog"] [data-testid="typed-name-gate"]');
    await sleep(200);
    assert.equal(await okDisabled(page), true, "disabled when the dialog opens");
    // Phase 2 replaced the "marker only" wording with the enforced rule (check-admin-phase2.mjs covers the customer side).
    assert.match(await page.$eval('[role="dialog"]', (d) => d.innerText), /members can still sign in and read their data, but changes that add something are refused/i, "the dialog states the suspension rule");
    await typeInto(page, "#owner-action-reason", "Customer asked by email, ticket 42");
    assert.equal(await okDisabled(page), true, "a reason alone is not enough");
    for (const wrong of [ORG_NAME.toLowerCase(), `${ORG_NAME} `, "Acme Traders"]) {
      await typeInto(page, "#owner-action-typed-name", wrong);
      assert.equal(await okDisabled(page), true, `"${wrong}" keeps the button disabled`);
      await page.$eval('[role="dialog"] form', (f) => f.requestSubmit());
      await page.keyboard.press("Enter");
      await sleep(150);
    }
    assert.equal(net.posts.length, 0, "nothing is sent before the name matches");
    await typeInto(page, "#owner-action-typed-name", ORG_NAME);
    assert.equal(await okDisabled(page), false, "the exact name enables the button");
    await page.click('[role="dialog"] [data-testid="confirm-ok"]');
    await settle(page, 400);
    assert.equal(net.posts.length, 1);
    assert.deepEqual(net.posts[0], { path: `/api/v1/owner/organizations/${ORG_ID}/suspend`, body: { reason: "Customer asked by email, ticket 42", confirm_name: ORG_NAME } });
    assert.ok(await page.$('[data-testid="org-suspended-note"]'), "the page shows the suspension after a reload");
    assert.ok(await page.$('[data-testid="org-unsuspend-open"]'), "and offers to lift it");
    await shot(page, "organization-detail-1440");
    // An action error never shows the server's raw text.
    for (const reply of [[500, { detail: RAW }], [422, { detail: [{ loc: ["body", "confirm_name"], msg: "Field required" }] }], [503, { detail: "upstream connect error or disconnect/reset before headers" }]]) {
      failAction = reply;
      await page.click('[data-testid="org-unsuspend-open"]');
      await page.waitForSelector('[role="dialog"] #owner-action-typed-name');
      await sleep(200);
      await typeInto(page, "#owner-action-reason", "Checking the error wording");
      await typeInto(page, "#owner-action-typed-name", ORG_NAME);
      await page.click('[role="dialog"] [data-testid="confirm-ok"]');
      await page.waitForSelector('[data-testid="owner-action-error"]');
      const shown = await page.$eval('[data-testid="owner-action-error"]', (e) => e.innerText);
      assert.doesNotMatch(shown, /traceback|psycopg|owner_reads|field required|upstream|\[|\{|request failed/i, `${reply[0]}: no raw text`);
      assert.match(shown, reply[0] === 422 ? /not accepted/ : /could not complete/, `${reply[0]}: reviewed wording`);
      await page.keyboard.press("Escape");
      await sleep(200);
      if (await page.$('[role="dialog"]')) { await page.keyboard.press("Escape"); await sleep(200); }
      const discard = await page.$$('[role="dialog"] button');
      for (const b of discard) if (/discard|close without/i.test(await b.evaluate((x) => x.textContent))) { await b.click(); break; }
      await sleep(250);
    }
    failAction = null;
    await close();
  }

  // 4. A list error never shows the server's raw text either.
  {
    failList = [500, { detail: RAW }];
    const { page, close } = await open("/admin/organizations");
    await page.waitForSelector('[data-testid="state-error"]');
    const body = await text(page);
    assert.doesNotMatch(body, /traceback|psycopg|owner_reads/i, "no raw server text on a list error");
    assert.match(body, /could not complete this/i);
    failList = [503, { detail: "This view took too long to load. Narrow the filters or try again in a moment." }];
    await page.click('[data-testid="state-error"] button');
    await settle(page, 300);
    assert.match(await text(page), /took too long to load/, "a reviewed server sentence is shown as written");
    failList = null;
    await close();
  }

  // 5. Export carries the visible filter.
  {
    const { page, close } = await open("/admin/users?mfa=none&sort=email&dir=asc");
    await page.waitForSelector('[data-testid="user-table"]');
    await page.click('[data-testid="owner-export"]');
    await settle(page, 300);
    const ex = net.exports.at(-1);
    assert.equal(ex.path, "/api/v1/owner/exports/users.csv");
    assert.deepEqual(ex.params, { mfa: "none", sort: "email", dir: "asc" });
    await close();
  }

  // 6. Layout and accessibility audit at 1440, 390 and 320 (light and dark), screenshots at 390.
  suspended = false;
  for (const [label, width, height] of WIDTHS) {
    const mobile = width < 900;
    for (const [name, route] of [["analytics", "/admin/analytics"], ["organizations", "/admin/organizations"],
      ["organization-detail", `/admin/organizations/${ORG_ID}`], ["users", "/admin/users"], ["subscriptions", "/admin/subscriptions"]]) {
      for (const theme of ["dark", "light"]) {
        const { page, close } = await open(route, { width, height, theme });
        check(`${name} ${label} ${theme}`, await audit(page, { mobile }));
        if (theme === "dark" && label === "390" && ["analytics", "organizations", "organization-detail"].includes(name)) await shot(page, `${name}-390`);
        await close();
      }
    }
    // The suspend dialog on this width: no overflow, gate present.
    const { page, close } = await open(`/admin/organizations/${ORG_ID}`, { width, height });
    await page.click('[data-testid="org-suspend-open"]');
    await page.waitForSelector('[role="dialog"] [data-testid="typed-name-gate"]');
    await sleep(250);
    check(`suspend dialog ${label}`, await audit(page, { mobile, tabStops: 0 }));
    assert.equal(await okDisabled(page), true);
    if (label === "390") await shot(page, "suspend-dialog-390");
    await close();
  }

  assert.deepEqual(problems, [], `audit problems:\n${problems.join("\n")}`);
  console.log("admin phase 1: ok (KPI strip and range selector, charts, sorting with aria-sort by pointer and keyboard, sort control, " +
    "billing filter, export with the visible filter, typed-name gate on suspend (disabled until exact), no raw server text on " +
    "list or action errors, audit at 1440/390/320 in both themes)");
} finally {
  await h.close();
}
