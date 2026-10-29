// Owner console: Newsletter section (admin.cyphward.com/console/newsletter; /admin/newsletter locally). Every API call
// is answered from fixtures; nothing reaches a server, Brevo or a subscriber.
//   - hidden for non-owners: a signed-out console shows only the sign-in screen and calls no newsletter route; the
//     customer app has no link to it
//   - owner navigation (sidebar and the phone menu), the overview strip, the drafts table sorted by created time
//     (pointer and keyboard), the shared loading / empty / error panels and the "switched off" state
//   - draft detail: sections with links and sources as text with their hosts, the sandboxed preview (no scripts),
//     the draft rules status; a sent draft and a draft outside the rules have no send button
//   - send: the button stays disabled until the subject matches exactly; a wrong subject (case, trailing space,
//     Enter, a forced submit) never calls the send route; the exact body; sent / already sent / server error text,
//     never internals; the list refreshes afterwards
//   - the audit (no overflow, 44px targets on phones, labels, names, heading order, focus rings, contrast, no claim
//     wording) at 1440, 390 and 320, reduced motion respected
// CAPTURE=1 also writes the screenshots in docs/admin-newsletter-2026-10-29/ (JPEG, each under 250 KB).
import assert from "node:assert/strict";
import { mkdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { UI_BANNED, WIDTHS, audit, frontend, settle, sleep, startHarness } from "./lib/ui-refine-harness.mjs";
import { PREVIEW_DRAFT, PREVIEW_HTML, PREVIEW_TEXT } from "./lib/admin-newsletter-fixture.mjs";

const SUBJECT = PREVIEW_DRAFT.subject; // "Cyphward notes for October"
const SENT_SUBJECT = "Cyphward notes for September";
const RULES_OK = "Follows the draft rules";
const SHOTS = join(frontend, "..", "docs", "admin-newsletter-2026-10-29");
const CAPTURE = process.env.CAPTURE === "1";

const ids = { draft: "0b7c1d1e-0000-4000-8000-000000000001", sent: "0b7c1d1e-0000-4000-8000-000000000002",
              broken: "0b7c1d1e-0000-4000-8000-000000000003", claimed: "0b7c1d1e-0000-4000-8000-000000000004" };

function fixtures() {
  const base = { preview: PREVIEW_DRAFT.preview, created_by: "grokbot", approved_at: null, send_claimed_at: null,
                 sent_at: null, brevo_campaign_id: null, sections: PREVIEW_DRAFT.sections, preview_html: PREVIEW_HTML,
                 preview_text: PREVIEW_TEXT, send_error: null };
  return [
    { ...base, id: ids.draft, status: "draft", subject: SUBJECT, created_at: "2026-10-28T09:00:00Z", sendable: true },
    { ...base, id: ids.sent, status: "sent", subject: SENT_SUBJECT, created_at: "2026-09-29T09:00:00Z", sendable: false,
      sent_at: "2026-09-30T08:00:00Z", approved_at: "2026-09-30T07:59:00Z", send_claimed_at: "2026-09-30T07:59:00Z",
      brevo_campaign_id: "1000", sections: PREVIEW_DRAFT.sections.slice(0, 2) },
    { ...base, id: ids.broken, status: "draft", subject: "Draft that no longer renders", created_at: "2026-10-20T09:00:00Z",
      sendable: false, preview_html: null, preview_text: null, sections: PREVIEW_DRAFT.sections.slice(0, 1) },
    // A send that started and failed: the raw error is stored, and must never reach the screen.
    { ...base, id: ids.claimed, status: "draft", subject: "Draft whose send did not finish", created_at: "2026-10-10T09:00:00Z",
      sendable: false, send_claimed_at: "2026-10-11T09:00:00Z", approved_at: "2026-10-11T09:00:00Z",
      send_error: "before campaign: BrevoError list 503 Traceback psycopg" },
  ];
}

const h = await startHarness();
const problems = [];
const net = { newsletter: [], sends: [], draftLoads: 0 };
let ownerSignedIn = true;
let enabled = true;
let issues = fixtures();
let sendReply = null;

h.state.route = (p, method, request) => {
  if (p.startsWith("/api/v1/newsletter")) net.newsletter.push(`${method} ${p}`);
  if (p === "/api/v1/owner/me" && !ownerSignedIn) return [401, { detail: "Owner sign-in required." }];
  if (!p.startsWith("/api/v1/newsletter")) return undefined;
  if (!enabled) return [404, { detail: "Not Found" }];
  if (p === "/api/v1/newsletter/drafts" && method === "GET") {
    net.draftLoads += 1;
    return [200, { issues, confirmed_subscribers: 3 }];
  }
  if (p === "/api/v1/newsletter/stats" && method === "GET") return [200, { confirmed: 3, unsubscribed: 1, pending: 1 }];
  const m = p.match(/^\/api\/v1\/newsletter\/drafts\/([^/]+)\/send$/);
  if (m && method === "POST") {
    net.sends.push({ id: m[1], body: JSON.parse(request.postData() || "{}") });
    if (sendReply) return sendReply;
    const issue = issues.find((i) => i.id === m[1]);
    Object.assign(issue, { status: "sent", sendable: false, sent_at: "2026-10-29T10:00:00Z", send_claimed_at: "2026-10-29T10:00:00Z" });
    return [200, { id: m[1], status: "sent", brevo_campaign_id: "1001", sent_at: issue.sent_at, recipients: 3 }];
  }
  return [404, { detail: "Not Found" }];
};

const check = (label, r) => {
  for (const key of ["small", "unlabelled", "nameless", "skips", "noRing", "lowContrast", "bannedHits", "landmarks", "pageErrors"]) {
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
const rowIds = (page) => page.$$eval('[data-testid="newsletter-row"]', (rows) => rows.map((r) => r.dataset.id));
const sendDisabled = (page) => page.$eval('[data-testid="newsletter-send-confirm"]', (b) => b.disabled);

async function typeSubject(page, value) {
  await page.$eval("#newsletter-confirm-subject", (el) => { el.focus(); el.select(); });
  await page.keyboard.press("Backspace");
  if (value) await page.keyboard.type(value);
}

async function openSendDialog(page) {
  await page.click('[data-testid="newsletter-send-open"]');
  await page.waitForSelector('[role="dialog"] #newsletter-confirm-subject');
  await sleep(250);
}

async function shot(page, name, { fullPage = false } = {}) {
  if (!CAPTURE) return;
  mkdirSync(SHOTS, { recursive: true });
  const path = join(SHOTS, `${name}.jpg`);
  // The audit's Tab walk leaves a focus ring behind; a dialog keeps its own focus (the subject field).
  await page.evaluate(() => { if (!document.activeElement?.closest('[role="dialog"]')) document.activeElement?.blur?.(); window.scrollTo(0, 0); });
  await page.mouse.move(0, 0);
  await sleep(150);
  await page.screenshot({ path, type: "jpeg", quality: 72, fullPage });
  const kb = statSync(path).size / 1024;
  assert.ok(kb < 250, `${name}.jpg is ${kb.toFixed(0)} KB (keep it under 250 KB)`);
}

try {
  // 1. Hidden for non-owners: the console without an owner session is the sign-in screen and asks nothing of the
  //    newsletter routes, at the section's own URL too.
  {
    ownerSignedIn = false;
    for (const route of ["/admin", "/admin/newsletter", `/admin/newsletter/${ids.draft}`]) {
      net.newsletter.length = 0;
      const { page, close } = await open(route);
      assert.ok(await page.$("#owner-email"), `${route}: signed out shows the sign-in form`);
      assert.equal(await page.$('a[href$="/newsletter"]'), null, `${route}: no newsletter link when signed out`);
      assert.doesNotMatch(await text(page), /send to confirmed subscribers|drafts waiting/i, `${route}: no newsletter content`);
      assert.deepEqual(net.newsletter, [], `${route}: no newsletter request without an owner session`);
      await close();
    }
    ownerSignedIn = true;
    // The customer app (a signed-in organization owner) has no way into it.
    net.newsletter.length = 0;
    const { page, close } = await open("/overview");
    assert.equal(await page.$('a[href*="/admin"]'), null, "customer app: no link into the owner console");
    assert.equal(await page.$('a[href$="/newsletter/drafts"], a[href*="/admin/newsletter"]'), null, "customer app: no newsletter admin link");
    assert.deepEqual(net.newsletter.filter((r) => /drafts|stats|send/.test(r)), [], "customer app: no newsletter admin request");
    await close();
  }

  // 2. Owner navigation: the sidebar item, and the phone menu sheet.
  {
    const { page, close } = await open("/admin");
    const link = await page.$('aside a[href="/admin/newsletter"]');
    assert.ok(link, "sidebar has the Newsletter item");
    assert.match(await link.evaluate((a) => a.textContent), /NEWSLETTER/);
    await link.click();
    await page.waitForSelector('[data-testid="newsletter-drafts"]');
    assert.ok(await page.$eval('aside a[href="/admin/newsletter"]', (a) => a.classList.contains("active")), "item is marked active");
    await close();

    const phone = await open("/admin", { width: 390, height: 844 });
    await phone.page.click('button[aria-label="Open menu"]');
    await phone.page.waitForSelector('[role="dialog"][aria-label="Owner console menu"]');
    const item = await phone.page.$('[aria-label="Owner console sections"] a[href="/admin/newsletter"]');
    assert.ok(item, "phone menu has the Newsletter item");
    await item.click();
    await phone.page.waitForSelector('[data-testid="newsletter-drafts"]');
    await phone.close();
  }

  // 3. The list: overview strip, table, sorting by created time with the pointer and the keyboard.
  {
    const { page, close } = await open("/admin/newsletter");
    const t = await text(page);
    for (const want of [/CONFIRMED SUBSCRIBERS\s*\n?\s*3/i, /UNSUBSCRIBED\s*\n?\s*1/i, /DRAFTS WAITING\s*\n?\s*1/i, /LAST SENT/i, /Sep 30, 2026|30 Sept?/]) {
      assert.match(t, want, `overview strip shows ${want}`);
    }
    assert.match(t, /1 waiting from the earlier sign-up flow/);
    assert.doesNotMatch(t, /Traceback|BrevoError|psycopg|before campaign/, "a stored send error never reaches the screen");
    const head = await page.$$eval('[data-testid="newsletter-drafts"] thead th', (ths) => ths.map((th) => th.textContent.trim()));
    assert.deepEqual(head.map((x) => x.replace(/\s+/g, " ")), ["SUBJECT", "STATUS", "CREATED", "CREATED BY", "SECTIONS"]);
    const newest = [ids.draft, ids.broken, ids.claimed, ids.sent];
    assert.deepEqual(await rowIds(page), newest, "newest first by default");
    const sortHeader = '[data-testid="newsletter-drafts"] th[aria-sort]';
    assert.equal(await page.$eval(sortHeader, (th) => th.getAttribute("aria-sort")), "descending");
    await page.click('[data-testid="newsletter-sort"]');
    assert.deepEqual(await rowIds(page), [...newest].reverse(), "oldest first after one press");
    assert.equal(await page.$eval(sortHeader, (th) => th.getAttribute("aria-sort")), "ascending");
    // Keyboard: the header button with Enter, then the row link with Enter.
    await page.focus(`${sortHeader} button`);
    await page.keyboard.press("Enter");
    assert.deepEqual(await rowIds(page), newest, "Enter on the column header sorts again");
    await page.focus('[data-testid="newsletter-drafts"] tbody tr:first-child a');
    await page.keyboard.press("Enter");
    await page.waitForFunction((s) => document.querySelector("h1")?.textContent === s, {}, SUBJECT);
    const reduced = await page.evaluate(() => getComputedStyle(document.querySelector("main.page")).animationName);
    assert.equal(reduced, "none", "reduced motion: the page enters without animation");
    await close();
  }

  // 4. Draft detail: sections, links and sources as text with hosts, the sandboxed preview, the rules status.
  {
    const { page, close } = await open(`/admin/newsletter/${ids.draft}`);
    assert.equal(await page.$eval("h1", (el) => el.textContent), SUBJECT);
    const t = await text(page);
    assert.match(t, new RegExp(PREVIEW_DRAFT.preview.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    for (const s of PREVIEW_DRAFT.sections) assert.ok(t.includes(s.heading), `section heading ${s.heading}`);
    assert.deepEqual(await page.$$eval("article h3", (hs) => hs.map((x) => x.textContent)), PREVIEW_DRAFT.sections.map((s) => s.heading));
    assert.match(t, /PRODUCT[\s\S]*SECURITY TIP[\s\S]*REGULATION/);
    assert.match(t, /See pricing · cyphward\.com/);
    assert.match(t, /NDPC guidance note · ndpc\.gov\.ng/);
    assert.ok(t.includes("https://ndpc.gov.ng/guidance"), "source URL shown as text");
    assert.equal(await page.$$eval("main article a", (as) => as.length), 0, "links and sources are text, not links");
    const frame = await page.$eval('[data-testid="newsletter-preview-frame"]', (f) => ({
      sandbox: f.getAttribute("sandbox"), hasSrc: f.hasAttribute("src"), srcdoc: f.getAttribute("srcdoc"), title: f.title }));
    assert.equal(frame.sandbox, "", "preview iframe is sandboxed with no allowances (no scripts)");
    assert.equal(frame.hasSrc, false);
    assert.equal(frame.srcdoc, PREVIEW_HTML, "preview is the rendered email from the API");
    assert.match(frame.title, /Email preview/);
    assert.equal(await page.$eval('[data-testid="newsletter-rules"]', (el) => el.textContent.trim()), RULES_OK);
    assert.ok(await page.$('[data-testid="newsletter-send-open"]'), "an unsent draft has the send button");
    assert.match(await page.$eval('[data-testid="newsletter-send-open"]', (b) => b.textContent), /SEND TO CONFIRMED SUBSCRIBERS/);
    await close();
  }

  // 5. A sent draft, a draft outside the rules and a draft whose send did not finish: no send button.
  {
    for (const [id, want] of [[ids.sent, /SENT/], [ids.broken, /does not follow the draft rules/], [ids.claimed, /did not finish/]]) {
      const { page, close } = await open(`/admin/newsletter/${id}`);
      assert.equal(await page.$('[data-testid="newsletter-send-open"]'), null, `${id}: no send button`);
      const t = await text(page);
      assert.match(t, want);
      assert.doesNotMatch(t, /Traceback|BrevoError|psycopg|before campaign/);
      await close();
    }
    const { page, close } = await open("/admin/newsletter/not-a-draft");
    assert.match(await text(page), /This draft is not in the list/);
    assert.ok(await page.$('[data-testid="state-empty"]'));
    await close();
  }

  // 6. Send: disabled until the subject matches exactly; a wrong subject never calls the send route.
  {
    const { page, close } = await open(`/admin/newsletter/${ids.draft}`, { width: 390, height: 844 });
    await openSendDialog(page);
    const dialogText = await page.$eval('[role="dialog"]', (d) => d.innerText);
    assert.match(dialogText, /3 confirmed subscribers/);
    assert.match(dialogText, /Cyphward News/);
    assert.match(dialogText, /news@cyphward\.com/);
    assert.equal(await page.evaluate(() => document.activeElement?.id), "newsletter-confirm-subject", "focus starts in the subject field");
    assert.equal(await sendDisabled(page), true, "disabled while empty");
    for (const wrong of [SUBJECT.toLowerCase(), `${SUBJECT} `, ` ${SUBJECT}`, SUBJECT.slice(0, -1), SUBJECT.toUpperCase()]) {
      await typeSubject(page, wrong);
      assert.equal(await sendDisabled(page), true, `disabled for ${JSON.stringify(wrong)}`);
      await page.keyboard.press("Enter");
      await page.$eval('[role="dialog"] form', (f) => f.requestSubmit());
      await page.$eval('[data-testid="newsletter-send-confirm"]', (b) => b.click());
      await sleep(150);
    }
    assert.equal(net.sends.length, 0, "a wrong subject never calls the send route");
    assert.match(await page.$eval("#newsletter-confirm-hint", (el) => el.textContent), /Not a match yet/);

    await typeSubject(page, SUBJECT);
    assert.equal(await sendDisabled(page), false, "enabled once the subject matches exactly");
    await shot(page, "newsletter-send-dialog-390");
    const loadsBefore = net.draftLoads;
    await page.click('[data-testid="newsletter-send-confirm"]');
    await page.waitForSelector('[data-testid="newsletter-send-result"]');
    assert.equal(net.sends.length, 1, "one send call");
    assert.deepEqual(net.sends[0], { id: ids.draft, body: { approve: true, subject: SUBJECT } }, "exact body");
    assert.equal(await page.$eval('[data-testid="newsletter-send-result"]', (el) => el.dataset.kind), "sent");
    assert.match(await page.$eval('[data-testid="newsletter-send-result"]', (el) => el.innerText), /Sent to 3 confirmed subscribers\./);
    await settle(page, 300);
    assert.ok(net.draftLoads > loadsBefore, "the list is fetched again after the send");
    await page.click('[data-testid="newsletter-send-result"] button');
    await sleep(350);
    assert.equal(await page.$('[data-testid="newsletter-send-open"]'), null, "the sent draft no longer has a send button");
    assert.match(await page.$eval('[data-testid="newsletter-rules"]', (el) => el.closest("dl").innerText), /SENT/);
    await close();
  }

  // 7. Send results: already sent, the server's plain sentence, and never internals.
  {
    const cases = [
      [[409, { detail: "This issue has already been sent or a send was already attempted." }], "already", /Already sent\. This issue has already been sent/],
      [[502, { detail: "Brevo did not confirm the send of campaign 1001. Check it in Brevo before doing anything else." }], "error", /Check it in Brevo before doing anything else/],
      [[422, { detail: "Type the draft's subject exactly to approve sending it." }], "error", /Type the draft's subject exactly/],
      [[500, { detail: "Traceback (most recent call last): psycopg.errors.UniqueViolation" }], "error", /may or may not have gone out/],
      [[502, { detail: "before campaign: BrevoError Traceback at newsletter.py line 9" }], "error", /may or may not have gone out/],
      [[403, { detail: "Request must come from the owner console." }], "error", /Nothing was sent: the server accepts a send only from the owner console/],
    ];
    for (const [reply, kind, want] of cases) {
      issues = fixtures();
      sendReply = reply;
      net.sends.length = 0;
      const { page, close } = await open(`/admin/newsletter/${ids.draft}`);
      await openSendDialog(page);
      await typeSubject(page, SUBJECT);
      await page.keyboard.press("Enter"); // Enter submits once the subject matches
      await page.waitForSelector('[data-testid="newsletter-send-result"]');
      const result = await page.$eval('[data-testid="newsletter-send-result"]', (el) => ({ kind: el.dataset.kind, text: el.innerText }));
      assert.equal(net.sends.length, 1, `${reply[0]}: one call, no retry`);
      assert.equal(result.kind, kind, `${reply[0]} result kind`);
      assert.match(result.text, want, `${reply[0]} result text`);
      assert.doesNotMatch(result.text, /Traceback|psycopg|BrevoError|\.py\b|Your role cannot/, `${reply[0]}: no internals`);
      await close();
    }
    sendReply = null;
    issues = fixtures();
  }

  // 8. Shared state panels: loading, empty, error (with a working retry), and the feature switched off.
  {
    issues = [];
    let { page, close } = await open("/admin/newsletter");
    assert.ok(await page.$('[data-testid="state-empty"]'), "empty panel");
    assert.match(await text(page), /No drafts yet/);
    await close();
    issues = fixtures();

    h.state.failures.add("/newsletter/drafts");
    ({ page, close } = await open("/admin/newsletter"));
    assert.ok(await page.$('[data-testid="state-error"]'), "error panel");
    assert.doesNotMatch(await text(page), /Internal Server Error/);
    h.state.failures.delete("/newsletter/drafts");
    await page.click('[data-testid="state-error"] button');
    await page.waitForSelector('[data-testid="newsletter-drafts"]');
    await close();

    enabled = false;
    ({ page, close } = await open("/admin/newsletter"));
    assert.match(await text(page), /The newsletter is switched off/);
    assert.equal(await page.$('[data-testid="state-error"]'), null);
    await close();
    enabled = true;

    // Loading: the drafts reply is held back in the page for a moment.
    const tab = await h.newPage({});
    await tab.page.setViewport({ width: 1440, height: 900 });
    await tab.page.evaluateOnNewDocument(() => {
      const real = window.fetch.bind(window);
      window.fetch = (input, init) => (String(input).includes("/newsletter/drafts")
        ? new Promise((r) => setTimeout(r, 1500)).then(() => real(input, init)) : real(input, init));
    });
    await tab.page.goto(`${h.origin}/admin/newsletter`, { waitUntil: "domcontentloaded" });
    await tab.page.waitForSelector('[data-testid="state-loading"]', { timeout: 8000 });
    await tab.page.waitForSelector('[data-testid="newsletter-drafts"]', { timeout: 8000 });
    await tab.close();
  }

  // 9. The audit, at every width, both themes at the two common widths; and the screenshots.
  for (const theme of ["dark", "light"]) {
    for (const [label, width, height] of WIDTHS) {
      if (theme === "light" && label === "320") continue;
      issues = fixtures();
      for (const [name, route] of [["list", "/admin/newsletter"], ["detail", `/admin/newsletter/${ids.draft}`]]) {
        const { page, errors, close } = await h.newPage({ theme });
        await page.setViewport({ width, height });
        await page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
        await settle(page, 600);
        const r = await audit(page, { mobile: width < 768, tabStops: theme === "dark" ? 40 : 0 });
        check(`${name} ${theme} ${label}`, { ...r, pageErrors: errors.splice(0) });
        if (theme === "dark" && (label === "1440" || label === "390")) await shot(page, `newsletter-${name}-${label}`);
        if (name === "detail") {
          await openSendDialog(page);
          const d = await audit(page, { mobile: width < 768, tabStops: 0 });
          check(`send dialog ${theme} ${label}`, { ...d, h1: 1, pageErrors: errors.splice(0) });
          if (theme === "dark" && label === "1440") await shot(page, "newsletter-send-dialog-1440");
        }
        await close();
      }
    }
  }
  assert.ok(UI_BANNED.length > 5);
} finally {
  await h.close();
}

if (problems.length) {
  console.error(`admin newsletter: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log("admin newsletter: ok (hidden for non-owners, navigation, overview strip, sorting by pointer and keyboard, " +
  "detail with sandboxed preview, send disabled until the subject matches exactly, no call on a wrong subject, " +
  `result texts, state panels, audit at 1440/390/320)${CAPTURE ? `; screenshots in ${SHOTS}` : ""}`);
