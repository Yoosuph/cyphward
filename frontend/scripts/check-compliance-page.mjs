// Compliance readiness page (packet C1) against a stubbed API.
// Desktop, 390px and 320px: disclaimer, readiness counts, status chips with
// source labels, "reference pending review", gap → findings and Create task
// (no duplicate when a task exists), locked groups on Starter, no verdict
// language in rendered text and no horizontal overflow.
import assert from "node:assert/strict";
import { createServer } from "vite";
import puppeteer from "puppeteer-core";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("..", import.meta.url));
process.chdir(frontend);
const DISCLAIMER =
  "Readiness evidence, not legal advice or a compliance determination. Filing of Compliance Audit Returns for UHL/EHL organisations must go through a licensed DPCO.";
const BANNED = ["compliant", "certified", "satisfies", "satisfied", "passes audit", "compliance score", "fully meets"];

const user = { id: "c1-user", email: "c1@example.test", full_name: "Compliance Review" };
const org = { id: "c1-org", name: "Acme Traders", slug: "acme", plan: "growth" };
const domain = { id: "d1", org_id: org.id, domain: "acme.ng", verification_status: "verified", created_at: "2026-10-01T00:00:00Z" };

const evidence = (status, extra = {}) => ({
  domain_id: "d1", domain: "acme.ng", status,
  status_label: { present: "Evidence present", gap: "Gap", not_assessed: "Not assessed" }[status],
  reason: "x", reason_text: { present: "Every requested check finished for this domain.", gap: "Open findings linked to this requirement.", not_assessed: "No scan with recorded coverage has finished for this domain yet." }[status],
  source: status === "not_assessed" ? null : "tool_observed",
  source_label: status === "not_assessed" ? null : "Tool observed",
  observed_at: status === "not_assessed" ? null : "2026-10-16T10:00:00Z",
  expires_at: status === "not_assessed" ? null : "2026-11-15T10:00:00Z",
  scan_id: "s1", finding_ids: [], details: {}, ...extra,
});
const req = (key, group, title, status, extra = {}) => ({
  key, group, title, summary: `${title} — what the evidence shows.`, clause: "NDPA 2023 s.39(2)", clause_verified: false,
  clause_label: "NDPA 2023 s.39(2) · reference pending review", evidence_type_labels: ["Tool observed"],
  checks_performed: group === "security" ? "Certificate validity and expiry on each in-scope web host." : null,
  not_checked: group === "security" ? "Cipher strength and internal systems." : null,
  freshness_days: 30, remediation_hint: "Do the next sensible thing.",
  status, status_label: { present: "Evidence present", gap: "Gap", not_assessed: "Not assessed" }[status],
  reason: "x", reason_text: "Reason in plain words.",
  source: status === "not_assessed" && !extra.source ? null : "tool_observed",
  source_label: status === "not_assessed" && !extra.source ? null : "Tool observed",
  domains: [], findings: [], informational_findings: [], ...extra,
});
const finding = { id: "f-dmarc", title: "Missing Email DMARC Authentication Policy", severity: "critical", status: "open" };

function overview(plan) {
  const security = [
    req("ndpa.s39.encryption_in_transit", "security", "Personal data protected in transit", "present", { domains: [evidence("present")] }),
    req("ndpa.s39.exposed_services_inventoried", "security", "Internet-exposed services inventoried", "present",
      { domains: [evidence("present", { details: { open_ports: { "acme.ng": [80, 443, 3389] } } })] }),
    req("ndpa.s39.email_anti_spoofing", "security", "Email anti-spoofing records", "gap",
      { domains: [evidence("gap", { finding_ids: [finding.id] })], findings: [finding] }),
    req("ndpa.s39.known_vulnerability_testing", "security", "Testing for known vulnerabilities", "not_assessed",
      { domains: [evidence("not_assessed")] }),
  ];
  const dpo = [req("gaid.dpo.designated", "dpo", "Data protection officer designated", "not_assessed")];
  const counts = (items) => ({
    percent: 0, present: items.filter((r) => r.status === "present").length,
    gap: items.filter((r) => r.status === "gap").length,
    not_assessed: items.filter((r) => r.status === "not_assessed").length, applicable: items.length,
  });
  return {
    disclaimer: DISCLAIMER,
    note: "Only the security measures group has an evidence source today.",
    register: { version: "ndpa-gaid-v1", title: "NDPA 2023 / GAID 2025 readiness register", references_pending_review: 11 },
    plan,
    readiness: { percent: 18, present: 2, gap: 1, not_assessed: 8, applicable: 11 },
    domains: [{ id: "d1", domain: "acme.ng" }],
    groups: [
      { key: "security", title: "Security measures", locked: false, counts: counts(security), requirement_count: 7, requirements: security },
      { key: "dpo", title: "Data protection officer", locked: plan === "starter", counts: counts(dpo), requirement_count: 4,
        requirements: plan === "starter" ? [] : dpo },
    ],
  };
}

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
  let existingTasks = [];
  const posts = [];
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      return url.origin === origin ? void request.continue() : void request.abort();
    }
    let body = {};
    if (url.pathname.endsWith("/auth/bootstrap")) body = { user, email_verified: true, memberships: [{ org: { ...org, plan }, role: "member", domains: [domain] }] };
    else if (url.pathname.endsWith("/compliance/overview")) body = overview(plan);
    else if (url.pathname.endsWith("/remediation") && request.method() === "GET") body = { tasks: existingTasks, total: existingTasks.length };
    else if (url.pathname.endsWith("/remediation") && request.method() === "POST") {
      posts.push(JSON.parse(request.postData() || "{}"));
      body = { task: { id: "t-new", title: "Fix", status: "open" } };
    } else if (url.pathname.endsWith("/domains")) body = [domain];
    else if (url.pathname.includes("/notifications")) body = { notifications: [], unread_count: 0 };
    else if (url.pathname.includes("/platform/")) return void request.respond({ status: 403, contentType: "application/json", body: '{"detail":"no"}' });
    void request.respond({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.evaluateOnNewDocument((u) => {
    localStorage.setItem(`cyphward-tour-v1:${u.id}`, "done");
    localStorage.setItem("cyphward-session", JSON.stringify({ access_token: "t", refresh_token: "r", user: u, _expires_at: Date.now() + 3600000 }));
    localStorage.setItem("cyphward-welcome-sent", u.id);
    localStorage.setItem("cyphward-theme", "light");
    localStorage.setItem("cyphward-cookie-consent", "accepted");
  }, user);

  const clickText = (text) => page.evaluate((t) => {
    const el = [...document.querySelectorAll("button, a")].find((b) => b.textContent.includes(t));
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
      percent: document.querySelector('[data-testid="readiness-percent"]').textContent.trim(),
      text: document.body.innerText,
      overflow: document.documentElement.scrollWidth - window.innerWidth,
      nav: !!document.querySelector('a[href="/comply"]'),
    }));
    assert.equal(view.disclaimer, DISCLAIMER, `${name}: disclaimer`);
    assert.equal(view.percent, "18%", `${name}: readiness`);
    for (const label of ["2 PRESENT", "1 GAPS", "8 NOT ASSESSED", "reference pending review", "No evidence yet"]) {
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

  assert.deepEqual(errors, [], "no page errors");
  console.log("compliance page: desktop/390/320 passed");
} finally {
  await browser?.close();
  await server.close();
}
