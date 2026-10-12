import assert from "node:assert/strict";
import { createServer } from "vite";
import puppeteer from "puppeteer-core";
import { fileURLToPath } from "node:url";
import { writeFile } from "node:fs/promises";
const frontend = fileURLToPath(new URL("..", import.meta.url));
const out = fileURLToPath(
  new URL("../../docs/scans-ui-review-2026-10-12/", import.meta.url),
);
const prefix = "implemented";
const capture = process.env.CYPHWARD_SCANS_SCREENSHOTS === "1";
process.chdir(frontend);
const server = await createServer({
  root: frontend,
  server: { host: "127.0.0.1", port: 0 },
});
let browser;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({
    executablePath: "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const user = {
    id: "design-user",
    email: "design@example.test",
    full_name: "Design Review",
  };
  const org = {
    id: "design-org",
    name: "Demo Workspace",
    slug: "design-review",
    plan: "growth",
  };
  const domain = {
    id: "design-domain",
    org_id: org.id,
    domain: "example.ng",
    verification_status: "verified",
    created_at: "2026-10-01T00:00:00Z",
  };
  const stages = [
    "discovery",
    "dns",
    "http",
    "ports",
    "tls",
    "nuclei",
    "security_checks",
    "normalization",
    "scoring",
    "ai_analysis",
  ];
  const progress = Object.fromEntries(
    stages.map((key, index) => [
      key,
      {
        status: "completed",
        items: index < 7 ? 5 : 1,
        duration_ms: 1000 + index * 350,
        ...(key === "scoring" ? { scope: "organization" } : {}),
      },
    ]),
  );
  progress.nuclei = {
    status: "failed",
    items: 0,
    duration_ms: 300000,
    error:
      "Two targets timed out; their vulnerability checks were not completed.",
  };
  const scans = [
    {
      id: "demo-scan-001",
      domain: "example.ng",
      status: "completed",
      score: 35.2,
      created_at: "2026-10-12T06:00:00Z",
      completed_at: "2026-10-12T06:18:00Z",
      findings_discovered: 18,
      current_stage: "completed",
      stage_progress: progress,
    },
    {
      id: "demo-scan-002",
      domain: "example.ng",
      status: "completed",
      score: 35.2,
      created_at: "2026-10-11T06:00:00Z",
      findings_discovered: 18,
      current_stage: "completed",
      stage_progress: {
        ...progress,
        nuclei: { status: "completed", items: 0, duration_ms: 250000 },
      },
    },
    {
      id: "demo-scan-003",
      domain: "example.ng",
      status: "failed",
      score: null,
      created_at: "2026-10-10T06:00:00Z",
      findings_discovered: 0,
      current_stage: "http",
      stage_progress: {
        discovery: { status: "completed", items: 5 },
        dns: { status: "completed", items: 5 },
        http: { status: "failed", error: "Connection timed out" },
      },
    },
  ];
  let role = "owner";
  let listUnavailable = false;
  let emptyList = false;
  let delayId = null;
  let delayedRequest = null;
  let launchFailure = true;
  let launchRequests = 0;
  let slowResponses = false;
  const raw_results = [
    {
      stage: "nuclei",
      raw_data: {
        attempted_hosts: [
          "example.ng",
          "www.example.ng",
          "app.example.ng",
          "mail.example.ng",
          "api.example.ng",
        ],
        successful_hosts: ["example.ng", "www.example.ng", "app.example.ng"],
        failed_hosts: {
          "mail.example.ng": "timeout",
          "api.example.ng": "timeout",
        },
      },
    },
  ];
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) {
      let body = {},
        status = 200;
      if (url.pathname.endsWith("/auth/bootstrap"))
        body = {
          user,
          email_verified: true,
          memberships: [{ org, role, domains: [domain] }],
        };
      else if (url.pathname.endsWith("/domains")) body = [domain];
      else if (url.pathname.endsWith("/scans")) {
        body = emptyList ? [] : scans;
        if (listUnavailable) {
          status = 503;
          body = { detail: "Temporary scan-list outage" };
        }
      } else if (url.pathname.endsWith("/scans/launch")) {
        launchRequests++;
        if (launchFailure) {
          status = 503;
          body = { detail: "Temporary launch outage" };
        } else {
          const queued = {
            ...scans[0],
            id: "demo-scan-new",
            status: "queued",
            score: null,
            findings_discovered: 0,
            stage_progress: Object.fromEntries(
              stages.map((key) => [key, { status: "pending" }]),
            ),
          };
          scans.unshift(queued);
          body = { message: "Queued", domain: domain.domain, scan: queued };
        }
      } else if (url.pathname.includes("/scans/")) {
        if (delayId && url.pathname.endsWith(delayId)) {
          delayedRequest = request;
          return;
        }
        body = {
          scan: scans.find((s) => url.pathname.endsWith(s.id)) || scans[0],
          raw_results,
        };
      } else if (url.pathname.includes("/notifications"))
        body = { notifications: [], unread_count: 0 };
      else if (url.pathname.includes("/platform/")) {
        status = 403;
        body = { detail: "Not staff" };
      }
      const response = {
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      };
      if (slowResponses && /\/scans(?:\/demo-scan-new)?$/.test(url.pathname)) {
        setTimeout(() => {
          void request.respond(response);
        }, 4000);
      } else {
        void request.respond(response);
      }
    } else if (url.origin === origin) void request.continue();
    else void request.abort();
  });
  await page.evaluateOnNewDocument((user) => {
    localStorage.setItem(
      "cyphward-session",
      JSON.stringify({
        access_token: "design-mock-token",
        refresh_token: "design-mock-refresh",
        user,
        _expires_at: Date.now() + 3600000,
      }),
    );
    localStorage.setItem("cyphward-welcome-sent", user.id);
    localStorage.setItem("cyphward-theme", "light");
    localStorage.setItem("cyphward-cookie-consent", "accepted");
  }, user);
  const metrics = [];
  for (const [name, width, height] of [
    ["desktop", 1440, 1000],
    ["mobile", 390, 844],
    ["small-mobile", 320, 844],
  ]) {
    await page.setViewport({ width, height });
    await page.goto(`${origin}/scans`);
    await page.waitForFunction(
      () =>
        document.body.textContent.includes("Completed with limited coverage") &&
        document.body.textContent.includes("3 of 5 targets checked"),
    );
    await new Promise((resolve) => setTimeout(resolve, 500));
    if (capture)
      await page.screenshot({
        path: `${out}${prefix}-${name}.png`,
        fullPage: true,
      });
    const metric = await page.evaluate((name) => {
      const table = document.querySelector("table");
      const history = document.querySelector(".scan-history") || table;
      const primary = [...document.querySelectorAll("button")].find(
        (b) => b.getAttribute("aria-label") === "Start scan",
      );
      return {
        name,
        viewport: innerWidth,
        pageWidth: document.documentElement.scrollWidth,
        pageHeight: document.documentElement.scrollHeight,
        historyTop: history.getBoundingClientRect().top,
        historyWidth: history.getBoundingClientRect().width,
        startButtonHeight: primary.getBoundingClientRect().height,
      };
    }, name);
    metrics.push(metric);
    if (prefix === "implemented") {
      assert.equal(metric.pageWidth, width, "No horizontal page overflow");
      assert.ok(metric.historyWidth <= width, "History fits its viewport");
      assert.ok(
        metric.startButtonHeight >= 44,
        "Launch has a 44px touch target",
      );
      assert.equal(
        await page.$eval(".scan-checks-panel", (element) => element.open),
        width > 900,
        "Checks expanded on desktop and collapsed on phones",
      );
    }
    if (name === "mobile") {
      await page.evaluate(() =>
        (
          document.querySelector(".scan-history") ||
          document.querySelector("table")
        ).scrollIntoView(),
      );
      await new Promise((resolve) => setTimeout(resolve, 700));
      if (capture)
        await page.screenshot({ path: `${out}${prefix}-mobile-history.png` });
      await page.evaluate(() => scrollTo(0, 0));
      await page.evaluate(() =>
        [...document.querySelectorAll("button")]
          .find((b) => b.getAttribute("aria-label") === "Start scan")
          .click(),
      );
      await page.waitForSelector('.modal-backdrop[role="dialog"]', {
        timeout: 5000,
      });
      if (capture)
        await page.screenshot({ path: `${out}${prefix}-mobile-launch.png` });
    }
  }
  if (prefix === "implemented") {
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`${origin}/scans`);
    await page.waitForSelector(".scan-history-card");
    await page.select('select[aria-label="Filter scans by status"]', "failed");
    assert.equal(
      await page.$$eval(".scan-history-card", (cards) => cards.length),
      1,
    );
    await page.select('select[aria-label="Filter scans by status"]', "all");
    await page.evaluate(() =>
      document
        .querySelector(
          '.scan-history-mobile button[aria-label="View scan demo-scan-002"]',
        )
        .click(),
    );
    await page.waitForFunction(
      () =>
        document.querySelector(".scan-summary .scan-section-label")
          ?.textContent === "Selected scan" &&
        !document.querySelector(".scan-summary .scan-coverage-notice"),
    );
    delayId = "demo-scan-001";
    await page.evaluate(() =>
      document
        .querySelector(
          '.scan-history-mobile button[aria-label="View scan demo-scan-001"]',
        )
        .click(),
    );
    await page.waitForFunction(
      () => !!document.querySelector(".scan-summary .scan-coverage-notice"),
    );
    const deadline = Date.now() + 5000;
    while (!delayedRequest && Date.now() < deadline)
      await new Promise((resolve) => setTimeout(resolve, 20));
    assert.ok(delayedRequest, "Older scan detail request is delayed");
    await page.evaluate(() =>
      document
        .querySelector(
          '.scan-history-mobile button[aria-label="View scan demo-scan-003"]',
        )
        .click(),
    );
    await page.waitForFunction(
      () =>
        document.querySelector(".scan-summary .scan-score strong")
          ?.textContent === "Not assessed",
    );
    await delayedRequest.respond({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ scan: scans[0], raw_results }),
    });
    delayId = null;
    await new Promise((resolve) => setTimeout(resolve, 150));
    assert.equal(
      await page.$eval(
        ".scan-summary .scan-score strong",
        (element) => element.textContent,
      ),
      "Not assessed",
      "Older response does not replace selected scan",
    );
    await page.keyboard.press("Escape");
    assert.equal(
      await page.$(".drawer.open"),
      null,
      "Escape closes scan details",
    );
    listUnavailable = true;
    await page.evaluate(() =>
      document.querySelector('button[aria-label="Refresh scans"]').click(),
    );
    await page.waitForFunction(() =>
      document.body.textContent.includes(
        "Refresh failed. Showing the last available scans.",
      ),
    );
    assert.equal(
      await page.$$eval(".scan-history-card", (cards) => cards.length),
      3,
      "Refresh outage retains history",
    );
    listUnavailable = false;
    role = "member";
    await page.reload();
    await page.waitForSelector(".scan-summary");
    assert.equal(
      await page.$('button[aria-label="Start scan"]'),
      null,
      "Member cannot launch",
    );
    role = "owner";
    domain.verification_status = "pending";
    await page.reload();
    await page.waitForSelector('button[aria-label="Verify domain"]');
    emptyList = true;
    await page.reload();
    await page.waitForFunction(() =>
      document.body.textContent.includes("Your first scan starts here"),
    );
    assert.equal(
      await page.$(".scan-summary"),
      null,
      "Empty account has no fabricated scan summary",
    );
    if (capture)
      await page.screenshot({ path: `${out}implemented-empty-mobile.png` });
    emptyList = false;
    domain.verification_status = "verified";
    await page.reload();
    await page.waitForSelector(
      'button[aria-label="Start scan"]:not([disabled])',
    );
    await page.click('button[aria-label="Start scan"]');
    await page.waitForSelector(".modal-backdrop");
    await page.waitForFunction(() =>
      document
        .querySelector(".modal-backdrop")
        ?.contains(document.activeElement),
    );
    await page.keyboard.down("Shift");
    await page.keyboard.press("Tab");
    await page.keyboard.up("Shift");
    assert.ok(
      await page.evaluate(() =>
        document
          .querySelector(".modal-backdrop")
          ?.contains(document.activeElement),
      ),
      "Dialog traps Shift+Tab",
    );
    await page.keyboard.press("Tab");
    assert.ok(
      await page.evaluate(() =>
        document
          .querySelector(".modal-backdrop")
          ?.contains(document.activeElement),
      ),
      "Dialog traps Tab",
    );
    await page.evaluate(() =>
      [...document.querySelectorAll(".modal-backdrop button")]
        .find((button) => button.textContent.trim() === "Start scan")
        .click(),
    );
    await page.waitForSelector('.scan-launch [role="alert"]');
    assert.equal(launchRequests, 1);
    assert.ok(
      await page.$(".modal-backdrop"),
      "Launch error preserves the dialog",
    );
    launchFailure = false;
    await page.evaluate(() =>
      [...document.querySelectorAll(".modal-backdrop button")]
        .find((button) => button.textContent.trim() === "Start scan")
        .click(),
    );
    await page.waitForFunction(
      () =>
        document.querySelector(".scan-summary .scan-badge")?.textContent ===
        "Queued",
    );
    assert.equal(launchRequests, 2);
    slowResponses = true;
    scans[0].status = "completed";
    scans[0].stage_progress = progress;
    await page.waitForFunction(
      () =>
        document.querySelector(".scan-summary .scan-lifecycle")?.textContent ===
        "Scan completed",
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS: responsive layout, target sizes, history filters, stale scan-detail response, outage recovery, member permissions, verified-domain launch, empty state, keyboard containment, launch error/success and polling with slow responses",
    );
  }
  if (capture)
    await writeFile(
      `${out}${prefix}-metrics.json`,
      JSON.stringify(metrics, null, 2) + "\n",
    );
  console.log(JSON.stringify(metrics, null, 2));
} finally {
  if (browser) await browser.close();
  await server.close();
}
