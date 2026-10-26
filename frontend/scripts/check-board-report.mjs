// Local browser regression for the board report: every API request is mocked; no live account used.
// Hostile organisation/model text must render as text (modal and print frame), the print frame must be
// sandboxed without scripts, and a summary without org_name must not crash the modal.
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import puppeteer from 'puppeteer-core';

const HOSTILE = '</title><img src=x onerror=alert(1)>';
const root = fileURLToPath(new URL('..', import.meta.url));
const server = await createServer({ root, server: { host: '127.0.0.1', port: 0 } });
let browser;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({
    executablePath: process.env.CHROME_BIN || '/usr/bin/chromium',
    headless: true, args: ['--no-sandbox'],
  });
  const user = { id: 'local-user', email: 'test@example.test', full_name: 'Local Test' };
  const org = { id: 'local-org', name: 'Board Regression', slug: 'board-test', plan: 'growth', domains_count: 1, verified_domains_count: 1 };
  const domain = { id: 'local-domain', org_id: org.id, domain: 'example.test', verification_status: 'verified', created_at: '2026-10-01T00:00:00Z' };
  const overview = {
    organization: org, score: 72.5, max_score: 100, grade: null, posture_label: 'Partial assessment',
    status_color: 'accent', assessed: true, model: 'cyphward-risk-v3', scope: 'organization',
    risk_points: 10, trend: null, trend_baseline_at: null,
    assessment: { scan_id: 'scan-1', status: 'completed', completed_at: '2026-10-09T00:00:00Z', coverage: { version: 1, state: 'partial', evaluated_checks: 1 } },
    counts: { total_assets: 1, total_findings: 1, critical: 0, high: 1, medium: 0, low: 0, info: 0 },
    subscores: [], factors: [], recent_scans: [],
  };
  const hostileSummary = {
    org_name: HOSTILE, score: 72.5, grade: null, posture_label: 'Partial assessment',
    executive_headline: HOSTILE, board_summary: `Summary ${HOSTILE}`, key_strengths: [HOSTILE],
    critical_action_items: [{ priority: 'HIGH', title: HOSTILE, impact: HOSTILE, owner: 'Assign an owner' }],
    compliance_verdict: 'Technical evidence only.', generated_at: 'Live Telemetry',
  };
  const { org_name: _drop, posture_label: _drop2, ...missingName } = hostileSummary;

  async function openReport(summary) {
    const page = await browser.newPage();
    const errors = [];
    const dialogs = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => { dialogs.push(dialog.message()); void dialog.dismiss(); });
    await page.setRequestInterception(true);
    page.on('request', request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith('/api/')) {
        let body = {};
        if (url.pathname.endsWith('/auth/bootstrap')) body = { user, email_verified: true, memberships: [{ org, role: 'owner', domains: [domain] }] };
        else if (url.pathname.endsWith('/domains')) body = [domain];
        else if (url.pathname.endsWith('/scans')) body = [];
        else if (url.pathname.endsWith('/overview')) body = overview;
        else if (url.pathname.endsWith('/ai/executive-summary')) body = summary;
        else if (url.pathname.includes('/notifications')) body = { notifications: [], unread_count: 0 };
        void request.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      } else if (url.origin === origin) void request.continue();
      else void request.abort();
    });
    await page.evaluateOnNewDocument((user) => {
      localStorage.setItem(`cyphward-tour-v1:${user.id}`, 'done');
      localStorage.setItem('cyphward-session', JSON.stringify({
        access_token: 'local-mocked-token', refresh_token: 'local-mocked-refresh', user,
        _expires_at: Date.now() + 3600000,
      }));
      localStorage.setItem('cyphward-welcome-sent', user.id);
    }, user);
    await page.goto(`${origin}/overview`);
    const button = await page.waitForSelector('xpath/.//button[.//span[text()="GENERATE BOARD REPORT"]]');
    await button.click();
    await page.waitForSelector('#cyphward-board-report h4');
    return { page, errors, dialogs };
  }

  async function printFrame(page) {
    await page.click('button[title="Print or Save PDF"]');
    await page.waitForFunction(() => {
      const frame = document.querySelector('iframe[title="Cyphward Print Frame"]');
      return frame?.contentDocument?.querySelector('#cyphward-board-report');
    }, { timeout: 3000 });
    return page.evaluate(() => {
      const frame = document.querySelector('iframe[title="Cyphward Print Frame"]');
      const doc = frame.contentDocument;
      return {
        sandbox: frame.getAttribute('sandbox'),
        title: doc.title,
        titleElements: doc.querySelectorAll('title').length,
        compatMode: doc.compatMode,
        images: doc.querySelectorAll('img').length,
        heading: doc.querySelector('#cyphward-board-report h4')?.textContent,
        text: doc.body.textContent,
      };
    });
  }

  // 1. Hostile org_name and model text render as text.
  {
    const { page, errors, dialogs } = await openReport(hostileSummary);
    const modal = await page.evaluate(() => ({
      heading: document.querySelector('#cyphward-board-report h4')?.textContent,
      injected: document.querySelectorAll('img[src="x"]').length,
      text: document.querySelector('#cyphward-board-report')?.textContent || '',
    }));
    assert.equal(modal.heading, HOSTILE, 'org_name is shown literally in the modal');
    assert.equal(modal.injected, 0, 'no injected image element in the page');
    assert.ok(!modal.text.includes('VERIFICATION HASH'), 'the fake verification hash is gone');
    const frame = await printFrame(page);
    assert.equal(frame.sandbox, 'allow-same-origin allow-modals', 'print frame is sandboxed without scripts');
    assert.equal(frame.title, `CYPHWARD Board Report — ${HOSTILE}`, 'title is set as text');
    assert.equal(frame.titleElements, 1, 'the title was not broken out of');
    assert.equal(frame.compatMode, 'CSS1Compat', 'print document is in standards mode');
    assert.equal(frame.images, 0, 'no image element in the print document');
    assert.equal(frame.heading, HOSTILE, 'org_name is literal text in the print document');
    assert.ok(!frame.text.includes('VERIFICATION HASH'));
    await new Promise(resolve => setTimeout(resolve, 600));
    assert.deepEqual(dialogs, [], 'no script ran');
    assert.deepEqual(errors, []);
    await page.close();
  }

  // 2. A summary without org_name (or posture label) does not crash.
  {
    const { page, errors } = await openReport(missingName);
    const heading = await page.$eval('#cyphward-board-report h4', el => el.textContent);
    assert.equal(heading, '—', 'missing org_name shows a placeholder');
    const frame = await printFrame(page);
    assert.equal(frame.title, 'CYPHWARD Board Report');
    assert.deepEqual(errors, [], 'no page error without org_name');
    await page.close();
  }

  console.log('PASS: board report renders hostile org/model text literally, prints in a script-free sandbox, and survives a missing org_name');
} finally {
  if (browser) await browser.close();
  await server.close();
}
