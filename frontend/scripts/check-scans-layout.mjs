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
  // Optional privacy stage: shown as its own row, never counted in checks or coverage.
  progress.privacy = { status: "completed", items: 1, duration_ms: 4200 };
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
  let launchConflict = false;
  let launchRequests = 0;
  let launch401Once = false;
  let launchIntentHeaders = [];
  let refreshRequests = 0;
  let slowResponses = false;
  const raw_results = [
    {
      stage: "privacy",
      raw_data: {
        privacy_observations: [{
          hostname: "example.ng", catch_all: true,
          pages: [
            { kind: "privacy_policy", matched: true, found_by: "link", url: "https://example.ng/privacy-policy-for-our-customers-in-nigeria-and-abroad" },
            { kind: "cookie_notice", matched: false, off_domain: false },
          ],
          first_response_cookies: [{ name: "__cf_bm", category: "infrastructure" }, { name: "_ga", category: "tracker" }],
          trackers: [{ vendor: "google_tag_manager", strength: "loader", consent_blocked: false }],
          consent_manager: null, security_txt: { present: true, has_contact: true },
        }],
        attempted_hosts: ["example.ng"], successful_hosts: ["example.ng"], failed_hosts: {},
      },
    },
    {
      stage: "discovery",
      raw_data: {
        target_selection: {
          version: 1,
          requested_hosts: ["example.ng", "registered.example.ng", "a.example.ng"],
          selected_hosts: ["example.ng", "registered.example.ng"],
          omitted_hosts: { "a.example.ng": "dns_max_hosts", "external.test": "outside_authorised_scope" },
        },
      },
    },
    {
      stage: "nuclei",
      raw_data: {
        tool_coverage: { version: 1, tool_version: "3.4.10", evaluated_templates: null },
        stage_plan: { version: 1, requested_hosts: ["example.ng", "capped.example.ng", "budget.example.ng"] },
        omitted_hosts: { "capped.example.ng": "stage_host_cap", "budget.example.ng": "recon_budget_exhausted" },
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
      if (url.pathname.endsWith("/auth/refresh")) {
        refreshRequests++;
        body = {
          access_token: "design-mock-token-refreshed",
          refresh_token: "design-mock-refresh-rotated",
          expires_in: 3600,
          user,
        };
      } else if (url.pathname.endsWith("/auth/bootstrap"))
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
        launchIntentHeaders.push(request.headers()["idempotency-key"]);
        if (launch401Once) {
          launch401Once = false;
          status = 401;
          body = { detail: "Access token expired" };
        } else if (launchConflict) {
          launchConflict = false;
          status = 409;
          body = {
            detail: "A scan is already queued or running for example.ng.",
            code: "scan_already_active",
            scan_id: "demo-scan-002",
          };
        } else if (launchFailure) {
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
    // The first-run tour is covered by check-onboarding-flow.mjs.
    localStorage.setItem(`cyphward-tour-v1:${user.id}`, "done");
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
        document.body.textContent.includes("3 of 5 tool runs completed") &&
        document.body.textContent.includes("3 in-scope hosts requested") &&
        document.body.textContent.includes("DNS host limit reached") &&
        document.body.textContent.includes("Engine version: 3.4.10") &&
        document.body.textContent.includes("Template evaluation coverage: unknown") &&
        document.body.textContent.includes("Scan work budget exhausted") &&
        document.body.textContent.includes("Stage host limit reached"),
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
      await page.evaluate(() => {
        document.querySelector(".scan-checks-panel").open = true;
        document.querySelector('.scan-check[data-stage="discovery"]').open = true;
        document.querySelector(".scan-target-scope details").open = true;
        document.querySelector('.scan-check[data-stage="nuclei"]').open = true;
        document.querySelectorAll('.scan-check[data-stage="nuclei"] .scan-target-scope details').forEach(element => { element.open = true; });
        const privacy = document.querySelector('.scan-check[data-stage="privacy"]');
        privacy.open = true;
        privacy.querySelectorAll("details").forEach(element => { element.open = true; });
      });
      const privacyText = await page.$eval('.scan-check[data-stage="privacy"]', (element) => element.innerText);
      for (const expected of ["Privacy notices (static)", "answers every address", "__cf_bm (infrastructure)",
                              "_ga (tracker)", "google tag manager (loader)", "present, with contact", "Heuristic"]) {
        assert.ok(privacyText.includes(expected), `Privacy row shows ${expected}`);
      }
      assert.ok((await page.$eval(".scan-checks-panel summary", (element) => element.innerText)).includes("of 7 checks completed"),
        "Privacy is not counted among the declared checks");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width,
        "Expanded target exclusions fit desktop and mobile");
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
    const selection = raw_results[0].raw_data.target_selection;
    delete raw_results[0].raw_data.target_selection;
    await page.goto(`${origin}/scans`);
    await page.waitForFunction(() => document.body.textContent.includes(
      "Target selection was not recorded. Full coverage cannot be confirmed."));
    raw_results[0].raw_data.target_selection = selection;
    // Long histories must keep their header visible and the last action reachable.
    scans.push(
      ...Array.from({ length: 12 }, (_, index) => ({
        ...scans[1],
        id: `history-extra-${index}`,
      })),
    );
    for (const width of [1440, 390]) {
      await page.setViewport({ width, height: 844 });
      await page.goto(`${origin}/scans`);
      await page.waitForSelector(
        '.scan-history button[aria-label="View scan history-extra-11"]',
      );
      const selector =
        width > 900 ? ".scan-history-desktop" : ".scan-history-mobile";
      await page.$eval(".scan-history", (element) =>
        element.scrollIntoView({ block: "start", behavior: "instant" }),
      );
      await page.focus(selector);
      await new Promise((resolve) => setTimeout(resolve, 300));
      const headingTop = await page.$eval(
        ".scan-history-heading",
        (element) => element.getBoundingClientRect().top,
      );
      await page.keyboard.press("End");
      await page.waitForFunction(
        (selector) => {
          const element = document.querySelector(selector);
          const action = element
            .querySelector('button[aria-label="View scan history-extra-11"]')
            .getBoundingClientRect();
          const panel = element.getBoundingClientRect();
          return (
            element.scrollTop > 0 &&
            action.top >= panel.top &&
            action.bottom <= panel.bottom
          );
        },
        {},
        selector,
      );
      const visible = await page.$eval(selector, (element) => {
        const action = element
          .querySelector('button[aria-label="View scan history-extra-11"]')
          .getBoundingClientRect();
        const panel = element.getBoundingClientRect();
        return action.top >= panel.top && action.bottom <= panel.bottom;
      });
      assert.ok(visible, `Last history action is reachable at ${width}px`);
      assert.ok(
        Math.abs(
          (await page.$eval(
            ".scan-history-heading",
            (element) => element.getBoundingClientRect().top,
          )) - headingTop,
        ) < 1,
        "History scroll keeps heading and filters fixed",
      );
    }
    scans.splice(3);
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
    launch401Once = true;
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
    assert.equal(launchRequests, 3, "401 causes one authenticated replay");
    assert.equal(refreshRequests, 1, "401 rotates the session once");
    assert.ok(launchIntentHeaders[0], "Launch sends an idempotency key");
    assert.ok(launchIntentHeaders[0].length <= 128);
    assert.equal(new Set(launchIntentHeaders.slice(0, 3)).size, 1,
      "Network uncertainty and auth replay reuse the same launch intent");
    await page.click('button[aria-label="Start scan"]');
    await page.waitForSelector(".modal-backdrop");
    await page.evaluate(() =>
      [...document.querySelectorAll(".modal-backdrop button")]
        .find((button) => button.textContent.trim() === "Start scan")
        .click(),
    );
    await page.waitForFunction(() => document.querySelector(".scan-summary .scan-badge")?.textContent === "Queued");
    assert.equal(launchRequests, 4);
    assert.notEqual(launchIntentHeaders[3], launchIntentHeaders[0],
      "A new deliberate launch uses a fresh intent key");
    launchConflict = true;
    await page.click('button[aria-label="Start scan"]');
    await page.waitForSelector(".modal-backdrop");
    const existingDetailRequest = page.waitForRequest((request) =>
      request.url().endsWith("/scans/demo-scan-002"), { timeout: 5000 });
    await page.evaluate(() =>
      [...document.querySelectorAll(".modal-backdrop button")]
        .find((button) => button.textContent.trim() === "Start scan")
        .click(),
    );
    await existingDetailRequest;
    await page.waitForSelector(".drawer.open");
    assert.equal(launchRequests, 5);
    // Declared-scope (version 2) coverage: the payload decides the label, detail lists and Known-CVE line.
    const nucleiLine = "Known-CVE templates: matches reported; clean results not proven.";
    const declaredCoverage = (state) => ({
      version: 2,
      check_set: "cyphward-checks-v1",
      domain: "example.ng",
      state,
      requested_checks: 8,
      evaluated_checks: state === "complete" ? 7 : 6,
      evaluated_groups: [],
      missing: state === "complete" ? [] : [{ hostname: "example.ng", check: "dns.dmarc", reason: "dns_not_observed" }],
      omitted_checks: [{ hostname: "static.example.ng", check: "tls.certificate", reason: "no_https" }],
      families: {
        "dns.spf": { requested: 1, evaluated: 1, omitted: 0 },
        "dns.dmarc": { requested: 1, evaluated: state === "complete" ? 1 : 0, omitted: 0 },
        "ports.inventory": { requested: 2, evaluated: 2, omitted: 0 },
        "http.headers": { requested: 2, evaluated: 2, omitted: 0 },
        "tls.certificate": { requested: 2, evaluated: 1, omitted: 1 },
      },
      targets: { selected: 2, in_scope: 2, assessed: 2, omitted: {} },
      nuclei: { gating: false, state: "matches_only", hosts_run: 2, matches: 0, label: nucleiLine },
      label: state === "complete"
        ? "example.ng: all declared checks complete on 2 hosts"
        : "example.ng: 6 of 8 declared checks conclusive",
      reason: "",
    });
    const declaredScans = [
      {
        id: "v2-complete",
        domain: "example.ng",
        status: "completed",
        // The real API serialises Postgres numeric scores as strings.
        score: "61.4",
        created_at: "2026-10-14T06:00:00Z",
        completed_at: "2026-10-14T06:12:00Z",
        findings_discovered: 4,
        current_stage: "completed",
        stage_progress: {
          ...progress,
          nuclei: { status: "failed", items: 0, duration_ms: 90000, error: "Known-CVE run timed out." },
          scoring: { status: "completed", scope: "organization", coverage: declaredCoverage("complete") },
        },
      },
      {
        id: "v2-partial",
        domain: "example.ng",
        status: "completed",
        score: 48.2,
        created_at: "2026-10-13T06:00:00Z",
        completed_at: "2026-10-13T06:12:00Z",
        findings_discovered: 9,
        current_stage: "completed",
        stage_progress: {
          ...progress,
          scoring: { status: "completed", scope: "organization", coverage: declaredCoverage("partial") },
        },
      },
    ];
    scans.push(...declaredScans);
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.querySelector(".drawer.open"));
    for (const [width, height] of [
      [1440, 1000],
      [390, 844],
      [320, 844],
    ]) {
      await page.setViewport({ width, height });
      await page.goto(`${origin}/scans`);
      await page.waitForSelector('button[aria-label="View scan v2-complete"]');
      await page.evaluate(() =>
        document.querySelector('button[aria-label="View scan v2-complete"]').click(),
      );
      await page.waitForFunction(() =>
        document.querySelector(".scan-summary .scan-score strong")?.textContent.startsWith("61.4"),
      );
      const complete = await page.evaluate((nucleiLine) => ({
        badge: document.querySelector(".scan-summary .scan-badge")?.textContent,
        notice: !!document.querySelector(".scan-summary .scan-coverage-notice"),
        limitedNotice: document.body.textContent.includes("Completed with limited coverage"),
        nuclei: document.body.textContent.includes(nucleiLine),
        overflow: document.documentElement.scrollWidth <= window.innerWidth,
      }), nucleiLine);
      assert.equal(complete.badge, "Declared checks complete", `Complete v2 coverage label at ${width}px`);
      assert.equal(complete.notice, false, "Complete v2 coverage has no limited-coverage notice");
      assert.equal(complete.limitedNotice, false, "Optional failed stage does not downgrade complete v2 coverage");
      assert.ok(complete.nuclei, "Known-CVE line is shown separately");
      assert.ok(complete.overflow, `No horizontal overflow on complete v2 scan at ${width}px`);
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => !document.querySelector(".drawer.open"));

      await page.evaluate(() =>
        document.querySelector('button[aria-label="View scan v2-partial"]').click(),
      );
      await page.waitForFunction(() =>
        document.querySelector(".scan-summary .scan-score strong")?.textContent.startsWith("48.2"),
      );
      await page.evaluate(() => {
        document.querySelector(".scan-checks-panel").open = true;
      });
      const partial = await page.evaluate(() => ({
        badge: document.querySelector(".scan-summary .scan-badge")?.textContent,
        notice: document.querySelector(".scan-summary .scan-coverage-notice strong")?.textContent,
        dmarc: document.body.textContent.includes("example.ng · DMARC: DNS result not recorded"),
        label: document.body.textContent.includes("example.ng: 6 of 8 declared checks conclusive"),
        overflow: document.documentElement.scrollWidth <= window.innerWidth,
      }));
      assert.equal(partial.badge, "Limited coverage", `Partial v2 coverage label at ${width}px`);
      assert.equal(partial.notice, "Completed with limited coverage");
      assert.ok(partial.dmarc, "Missing DMARC check has a readable reason");
      assert.ok(partial.label, "Partial v2 coverage shows its label line");
      assert.ok(partial.overflow, `No horizontal overflow on partial v2 scan at ${width}px`);
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => !document.querySelector(".drawer.open"));
    }
    // Return to the monitored scan so the polling check below still covers it.
    await page.goto(`${origin}/scans`);
    await page.waitForSelector('button[aria-label="View scan demo-scan-002"]');
    await page.evaluate(() =>
      document.querySelector('button[aria-label="View scan demo-scan-002"]').click(),
    );
    await page.waitForFunction(() =>
      document.querySelector(".scan-summary .scan-section-label")?.textContent === "Selected scan",
    );
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.querySelector(".drawer.open"));
    slowResponses = true;
    const monitoredScan = scans.find((scan) => scan.id === "demo-scan-002");
    monitoredScan.status = "completed";
    monitoredScan.stage_progress = progress;
    await page.waitForFunction(
      () =>
        document.querySelector(".scan-summary .scan-lifecycle")?.textContent ===
        "Scan completed",
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS: responsive layout, target sizes, history filters, stale scan-detail response, outage recovery, member permissions, verified-domain launch, empty state, keyboard containment, launch intent idempotency across outage/auth replay, fresh subsequent intent, active-scan navigation and polling with slow responses",
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
