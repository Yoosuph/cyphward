// Admin phase 2 (docs/admin-phase2-2026-10-31): the customer side of a suspension, the plain scan-failure sentence and
// the owner's restore-member action. Every API call is answered from fixtures; nothing reaches a server.
//   - suspended organisation: the banner is on every customer page (what still works, who to contact: the existing
//     info@cyphward.com and the contact page), and the main write buttons are disabled with an explanation
//   - an active organisation: no banner, the same buttons enabled
//   - a suspension that starts mid-session: the first write refused with organization_suspended shows the banner and
//     disables the button, never raw server text
//   - a failed scan shows the reviewed sentence from its failure code
//   - owner console: the suspension note states the enforced rule; a removed member can be restored behind the
//     typed-name gate (the body carries the audit id); a suspended organisation offers no restore; the scan page
//     shows the customer's sentence next to the raw error (owner only)
//   - layout audit of the banner at 1440, 390 and 320 in dark and light: no horizontal scroll, no claim wording
import assert from "node:assert/strict";
import { WIDTHS, audit, settle, sleep, startHarness } from "./lib/ui-refine-harness.mjs";
import { domain, org, user } from "./lib/compliance-fixtures.mjs";

const SUSPENDED_MESSAGE = "This organisation is suspended, so changes are paused. You can still sign in and read your " +
  "dashboards, scans, findings, reports and compliance pages. To ask about it, contact us at info@cyphward.com or through the contact page.";
const ORG_ID = "0a000000-0000-4000-8000-000000000001";
const ORG_NAME = "Acme Traders Ltd";
const AUDIT_ID = "5a000000-0000-4000-8000-0000000000a1";

const h = await startHarness();
let suspended = true;
let refuseWrites = false;
const posts = [];

const failedScan = {
  id: "s-failed", domain: "acme.ng", status: "failed", score: null, created_at: "2026-10-30T06:00:00Z", findings_discovered: 0,
  current_stage: "http", failure: { code: "blocked", message: "The site blocked our check." },
  stage_progress: { discovery: { status: "completed", items: 2 }, http: { status: "failed", error: "This check did not finish." } },
};
const ownerDetail = (orgSuspended) => ({
  organization: { id: ORG_ID, name: ORG_NAME, slug: "acme", plan: "growth", sector: "Retail", created_at: "2026-09-01T00:00:00Z",
    suspended: orgSuspended, suspension_changed_at: orgSuspended ? "2026-10-30T08:00:00Z" : null },
  members: [{ id: "u1", email: "owner@acme.example", full_name: "Ada Owner", role: "owner", last_seen_at: "2026-10-28T09:00:00Z" }],
  removed_members: [
    { audit_id: AUDIT_ID, email: "dev@acme.example", role: "member", removed_at: "2026-10-29T10:00:00Z", restored: false, is_member: false },
    { audit_id: "5a000000-0000-4000-8000-0000000000a2", email: "old@acme.example", role: "admin", removed_at: "2026-10-20T10:00:00Z", restored: true, is_member: true },
  ],
  domains: [], subscriptions: [], invoices: [], scans: [], open_findings: [], activity: [], owner_actions: [],
  plans: [{ slug: "starter", label: "Starter" }, { slug: "growth", label: "Growth" }],
});
let ownerOrgSuspended = false;

h.state.route = (p, method, request) => {
  if (p.endsWith("/auth/bootstrap")) {
    return [200, { user, email_verified: true, memberships: [{ org: { ...org, display_timezone: "Africa/Lagos", suspended }, role: "owner", domains: [domain] }] }];
  }
  if (p === "/api/v1/scans" && method === "GET") return [200, [failedScan]];
  if (p === `/api/v1/scans/${failedScan.id}`) return [200, { scan: failedScan, raw_results: [], targets: [] }];
  if (p.startsWith("/api/v1/owner/organizations/") && method === "GET") return [200, ownerDetail(ownerOrgSuspended)];
  if (p === "/api/v1/owner/scans/sc1") {
    return [200, { scan: { id: "sc1", org_id: ORG_ID, org_name: ORG_NAME, domain: "acme.ng", status: "failed", state: "failed",
      error_message: "http: httpx.ConnectError [Errno 111] at 10.0.0.7", failure: { code: "unreachable", message: "We could not reach the site." },
      created_at: "2026-10-30T06:00:00Z", coverage: {} }, stages: [], hosts: [] }];
  }
  if (method !== "GET" && p.startsWith("/api/v1/owner/")) {
    posts.push({ path: p, body: JSON.parse(request.postData() || "{}") });
    return [200, { organization_id: ORG_ID, restored_user_id: "u2", role: "member", members: 2 }];
  }
  if (method !== "GET" && refuseWrites && !p.startsWith("/api/v1/auth/")) {
    return [403, { detail: { code: "organization_suspended", message: SUSPENDED_MESSAGE } }];
  }
  return undefined;
};

async function open(route, { width = 1440, height = 900, theme = "dark" } = {}) {
  const tab = await h.newPage({ theme });
  await tab.page.setViewport({ width, height });
  await tab.page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
  await settle(tab.page, 600);
  return tab;
}
const text = (page) => page.evaluate(() => document.body.innerText);
const banner = (page) => page.$('[data-testid="org-suspended-banner"]');
const writeStates = (page) => page.$$eval("[data-write]", (els) => els.map((e) => ({ write: e.dataset.write, disabled: e.disabled, title: e.title })));
const okDisabled = (page) => page.$eval('[role="dialog"] [data-testid="confirm-ok"]', (b) => b.disabled);
async function typeInto(page, selector, value) {
  await page.$eval(selector, (el) => { el.focus(); el.select?.(); });
  await page.keyboard.down("Control"); await page.keyboard.press("a"); await page.keyboard.up("Control");
  await page.keyboard.press("Backspace");
  if (value) await page.keyboard.type(value);
}

// Each page and the write buttons it must show disabled while suspended.
const PAGES = [
  ["/overview", ["scan-launch"]],
  ["/scans", ["scan-launch"]],
  ["/domains", ["domain-add", "domain-verify", "domain-remove"]],
  ["/settings", ["settings-save"], "#settings-tab-team", ["member-invite"]],
  ["/reports", ["report-generate"]],
  ["/remediation", ["remediation-create"]],
  ["/findings", []],
  ["/assets", []],
  ["/comply", []],
];
const problems = [];
let disabledCount = 0;

try {
  // 1. Suspended: banner on every page, write buttons disabled with the reason.
  suspended = true;
  for (const [route, firstWrites, tab, tabWrites] of PAGES) {
    const { page, errors, close } = await open(route);
    let writes = firstWrites;
    await page.waitForSelector('[data-testid="org-suspended-banner"]', { timeout: 8000 }).catch(() => {});
    assert.ok(await banner(page), `${route}: the suspension banner is shown`);
    const shown = await page.$eval('[data-testid="org-suspended-banner"]', (e) => e.innerText);
    assert.match(shown, /This organisation is suspended\./, `${route}: banner title`);
    assert.match(shown, /You can still sign in and read your dashboards, scans, findings, reports and compliance pages\./, `${route}: what still works`);
    assert.match(shown, /new scans, domains, settings, members/, `${route}: what is paused`);
    assert.match(shown, /info@cyphward\.com/, `${route}: who to contact`);
    const links = await page.$$eval('[data-testid="org-suspended-banner"] a', (as) => as.map((a) => a.getAttribute("href")));
    assert.deepEqual(links, ["mailto:info@cyphward.com", "/contact"], `${route}: contact links`);
    let states = await writeStates(page);
    if (tab) {  // a second tab of the same page (Settings > Team)
      await page.click(tab);
      await settle(page, 300);
      states = [...states, ...(await writeStates(page))];
      writes = [...writes, ...tabWrites];
    }
    for (const w of writes) {
      const found = states.filter((s) => s.write === w);
      assert.ok(found.length > 0, `${route}: write button ${w} rendered`);
      for (const s of found) {
        assert.equal(s.disabled, true, `${route}: ${w} disabled while suspended`);
        assert.match(s.title, /suspended/, `${route}: ${w} explains why`);
        disabledCount++;
      }
    }
    if (route === "/comply") assert.match(await text(page), /View only/, "compliance is view only while suspended");
    if (route === "/scans") {
      assert.equal(await page.$eval('[data-testid="scan-failure"]', (e) => e.innerText), "The site blocked our check.", "failure sentence");
      assert.doesNotMatch(await text(page), /error_message|Errno|Traceback/, "no raw failure text");
    }
    assert.deepEqual(errors, [], `${route}: no page errors`);
    await close();
  }

  // 2. Active organisation: no banner, buttons enabled.
  suspended = false;
  for (const [route, firstWrites, tab, tabWrites] of PAGES.filter(([, w]) => w.length)) {
    const { page, close } = await open(route);
    await sleep(200);
    let writes = firstWrites;
    assert.equal(await banner(page), null, `${route}: no banner for an active organisation`);
    let states = await writeStates(page);
    if (tab) {
      await page.click(tab);
      await settle(page, 300);
      states = [...states, ...(await writeStates(page))];
      writes = [...writes, ...tabWrites];
    }
    for (const w of writes.filter((x) => x !== "domain-verify")) {
      const found = states.filter((s) => s.write === w);
      assert.ok(found.length > 0 && found.some((s) => !s.disabled), `${route}: ${w} enabled when active`);
    }
    await close();
  }

  // 3. A suspension that starts mid-session: the first refused write shows the banner and disables the button.
  {
    suspended = false;
    refuseWrites = true;
    const { page, close } = await open("/reports");
    assert.equal(await banner(page), null);
    await page.click('[data-write="report-generate"]');
    await page.waitForSelector('[data-testid="org-suspended-banner"]', { timeout: 5000 });
    await sleep(300);
    const body = await text(page);
    assert.doesNotMatch(body, /\{"|organization_suspended|\b403\b/, "no raw server body or code on screen");
    assert.equal(await page.$eval('[data-write="report-generate"]', (b) => b.disabled), true, "the button is disabled after the refusal");
    refuseWrites = false;
    await close();
  }

  // 4. Owner console: suspension wording, restore behind the typed-name gate, no restore while suspended.
  {
    ownerOrgSuspended = false;
    const { page, close } = await open(`/admin/organizations/${ORG_ID}`);
    await page.waitForSelector('[data-testid="removed-member-row"]');
    const rows = await page.$$eval('[data-testid="removed-member-row"]', (rs) => rs.map((r) => r.innerText.replace(/\s+/g, " ")));
    assert.match(rows[0], /dev@acme\.example/); assert.match(rows[1], /restored/i);
    assert.equal((await page.$$('[data-testid="member-restore-open"]')).length, 1, "only the unrestored removal offers RESTORE");
    await page.click('[data-testid="member-restore-open"]');
    await page.waitForSelector('[role="dialog"] [data-testid="typed-name-gate"]');
    await sleep(200);
    assert.match(await page.$eval('[role="dialog"]', (d) => d.innerText), /join date from the removal record/i);
    await typeInto(page, "#owner-action-reason", "Removed by mistake, ticket 7");
    for (const wrong of [ORG_NAME.toLowerCase(), `${ORG_NAME} `]) {
      await typeInto(page, "#owner-action-typed-name", wrong);
      assert.equal(await okDisabled(page), true, `"${wrong}" keeps restore disabled`);
    }
    assert.equal(posts.length, 0, "nothing is sent before the name matches");
    await typeInto(page, "#owner-action-typed-name", ORG_NAME);
    assert.equal(await okDisabled(page), false);
    await page.click('[role="dialog"] [data-testid="confirm-ok"]');
    await settle(page, 400);
    assert.deepEqual(posts.at(-1), { path: `/api/v1/owner/organizations/${ORG_ID}/members/restore`,
      body: { reason: "Removed by mistake, ticket 7", confirm_name: ORG_NAME, audit_id: AUDIT_ID } });
    await close();

    ownerOrgSuspended = true;
    const s = await open(`/admin/organizations/${ORG_ID}`);
    await s.page.waitForSelector('[data-testid="org-suspended-note"]');
    assert.match(await s.page.$eval('[data-testid="org-suspended-note"]', (e) => e.innerText), /every change, new scan and scheduled scan is paused/);
    assert.equal((await s.page.$$('[data-testid="member-restore-open"]')).length, 0, "no restore while suspended");
    assert.match(await text(s.page), /lift the suspension to restore/);
    await s.close();

    const sc = await open("/admin/scans/sc1");
    await sc.page.waitForSelector('[data-testid="scan-failure-sentence"]');
    assert.match(await sc.page.$eval('[data-testid="scan-failure-sentence"]', (e) => e.innerText), /We could not reach the site\./);
    assert.match(await sc.page.$eval('[data-testid="scan-raw-error"]', (e) => e.innerText), /Errno 111/, "the owner keeps the raw text");
    await sc.close();
  }

  // 5. Layout audit with the banner on: no page scroll, no claim wording, banner targets and contrast.
  suspended = true;
  const ours = /organisation is suspended|Changes are paused|info@cyphward|contact page/i;
  for (const [label, width, height] of WIDTHS) {
    for (const route of ["/overview", "/scans", "/settings"]) {
      for (const theme of ["dark", "light"]) {
        const { page, close } = await open(route, { width, height, theme });
        await page.waitForSelector('[data-testid="org-suspended-banner"]');
        const r = await audit(page, { mobile: width < 900, tabStops: 0 });
        if (r.overflow > 0) problems.push(`${route} ${label} ${theme}: horizontal overflow ${r.overflow}px`);
        if (r.bannedHits?.length) problems.push(`${route} ${label} ${theme}: banned ${JSON.stringify(r.bannedHits)}`);
        for (const key of ["small", "lowContrast", "unlabelled", "nameless"]) {
          const mine = (r[key] || []).filter((x) => ours.test(JSON.stringify(x)));
          if (mine.length) problems.push(`${route} ${label} ${theme}: ${key} ${JSON.stringify(mine)}`);
        }
        const box = await page.$eval('[data-testid="org-suspended-banner"]', (e) => { const b = e.getBoundingClientRect(); return { left: b.left, right: b.right, vw: window.innerWidth }; });
        if (box.left < 0 || box.right > box.vw) problems.push(`${route} ${label}: banner outside the viewport`);
        await close();
      }
    }
  }
  assert.deepEqual(problems, [], `audit problems:\n${problems.join("\n")}`);
  console.log(`admin phase 2: ok (banner on ${PAGES.length} customer pages with what works and who to contact, ${disabledCount} write buttons ` +
    "disabled with a reason, no banner and enabled buttons when active, mid-session refusal shows the banner without raw text, failure " +
    "sentence on the scans page, owner restore behind the typed-name gate with the audit id, no restore while suspended, owner sees " +
    "sentence and raw error, banner audit at 1440/390/320 in dark and light)");
} finally {
  await h.close();
}
