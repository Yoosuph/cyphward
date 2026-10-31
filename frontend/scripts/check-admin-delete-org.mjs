// Delete organisation in the owner console (docs/admin-delete-org). Every API call is answered from fixtures; nothing
// reaches a server.
//   - danger zone: at the bottom of the organization page, after every other panel, separate from the other actions
//   - soft delete: opened by pointer and by keyboard; the confirm button stays disabled until the reason is written and
//     the exact name is typed (case and trailing space refused); nothing is sent before; the body carries confirm_name
//   - blocked: an active paid subscription or a protected organization disables the button and says why
//   - deleted: the note says what happened and until when it can be restored; suspend and member actions are gone;
//     restore behind the same typed-name gate
//   - purge (after the window): both the name and the word DELETE are needed (either alone keeps it disabled); a refusal
//     because records are retained shows the counts in the console's words and never the server's raw text
//   - organizations list: the Deleted filter (hide by default, include, only) is sent to the server and to the export,
//     and a deleted row says so
//   - the audit (no horizontal scroll, 44 px targets on phones, labels, names, contrast, no claim wording) at 1440, 390
//     and 320, on the page and with each dialog open
import assert from "node:assert/strict";
import { WIDTHS, audit, settle, sleep, startHarness } from "./lib/ui-refine-harness.mjs";

const ORG_ID = "0a000000-0000-4000-8000-000000000001";
const ORG_NAME = "Acme Traders Ltd";
const RAW = "Traceback psycopg.errors.QueryCanceled compliance_reviewer_grants PURGE-RAW-TEXT";
const HOLD_MESSAGE = "Some records of this organization are still inside their retention period, so it cannot be purged yet. Nothing was changed.";

const h = await startHarness();
const problems = [];
const net = { posts: [], lists: [], exports: [] };
let lifecycle = "active"; // active | blocked-paid | protected | deleted | purgeable
let purgeAnswer = "hold"; // hold | ok

const orgRow = (deleted) => ({
  id: ORG_ID, name: ORG_NAME, slug: "acme", plan: "growth", billing: "free", subscription_status: null, suspended: false,
  deleted, deleted_at: deleted ? "2026-09-20T10:00:00Z" : null, members: 2, owner_email: "owner@acme.example", domains: 1,
  domains_verified: 1, last_scan_at: null, last_scan_status: null, created_at: "2026-09-01T00:00:00Z",
});
const detail = () => {
  const deleted = lifecycle === "deleted" || lifecycle === "purgeable";
  return {
    organization: {
      id: ORG_ID, name: ORG_NAME, slug: "acme", plan: "growth", sector: "Retail", created_at: "2026-09-01T00:00:00Z",
      suspended: false, suspension_changed_at: null, status: deleted ? "deleted" : "active", deleted,
      deleted_at: deleted ? "2026-09-20T10:00:00Z" : null, deleted_by_email: deleted ? "owner@cyphward.example" : null,
      restore_until: deleted ? "2026-10-20T10:00:00Z" : null, restorable: lifecycle === "deleted",
      purge_window_passed: lifecycle === "purgeable", restore_window_days: 30, protected: lifecycle === "protected",
      paid_subscription_active: lifecycle === "blocked-paid",
    },
    members: [
      { id: "u1", email: "owner@acme.example", full_name: "Ada Owner", role: "owner", last_seen_at: "2026-10-28T09:00:00Z" },
      { id: "u2", email: "dev@acme.example", full_name: null, role: "member", last_seen_at: null },
    ],
    removed_members: [{ audit_id: "5a000000-0000-4000-8000-0000000000a1", email: "old@acme.example", role: "member",
      removed_at: "2026-10-01T10:00:00Z", restored: false, is_member: false }],
    domains: [{ id: "d1", domain: "acme.example", verification_status: "verified", verified_at: "2026-09-02T00:00:00Z" }],
    subscriptions: [{ plan: "growth", status: lifecycle === "blocked-paid" ? "active" : "canceled", current_period_end: "2026-11-20T00:00:00Z" }],
    invoices: [], scans: [], open_findings: [], activity: [{ action: "scan.launched", user_email: "owner@acme.example", created_at: "2026-10-01T09:00:00Z" }],
    owner_actions: [], plans: [{ slug: "starter", label: "Starter" }, { slug: "growth", label: "Growth" }],
  };
};

h.state.route = (p, method, request) => {
  const url = new URL(request.url());
  if (p === "/api/v1/owner/organizations" && method === "GET") {
    const params = Object.fromEntries(url.searchParams);
    net.lists.push(params);
    const items = params.deleted === "only" ? [orgRow(true)] : params.deleted === "include"
      ? [orgRow(true), { ...orgRow(false), id: "0a000000-0000-4000-8000-000000000002", name: "Kola Foods", slug: "kola" }]
      : [{ ...orgRow(false), id: "0a000000-0000-4000-8000-000000000002", name: "Kola Foods", slug: "kola" }];
    return [200, { items, total: items.length, limit: 50, offset: 0, sort: "created", dir: "desc" }];
  }
  if (p.startsWith("/api/v1/owner/exports/")) {
    net.exports.push({ path: p, params: Object.fromEntries(url.searchParams) });
    return [200, ""];
  }
  if (p === `/api/v1/owner/organizations/${ORG_ID}` && method === "GET") return [200, detail()];
  if (method === "POST" && p.startsWith(`/api/v1/owner/organizations/${ORG_ID}/`)) {
    const body = JSON.parse(request.postData() || "{}");
    net.posts.push({ path: p, body });
    if (p.endsWith("/delete")) { lifecycle = "deleted"; return [200, { organization_id: ORG_ID, deleted: true, deleted_at: "2026-10-31T10:00:00Z", restore_until: "2026-11-30T10:00:00Z", queued_scans_cancelled: 0 }]; }
    if (p.endsWith("/restore")) { lifecycle = "active"; return [200, { organization_id: ORG_ID, deleted: false, status: "active" }]; }
    if (p.endsWith("/purge")) {
      if (purgeAnswer === "hold") {
        return [409, { detail: { code: "retention_hold", message: HOLD_MESSAGE, retention_months: 36, raw: RAW,
          counts: { reviewer_grants: 1, packs: 2, snapshots: 3, documents: 0, evidence_files: 4, extra: RAW } } }];
      }
      return [200, { organization_id: ORG_ID, purged: true, evidence_files_queued: true }];
    }
  }
  return undefined;
};

async function open(route, { width = 1440, height = 900, theme = "dark" } = {}) {
  const tab = await h.newPage({ theme });
  await tab.page.setViewport({ width, height });
  await tab.page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
  await settle(tab.page, 500);
  return tab;
}
const text = (page) => page.evaluate(() => document.body.innerText);
const okDisabled = (page) => page.$eval('[role="dialog"] [data-testid="confirm-ok"]', (b) => b.disabled);
async function typeInto(page, selector, value) {
  await page.$eval(selector, (el) => { el.focus(); el.select?.(); });
  await page.keyboard.down("Control"); await page.keyboard.press("a"); await page.keyboard.up("Control");
  await page.keyboard.press("Backspace");
  if (value) await page.keyboard.type(value);
}
const ours = /danger|delete|deleted|restore|purge|retention|DELETE/i;
const check = (label, r, { all = false } = {}) => {
  for (const key of ["small", "unlabelled", "nameless", "noRing", "lowContrast", "bannedHits"]) {
    const list = (r[key] || []).filter((x) => all || ours.test(JSON.stringify(x)));
    if (list.length) problems.push(`${label}: ${key} ${JSON.stringify(list.slice(0, 6))}`);
  }
  if (r.overflow > 0) problems.push(`${label}: horizontal overflow ${r.overflow}px`);
};
const orgPage = `/admin/organizations/${ORG_ID}`;

try {
  // 1. Danger zone at the bottom; soft delete behind the typed-name gate, opened by keyboard.
  {
    lifecycle = "active";
    const { page, errors, close } = await open(orgPage);
    await page.waitForSelector('[data-testid="org-danger-zone"]');
    const order = await page.evaluate(() => {
      const zone = document.querySelector('[data-testid="org-danger-zone"]');
      const grid = zone.parentElement;
      const last = grid.lastElementChild === zone;
      const panelsAbove = [...grid.children].filter((c) => c !== zone).every((c) => c.getBoundingClientRect().top <= zone.getBoundingClientRect().top);
      const headerHasDelete = !!document.querySelector('.mb-6 [data-testid="org-delete-open"]');
      return { last, panelsAbove, headerHasDelete, heading: zone.querySelector("h2")?.textContent };
    });
    assert.deepEqual(order, { last: true, panelsAbove: true, headerHasDelete: false, heading: "Danger zone" }, "danger zone at the bottom, apart from the header actions");
    assert.ok(await page.$('[data-testid="org-suspend-open"]'), "the other actions stay in the header");
    assert.equal(await page.$eval('[data-testid="org-delete-open"]', (b) => b.disabled), false);
    await page.focus('[data-testid="org-delete-open"]');
    await page.keyboard.press("Enter");
    await page.waitForSelector('[role="dialog"] [data-testid="typed-name-gate"]');
    await sleep(200);
    const dialog = await page.$eval('[role="dialog"]', (d) => d.innerText);
    assert.match(dialog, /you can restore it for 30 days/i);
    assert.match(dialog, /queued scans are cancelled, a scan that is already running finishes/i);
    assert.equal(await okDisabled(page), true, "disabled when the dialog opens");
    await typeInto(page, "#owner-action-reason", "Customer asked to close, ticket 91");
    assert.equal(await okDisabled(page), true, "a reason alone is not enough");
    for (const wrong of [ORG_NAME.toLowerCase(), `${ORG_NAME} `, "Acme Traders"]) {
      await typeInto(page, "#owner-action-typed-name", wrong);
      assert.equal(await okDisabled(page), true, `"${wrong}" keeps delete disabled`);
      await page.keyboard.press("Enter");
      await sleep(150);
    }
    assert.equal(net.posts.length, 0, "nothing is sent before the name matches");
    await typeInto(page, "#owner-action-typed-name", ORG_NAME);
    assert.equal(await okDisabled(page), false);
    await page.keyboard.press("Enter"); // the form submits from the keyboard
    await settle(page, 400);
    assert.deepEqual(net.posts.at(-1), { path: `/api/v1/owner/organizations/${ORG_ID}/delete`,
      body: { reason: "Customer asked to close, ticket 91", confirm_name: ORG_NAME } });
    // After the reload the page shows the deleted state.
    await page.waitForSelector('[data-testid="org-deleted-note"]');
    assert.equal(await page.$('[data-testid="org-suspend-open"]'), null, "no suspend on a deleted organization");
    assert.equal((await page.$$('[data-testid="member-remove-open"]')).length, 0, "no member actions while deleted");
    assert.equal((await page.$$('[data-testid="member-restore-open"]')).length, 0);
    assert.deepEqual(errors, []);
    await close();
  }

  // 2. Blocked: paid subscription, protected organization.
  for (const [state, why] of [["blocked-paid", /active paid subscription/], ["protected", /protected/]]) {
    lifecycle = state;
    const { page, close } = await open(orgPage);
    await page.waitForSelector('[data-testid="org-danger-zone"]');
    assert.equal(await page.$eval('[data-testid="org-delete-open"]', (b) => b.disabled), true, `${state}: delete disabled`);
    assert.match(await page.$eval('[data-testid="org-delete-blocked"]', (e) => e.innerText), why);
    assert.equal(await page.$eval('[data-testid="org-delete-open"]', (b) => b.getAttribute("aria-describedby")), "org-delete-blocked");
    await close();
  }

  // 3. Deleted, inside the window: note and restore behind the typed-name gate.
  {
    lifecycle = "deleted";
    const before = net.posts.length;
    const { page, close } = await open(orgPage);
    await page.waitForSelector('[data-testid="org-deleted-note"]');
    const note = await page.$eval('[data-testid="org-deleted-note"]', (e) => e.innerText);
    assert.match(note, /cannot sign in to it/); assert.match(note, /can be restored until/);
    assert.equal(await page.$('[data-testid="org-purge-open"]'), null, "no purge inside the window");
    await page.click('[data-testid="org-restore-open"]');
    await page.waitForSelector('[role="dialog"] [data-testid="typed-name-gate"]');
    await sleep(200);
    assert.match(await page.$eval('[role="dialog"]', (d) => d.innerText), /if it was suspended it stays suspended/);
    await typeInto(page, "#owner-action-reason", "Deleted by mistake, ticket 92");
    await typeInto(page, "#owner-action-typed-name", "acme traders ltd");
    assert.equal(await okDisabled(page), true);
    assert.equal(net.posts.length, before);
    await typeInto(page, "#owner-action-typed-name", ORG_NAME);
    assert.equal(await okDisabled(page), false);
    await page.click('[role="dialog"] [data-testid="confirm-ok"]');
    await settle(page, 400);
    assert.deepEqual(net.posts.at(-1), { path: `/api/v1/owner/organizations/${ORG_ID}/restore`,
      body: { reason: "Deleted by mistake, ticket 92", confirm_name: ORG_NAME } });
    await page.waitForSelector('[data-testid="org-delete-open"]');
    await close();
  }

  // 4. After the window: purge needs the name and DELETE; the retention refusal shows counts only.
  {
    lifecycle = "purgeable";
    purgeAnswer = "hold";
    const before = net.posts.length;
    const { page, close } = await open(orgPage);
    await page.waitForSelector('[data-testid="org-purge-open"]');
    assert.equal(await page.$('[data-testid="org-restore-open"]'), null, "no restore after the window");
    await page.click('[data-testid="org-purge-open"]');
    await page.waitForSelector('[role="dialog"] #owner-action-typed-word');
    await sleep(200);
    assert.equal((await page.$$('[role="dialog"] [data-testid="typed-name-gate"]')).length, 2, "two typed gates");
    assert.match(await page.$eval('[role="dialog"]', (d) => d.innerText), /This cannot be undone\./);
    await typeInto(page, "#owner-action-reason", "Closed account past the window, ticket 93");
    for (const [name, word] of [[ORG_NAME, ""], [ORG_NAME, "delete"], [ORG_NAME, "DELETE "], ["", "DELETE"], [ORG_NAME.toUpperCase(), "DELETE"]]) {
      await typeInto(page, "#owner-action-typed-name", name);
      await typeInto(page, "#owner-action-typed-word", word);
      assert.equal(await okDisabled(page), true, `name "${name}" with word "${word}" keeps purge disabled`);
    }
    assert.equal(net.posts.length, before, "nothing is sent before both match");
    await typeInto(page, "#owner-action-typed-name", ORG_NAME);
    await typeInto(page, "#owner-action-typed-word", "DELETE");
    assert.equal(await okDisabled(page), false);
    await page.click('[role="dialog"] [data-testid="confirm-ok"]');
    await page.waitForSelector('[data-testid="purge-hold"]');
    assert.deepEqual(net.posts.at(-1), { path: `/api/v1/owner/organizations/${ORG_ID}/purge`,
      body: { reason: "Closed account past the window, ticket 93", confirm_name: ORG_NAME, confirm_word: "DELETE" } });
    const shown = await page.$eval('[data-testid="owner-action-error"]', (e) => e.innerText);
    assert.match(shown, /still inside their retention period/);
    assert.match(shown, /Still inside the 36-month retention period/);
    const items = await page.$$eval('[data-testid="purge-hold"] li', (lis) => lis.map((l) => l.innerText));
    assert.deepEqual(items, ["1 reviewer access grant", "2 evidence packs", "3 assessment snapshots", "4 evidence files"]);
    assert.doesNotMatch(await text(page), /PURGE-RAW-TEXT|Traceback|retention_hold|\{"/, "no raw server text");
    check("purge hold 1440", await audit(page, { mobile: false, tabStops: 0 }));
    purgeAnswer = "ok";
    await page.click('[role="dialog"] [data-testid="confirm-ok"]');
    await settle(page, 400);
    assert.equal(await page.$('[role="dialog"]'), null, "the dialog closes after the purge");
    await close();
  }

  // 5. Organizations list: the Deleted filter, sent to the server and to the export.
  {
    const { page, close } = await open("/admin/organizations");
    await page.waitForSelector("#org-deleted");
    const options = await page.$$eval("#org-deleted option", (os) => os.map((o) => [o.value, o.textContent.trim()]));
    assert.deepEqual(options, [["", "Hide deleted"], ["include", "Include deleted"], ["only", "Deleted only"]]);
    assert.equal(net.lists.at(-1).deleted, undefined, "the default hides deleted organizations (no parameter)");
    assert.doesNotMatch(await text(page), /Acme Traders Ltd/);
    await page.select("#org-deleted", "only");
    await settle(page, 300);
    assert.equal(net.lists.at(-1).deleted, "only");
    await page.waitForFunction(() => document.body.innerText.includes("Acme Traders Ltd"));
    assert.match(await page.$eval('[data-testid="org-table"]', (t) => t.innerText), /deleted/i, "the row says deleted");
    await page.click('[data-testid="owner-export"]');
    await settle(page, 300);
    assert.equal(net.exports.at(-1).path, "/api/v1/owner/exports/organizations.csv");
    assert.equal(net.exports.at(-1).params.deleted, "only", "the export carries the Deleted filter");
    await page.focus("#org-deleted");
    await page.keyboard.press("ArrowDown"); // keyboard changes the filter too
    await settle(page, 300);
    await close();
  }

  // 6. Audit at 1440, 390 and 320, both themes: the page in each state and each dialog open.
  for (const [label, width, height] of WIDTHS) {
    const mobile = width < 900;
    for (const [state, opener] of [["active", "org-delete-open"], ["deleted", "org-restore-open"], ["purgeable", "org-purge-open"]]) {
      for (const theme of ["dark", "light"]) {
        lifecycle = state;
        const { page, close } = await open(orgPage, { width, height, theme });
        await page.waitForSelector('[data-testid="org-danger-zone"]');
        check(`${state} ${label} ${theme}`, await audit(page, { mobile, tabStops: 0 }));
        const box = await page.$eval('[data-testid="org-danger-zone"]', (e) => { const b = e.getBoundingClientRect(); return { left: b.left, right: b.right, vw: window.innerWidth }; });
        if (box.left < 0 || box.right > box.vw) problems.push(`${state} ${label}: danger zone outside the viewport`);
        if (mobile) {
          const target = await page.$eval(`[data-testid="${opener}"]`, (b) => b.getBoundingClientRect().height);
          if (target < 44) problems.push(`${state} ${label}: ${opener} is ${target}px tall`);
        }
        await page.click(`[data-testid="${opener}"]`);
        await page.waitForSelector('[role="dialog"] [data-testid="typed-name-gate"]');
        await sleep(250);
        check(`${state} dialog ${label} ${theme}`, await audit(page, { mobile, tabStops: 0 }), { all: true });
        await close();
      }
    }
  }
  assert.deepEqual(problems, [], `audit problems:\n${problems.join("\n")}`);
  console.log("admin delete org: ok (danger zone at the bottom apart from the other actions, soft delete by keyboard behind the " +
    "typed-name gate, blocked with a reason for a paid subscription or a protected organization, deleted note without suspend " +
    "or member actions, restore behind the typed-name gate, purge needs the name and DELETE, retention refusal shows counts " +
    "in the console's words and no raw text, Deleted filter sent to the list and the export, audit at 1440/390/320 in both " +
    "themes with each dialog open)");
} finally {
  await h.close();
}
