// Compliance readiness page (packet C1) against a stubbed API.
// Desktop, 390px and 320px: disclaimer, readiness counts, status chips with
// source labels, "reference pending review", gap → findings and Create task
// (no duplicate when a task exists), locked groups on Starter, no verdict
// language in rendered text and no horizontal overflow.
import assert from "node:assert/strict";
import { createServer } from "vite";
import puppeteer from "puppeteer-core";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const frontend = fileURLToPath(new URL("..", import.meta.url));
process.chdir(frontend);
import {
  DISCLAIMER,
  BANNED,
  DOC_BANNED,
  ORG_ZONE,
  BROWSER_ZONE,
  HOUR,
  user,
  org,
  domain,
  evidence,
  req,
  finding,
  overview,
  members,
  localIso,
  qdef,
  attested,
  freshQuestions,
  incidentView,
  CHECKLIST,
  INCIDENT_DISCLAIMER,
  freshIncidents,
  DOC_TITLES,
  DOC_LABEL,
  draftText,
  docVersion,
  approved,
  freshDocuments,
  docsListing,
} from "./lib/compliance-fixtures.mjs";

const server = await createServer({ root: frontend, server: { host: "127.0.0.1", port: 0 } });
let browser;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || "/usr/bin/chromium", headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let plan = "growth";
  let role = "member";
  let existingTasks = [];
  const posts = [];
  const writes = [];
  let questions = freshQuestions();
  let incidents = freshIncidents(Date.now());
  const downloads = [];
  const flags = { failReads: new Set(), failWrites: false, delayMs: 0 };
  const freshPacks = () => [{ id: "p-old00000000", snapshot_id: "s-old00000000", kind: "readiness_pack", pack_version: "cyphward-ndpa-pack-v1",
    issued_at: "2026-10-10T09:00:00Z", retain_until: "2029-10-10T09:00:00Z", issued_by: user.id, window_start: null, window_end: null, html_sha256: "a".repeat(64), pdf_sha256: "d".repeat(64) }];
  let packs = freshPacks();
  let documents = freshDocuments();
  const freshFiles = () => [{ id: "ef-old", question_key: "dpo.designated", attestation_id: "a-dpo", display_name: "dpo-appointment-letter.pdf",
    content_type: "application/pdf", type_label: "PDF", size_bytes: 52341, sha256: "e".repeat(64), uploaded_at: "2026-10-17T09:00:00Z", uploaded_by: "Ada Obi" }];
  let evidenceFiles = freshFiles();
  const fileEvents = [];
  const reset = () => { flags.failReads.clear(); flags.failWrites = false; flags.delayMs = 0; evidenceFiles = freshFiles(); fileEvents.length = 0; questions = freshQuestions(); incidents = freshIncidents(Date.now()); packs = freshPacks(); documents = freshDocuments(); writes.length = 0; posts.length = 0; downloads.length = 0; };
  const json = (request, status, body) => void request.respond({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      return url.origin === origin ? void request.continue() : void request.abort();
    }
    const method = request.method();
    const path = url.pathname;
    if (flags.delayMs && method === "GET" && !path.endsWith("/auth/bootstrap")) {
      const realRespond = request.respond.bind(request);
      request.respond = (r) => new Promise((resolve) => setTimeout(() => resolve(realRespond(r)), flags.delayMs));
    }
    if ((flags.failWrites && method !== "GET") || (method === "GET" && [...flags.failReads].some((k) => path.includes(k)))) {
      return void request.respond({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Internal Server Error" }) });
    }
    const growth = plan !== "starter";
    if (path.endsWith("/auth/bootstrap")) return json(request, 200, { user, email_verified: true, memberships: [{ org: { ...org, plan }, role, domains: [domain] }] });
    if (path.endsWith("/compliance/overview")) return json(request, 200, overview(plan));
    if (path.endsWith("/compliance/questionnaire")) {
      if (!growth) return json(request, 403, { detail: "This part of the compliance pages is part of the Growth plan." });
      const shown = questions.filter((q) => q.shown);
      return json(request, 200, { disclaimer: DISCLAIMER, version: "ndpa-gaid-questionnaire-v1", register_version: "x", display_timezone: ORG_ZONE,
        answered: shown.filter((q) => q.answer_state !== "unanswered").length, questions });
    }
    if (path.endsWith("/compliance/attestations") && method === "POST") {
      const body = JSON.parse(request.postData() || "{}");
      writes.push({ method, path, body });
      const q = questions.find((x) => x.key === body.question_key);
      const owner = members.find((m) => m.id === body.owner_user_id);
      q.current = attested(`a-${writes.length}`, body.answer.value, owner, { date: body.answer.date || null, text: body.answer.text || null,
        evidence_link: body.evidence_link || null, notes: body.notes || null, attested_at: new Date().toISOString(),
        expires_at: body.expires_at || new Date(Date.now() + 365 * 24 * HOUR).toISOString() });
      q.answer_state = body.answer.value === "not_sure" ? "not_sure" : "answered";
      const tier = questions.find((x) => x.key === "registration.tier");
      const major = questions.find((x) => x.key === "registration.major_importance");
      tier.shown = major.current?.value === "yes";
      return json(request, 201, q.current);
    }
    if (path.includes("/compliance/evidence-files")) {
      if (!growth) return json(request, 403, { detail: "This part of the compliance pages is part of the Growth plan." });
      const one = path.match(/\/evidence-files\/([^/]+)(\/download)?$/);
      if (!one && method === "GET") {
        return json(request, 200, { files: evidenceFiles, usage: { files: evidenceFiles.length, bytes: 1 }, uploads_available: true,
          limits: { max_bytes: 10 * 1024 * 1024, max_files: 100, max_total_bytes: 500 * 1024 * 1024, extensions: ["docx", "jpeg", "jpg", "pdf", "png"], label: "x" } });
      }
      if (!one && method === "POST") {
        const key = url.searchParams.get("question_key");
        const name = decodeURIComponent(request.headers()["x-file-name"] || "");
        fileEvents.push({ method, key, name, type: request.headers()["content-type"], auth: request.headers().authorization });
        if (name.startsWith("refused")) return setTimeout(() => json(request, 422, { detail: "The file's contents do not match its PDF name. Check the file and try again." }), 100);
        return setTimeout(() => {
          evidenceFiles.push({ id: `ef-new-${fileEvents.length}`, question_key: key, attestation_id: null, display_name: name, content_type: "application/pdf",
            type_label: "PDF", size_bytes: 20, sha256: "f".repeat(64), uploaded_at: new Date().toISOString(), uploaded_by: "Compliance Review" });
          json(request, 201, evidenceFiles.at(-1));
        }, 600);
      }
      if (one && one[2] && method === "GET") {
        fileEvents.push({ method, id: one[1] });
        return json(request, 200, { url: `https://files.example.test/object/sign/${one[1]}?token=t&download=x`, expires_in: 60, display_name: "dpo-appointment-letter.pdf" });
      }
      if (one && method === "DELETE") {
        fileEvents.push({ method, id: one[1] });
        evidenceFiles = evidenceFiles.filter((f) => f.id !== one[1]);
        return json(request, 200, { id: one[1], removed: true, object_deleted: true });
      }
    }
    if (path.includes("/compliance/documents")) {
      if (!growth) return json(request, 403, { detail: "This part of the compliance pages is part of the Growth plan." });
      const generatedToday = 3 + writes.filter((w) => w.path.endsWith("/generate")).length;
      const generate = path.match(/\/documents\/([a-z_]+)\/generate$/);
      const approve = path.match(/\/documents\/([^/]+)\/approve$/);
      if (generate && method === "POST") {
        writes.push({ method, path });
        const version = documents.filter((d) => d.kind === generate[1]).length + 1;
        const made = docVersion(generate[1], version, { generated_at: new Date().toISOString() });
        documents.push(made);
        return json(request, 201, { id: made.id, version });
      }
      if (approve && method === "POST") {
        writes.push({ method, path });
        const target = documents.find((d) => d.id === approve[1]);
        target.approval = approved("Compliance Review", new Date().toISOString());
        return json(request, 201, { id: "ap-1", approved_at: target.approval.approved_at });
      }
      const one = path.match(/\/documents\/([^/]+)$/);
      if (one) {
        const d = documents.find((x) => x.id === one[1]);
        const latestVersion = Math.max(...documents.filter((x) => x.kind === d.kind).map((x) => x.version));
        return json(request, 200, { ...d, title: DOC_TITLES[d.kind], label: DOC_LABEL, text: draftText(d.kind, d.version), is_latest: d.version === latestVersion });
      }
      return json(request, 200, docsListing(documents, generatedToday));
    }
    if (path.includes("/compliance/incidents")) {
      if (!growth) return json(request, 403, { detail: "This part of the compliance pages is part of the Growth plan." });
      const now = Date.now();
      if (method === "GET") {
        return json(request, 200, { disclaimer: INCIDENT_DISCLAIMER, checklist: CHECKLIST, deadline_hours: 72, display_timezone: ORG_ZONE,
          incidents: incidents.map((i) => incidentView(i, ORG_ZONE, now)) });
      }
      const body = JSON.parse(request.postData() || "{}");
      writes.push({ method, path, body });
      if (method === "POST") {
        const utc = (v) => (v ? new Date(v).toISOString() : null); // the app sends UTC, so the mock stores it as sent
        const created = { id: `i-new-${writes.length}`, ...body, detected_at: utc(body.detected_at), became_aware_at: utc(body.became_aware_at),
          notified_commission_at: utc(body.notified_commission_at), notified_subjects_at: utc(body.notified_subjects_at) };
        incidents.unshift(created);
        return json(request, 201, incidentView(created, ORG_ZONE, now));
      }
      const target = incidents.find((i) => path.endsWith(`/${i.id}`));
      for (const [k, v] of Object.entries(body)) target[k] = k.startsWith("notified_") && v ? new Date(v).toISOString() : v;
      return json(request, 200, incidentView(target, ORG_ZONE, now));
    }
    if (path.includes("/api/v1/packs")) {
      if (!growth) return json(request, 403, { detail: "Evidence packs are part of the Growth plan." });
      if (/\/packs\/[^/]+\/(html|pdf)$/.test(path)) {
        downloads.push(path);
        return void request.respond({ status: 200, contentType: path.endsWith("pdf") ? "application/pdf" : "text/html", body: "stored bytes" });
      }
      if (method === "POST") {
        const body = JSON.parse(request.postData() || "{}");
        writes.push({ method, path, body });
        packs.unshift({ id: `p-new-${writes.length}000000`, snapshot_id: "s-new0000000", kind: body.kind, pack_version: "cyphward-ndpa-pack-v1",
          issued_at: new Date().toISOString(), retain_until: "2029-10-18T09:00:00Z", issued_by: user.id, window_start: null, window_end: null,
          html_sha256: "b".repeat(64), pdf_sha256: "c".repeat(64) });
        return json(request, 201, { pack: packs[0], created: true });
      }
      return json(request, 200, { packs, total: packs.length, notice: "Supporting evidence only. Not a Compliance Audit Return.", retention_months: 36,
        retention: "Kept for 36 months from the day it is issued (the default is 36 months, 3 years), and removed with your organisation. Names of answer owners recorded at the time stay in issued snapshots and packs." });
    }
    if (path.endsWith("/api/v1/members")) return json(request, 200, members);
    let body = {};
    if (path.endsWith("/remediation") && method === "GET") body = { tasks: existingTasks, total: existingTasks.length };
    else if (path.endsWith("/remediation") && method === "POST") {
      posts.push(JSON.parse(request.postData() || "{}"));
      body = { task: { id: "t-new", title: "Fix", status: "open" } };
    } else if (path.endsWith("/domains")) body = [domain];
    else if (path.includes("/notifications")) body = { notifications: [], unread_count: 0 };
    else if (path.includes("/platform/")) return void request.respond({ status: 403, contentType: "application/json", body: '{"detail":"no"}' });
    json(request, 200, body);
  });
  await page.emulateTimezone(BROWSER_ZONE);
  // Run the page's slow timers (the countdown tick) quickly so the live behaviour can be asserted.
  await page.evaluateOnNewDocument(() => {
    const original = window.setInterval.bind(window);
    window.setInterval = (fn, ms, ...rest) => original(fn, ms >= 10000 && ms <= 30000 ? 150 : ms, ...rest);
  });
  await page.evaluateOnNewDocument((u) => {
    localStorage.setItem(`cyphward-tour-v1:${u.id}`, "done");
    localStorage.setItem("cyphward-session", JSON.stringify({ access_token: "t", refresh_token: "r", user: u, _expires_at: Date.now() + 864000000 }));
    localStorage.setItem("cyphward-welcome-sent", u.id);
    localStorage.setItem("cyphward-theme", "light");
    localStorage.setItem("cyphward-cookie-consent", "accepted");
  }, user);

  const clickExact = (text, within = "body") => page.evaluate((t, scope) => {
    const root = document.querySelector(scope);
    const el = [...(root || document).querySelectorAll("button, a")].find((b) => !b.closest("[inert]") && b.textContent.replace(/\s+/g, " ").trim() === t);
    if (el) el.click();
    return !!el;
  }, text, within);
  const setVal = (selector, value) => page.evaluate((sel, v) => {
    const el = document.querySelector(sel);
    if (!el) throw new Error(`missing ${sel}`);
    const proto = el.tagName === "SELECT" ? HTMLSelectElement.prototype : el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  }, selector, value);
  const chooseRadio = (scope, label) => page.evaluate((sc, text) => {
    const l = [...document.querySelector(sc).querySelectorAll("label")].find((x) => x.textContent.trim() === text);
    if (!l) return false;
    l.querySelector("input").click();
    return true;
  }, scope, label);
  const bodyText = () => page.evaluate(() => document.body.innerText);
  const overflowOf = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  const activeInfo = () => page.evaluate(() => {
    const a = document.activeElement;
    return { id: a?.id || "", testid: a?.getAttribute?.("data-testid") || "", tag: a?.tagName || "", inDialog: !!a?.closest?.('[role="dialog"]') };
  });
  const openTab = async (label) => {
    assert.ok(await page.evaluate(label => {
      const button = [...document.querySelectorAll('[role="tab"]')].find(button => button.getAttribute('aria-label') === label);
      button?.click();
      return Boolean(button);
    }, label), `tab ${label}`);
    await page.waitForFunction(label => document.querySelector('[role="tab"][aria-selected="true"]')?.getAttribute('aria-label') === label, {}, label);
  };
  const noVerdicts = async (where) => {
    const lowered = (await bodyText()).toLowerCase();
    for (const phrase of where.includes("documents") ? DOC_BANNED : BANNED) assert.ok(!lowered.includes(phrase), `${where}: verdict language "${phrase}"`);
  };
  const qsel = (key) => `[data-testid="question-${key}"]`;
  const gotoComply = async () => {
    await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
    await page.waitForSelector('[data-testid="compliance-disclaimer"]', { timeout: 10000 });
  };

  const clickText = (text) => page.evaluate((t) => {
    const el = [...document.querySelectorAll("button, a")].find((b) => !b.closest("[inert]") && b.textContent.includes(t));
    if (el) el.click();
    return !!el;
  }, text);

  for (const [name, width] of [["desktop", 1440], ["mobile", 390], ["small-mobile", 320]]) {
    plan = "growth";
    existingTasks = [];
    posts.length = 0;
    await page.setViewport({ width, height: 900 });
    await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
    await page.waitForSelector('[data-testid="compliance-disclaimer"]', { timeout: 10000 });

    const view = await page.evaluate(() => ({
      disclaimer: document.querySelector('[data-testid="compliance-disclaimer"]').textContent.trim(),
      line: document.querySelector('[data-testid="readiness-line"]').textContent.replace(/\s+/g, " ").trim(),
      text: document.body.innerText,
      overflow: document.documentElement.scrollWidth - window.innerWidth,
      nav: !!document.querySelector('a[href="/comply"]'),
    }));
    assert.equal(view.disclaimer, DISCLAIMER, `${name}: disclaimer`);
    assert.equal(view.line, "3 of 11 have evidence · 7 awaiting input or upcoming checks", `${name}: readiness line`);
    assert.ok(!/\d%/.test(view.text), `${name}: no bare percentage`);
    for (const label of ["2 PRESENT", "1 GAPS", "1 NOT ASSESSED", "7 AWAITING INPUT", "Awaiting your input", "reference pending review", "No evidence yet"]) {
      assert.ok(view.text.includes(label) || view.text.toUpperCase().includes(label.toUpperCase()), `${name}: ${label}`);
    }
    assert.ok(view.text.toUpperCase().includes("TOOL OBSERVED"), `${name}: source label`);
    assert.ok(view.overflow <= 0, `${name}: horizontal overflow ${view.overflow}px`);
    if (width === 1440) assert.ok(view.nav, "sidebar has the Compliance entry");

    // Expand the ports requirement: the open ports are listed with "present".
    assert.ok(await clickText("Internet-exposed services inventoried"));
    await page.waitForFunction(() => document.body.innerText.includes("Open ports:"), { timeout: 5000 });
    assert.ok((await page.evaluate(() => document.body.innerText)).includes("acme.ng 80, 443, 3389"), `${name}: ports listed`);

    // Expand the gap: its finding and Create task.
    assert.ok(await clickText("Email anti-spoofing records"));
    await page.waitForFunction(() => document.body.innerText.includes("OPEN FINDINGS BEHIND THIS GAP"), { timeout: 5000 });
    assert.ok(await clickText("CREATE TASK"));
    await page.waitForFunction(() => document.body.innerText.includes("TASK CREATED"), { timeout: 5000 });
    assert.equal(posts.length, 1, `${name}: one task created`);
    assert.equal(posts[0].finding_id, "f-dmarc");

    // Externally observed evidence: source label, page found and change flag, tracker gap and cookie categories.
    assert.ok(view.text.toUpperCase().includes("EXTERNALLY OBSERVED"), `${name}: external source label`);
    assert.ok(await clickText("Privacy policy published"));
    await page.waitForFunction(() => document.body.innerText.includes("changed since last scan"), { timeout: 5000 });
    assert.ok(await clickText("No non-essential cookies before consent"));
    await page.waitForFunction(() => document.body.innerText.includes("Observed: google analytics"), { timeout: 5000 });
    assert.ok((await page.evaluate(() => document.body.innerText)).includes("__cf_bm (infrastructure)"), `${name}: cookie categories`);

    const lowered = (await page.evaluate(() => document.body.innerText)).toLowerCase();
    for (const phrase of BANNED) assert.ok(!lowered.includes(phrase), `${name}: verdict language "${phrase}"`);
    const expandedOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(expandedOverflow <= 0, `${name}: overflow after expanding ${expandedOverflow}px`);
    if (process.env.CYPHWARD_COMPLIANCE_SCREENSHOTS === "1") await page.screenshot({ path: `/tmp/compliance-${name}.png`, fullPage: true });
  }

  // An existing task for the finding is shown instead of creating a duplicate.
  existingTasks = [{ id: "t-old", finding_id: "f-dmarc", title: "Fix DMARC", status: "open" }];
  posts.length = 0;
  await page.setViewport({ width: 1440, height: 900 });
  await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
  await page.waitForSelector('[data-testid="compliance-disclaimer"]');
  await clickText("Email anti-spoofing records");
  await page.waitForFunction(() => document.body.innerText.includes("CREATE TASK"));
  await clickText("CREATE TASK");
  await page.waitForFunction(() => document.body.innerText.includes("VIEW TASK"), { timeout: 5000 });
  assert.equal(posts.length, 0, "no duplicate task");

  // Starter: other groups locked, readiness still shown.
  plan = "starter";
  await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
  await page.waitForSelector('[data-testid="compliance-disclaimer"]');
  const starter = await page.evaluate(() => document.body.innerText);
  assert.ok(starter.toUpperCase().includes("GROWTH PLAN") && starter.includes("SEE PLANS"), "locked group prompt");
  assert.ok(!starter.includes("Data protection officer designated"), "locked requirements hidden");
  assert.ok(starter.includes("Email anti-spoofing records"), "security group open on Starter");


  // ---------------- C3: owners and admins (all three widths) ----------------
  role = "admin";
  plan = "growth";
  for (const [name, width] of [["desktop", 1440], ["mobile", 390], ["small-mobile", 320]]) {
    reset();
    await page.setViewport({ width, height: 900 });
    await gotoComply();

    // Readiness: attested answers, renewal due and the Excluded section, in the organisation's zone.
    await clickText("Data protection officer designated");
    await page.waitForSelector('[data-testid="told-us"]', { timeout: 5000 });
    const told = await page.evaluate(() => document.querySelector('[data-testid="told-us"]').textContent.replace(/\s+/g, " ").trim());
    assert.match(told, /^You told us: Yes · Ada Obi, Legal on 16 Oct 2026 \(owner Ada Obi, renews 16 Oct 2027\)/, `${name}: told-us line (org zone, not the browser's)`);
    const readiness = await bodyText();
    assert.ok(readiness.toUpperCase().includes("RENEWAL DUE"), `${name}: renewal due on the expired answer`);
    assert.ok(readiness.includes("CUSTOMER ATTESTED"), `${name}: answer labelled customer attested`);
    const excluded = await page.evaluate(() => document.querySelector('[data-testid="excluded-section"]')?.innerText || "");
    assert.ok(excluded.includes("Impact assessment for high-risk processing") && excluded.includes("do not carry out high-risk processing"), `${name}: excluded section with reason`);
    assert.ok(!(await page.evaluate(() => document.querySelector('section[aria-label="Registration"]').innerText)).includes("Impact assessment for high-risk processing"),
      `${name}: excluded requirement is not listed as a requirement`);
    await noVerdicts(`${name} readiness`);

    // Questionnaire: applicability first, follow-ups only when shown.
    await openTab("Answer questions");
    await page.waitForSelector('[data-testid="questionnaire"]');
    let text = await bodyText();
    assert.ok(text.includes("What applies to you") && text.includes("major importance"), `${name}: applicability step first`);
    assert.ok(!text.includes("Which tier"), `${name}: follow-up hidden until shown`);
    assert.ok(text.includes("dates are in America/New_York"), `${name}: zone named`);
    const told2 = await page.evaluate(() => document.querySelector('[data-testid="question-dpia.high_risk_processing"] [data-testid="told-us"]').textContent);
    assert.ok(told2.includes("on 16 Oct 2026") && told2.includes("renews 16 Oct 2027"), `${name}: answered applicability question`);

    assert.ok(await clickExact("Answer", qsel("registration.major_importance")));
    const form = `[data-testid="form-registration.major_importance"]`;
    await page.waitForSelector(form);
    assert.deepEqual(await page.evaluate((f) => [...document.querySelectorAll(`${f} select`)[0].options].map((o) => o.textContent), form),
      ["Choose a member", "Compliance Review", "Ada Obi", "Tunde Bello"], `${name}: owner picker is the members`);
    assert.equal(await page.evaluate((f) => document.querySelectorAll(`${f} select`)[0].value, form), user.id, `${name}: owner defaults to the viewer`);
    const longest = await page.evaluate((f) => [...document.querySelectorAll(`${f} select`)[1].options].map((o) => o.textContent), form);
    assert.ok(longest.includes("24 months (longest)") && longest.includes("A date I choose") && !longest.some((o) => /36|48/.test(o)), `${name}: expiry capped at 24 months`);
    assert.ok(await chooseRadio(form, "Yes"));
    await setVal(`${form} input[type="url"]`, "http://insecure.example");
    assert.ok(await overflowOf() <= 0, `${name}: overflow with the form open`);
    await clickExact("Save answer", form);
    await page.waitForFunction(() => document.querySelector('[data-testid="form-error"]')?.textContent.includes("https"), { timeout: 5000 });
    assert.equal(writes.length, 0, `${name}: an http link is not sent`);
    await setVal(`${form} input[type="url"]`, "https://example.com/registration-proof");
    await setVal(`${form} textarea`, "Certificate is in the shared drive.");
    await clickExact("Save answer", form);
    await page.waitForFunction(() => document.body.innerText.includes("Which tier"), { timeout: 5000 });
    assert.equal(writes.length, 1, `${name}: one attestation sent`);
    const sent = writes[0].body;
    assert.equal(sent.question_key, "registration.major_importance");
    assert.deepEqual(sent.answer, { value: "yes" });
    assert.equal(sent.evidence_link, "https://example.com/registration-proof");
    assert.equal(sent.notes, "Certificate is in the shared drive.");
    assert.ok(members.some((m) => m.id === sent.owner_user_id), `${name}: owner is a member`);
    assert.equal(sent.expires_at, undefined, `${name}: default expiry is left to the server`);

    // A 24-month expiry stays inside the API's 730-day cap.
    assert.ok(await clickExact("Update answer", qsel("registration.major_importance")));
    await chooseRadio(form, "Yes");
    const expirySelect = await page.evaluateHandle((f) => [...document.querySelectorAll(`${f} select`)].find((x) => x.id.endsWith("-expiry")), form);
    await page.evaluate((el) => { el.value = "729"; el.dispatchEvent(new Event("change", { bubbles: true })); }, expirySelect);
    await clickExact("Save answer", form);
    await page.waitForFunction(() => !document.querySelector('[data-testid="form-registration.major_importance"]'), { timeout: 5000 });
    const days = (Date.parse(writes[1].body.expires_at) - Date.now()) / (24 * HOUR);
    assert.ok(days > 700 && days < 730, `${name}: 24-month expiry is ${days} days, inside the cap`);

    // Digits in a text answer are refused before sending; a date question takes no expiry.
    assert.ok(await clickExact("2. Data protection officer", 'nav[aria-label="Question groups"]'));
    await page.waitForSelector(qsel("dpo.six_monthly_report"));
    assert.ok(await clickExact("Update answer", qsel("dpo.designated")));
    const dform = `[data-testid="form-dpo.designated"]`;
    await setVal(`${dform} input[type="text"]`, "Ada 12345678");
    await clickExact("Save answer", dform);
    await page.waitForFunction(() => document.querySelector('[data-testid="form-dpo.designated"] [data-testid="form-error"]')?.textContent.includes("ID numbers"), { timeout: 5000 });
    assert.equal(writes.length, 2, `${name}: digits not sent`);
    await clickExact("Cancel", dform);
    assert.ok(await clickExact("Answer", qsel("dpo.six_monthly_report")));
    const sform = `[data-testid="form-dpo.six_monthly_report"]`;
    await page.waitForSelector(sform);
    assert.ok(await chooseRadio(sform, "I know the date"));
    await page.waitForSelector('[data-testid="expiry-follows-date"]');
    assert.ok(!(await page.evaluate((f) => [...document.querySelectorAll(`${f} select`)].some((x) => x.id.endsWith("-expiry")), sform)), `${name}: no expiry control on a date answer`);
    assert.equal(await page.evaluate((f) => document.querySelector(`${f} input[type="date"]`).max.length, sform), 10, `${name}: date capped at today`);
    await setVal(`${sform} input[type="date"]`, "2026-09-30");
    await clickExact("Save answer", sform);
    await page.waitForFunction(() => !document.querySelector('[data-testid="form-dpo.six_monthly_report"]'), { timeout: 5000 });
    assert.deepEqual(writes[2].body.answer, { value: "date", date: "2026-09-30" }, `${name}: date answer`);
    assert.equal(writes[2].body.expires_at, undefined, `${name}: date answers send no expiry`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow in the questionnaire`);
    await noVerdicts(`${name} questionnaire`);

    // Evidence files (C6): list, checks mirroring the server, progress, upload, download link, confirm-then-remove.
    assert.ok(await clickExact("2. Data protection officer", 'nav[aria-label="Question groups"]'));
    const fq = qsel("dpo.designated");
    await page.waitForSelector(`${fq} [data-testid="file-ef-old"]`);
    const listed = await page.evaluate((q) => document.querySelector(`${q} [data-testid="file-ef-old"]`).innerText.replace(/\s+/g, " "), fq);
    assert.match(listed, /dpo-appointment-letter\.pdf PDF · 51 KB · 17 Oct 2026 · Ada Obi/, `${name}: file row shows name, type, size, date, uploader (${listed})`);
    assert.ok(await page.evaluate((q) => /Cyphward does not read or review it/.test(document.querySelector(q).innerText), fq), `${name}: attach area says it is not reviewed`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow with files listed`);
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cyph-files-"));
    const make = (file, bytes) => { const full = path.join(tmp, file); fs.writeFileSync(full, bytes); return full; };
    const fileInput = await page.$(`${fq} [data-testid="file-input-dpo.designated"]`);
    for (const [bad, bytes, pattern] of [["tool.exe", "MZ", /Only PDF, PNG, JPG\/JPEG or DOCX files up to 10 MB/], ["report.exe.pdf", "%PDF-1", /second extension/],
      ["empty.pdf", "", /empty/], ["big.pdf", Buffer.alloc(10 * 1024 * 1024 + 1), /limit is 10\.0 MB/]]) {
      await fileInput.uploadFile(make(bad, bytes));
      await page.waitForFunction((q) => document.querySelector(`${q} [data-testid="file-error"]`), { timeout: 5000 }, fq);
      const msg = await page.evaluate((q) => document.querySelector(`${q} [data-testid="file-error"]`).textContent, fq);
      assert.match(msg, pattern, `${name}: ${bad} refused before sending (${msg})`);
    }
    assert.equal(fileEvents.filter((e) => e.method === "POST").length, 0, `${name}: refused files are never sent`);
    await fileInput.uploadFile(make("refused-mismatch.pdf", "%PDF-1"));
    await page.waitForFunction((q) => document.querySelector(`${q} [data-testid="upload-progress"]`), { timeout: 5000 }, fq);
    assert.ok(await page.evaluate((q) => /Uploading refused-mismatch\.pdf/.test(document.querySelector(`${q} [data-testid="upload-progress"]`).innerText), fq), `${name}: progress shown`);
    await page.waitForFunction((q) => /do not match/.test(document.querySelector(`${q} [data-testid="file-error"]`)?.textContent || ""), { timeout: 5000 }, fq);
    assert.equal(await page.evaluate((q) => !!document.querySelector(`${q} [data-testid="upload-progress"]`), fq), false, `${name}: progress ends on a server refusal`);
    await fileInput.uploadFile(make("new-minutes.pdf", "%PDF-1.4 hello"));
    await page.waitForFunction((q) => document.body.innerText.includes("new-minutes.pdf") && !document.querySelector(`${q} [data-testid="upload-progress"]`), { timeout: 5000 }, fq);
    const sentUpload = fileEvents.filter((e) => e.method === "POST").at(-1);
    assert.deepEqual([sentUpload.key, sentUpload.name, sentUpload.type, sentUpload.auth], ["dpo.designated", "new-minutes.pdf", "application/octet-stream", "Bearer t"], `${name}: raw upload with the session`);
    // Download: the API is called, then the signed link is followed as a download.
    await page.evaluate(() => { window.__followed = []; HTMLAnchorElement.prototype.click = function () { window.__followed.push([this.href, this.getAttribute("download")]); }; });
    assert.ok(await page.evaluate((q) => { document.querySelector(`${q} [data-testid="file-ef-old"] button[aria-label^="Download"]`).click(); return true; }, fq));
    await page.waitForFunction(() => window.__followed.length === 1, { timeout: 5000 });
    const followed = await page.evaluate(() => window.__followed[0]);
    assert.ok(followed[0].startsWith("https://files.example.test/object/sign/ef-old?token=") && followed[0].includes("download="), `${name}: the signed link is followed`);
    assert.equal(followed[1], "dpo-appointment-letter.pdf", `${name}: saved under the display name`);
    // Remove asks first; cancel keeps the file, confirm removes it.
    const removeBtn = `${fq} [data-testid="file-ef-old"] button[aria-label^="Remove"]`;
    await page.evaluate((b) => document.querySelector(b).click(), removeBtn);
    await page.waitForFunction(() => /remove this file\?/i.test(document.body.innerText), { timeout: 5000 });
    assert.equal(fileEvents.filter((e) => e.method === "DELETE").length, 0, `${name}: nothing removed before the confirm step`);
    assert.ok(await page.evaluate(() => { document.querySelector('[data-testid="confirm-cancel"]').click(); return true; }));
    await page.waitForFunction(() => !/remove this file\?/i.test(document.body.innerText), { timeout: 5000 });
    assert.equal(fileEvents.filter((e) => e.method === "DELETE").length, 0, `${name}: cancel keeps the file`);
    await page.evaluate((b) => document.querySelector(b).click(), removeBtn);
    await page.waitForFunction(() => /remove this file\?/i.test(document.body.innerText), { timeout: 5000 });
    assert.ok(await page.evaluate(() => { document.querySelector('[data-testid="confirm-ok"]').click(); return true; }));
    await page.waitForFunction(() => !document.body.innerText.includes("dpo-appointment-letter.pdf"), { timeout: 5000 });
    assert.equal(fileEvents.filter((e) => e.method === "DELETE").length, 1, `${name}: one removal after the confirm`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow with the attach area`);
    // Keyboard: the attach button is reachable and its label is plain text.
    assert.ok(await page.evaluate((q) => [...document.querySelectorAll(`${q} button`)].some((b) => b.textContent.trim() === "ATTACH EVIDENCE" && b.tabIndex === 0), fq), `${name}: attach button is focusable`);
    await noVerdicts(`${name} evidence files`);
    fs.rmSync(tmp, { recursive: true, force: true });
    if (process.env.CYPHWARD_COMPLIANCE_SCREENSHOTS === "1") await page.screenshot({ path: `/tmp/compliance-files-${name}.png`, fullPage: true });

    // Incidents: list, badges, countdown, zone and the checklist.
    await openTab("Incidents");
    await page.waitForSelector('[data-testid="incidents"]');
    const inc = await page.evaluate(() => ({
      text: document.body.innerText,
      overdue: document.querySelector('[data-testid="incident-i-over"] [data-testid="badge-overdue"]')?.textContent.trim(),
      live: document.querySelector('[data-testid="incident-i-live"] [data-testid="countdown"]')?.textContent.trim(),
      late: document.querySelector('[data-testid="incident-i-late"] [data-testid="badge-notified-late"]')?.textContent.trim(),
      overdueOnLive: !!document.querySelector('[data-testid="incident-i-live"] [data-testid="badge-overdue"]'),
      steps: [...document.querySelectorAll('[data-testid="incident-checklist"] li')].length,
      disclaimer: document.querySelector('[data-testid="incident-disclaimer"]').textContent.trim(),
    }));
    assert.equal(inc.overdue, "Overdue", `${name}: overdue badge`);
    assert.match(inc.live, /^59h (29|30|28)m left$/, `${name}: countdown in hours and minutes (${inc.live})`);
    assert.equal(inc.late, "Notified late", `${name}: notified late`);
    assert.ok(!inc.overdueOnLive, `${name}: a running countdown is not overdue`);
    assert.equal(inc.steps, 6, `${name}: six checklist steps`);
    assert.equal(inc.disclaimer, INCIDENT_DISCLAIMER, `${name}: incident disclaimer`);
    assert.ok(inc.text.includes("All times are in America/New_York"), `${name}: zone named`);
    assert.ok(await clickExact("Details", '[data-testid="incident-i-live"]'));
    await page.waitForSelector('[role="dialog"] [data-testid="incident-details"]');
    assert.ok((await bodyText()).includes("Disk was encrypted."), `${name}: notes shown in the details dialog`);
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 3000 });

    // Create: the form is a dialog with native pickers; a time typed in the organisation's zone goes out as UTC.
    assert.ok(await clickExact("Record an incident"));
    await page.waitForSelector('[role="dialog"] [data-testid="incident-form"]');
    assert.equal(await page.evaluate(() => document.querySelector("#inc-detected").type + "/" + document.querySelector("#inc-aware").type), "datetime-local/datetime-local", `${name}: native pickers`);
    // The offset is today's (daylight saving ends in New York on the first Sunday of November), not a fixed -04:00.
    const nyOffset = new Intl.DateTimeFormat("en-US", { timeZone: ORG_ZONE, timeZoneName: "longOffset" })
      .formatToParts(new Date()).find((p) => p.type === "timeZoneName").value.replace("GMT", "UTC");
    assert.ok((await bodyText()).includes(`Time in America/New_York (${nyOffset})`), `${name}: zone beside the time field (${nyOffset})`);
    await setVal("#inc-title", "Shared drive link left public");
    await setVal("#inc-severity", "high");
    await setVal("#inc-detected", "2026-10-15T09:30");
    await setVal("#inc-aware", "2026-10-15T10:45");
    assert.ok(await overflowOf() <= 0, `${name}: overflow with the incident dialog open`);
    const writesBefore = writes.length;
    await page.click('[data-testid="incident-save"]');
    await page.waitForFunction(() => document.body.innerText.includes("Shared drive link left public") && !document.querySelector('[data-testid="incident-form"]'), { timeout: 5000 });
    const created = writes[writesBefore].body;
    assert.equal(created.detected_at, "2026-10-15T13:30:00.000Z", `${name}: sent as UTC (09:30 in New York is 13:30 UTC)`);
    assert.equal(created.became_aware_at, "2026-10-15T14:45:00.000Z");
    assert.equal(created.title, "Shared drive link left public");
    assert.ok(!("notified_commission_at" in created), `${name}: unset times are not sent`);
    assert.ok((await page.evaluate(() => document.querySelector(".toasts")?.innerText || "")).includes("Incident recorded."), `${name}: a toast confirms the save`);
    const shown = await page.evaluate(() => document.querySelector('[data-testid^="incident-i-new"]').innerText);
    assert.ok(shown.includes("15 Oct 2026 10:45"), `${name}: shown in the organisation's zone (${shown})`);

    // Edit: only changed fields go out; title and the awareness times are read-only; clearing sends null;
    // recording the Commission time asks first and Cancel sends nothing.
    assert.ok(await clickExact("Edit", '[data-testid="incident-i-live"]'));
    await page.waitForSelector('[data-testid="incident-form"]');
    assert.equal(await page.evaluate(() => !!document.querySelector("#inc-title, #inc-detected, #inc-aware")), false, `${name}: immutable fields are not editable`);
    assert.equal(await page.evaluate(() => document.querySelector("#inc-subjects").value.length), 16, `${name}: prefilled from the zone's wall time`);
    await setVal("#inc-subjects", "");
    const awareMs = Date.now() - 12.5 * HOUR;
    const commissionWall = localIso(new Date(awareMs + HOUR).toISOString(), ORG_ZONE).slice(0, 16);
    await setVal("#inc-commission", commissionWall);
    const before = writes.length;
    await page.click('[data-testid="incident-save"]');
    await page.waitForSelector('[data-testid="confirm-dialog"]', { timeout: 5000 });
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("data-testid")), "confirm-cancel", `${name}: Cancel is the default focus, even for a deliberate action`);
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => !document.querySelector('[data-testid="confirm-dialog"]'), { timeout: 3000 });
    assert.equal(writes.length, before, `${name}: Enter on the default focus does not confirm`);
    await page.click('[data-testid="incident-save"]');
    await page.waitForSelector('[data-testid="confirm-dialog"]');
    const ask = await page.evaluate(() => document.querySelector('[data-testid="confirm-dialog"]').innerText);
    assert.ok(/record notification time/i.test(ask) && /countdown stops/.test(ask), `${name}: confirmation names the action and what cannot be undone (${ask})`);
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.querySelector('[data-testid="confirm-dialog"]'), { timeout: 3000 });
    assert.ok(await page.evaluate(() => !!document.querySelector('[data-testid="incident-form"]')), `${name}: Esc closes only the top dialog`);
    assert.equal(writes.length, before, `${name}: cancelling the confirmation sends nothing`);
    // A failed save after confirming: the confirmation's opener is disabled, so focus must land inside the form dialog, not on the page.
    flags.failWrites = true;
    await page.click('[data-testid="incident-save"]');
    await page.waitForSelector('[data-testid="confirm-dialog"]');
    await page.click('[data-testid="confirm-ok"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="incident-error"]'), { timeout: 5000 });
    await new Promise((r) => setTimeout(r, 100));
    assert.ok((await activeInfo()).inDialog, `${name}: focus stays in the dialog after a failed save`);
    flags.failWrites = false;
    await page.waitForFunction(() => !document.querySelector('[data-testid="confirm-dialog"]'), { timeout: 3000 });
    await page.click('[data-testid="incident-save"]');
    await page.waitForSelector('[data-testid="confirm-dialog"]');
    await page.click('[data-testid="confirm-ok"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="incident-i-live"] [data-testid="badge-notified"], [data-testid="incident-i-live"] [data-testid="badge-notified-late"]'), { timeout: 5000 });
    const sentCommission = writes[before].body.notified_commission_at;
    assert.equal(sentCommission, new Date(awareMs + HOUR).toISOString().slice(0, 16) + ":00.000Z", `${name}: the Commission time goes out as UTC`);
    assert.equal(writes[before].body.notified_subjects_at, null, `${name}: clearing sends null`);
    assert.deepEqual(Object.keys(writes[before].body).sort(), ["notified_commission_at", "notified_subjects_at"], `${name}: PATCH carries only the changes`);
    assert.match(writes[before].path, /\/compliance\/incidents\/i-live$/);
    assert.ok(await overflowOf() <= 0, `${name}: overflow in incidents`);
    await noVerdicts(`${name} incidents`);
    if (process.env.CYPHWARD_COMPLIANCE_SCREENSHOTS === "1") await page.screenshot({ path: `/tmp/compliance-incidents-${name}.png`, fullPage: true });

    // Packs: list, issue, download; supporting-evidence notice; no verdict language.
    await openTab("Packs");
    await page.waitForSelector('[data-testid="packs"]');
    const pk = await page.evaluate(() => ({ rows: document.querySelectorAll('[data-testid="pack-list"] li').length,
      notice: document.querySelector('[data-testid="packs-notice"]')?.textContent || "",
      retention: document.querySelector('[data-testid="packs-retention"]')?.textContent || "",
      row: document.querySelector('[data-testid="pack-list"] li')?.textContent || "" }));
    assert.equal(pk.rows, 1, `${name}: the issued pack is listed`);
    assert.ok(/36 months/.test(pk.retention) && /names of answer owners/i.test(pk.retention), `${name}: packs show the retention period and the owner-name disclosure`);
    assert.ok(/kept until/i.test(pk.row), `${name}: each pack shows when it becomes eligible for removal`);
    assert.ok(/not a compliance audit return/i.test(pk.notice), `${name}: packs say they are not a Compliance Audit Return`);
    const beforePack = writes.length;
    await page.evaluate(() => document.querySelector('[data-testid="issue-dpo_section"]').click());
    await page.waitForSelector('[data-testid="confirm-dialog"]', { timeout: 5000 });
    const packAsk = await page.evaluate(() => document.querySelector('[data-testid="confirm-dialog"]').innerText);
    assert.ok(/issue pack/i.test(packAsk) && /cannot be edited or taken back/.test(packAsk), `${name}: issuing a pack asks, names the action and says what cannot be undone`);
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("data-testid")), "confirm-cancel", `${name}: Cancel is the default focus for issuing a pack`);
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => !document.querySelector('[data-testid="confirm-dialog"]'), { timeout: 3000 });
    assert.equal(writes.length, beforePack, `${name}: cancelling sends nothing`);
    await page.evaluate(() => document.querySelector('[data-testid="issue-dpo_section"]').click());
    await page.waitForSelector('[data-testid="confirm-dialog"]');
    await page.click('[data-testid="confirm-ok"]');
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="pack-list"] li').length === 2, { timeout: 5000 });
    assert.ok((await page.evaluate(() => document.querySelector(".toasts")?.innerText || "")).includes("Pack issued."), `${name}: a toast confirms the pack`);
    await new Promise((r) => setTimeout(r, 100));
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("data-testid")), "issue-dpo_section", `${name}: focus is back on the issue button, not lost`);
    assert.equal(writes[beforePack].body.kind, "dpo_section", `${name}: issue sends the kind`);
    assert.ok(/^ui-/.test(writes[beforePack].body.request_key || ""), `${name}: each click carries its own request key`);
    assert.deepEqual(Object.keys(writes[beforePack].body).sort(), ["kind", "request_key"], `${name}: issue sends only the kind and the key`);
    await page.evaluate(() => document.querySelector('[data-testid="download-pdf"]').click());
    for (let waited = 0; waited < 3000 && !downloads.some((d) => d.endsWith("/pdf")); waited += 100) await new Promise((r) => setTimeout(r, 100));
    assert.ok(downloads.some((d) => d.endsWith("/pdf")), `${name}: the PDF is fetched with the session`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow in packs`);
    await noVerdicts(`${name} packs`);
  }

  // The countdown runs on its own and flips to Overdue when the deadline passes.
  reset();
  await page.setViewport({ width: 1440, height: 900 });
  await gotoComply();
  await openTab("Incidents");
  await page.waitForSelector('[data-testid="incident-i-live"] [data-testid="countdown"]');
  await page.evaluate(() => { const real = Date.now.bind(Date); window.__skew = 0; Date.now = () => real() + window.__skew; });
  await page.evaluate((h) => { window.__skew = h; }, 2 * HOUR);
  await page.waitForFunction(() => /^57h (2\d|30)m left$/.test(document.querySelector('[data-testid="incident-i-live"] [data-testid="countdown"]')?.textContent.trim() || ""), { timeout: 5000 });
  await page.evaluate((h) => { window.__skew = h; }, 61 * HOUR);
  await page.waitForFunction(() => document.querySelector('[data-testid="incident-i-live"] [data-testid="badge-overdue"]'), { timeout: 5000 });
  await page.evaluate(() => { window.__skew = 0; });

  // ---------------- C3: members see everything and can change nothing ----------------
  role = "member";
  for (const [name, width] of [["desktop", 1440], ["small-mobile", 320]]) {
    reset();
    await page.setViewport({ width, height: 900 });
    await gotoComply();
    await openTab("Answer questions");
    await page.waitForSelector('[data-testid="questionnaire"]');
    const q = await page.evaluate(() => ({
      buttons: [...document.querySelectorAll("button")].map((b) => b.textContent.trim()),
      forms: document.querySelectorAll("form, input, select, textarea").length,
      note: !!document.querySelector('[data-testid="read-only-note"]'),
      told: document.querySelectorAll('[data-testid="told-us"]').length,
    }));
    assert.ok(q.note && q.told >= 1, `${name}: members see the answers read-only`);
    assert.equal(q.forms, 0, `${name}: no form controls rendered for a member (questions)`);
    assert.ok(!q.buttons.some((b) => /^(answer|update answer|save answer)$/i.test(b)), `${name}: no answer buttons`);
    // Evidence files: a member sees the list and can download, but can neither attach nor remove.
    assert.ok(await clickExact("2. Data protection officer", 'nav[aria-label="Question groups"]'));
    await page.waitForSelector('[data-testid="file-ef-old"]');
    const mf = await page.evaluate(() => ({
      buttons: [...document.querySelectorAll('[data-testid="file-ef-old"] button')].map((b) => b.textContent.trim()),
      inputs: document.querySelectorAll('input[type="file"], [data-testid^="file-input-"]').length,
      attach: [...document.querySelectorAll("button")].some((b) => /ATTACH EVIDENCE|REMOVE/.test(b.textContent)),
    }));
    assert.deepEqual(mf.buttons, ["DOWNLOAD"], `${name}: members can only download`);
    assert.equal(mf.inputs, 0, `${name}: no file input for a member`);
    assert.equal(mf.attach, false, `${name}: no attach or remove for a member`);
    assert.ok(await clickExact("1. What applies to you", 'nav[aria-label="Question groups"]'));
    await openTab("Incidents");
    await page.waitForSelector('[data-testid="incidents"]');
    const i = await page.evaluate(() => ({
      buttons: [...document.querySelectorAll("button")].map((b) => b.textContent.trim()),
      forms: document.querySelectorAll("form, input, select, textarea").length,
      rows: document.querySelectorAll('[data-testid^="incident-i-"]').length,
      overdue: !!document.querySelector('[data-testid="badge-overdue"]'),
    }));
    assert.equal(i.rows, 3, `${name}: members see the incidents`);
    assert.ok(i.overdue, `${name}: members see the overdue badge`);
    assert.equal(i.forms, 0, `${name}: no form controls rendered for a member (incidents)`);
    assert.ok(!i.buttons.some((b) => /^(edit|record an incident|record incident|update this incident)$/i.test(b)), `${name}: no incident write buttons`);
    await openTab("Packs");
    await page.waitForSelector('[data-testid="packs"]');
    const mp = await page.evaluate(() => ({ rows: document.querySelectorAll('[data-testid="pack-list"] li').length,
      issue: [...document.querySelectorAll("button")].some((b) => /^issue /i.test(b.textContent.trim())),
      note: !!document.querySelector('[data-testid="read-only-note"]'),
      download: !!document.querySelector('[data-testid="download-pdf"]') }));
    assert.ok(mp.rows === 1 && mp.download && mp.note && !mp.issue, `${name}: members download packs but cannot issue`);
    await noVerdicts(`${name} member packs`);
    assert.equal(writes.length, 0, `${name}: members send no writes`);
    assert.ok(await overflowOf() <= 0, `${name}: member overflow`);
    await noVerdicts(`${name} member`);
  }


  // ---------------- C5: documents (owners/admins, then members, then Starter) ----------------
  const docKinds = ["privacy_policy", "cookie_notice", "breach_response_plan", "retention_schedule"];
  const docCard = (kind) => `[data-testid="doc-${kind}"]`;
  const statusOf = (kind) => page.evaluate((k) => document.querySelector(`[data-testid="doc-status-${k}"]`)?.textContent.trim().toUpperCase(), kind);
  const stubClipboard = () => page.evaluate(() => {
    window.__copied = [];
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (t) => { window.__copied.push(t); } } });
  });
  role = "admin";
  plan = "growth";
  for (const [name, width] of [["desktop", 1440], ["mobile", 390], ["small-mobile", 320]]) {
    reset();
    await page.setViewport({ width, height: 900 });
    await gotoComply();
    await openTab("Documents");
    await page.waitForSelector('[data-testid="documents"]');
    const d = await page.evaluate(() => ({
      disclaimer: document.querySelector('[data-testid="documents-disclaimer"]').textContent,
      quota: document.querySelector('[data-testid="doc-quota"]').textContent,
      cards: document.querySelectorAll('section[aria-label="Documents"] > ul > li').length,
    }));
    assert.ok(d.disclaimer.startsWith(DOC_LABEL), `${name}: documents disclaimer leads with the label`);
    assert.ok(d.disclaimer.includes("does not change your readiness page"), `${name}: approval does not touch readiness`);
    assert.equal(d.quota, "3 of 10 drafts used today · times are in America/New_York", `${name}: quota line`);
    assert.equal(d.cards, 4, `${name}: four documents`);
    assert.deepEqual(await Promise.all(docKinds.map(statusOf)), ["DRAFT", "NOT GENERATED", "APPROVED", "DRAFT"], `${name}: statuses`);
    assert.ok((await bodyText()).includes("Your answers have changed since this version"), `${name}: stale note`);
    assert.ok(await overflowOf() <= 0, `${name}: documents overflow`);

    // View: opens in a dialog with the banner, highlighted placeholders, label as the first line, copy and download.
    assert.ok(await clickExact("View", docCard("privacy_policy")));
    await page.waitForSelector('[role="dialog"] [data-testid="doc-viewer"]');
    const v = await page.evaluate(() => ({
      banner: document.querySelector('[data-testid="doc-banner"]').textContent,
      text: document.querySelector('[data-testid="doc-text"]').textContent,
      marks: [...document.querySelectorAll('[data-testid="placeholder"]')].map((m) => m.textContent),
      buttons: [...document.querySelectorAll('[role="dialog"] button')].map((b) => b.textContent.trim()),
    }));
    assert.ok(v.banner.startsWith(DOC_LABEL), `${name}: banner`);
    assert.ok(v.text.startsWith(DOC_LABEL), `${name}: label is the first line of the text`);
    assert.deepEqual(v.marks, ["[MISSING: name of your data protection officer]", "[MISSING: how long you keep each kind of personal data]"], `${name}: placeholders highlighted`);
    for (const b of ["Copy text", "Copy Markdown", "Download text", "Download Markdown", "Approve this version"]) assert.ok(v.buttons.includes(b), `${name}: ${b}`);
    await stubClipboard();
    await clickExact("Copy text", '[data-testid="doc-viewer"]');
    await clickExact("Copy Markdown", '[data-testid="doc-viewer"]');
    const copied = await page.evaluate(() => window.__copied);
    assert.ok(copied[0].startsWith(DOC_LABEL) && !copied[0].includes("# "), `${name}: text copy keeps the label, drops heading marks`);
    assert.ok(copied[1].startsWith(DOC_LABEL) && copied[1].includes("# Privacy policy of Acme Traders"), `${name}: markdown copy`);
    assert.ok(await overflowOf() <= 0, `${name}: viewer overflow`);
    await noVerdicts(`${name} documents`);

    // Approve: a confirmation (over the document) says what it does not mean and what cannot be undone, then the approver and date show.
    assert.ok(await clickExact("Approve this version", '[role="dialog"]'));
    await page.waitForSelector('[data-testid="confirm-dialog"]');
    const approveAsk = await page.evaluate(() => document.querySelector('[data-testid="confirm-dialog"]').innerText);
    assert.ok(approveAsk.includes("does not mean the document is published or in force"), `${name}: approval wording`);
    assert.ok(approveAsk.includes("cannot be taken back") && /approve version/i.test(approveAsk), `${name}: approval names the action and what cannot be undone`);
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("data-testid")), "confirm-cancel", `${name}: Cancel is the default focus for approving`);
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => !document.querySelector('[data-testid="confirm-dialog"]'), { timeout: 3000 });
    assert.equal(writes.filter((w) => w.path.endsWith("/approve")).length, 0, `${name}: cancelling approves nothing`);
    assert.ok(await clickExact("Approve this version", '[role="dialog"]'));
    await page.waitForSelector('[data-testid="confirm-dialog"]');
    await page.click('[data-testid="confirm-ok"]');
    await page.waitForSelector('[data-testid="doc-approval"]', { timeout: 5000 });
    assert.match(await page.evaluate(() => document.querySelector('[data-testid="doc-approval"]').textContent), /^Approved by Compliance Review on \d/, `${name}: approver shown`);
    await new Promise((r) => setTimeout(r, 100));
    assert.ok((await activeInfo()).inDialog, `${name}: after approving, focus is inside the reopened document, not on the page`);
    assert.equal(writes.filter((w) => w.path.endsWith("/approve")).length, 1, `${name}: one approval sent`);
    assert.ok((await page.evaluate(() => document.querySelector(".toasts")?.innerText || "")).includes("Approval recorded."), `${name}: a toast confirms the approval`);
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 3000 });
    assert.equal(await statusOf("privacy_policy"), "APPROVED", `${name}: status moves to approved`);

    // Earlier versions stay listed; the older approved one opens without an approve button.
    await page.evaluate(() => document.querySelector('[data-testid="doc-history-privacy_policy"]').setAttribute("open", ""));
    const history = await page.evaluate(() => document.querySelector('[data-testid="doc-history-privacy_policy"]').innerText);
    assert.ok(history.includes("Version 2") && history.includes("Version 1") && history.includes("approved by Ada Obi"), `${name}: history`);
    assert.ok(await clickExact("View", '[data-testid="doc-history-privacy_policy"] li:last-child'));
    await page.waitForFunction(() => document.querySelector('[data-testid="doc-viewer"]')?.innerText.includes("an older version"), { timeout: 5000 });
    assert.ok(!(await page.evaluate(() => [...document.querySelectorAll('[role="dialog"] button')].some((b) => /approve/i.test(b.textContent)))), `${name}: no approve on an older version`);
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 3000 });

    // Generate a new document: it appears as a draft and opens.
    assert.ok(await clickExact("Generate", docCard("cookie_notice")));
    await page.waitForFunction(() => document.querySelector('[data-testid="doc-status-cookie_notice"]')?.textContent.trim().toUpperCase() === "DRAFT", { timeout: 5000 });
    await page.waitForSelector('[role="dialog"] [data-testid="doc-viewer"]', { timeout: 5000 });
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 3000 });
    assert.equal(writes.filter((w) => w.path.endsWith("/generate")).length, 1, `${name}: one generate sent`);
    assert.ok((await page.evaluate(() => document.querySelector('[data-testid="doc-quota"]').textContent)).startsWith("4 of 10 drafts used today"), `${name}: quota moves`);
    assert.ok(await overflowOf() <= 0, `${name}: overflow after generating`);
    await noVerdicts(`${name} documents after actions`);
  }

  role = "member";
  for (const [name, width] of [["desktop", 1440], ["mobile", 390], ["small-mobile", 320]]) {
    reset();
    await page.setViewport({ width, height: 900 });
    await gotoComply();
    await openTab("Documents");
    await page.waitForSelector('[data-testid="documents"]');
    assert.ok(await clickExact("View", docCard("privacy_policy")));
    await page.waitForSelector('[data-testid="doc-viewer"]');
    const m = await page.evaluate(() => ({
      buttons: [...document.querySelectorAll("button")].map((b) => b.textContent.trim()),
      note: !!document.querySelector('[data-testid="read-only-note"]'),
      banner: !!document.querySelector('[data-testid="doc-banner"]'),
    }));
    assert.ok(m.note && m.banner, `${name}: members see the banner and the read-only note`);
    assert.ok(!m.buttons.some((b) => /^(generate|generate new version|approve this version|approve version)$/i.test(b)), `${name}: no generate or approve buttons for a member`);
    assert.ok(m.buttons.includes("Copy text") && m.buttons.includes("Download Markdown"), `${name}: members can copy and download`);
    assert.equal(writes.length, 0, `${name}: members send no writes`);
    assert.ok(await overflowOf() <= 0, `${name}: member documents overflow`);
    await noVerdicts(`${name} member documents`);
  }

  role = "owner";
  plan = "starter";
  reset();
  await page.setViewport({ width: 390, height: 900 });
  await gotoComply();
  await openTab("Documents");
  await page.waitForSelector('[data-testid="growth-gate"]', { timeout: 5000 });
  assert.ok((await bodyText()).toUpperCase().includes("GROWTH PLAN"), "starter documents: upgrade prompt");
  assert.equal(writes.length, 0);
  plan = "growth";

  // ---------------- C3: Starter organisations get the upgrade treatment, not an error ----------------
  role = "owner";
  plan = "starter";
  reset();
  await page.setViewport({ width: 390, height: 900 });
  await gotoComply();
  for (const tabName of ["Answer questions", "Incidents", "Packs"]) {
    await openTab(tabName);
    await page.waitForSelector('[data-testid="growth-gate"]', { timeout: 5000 });
    const gate = await bodyText();
    assert.ok(gate.toUpperCase().includes("GROWTH PLAN") && gate.includes("SEE PLANS"), `starter ${tabName}: upgrade prompt`);
    assert.ok(!gate.includes("We couldn't load"), `starter ${tabName}: not an error`);
    assert.ok(await overflowOf() <= 0, `starter ${tabName}: overflow`);
  }
  assert.equal(writes.length, 0);

  // ---------------- UX: dialogs, states, dates, keyboard, touch targets ----------------
  const dialogOpen = () => page.evaluate(() => !!document.querySelector('[role="dialog"]'));
  const closed = () => page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 3000 });
  const tabUntil = async (match, max = 40) => {
    for (let i = 0; i < max; i++) {
      await page.keyboard.press("Tab");
      const a = await activeInfo();
      if (match(a)) return true;
    }
    return false;
  };
  role = "admin";
  plan = "growth";
  reset();
  await page.setViewport({ width: 1440, height: 900 });
  await gotoComply();
  await openTab("Incidents");
  await page.waitForSelector('[data-testid="incidents"]');

  // Dialog: role, label, focus in, trap, Esc, focus back, inert page, scroll lock.
  const opener = '[data-testid="incident-i-live"] [data-testid="incident-details-open"]';
  await page.focus(opener);
  await page.keyboard.press("Enter");
  await page.waitForSelector('[role="dialog"]');
  const dlg = await page.evaluate(() => {
    const d = document.querySelector('[role="dialog"]');
    return {
      modal: d.getAttribute("aria-modal"), label: document.getElementById(d.getAttribute("aria-labelledby") || "x")?.textContent || "",
      inside: d.contains(document.activeElement), rootInert: document.getElementById("root").hasAttribute("inert"),
      locked: document.body.classList.contains("scroll-locked"),
    };
  });
  assert.equal(dlg.modal, "true", "dialog: aria-modal");
  assert.equal(dlg.label, "Incident details", "dialog: labelled by its title");
  assert.ok(dlg.inside, "dialog: focus moves inside on open");
  assert.ok(dlg.rootInert && dlg.locked, "dialog: the page behind is inert and scroll-locked");
  for (const key of ["forward", "backward"]) {
    if (key === "backward") await page.keyboard.down("Shift");
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press("Tab");
      assert.ok((await activeInfo()).inDialog, `dialog: Tab ${key} stays inside (press ${i + 1})`);
    }
    if (key === "backward") await page.keyboard.up("Shift");
  }
  await noVerdicts("incident details dialog");
  await page.keyboard.press("Escape");
  await closed();
  await new Promise((r) => setTimeout(r, 100));
  assert.equal(await page.evaluate((sel) => document.activeElement === document.querySelector(sel) || document.activeElement.outerHTML.slice(0, 150), opener), true, "dialog: focus returns to the opener on Esc");
  assert.equal(await page.evaluate(() => document.getElementById("root").hasAttribute("inert") || document.body.classList.contains("scroll-locked")), false, "dialog: page is live again after closing");

  // Backdrop click closes a clean dialog; a dirty form asks first, and Esc asks too.
  await page.click(opener);
  await page.waitForSelector('[role="dialog"]');
  await page.mouse.click(8, 8);
  await closed();
  await page.click('[data-testid="incident-i-live"] [data-testid="incident-edit"]');
  await page.waitForSelector('[data-testid="incident-form"]');
  await setVal("#inc-notes", "Typed but not saved");
  await page.mouse.click(8, 8);
  await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 2, { timeout: 3000 });
  assert.ok(/discard your changes\?/i.test(await bodyText()), "dirty dialog: asks before discarding");
  assert.equal(await page.evaluate(() => document.activeElement?.textContent.trim()), "Keep editing", "dirty dialog: Keep editing is the default focus");
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 1, { timeout: 3000 });
  assert.equal(await page.evaluate(() => document.querySelector("#inc-notes").value), "Typed but not saved", "dirty dialog: Esc on the question keeps the input");
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 2, { timeout: 3000 });
  assert.ok(await clickExact("Discard changes"));
  await closed();
  assert.equal(writes.length, 0, "dirty dialog: nothing was sent");
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("data-testid") || document.activeElement?.outerHTML.slice(0, 120)), "incident-edit", "dirty dialog: focus returns to the Edit button");

  // Native pickers and clock changes: a time that does not exist or happens twice is explained and never sent.
  await clickExact("Record an incident");
  await page.waitForSelector('[data-testid="incident-form"]');
  const pickers = await page.evaluate(() => [...document.querySelectorAll('[data-testid="incident-form"] input')]
    .filter((i) => /detected|aware|commission|subjects/.test(i.id)).map((i) => i.type));
  assert.deepEqual(pickers, ["datetime-local", "datetime-local", "datetime-local", "datetime-local"], "dates: every time is a native datetime-local");
  await setVal("#inc-title", "Clock change check");
  await setVal("#inc-detected", "2026-03-08T02:30");
  await setVal("#inc-aware", "2026-03-08T03:30");
  await page.waitForSelector('[data-testid="datetime-problem"]');
  assert.ok((await bodyText()).includes("does not exist in America/New_York"), "dates: a skipped time is explained inline");
  await page.click('[data-testid="incident-save"]');
  await page.waitForFunction(() => document.querySelector('[data-testid="incident-error"]')?.textContent.includes("does not exist"), { timeout: 3000 });
  await setVal("#inc-detected", "2025-11-02T01:30");
  await page.waitForFunction(() => document.querySelector('[data-testid="datetime-problem"]')?.textContent.includes("twice"), { timeout: 3000 });
  await page.click('[data-testid="incident-save"]');
  await page.waitForFunction(() => document.querySelector('[data-testid="incident-error"]')?.textContent.includes("twice"), { timeout: 3000 });
  assert.equal(writes.length, 0, "dates: an unclear time is never sent");

  // A failed save: a plain message and a toast, never a status line, and the dialog stays open with the input.
  await setVal("#inc-detected", "2026-10-15T09:30");
  await setVal("#inc-aware", "2026-10-15T10:45");
  flags.failWrites = true;
  await page.click('[data-testid="incident-save"]');
  await page.waitForFunction(() => document.querySelector('[data-testid="incident-error"]')?.textContent.includes("could not save"), { timeout: 5000 });
  const failText = await page.evaluate(() => document.querySelector('[data-testid="incident-error"]').textContent + document.querySelector(".toasts").innerText);
  assert.ok(!/500|internal server|status|traceback/i.test(failText), `failure: no raw status in "${failText}"`);
  assert.ok(failText.includes("was not saved"), "failure: a toast says so");
  assert.ok(await dialogOpen(), "failure: the dialog stays open");
  flags.failWrites = false;
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 2, { timeout: 3000 });
  assert.ok(await clickExact("Discard changes"));
  await closed();

  // Focus ring on every control in a form dialog (keyboard focus).
  await clickExact("Record an incident");
  await page.waitForSelector('[data-testid="incident-form"]');
  const rings = [];
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press("Tab");
    const ring = await page.evaluate(() => {
      const a = document.activeElement;
      if (!a || !a.closest('[role="dialog"]')) return null;
      const c = getComputedStyle(a);
      return { id: a.id || a.getAttribute("data-testid") || a.tagName, visible: (c.outlineStyle !== "none" && parseFloat(c.outlineWidth) > 0) || c.boxShadow !== "none" };
    });
    if (ring) rings.push(ring);
  }
  assert.ok(rings.length >= 8, "focus ring: tabbed through the controls");
  assert.deepEqual(rings.filter((r) => !r.visible).map((r) => r.id), [], "focus ring: every control shows a visible focus ring");
  await page.keyboard.press("Escape");
  await closed();

  // Keyboard-only: arrow keys move between tabs, Enter opens the dialog, the form is filled and saved without a mouse.
  reset();
  await page.setViewport({ width: 1440, height: 900 });
  await gotoComply();
  await page.focus("#tab-readiness");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.waitForSelector('#tab-incidents[aria-selected="true"]');
  assert.equal(await page.evaluate(() => [document.activeElement.id, document.activeElement.getAttribute("aria-selected")].join()), "tab-incidents,true", "keyboard: arrow keys select and focus the next tab");
  await page.waitForSelector('[data-testid="incidents"]');
  assert.ok(await tabUntil((a) => a.testid === "incident-new", 10), "keyboard: Tab reaches Record an incident");
  await page.keyboard.press("Enter");
  await page.waitForSelector('[data-testid="incident-form"]');
  assert.equal((await activeInfo()).id, "inc-title", "keyboard: focus starts on the first field");
  await page.keyboard.type("Keyboard only entry");
  assert.ok(await tabUntil((a) => a.id === "inc-detected", 6), "keyboard: Tab reaches the detected time");
  await page.keyboard.type("10152026");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.type("0930AM");
  assert.ok(await tabUntil((a) => a.id === "inc-aware", 10), "keyboard: Tab reaches the aware time");
  await page.keyboard.type("10152026");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.type("1045AM");
  assert.ok(await tabUntil((a) => a.testid === "incident-save", 40), "keyboard: Tab reaches the save button");
  const kbBefore = writes.length;
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.body.innerText.includes("Keyboard only entry") && !document.querySelector('[data-testid="incident-form"]'), { timeout: 5000 });
  assert.equal(writes[kbBefore].body.detected_at, "2026-10-15T13:30:00.000Z", "keyboard: the time typed in the picker goes out as UTC");
  assert.equal(writes[kbBefore].body.title, "Keyboard only entry");
  assert.equal((await activeInfo()).testid, "incident-new", "keyboard: focus returns to the button that opened the dialog");

  // Empty and error states (incidents, packs), each with the right action and a plain message.
  reset();
  incidents.length = 0;
  packs.length = 0;
  await gotoComply();
  await openTab("Incidents");
  await page.waitForSelector('[data-testid="state-empty"]');
  const emptyIncidents = await page.evaluate(() => document.querySelector('[data-testid="state-empty"]').innerText);
  assert.ok(/No incidents recorded/.test(emptyIncidents) && /record an incident/i.test(emptyIncidents), "empty: incidents explain themselves and offer the action");
  await openTab("Packs");
  await page.waitForSelector('[data-testid="packs-empty"]');
  assert.ok(/No packs issued yet/.test(await page.evaluate(() => document.querySelector('[data-testid="packs-empty"]').innerText)), "empty: packs");
  await noVerdicts("empty states");
  reset();
  flags.failReads.add("/compliance/incidents");
  await gotoComply();
  await openTab("Incidents");
  await page.waitForSelector('[data-testid="state-error"]');
  const errText = await page.evaluate(() => document.querySelector('[data-testid="state-error"]').innerText);
  assert.ok(!/500|internal server|status|traceback/i.test(errText) && /try again/i.test(errText), `error: a human message with a retry (${errText})`);
  flags.failReads.clear();
  await clickExact("Try again");
  await page.waitForSelector('[data-testid="incidents"] [data-testid="incident-i-live"]', { timeout: 5000 });
  flags.failReads.add("/compliance/overview");
  await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
  await page.waitForSelector('[data-testid="state-error"]');
  assert.ok(!/500|internal server/i.test(await bodyText()), "error: the whole page shows no raw status");
  flags.failReads.clear();
  await clickExact("Try again");
  await page.waitForSelector('[data-testid="compliance-disclaimer"]', { timeout: 5000 });
  flags.delayMs = 1500;
  await page.goto(`${origin}/comply`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="state-loading"]', { timeout: 5000 });
  assert.ok(/Loading/.test(await page.evaluate(() => document.querySelector('[data-testid="state-loading"]').innerText)), "loading: a labelled loading state");
  await page.waitForSelector('[data-testid="compliance-disclaimer"]', { timeout: 8000 });
  flags.delayMs = 0;

  // A failed pack issue gives a plain toast.
  reset();
  await gotoComply();
  await openTab("Packs");
  await page.waitForSelector('[data-testid="packs"]');
  flags.failWrites = true;
  await page.evaluate(() => document.querySelector('[data-testid="issue-readiness_pack"]').click());
  await page.waitForSelector('[data-testid="confirm-dialog"]');
  await page.click('[data-testid="confirm-ok"]');
  await page.waitForFunction(() => document.querySelector(".toasts")?.innerText.includes("not issued"), { timeout: 5000 });
  assert.ok(!/500|internal server/i.test(await page.evaluate(() => document.querySelector(".toasts").innerText)), "failure: the toast has no raw status");
  flags.failWrites = false;

  // Questionnaire: a chosen renewal date is a native date and goes out as the end of that day in the organisation's zone, in UTC.
  reset();
  await gotoComply();
  await openTab("Answer questions");
  await page.waitForSelector('[data-testid="questionnaire"]');
  assert.ok(await clickExact("Answer", qsel("registration.major_importance")));
  const qf = `[data-testid="form-registration.major_importance"]`;
  await page.waitForSelector(qf);
  assert.ok(await chooseRadio(qf, "Yes"));
  await setVal(`${qf} select[id$="-expiry"]`, "custom");
  await page.waitForSelector(`${qf} input[id$="-expiry-date"]`);
  const exp = await page.evaluate((f) => { const i = document.querySelector(`${f} input[id$="-expiry-date"]`); return { type: i.type, min: i.min, max: i.max }; }, qf);
  assert.equal(exp.type, "date", "dates: the renewal date is a native date picker");
  assert.ok(exp.min && exp.max && exp.min < exp.max, "dates: the renewal date has a range");
  const wanted = new Date(Date.now() + 30 * 24 * HOUR).toISOString().slice(0, 10);
  await setVal(`${qf} input[id$="-expiry-date"]`, wanted);
  assert.ok((await bodyText()).includes("Day in America/New_York"), "dates: the zone is shown beside the date");
  await clickExact("Save answer", qf);
  await page.waitForFunction(() => !document.querySelector('[data-testid="form-registration.major_importance"]'), { timeout: 5000 });
  const sentExpiry = writes[0].body.expires_at;
  assert.ok(/Z$/.test(sentExpiry), "dates: the expiry is sent as UTC");
  const wall = new Intl.DateTimeFormat("en-CA", { timeZone: ORG_ZONE, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(sentExpiry));
  assert.equal(wall.replace(",", ""), `${wanted} 23:59`, `dates: it is 23:59 on the chosen day in New York (${wall})`);
  const nativeOnly = await page.evaluate(() => [...document.querySelectorAll("input")].filter((i) => /date/i.test(i.id) && i.type === "text").length);
  assert.equal(nativeOnly, 0, "dates: no free-text date inputs");

  // Mobile (390 and 320): dialogs are full screen with a sticky title bar, 44px controls, no overflow, content scrolls inside.
  for (const [name, width] of [["mobile", 390], ["small-mobile", 320]]) {
    reset();
    await page.setViewport({ width, height: 800, hasTouch: true, isMobile: true });
    await gotoComply();
    await openTab("Documents");
    await page.waitForSelector('[data-testid="documents"]');
    assert.ok(await clickExact("View", docCard("privacy_policy")));
    await page.waitForSelector('[role="dialog"] [data-testid="doc-viewer"]');
    await new Promise((r) => setTimeout(r, 450)); // let the open animation finish before measuring
    const m = await page.evaluate(() => {
      const d = document.querySelector('[role="dialog"]');
      const r = d.getBoundingClientRect();
      const bar = d.querySelector(".dialog-bar");
      const close = d.querySelector(".dialog-close").getBoundingClientRect();
      const body = d.querySelector(".dialog-body");
      return {
        w: r.width, h: r.height, vw: innerWidth, vh: innerHeight, sticky: getComputedStyle(bar).position, closeW: close.width, closeH: close.height,
        bodyOverflow: body.scrollWidth - body.clientWidth, scrolls: body.scrollHeight > body.clientHeight, pageOverflow: document.documentElement.scrollWidth - innerWidth,
        padBottom: parseFloat(getComputedStyle(body).paddingBottom),
      };
    });
    assert.ok(Math.abs(m.w - m.vw) < 1 && Math.abs(m.h - m.vh) < 1, `${name}: the dialog fills the screen (${m.w}x${m.h} in ${m.vw}x${m.vh})`);
    assert.equal(m.sticky, "sticky", `${name}: the title bar is sticky`);
    assert.ok(m.closeW >= 44 && m.closeH >= 44, `${name}: the close button is at least 44px`);
    assert.ok(m.bodyOverflow <= 0 && m.pageOverflow <= 0, `${name}: no horizontal overflow in the dialog`);
    assert.ok(m.scrolls, `${name}: the content scrolls inside the dialog`);
    assert.ok(m.padBottom >= 24, `${name}: room at the bottom for the safe area`);
    await page.keyboard.press("Escape");
    await closed();

    // Touch targets on the page and in a form dialog.
    await openTab("Incidents");
    await page.waitForSelector('[data-testid="incidents"]');
    await clickExact("Record an incident");
    await page.waitForSelector('[data-testid="incident-form"]');
    await new Promise((r) => setTimeout(r, 450));
    const small = await page.evaluate(() => [...document.querySelectorAll('button, [role="tab"], select, input:not([type="radio"]):not([type="hidden"]), textarea, summary')]
      .filter((el) => el.getClientRects().length > 0 && !el.closest("[inert]"))
      .map((el) => ({ el: `${el.tagName}#${el.id || el.getAttribute("data-testid") || el.textContent.trim().slice(0, 20)}`, h: Math.round(el.getBoundingClientRect().height) }))
      .filter((x) => x.h < 43));
    assert.deepEqual(small, [], `${name}: touch targets under 44px`);
    await page.keyboard.press("Escape");
    await closed();
    // The answer form: radio choices are 44px tall too.
    await openTab("Answer questions");
    await page.waitForSelector('[data-testid="questionnaire"]');
    assert.ok(await clickExact("Answer", qsel("registration.major_importance")));
    await page.waitForSelector('[data-testid="form-registration.major_importance"]');
    const answerSmall = await page.evaluate(() => [...document.querySelectorAll('[data-testid="form-registration.major_importance"] label, [data-testid="form-registration.major_importance"] button, [data-testid="form-registration.major_importance"] select, [data-testid="form-registration.major_importance"] input:not([type="radio"])')]
      .filter((el) => el.getClientRects().length > 0).map((el) => ({ el: `${el.tagName}#${el.id || el.textContent.trim().slice(0, 20)}`, h: Math.round(el.getBoundingClientRect().height) })).filter((x) => x.h < 43 && !/^LABEL#(Your answer|Who|Ask|Link|Notes)/i.test(x.el)));
    assert.deepEqual(answerSmall, [], `${name}: answer form touch targets under 44px`);
    await page.setViewport({ width: 1440, height: 900, hasTouch: false, isMobile: false });
  }

  assert.deepEqual(errors, [], "no page errors");
  console.log("compliance page, questionnaire, incidents, packs, documents, dialogs, dates, states, keyboard, touch targets, read-only members and the Starter gate: desktop/390/320 passed");
} finally {
  await browser?.close();
  await server.close();
}
