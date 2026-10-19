// Reviewer access (packet C6) against a stubbed API: the owner's "Reviewer access" tab (grant form with a native date
// field, list, revoke with confirm, activity) and the reviewer's limited Reviews page (organisation list, read-only
// readiness view, record practitioner review, verify clause reference). Desktop, 390px and 320px, keyboard use,
// no verdict language and no horizontal overflow.
import assert from "node:assert/strict";
import { createServer } from "vite";
import puppeteer from "puppeteer-core";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("..", import.meta.url));
process.chdir(frontend);
const DISCLAIMER =
  "Readiness evidence, not legal advice or a compliance determination. Filing of Compliance Audit Returns for UHL/EHL organisations must go through a licensed DPCO.";
const BANNED = ["compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit", "compliance score", "fully meets",
  "meets the requirement", "is met", "partial compliance", "fully compliant", "is compliant", "satisfy ndpa", "adequate", "adequacy", "guarantee"];
const NOTE = "A practitioner review is the practitioner's own note about a clause reference or a requirement. It does not change any status and is not a statement about the organisation's obligations.";

const owner = { id: "c6-owner", email: "owner@example.test", full_name: "Olu Owner" };
const reviewerUser = { id: "c6-reviewer", email: "ada@practice.test", full_name: "Dr Ada Reviewer" };
const org = { id: "c6-org", name: "Acme Traders", slug: "acme", plan: "growth" };
const domain = { id: "d1", org_id: org.id, domain: "acme.ng", verification_status: "verified", created_at: "2026-10-01T00:00:00Z" };

const requirement = (extra = {}) => ({
  key: "ndpa.s25.lawful_basis_documented", group: "lawful_basis", title: "Lawful basis documented", summary: "Each purpose has a recorded lawful basis.",
  clause: "NDPA 2023 s.25", clause_verified: false, clause_label: "NDPA 2023 s.25 · reference pending review", clause_review: null, practitioner_review: null,
  evidence_type_labels: ["Customer attested"], checks_performed: null, not_checked: null, freshness_days: 365, remediation_hint: "Write it down.",
  status: "present", status_label: "Evidence present", reason: "x", reason_text: "Your answer is current.", source: "customer_attested", source_label: "Customer attested",
  domains: [], findings: [], informational_findings: [],
  answers: [{ question_key: "lawful_basis.documented", status: "present", reason: "x", reason_text: "x", answered: true, owner_name: "Ada Obi",
    expires_at: "2027-10-16T00:00:00Z", value: "yes", date: null }], ...extra,
});

const server = await createServer({ root: frontend, server: { host: "127.0.0.1", port: 0 } });
let browser;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || "/usr/bin/chromium", headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  let me = owner;
  let memberships = [{ org: { ...org }, role: "owner", domains: [domain] }];
  let grants = [];
  let activity = [];
  let myGrants = [];
  let reqState = requirement();
  const writes = [];
  const reset = () => {
    grants = [{ id: "g-old", reviewer_email: "old@practice.test", purpose: "Last year", status: "expired", granted_at: "2025-10-01T00:00:00Z",
      granted_by_name: "Olu Owner", expires_at: "2025-11-01T00:00:00Z", revoked_at: null }];
    activity = [];
    reqState = requirement();
    writes.length = 0;
  };
  const json = (request, status, body) => void request.respond({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) return url.origin === origin ? void request.continue() : void request.abort();
    const method = request.method();
    const path = url.pathname;
    if (path.endsWith("/auth/bootstrap")) return json(request, 200, { user: me, email_verified: true, memberships });
    if (path.endsWith("/compliance/reviewer-grants") && method === "GET") {
      return json(request, 200, { grants, activity, audit: [], note: NOTE, can_grant: true,
        limits: { min_days: 1, default_days: 30, max_days: 90, purpose_max: 200 } });
    }
    if (path.endsWith("/compliance/reviewer-grants") && method === "POST") {
      const body = JSON.parse(request.postData() || "{}");
      writes.push({ path, body });
      const g = { id: `g-${writes.length}`, reviewer_email: body.email, purpose: body.purpose, status: "pending", granted_at: new Date().toISOString(),
        granted_by_name: "Olu Owner", expires_at: new Date(Date.now() + body.days * 86400000).toISOString(), revoked_at: null };
      grants.unshift(g);
      return json(request, 201, { grant: g });
    }
    if (/\/compliance\/reviewer-grants\/[^/]+\/revoke$/.test(path)) {
      writes.push({ path, body: {} });
      const g = grants.find((x) => path.includes(`/${x.id}/`));
      g.status = "revoked";
      g.revoked_at = new Date().toISOString();
      return json(request, 200, { revoked: true });
    }
    if (path.endsWith("/compliance/reviewer/grants")) return json(request, 200, { grants: myGrants, note: NOTE });
    if (path.endsWith("/compliance/reviewer/overview")) {
      assert.equal(request.headers()["x-organization-id"], org.id, "the reviewed organisation is named on the request");
      return json(request, 200, {
        disclaimer: DISCLAIMER, note: "n", register: { version: "v1", title: "Register", references_pending_review: reqState.clause_review?.verified ? 0 : 1 },
        plan: "growth", readiness: { with_evidence: 1, present: 1, gap: 0, awaiting_input: 0, not_assessed: 0, applicable: 1 }, domains: [],
        groups: [{ key: "lawful_basis", title: "Lawful basis", locked: false, counts: { with_evidence: 1, present: 1, gap: 0, awaiting_input: 0, not_assessed: 0, applicable: 1 },
          requirement_count: 1, requirements: [reqState] }],
        organisation: { id: org.id, name: org.name }, grant: { id: "g1", purpose: "Annual readiness review", expires_at: "2026-11-20T00:00:00Z" }, reviewer_note: NOTE });
    }
    if (/\/compliance\/reviewer\/requirements\/[^/]+\/review$/.test(path)) {
      const body = JSON.parse(request.postData() || "{}");
      assert.equal(request.headers()["x-organization-id"], org.id);
      writes.push({ path, body });
      reqState.practitioner_review = { outcome: body.outcome, outcome_label: body.outcome === "reviewed" ? "Reviewed" : "Reviewed, with comments", reviewer_name: "Dr Ada Reviewer",
        reviewed_at: new Date().toISOString(), comment: body.comment, label: "Practitioner review recorded by Dr Ada Reviewer on 2026-10-19" };
      return json(request, 201, { practitioner_review: reqState.practitioner_review });
    }
    if (/\/compliance\/reviewer\/requirements\/[^/]+\/clause-reference$/.test(path)) {
      const body = JSON.parse(request.postData() || "{}");
      writes.push({ path, body });
      reqState.clause_review = { verified: body.verified, reviewer_name: "Dr Ada Reviewer", at: new Date().toISOString(), note: body.note,
        label: body.verified ? "reference reviewed by Dr Ada Reviewer, 2026-10-19" : "reference marked as not confirmed by Dr Ada Reviewer, 2026-10-19" };
      reqState.clause_label = body.verified ? `NDPA 2023 s.25 · ${reqState.clause_review.label}` : reqState.clause_label;
      return json(request, 201, { clause_review: reqState.clause_review });
    }
    if (path.endsWith("/compliance/overview")) {
      return json(request, 200, { disclaimer: DISCLAIMER, note: "n", register: { version: "v1", title: "Register", references_pending_review: 1 }, plan: "growth",
        readiness: { with_evidence: 1, present: 1, gap: 0, awaiting_input: 0, not_assessed: 0, applicable: 1 }, domains: [],
        groups: [{ key: "lawful_basis", title: "Lawful basis", locked: false, counts: { with_evidence: 1, present: 1, gap: 0, awaiting_input: 0, not_assessed: 0, applicable: 1 },
          requirement_count: 1, requirements: [reqState] }] });
    }
    if (path.endsWith("/compliance/questionnaire")) return json(request, 200, { disclaimer: DISCLAIMER, version: "v", register_version: "x", display_timezone: "Africa/Lagos", answered: 0, questions: [] });
    if (path.endsWith("/domains")) return json(request, 200, [domain]);
    if (path.includes("/notifications")) return json(request, 200, { notifications: [], unread_count: 0 });
    json(request, 200, {});
  });
  await page.evaluateOnNewDocument((u) => {
    localStorage.setItem(`cyphward-tour-v1:${u.id}`, "done");
    localStorage.setItem("cyphward-session", JSON.stringify({ access_token: "t", refresh_token: "r", user: u, _expires_at: Date.now() + 864000000 }));
    localStorage.setItem("cyphward-welcome-sent", u.id);
    localStorage.setItem("cyphward-theme", "light");
    localStorage.setItem("cyphward-cookie-consent", "accepted");
  }, owner);

  const clickExact = (text, within = "body") => page.evaluate((t, scope) => {
    const root = document.querySelector(scope);
    const el = [...(root || document).querySelectorAll("button, a")].find((b) => b.textContent.replace(/\s+/g, " ").trim() === t);
    if (el) el.click();
    return !!el;
  }, text, within);
  const clickText = (text) => page.evaluate((t) => {
    const el = [...document.querySelectorAll("button, a")].find((b) => b.textContent.includes(t));
    if (el) el.click();
    return !!el;
  }, text);
  const setVal = (selector, value) => page.evaluate((sel, v) => {
    const el = document.querySelector(sel);
    if (!el) throw new Error(`missing ${sel}`);
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, selector, value);
  const bodyText = () => page.evaluate(() => document.body.innerText);
  const overflowOf = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  const noVerdicts = async (where) => {
    const lowered = (await bodyText()).toLowerCase();
    for (const phrase of BANNED) assert.ok(!lowered.includes(phrase), `${where}: verdict language "${phrase}"`);
  };
  const dialogText = () => page.evaluate(() => document.querySelector('[role="dialog"]')?.innerText || "");
  const waitDialogGone = () => page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 5000 });

  for (const [name, width] of [["desktop", 1440], ["mobile", 390], ["small-mobile", 320]]) {
    // ---------------- Owner: Reviewer access tab ----------------
    reset();
    me = owner;
    memberships = [{ org: { ...org }, role: "owner", domains: [domain] }];
    myGrants = [];
    await page.setViewport({ width, height: 900 });
    await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
    await page.waitForSelector('[data-testid="compliance-disclaimer"]', { timeout: 10000 });
    assert.equal(await page.evaluate(() => !!document.querySelector('[data-testid="reviews-link"]')), false, `${name}: no Reviews link without a grant`);
    assert.ok(await clickExact("REVIEWER ACCESS", '[role="tablist"]'), `${name}: tab`);
    await page.waitForSelector('[data-testid="grant-form"]');
    const attrs = await page.evaluate(() => {
      const d = document.querySelector("#rv-expiry");
      return { type: d.type, min: d.min, max: d.max, value: d.value };
    });
    assert.equal(attrs.type, "date", `${name}: native date field`);
    const dayDiff = (v) => Math.round((Date.parse(`${v}T00:00:00Z`) - Date.parse(`${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, "0")}-${String(new Date().getDate()).padStart(2, "0")}T00:00:00Z`)) / 86400000);
    assert.equal(dayDiff(attrs.min), 1, `${name}: earliest end date is tomorrow`);
    assert.equal(dayDiff(attrs.max), 90, `${name}: latest end date is 90 days out`);
    assert.equal(dayDiff(attrs.value), 30, `${name}: default is 30 days`);
    assert.ok((await bodyText()).includes("Nobody") === false && (await bodyText()).includes("Last year"), `${name}: existing grants listed`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow on the tab`);

    // Keyboard: Tab from the email field reaches the date field, then the purpose field, then the submit button.
    await page.focus("#rv-email");
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.id), "rv-expiry", `${name}: tab order email -> date`);
    // A native date field has day, month and year segments, each a Tab stop.
    for (let i = 0; i < 6 && (await page.evaluate(() => document.activeElement.id)) !== "rv-purpose"; i++) await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.id), "rv-purpose", `${name}: tab order date -> purpose`);
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute("data-testid")), "grant-submit", `${name}: tab order purpose -> submit`);

    // Empty form: refused locally, nothing sent.
    await clickExact("GIVE ACCESS", '[data-testid="grant-form"]');
    await page.waitForSelector('[data-testid="grant-error"]');
    assert.equal(writes.length, 0, `${name}: nothing sent`);

    await setVal("#rv-email", "dpco@practice.test");
    await setVal("#rv-purpose", "Annual readiness review");
    await clickExact("GIVE ACCESS", '[data-testid="grant-form"]');
    await page.waitForSelector('[role="dialog"]');
    const confirmText = await dialogText();
    assert.ok(confirmText.includes("dpco@practice.test") && confirmText.includes("not a member") && confirmText.includes("Neither changes any status"), `${name}: clear copy in the confirm`);
    assert.equal(writes.length, 0, `${name}: nothing sent before the confirm`);
    await noVerdicts(`${name} grant confirm`);
    await clickExact("CANCEL", '[role="dialog"]');
    await waitDialogGone();
    assert.equal(writes.length, 0, `${name}: cancel sends nothing`);
    await clickExact("GIVE ACCESS", '[data-testid="grant-form"]');
    await page.waitForSelector('[role="dialog"]');
    await clickExact("GIVE ACCESS", '[role="dialog"]');
    await page.waitForSelector('[data-testid="grant-pending"]', { timeout: 5000 });
    assert.equal(writes.length, 1, `${name}: one grant sent`);
    assert.deepEqual(writes[0].body, { email: "dpco@practice.test", days: 30, purpose: "Annual readiness review" }, `${name}: grant body`);
    const listed = await page.evaluate(() => document.querySelector('[data-testid="grant-pending"]').innerText);
    assert.ok(listed.includes("dpco@practice.test") && /waiting for the reviewer/i.test(listed), `${name}: pending shown without saying whether an account exists`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow after granting`);

    // Revoke asks first.
    assert.ok(await clickExact("END ACCESS", '[data-testid="grant-pending"]'));
    await page.waitForSelector('[role="dialog"]');
    assert.ok((await dialogText()).includes("lose access to your compliance pages straight away"), `${name}: revoke copy`);
    await clickExact("CANCEL", '[role="dialog"]');
    await waitDialogGone();
    assert.equal(writes.length, 1, `${name}: cancelling the revoke sends nothing`);
    assert.ok(await clickExact("END ACCESS", '[data-testid="grant-pending"]'));
    await page.waitForSelector('[role="dialog"]');
    await clickExact("END ACCESS", '[role="dialog"]');
    await page.waitForSelector('[data-testid="grant-revoked"]', { timeout: 5000 });
    assert.ok(writes[1].path.endsWith("/g-1/revoke"), `${name}: revoked the grant`);

    // What the reviewer recorded, newest first.
    activity = [
      { kind: "clause", id: "c1", requirement_key: "k", requirement_title: "Lawful basis documented", reviewer_name: "Dr Ada Reviewer", at: "2026-10-19T10:00:00Z", outcome: null, outcome_label: null, verified: true, text: "Citation checked" },
      { kind: "review", id: "r1", requirement_key: "k", requirement_title: "Lawful basis documented", reviewer_name: "Dr Ada Reviewer", at: "2026-10-18T10:00:00Z", outcome: "reviewed_with_comments", outcome_label: "Reviewed, with comments", verified: null, text: "Read with the guidance" },
    ];
    await clickExact("REFRESH", '[aria-label="Reviewer grants"]');
    await page.waitForSelector('[data-testid="activity-list"]');
    const act = await page.evaluate(() => document.querySelector('[data-testid="activity-list"]').innerText);
    assert.ok(act.indexOf("marked the clause reference as reviewed") < act.indexOf("recorded a review") && act.includes("Citation checked"), `${name}: activity newest first`);
    await noVerdicts(`${name} owner tab`);

    // An admin does not see the tab.
    memberships = [{ org: { ...org }, role: "admin", domains: [domain] }];
    await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
    await page.waitForSelector('[data-testid="compliance-disclaimer"]', { timeout: 10000 });
    assert.equal(await page.evaluate(() => !![...document.querySelectorAll('[role="tab"]')].find((t) => /reviewer access/i.test(t.textContent))), false, `${name}: admins cannot grant`);

    // Owners see a practitioner note beside the requirement.
    memberships = [{ org: { ...org }, role: "owner", domains: [domain] }];
    reqState = requirement({ practitioner_review: { outcome: "reviewed_with_comments", outcome_label: "Reviewed, with comments", reviewer_name: "Dr Ada Reviewer",
      reviewed_at: "2026-10-19T10:00:00Z", comment: "Read with the guidance", label: "Practitioner review recorded by Dr Ada Reviewer on 2026-10-19" },
      clause_review: { verified: true, reviewer_name: "Dr Ada Reviewer", at: "2026-10-19T10:00:00Z", note: null, label: "reference reviewed by Dr Ada Reviewer, 2026-10-19" },
      clause_label: "NDPA 2023 s.25 · reference reviewed by Dr Ada Reviewer, 2026-10-19", clause_verified: false });
    await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
    await page.waitForSelector('[data-testid="compliance-disclaimer"]', { timeout: 10000 });
    assert.ok((await bodyText()).includes("reference reviewed by Dr Ada Reviewer, 2026-10-19"), `${name}: overlay replaces pending`);
    assert.ok(!(await bodyText()).includes("reference pending review"), `${name}: no pending label left`);
    assert.ok(await clickText("Lawful basis documented"));
    await page.waitForSelector('[data-testid="practitioner-note"]');
    const note = await page.evaluate(() => document.querySelector('[data-testid="practitioner-note"]').innerText);
    assert.ok(note.includes("Practitioner review recorded by Dr Ada Reviewer on 2026-10-19") && note.includes("Read with the guidance") && /does not change the status/i.test(note), `${name}: note shown with its label`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow with the note`);
    await noVerdicts(`${name} note`);

    // ---------------- Reviewer: a user with no organisation ----------------
    reset();
    me = reviewerUser;
    memberships = [];
    myGrants = [{ org_id: org.id, org_name: org.name, purpose: "Annual readiness review", expires_at: "2026-11-20T00:00:00Z" }];
    await page.goto(`${origin}/reviews`, { waitUntil: "networkidle0" });
    await page.waitForSelector('[data-testid="review-orgs"]', { timeout: 10000 });
    assert.equal(new URL(page.url()).pathname, "/reviews", `${name}: a reviewer without a workspace stays on /reviews`);
    let text = await bodyText();
    assert.ok(text.includes("Acme Traders") && text.includes("Annual readiness review") && text.includes("not a") && text.includes("member"), `${name}: organisation listed with the limits`);
    await clickText("Acme Traders");
    await page.waitForSelector('[data-testid="review-org"]');
    assert.ok((await page.evaluate(() => document.querySelector('[data-testid="review-readiness"]').innerText)).includes("1 of 1 requirements have evidence"), `${name}: read-only readiness`);
    assert.ok(await clickText("Lawful basis documented"));
    await page.waitForSelector('[data-testid="record-review"]');
    text = await bodyText();
    assert.ok(text.includes("lawful_basis.documented: yes") && text.includes("Ada Obi"), `${name}: answer value and owner shown`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow in the reviewer view`);

    // Record practitioner review: copy first, then the write.
    assert.ok(await clickText("RECORD PRACTITIONER REVIEW"));
    await page.waitForSelector('[data-testid="dialog-review"]');
    const rtext = await dialogText();
    assert.ok(rtext.includes("does not change its status") && rtext.includes("says nothing about the organisation"), `${name}: review copy`);
    assert.equal(writes.length, 0);
    await page.keyboard.press("Escape");
    await waitDialogGone();
    assert.equal(writes.length, 0, `${name}: escape closes without writing`);
    await clickText("RECORD PRACTITIONER REVIEW");
    await page.waitForSelector('[data-testid="dialog-review"]');
    await page.evaluate(() => [...document.querySelectorAll('[role="dialog"] label')].find((l) => l.textContent.trim() === "Reviewed, with comments").querySelector("input").click());
    await setVal("#rv-text", "Read the clause and the guidance");
    await clickExact("RECORD REVIEW", '[role="dialog"]');
    await waitDialogGone();
    assert.deepEqual(writes[0].body, { outcome: "reviewed_with_comments", comment: "Read the clause and the guidance" }, `${name}: review body`);
    await page.waitForSelector('[data-testid="existing-note"]');
    assert.ok((await page.evaluate(() => document.querySelector('[data-testid="existing-note"]').innerText)).includes("Practitioner review recorded by Dr Ada Reviewer on 2026-10-19"), `${name}: note on file`);

    // Verify clause reference.
    assert.ok(await clickText("VERIFY CLAUSE REFERENCE"));
    await page.waitForSelector('[data-testid="dialog-clause"]');
    const ctext = await dialogText();
    assert.ok(ctext.includes("citation shown for this requirement") && ctext.includes("does not change the register for anyone else"), `${name}: clause copy`);
    await noVerdicts(`${name} clause dialog`);
    await clickExact("RECORD REFERENCE", '[role="dialog"]');
    await waitDialogGone();
    assert.deepEqual(writes[1].body, { verified: true, note: null }, `${name}: clause body`);
    await page.waitForFunction(() => document.body.innerText.includes("reference reviewed by Dr Ada Reviewer, 2026-10-19"), { timeout: 5000 });
    assert.ok(await overflowOf() <= 0, `${name}: overflow after recording`);
    await noVerdicts(`${name} reviewer page`);

    // Keyboard: the requirement rows and action buttons are reachable by Tab.
    const focusable = await page.evaluate(() => [...document.querySelectorAll("main button")].every((b) => b.tabIndex >= 0));
    assert.ok(focusable, `${name}: buttons are keyboard-focusable`);

    // A member of an organisation who also has a grant sees the header link, and an ordinary member without one does not.
    me = owner;
    memberships = [{ org: { ...org }, role: "owner", domains: [domain] }];
    myGrants = [{ org_id: "other", org_name: "Other Org", purpose: "p", expires_at: "2026-11-20T00:00:00Z" }];
    await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
    await page.waitForSelector('[data-testid="compliance-disclaimer"]', { timeout: 10000 });
    await page.waitForSelector('[data-testid="reviews-link"]', { timeout: 5000 });
  }

  // No grant: the Reviews page says so and offers nothing.
  me = reviewerUser;
  memberships = [];
  myGrants = [];
  await page.goto(`${origin}/reviews`, { waitUntil: "networkidle0" });
  await page.waitForSelector('[data-testid="reviews-empty"]', { timeout: 10000 });

  assert.deepEqual(errors, [], `page errors: ${errors.join("; ")}`);
  console.log("reviewer UI checks passed");
} finally {
  await browser?.close();
  await server.close();
}
