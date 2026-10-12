// Local browser regression: every API request is mocked; no live account used.
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import puppeteer from 'puppeteer-core';

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
  const page = await browser.newPage();
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const user = { id: 'local-user', email: 'test@example.test', full_name: 'Local Test' };
  const org = { id: 'local-org', name: 'Score Regression', slug: 'score-test', plan: 'growth', domains_count: 1, verified_domains_count: 1 };
  const domain = { id: 'local-domain', org_id: org.id, domain: 'example.test', verification_status: 'verified', created_at: '2026-10-01T00:00:00Z' };
  let payload = {
    organization: org, score: 38.5, max_score: 100, grade: 'F', posture_label: 'Critical',
    status_color: 'accent', assessed: true, model: 'cyphward-risk-v2', scope: 'organization',
    risk_points: 160, trend: null, trend_baseline_at: null,
    assessment: { scan_id: 'scan-1', status: 'completed', completed_at: '2026-10-09T00:00:00Z' },
    counts: { total_assets: 1, total_findings: 8, critical: 0, high: 8, medium: 0, low: 0, info: 0 },
    subscores: [], factors: [], recent_scans: [
      { id: 'old-zero-score', domain: 'example.test', score: 0, status: 'completed', stage_progress: {}, created_at: '2026-10-01T00:00:00Z' },
      { id: 'new-score', domain: 'example.test', score: 38.5, status: 'completed', stage_progress: { scoring: { scope: 'organization' } }, created_at: '2026-10-09T00:00:00Z' },
    ],
  };
  let mode = 'success';
  let role = 'owner';
  const partialScan = {
    id: 'partial-scan', domain: 'example.test', status: 'completed', score: 55.6,
    created_at: '2026-10-11T00:00:00Z', current_stage: 'completed', stage_progress: {
      nuclei: { status: 'failed', items: 1, error: '1 of 2 targets could not be assessed.' },
      ports: { status: 'skipped', error: 'naabu not installed' },
      scoring: { status: 'completed', scope: 'organization' },
    },
  };
  let delayed;
  await page.setRequestInterception(true);
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) {
      let body = {};
      let status = 200;
      if (url.pathname.endsWith('/auth/bootstrap')) body = { user, email_verified: true, memberships: [{ org, role, domains: [domain] }] };
      else if (url.pathname.endsWith('/domains')) body = [domain];
      else if (url.pathname.endsWith('/scans')) body = [partialScan];
      else if (url.pathname.endsWith('/scans/partial-scan')) body = {
        scan: partialScan, raw_results: [{ stage: 'nuclei', raw_data: {
          attempted_hosts: ['example.test', 'www.example.test'],
          successful_hosts: ['example.test'], failed_hosts: { 'www.example.test': 'timeout' },
        } }],
      };
      else if (url.pathname.endsWith('/overview')) {
        if (mode === 'delay') { delayed = request; return; }
        if (mode === 'failure') { status = 503; body = { detail: 'Simulated outage' }; }
        else body = payload;
      } else if (url.pathname.includes('/notifications')) body = { notifications: [], unread_count: 0 };
      void request.respond({ status, contentType: 'application/json', body: JSON.stringify(body) });
    } else if (url.origin === origin) void request.continue();
    else void request.abort();
  });
  await page.evaluateOnNewDocument((user) => {
    localStorage.setItem('cyphward-session', JSON.stringify({
      access_token: 'local-mocked-token', refresh_token: 'local-mocked-refresh', user,
      _expires_at: Date.now() + 3600000,
    }));
    localStorage.setItem('cyphward-welcome-sent', user.id);
  }, user);
  await page.goto(`${origin}/overview`);
  const ringIs = value => page.waitForFunction(value => document.querySelector('.ring-num')?.textContent === value, {}, value);
  const refresh = () => page.evaluate(() => [...document.querySelectorAll('button')].find(button => button.textContent.trim() === 'REFRESH').click());
  await ringIs('38.5');
  assert.ok(await page.evaluate(() => document.body.textContent.includes('Not enough comparable history')));
  assert.ok(await page.evaluate(() => document.body.textContent.includes('0/100')));
  assert.ok(await page.evaluate(() => document.body.textContent.includes('Legacy scan score')));
  assert.ok(await page.evaluate(() => document.body.textContent.includes('Organization at scan completion')));

  mode = 'failure';
  await refresh();
  await page.waitForFunction(() => document.body.textContent.includes('Refresh failed'));
  await ringIs('38.5');

  mode = 'success';
  payload = { ...payload, score: 50, trend: -2.4, risk_points: 100 };
  await refresh();
  await ringIs('50.0');
  assert.ok(await page.evaluate(() => document.body.textContent.includes('-2.4 pts')));
  assert.ok(!await page.evaluate(() => document.body.textContent.includes('Refresh failed')));

  // An older response arriving last must not overwrite the latest result.
  mode = 'delay';
  await refresh();
  const until = Date.now() + 5000;
  while (!delayed && Date.now() < until) await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(delayed, 'Delayed overview request was issued');
  mode = 'success';
  payload = { ...payload, score: 55.6, risk_points: 80 };
  await refresh();
  await ringIs('55.6');
  await delayed.respond({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...payload, score: 38.5 }) });
  await new Promise(resolve => setTimeout(resolve, 150));
  await ringIs('55.6');

  for (const width of [320, 390, 820, 1280]) {
    await page.setViewport({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `No horizontal overflow at ${width}px`);
    if (width <= 900) {
      const brand = await page.$eval('header.topbar a[aria-label="Cyphward dashboard"]', element => ({
        shield: element.querySelector('svg').getBoundingClientRect().height,
        text: element.textContent.trim(), visible: element.getBoundingClientRect().width > 0,
      }));
      assert.ok(brand.visible && brand.shield >= 32 && brand.text === 'CYPHWARD', `Readable full brand at ${width}px`);
      assert.ok(await page.evaluate(() => {
        const svg = document.querySelector('header.topbar a[aria-label="Cyphward dashboard"] svg');
        return [...svg.querySelectorAll('defs [id]')].every(definition => document.querySelectorAll(`[id="${definition.id}"]`).length === 1);
      }), 'Visible shield owns unique SVG paint IDs, independent of the hidden sidebar');
    }
  }
  await page.setViewport({ width: 390, height: 900 });
  if (process.env.CYPHWARD_REVIEW_SCREENSHOT) {
    await page.screenshot({ path: process.env.CYPHWARD_REVIEW_SCREENSHOT, fullPage: false });
  }
  await page.goto(`${origin}/scans`);
  await page.waitForFunction(() => document.body.textContent.includes('Completed with limited coverage'));
  await page.waitForFunction(() => document.body.textContent.includes('1 of 2 targets checked'));
  await page.evaluate(() => [...document.querySelectorAll('button')].find(button => button.textContent.trim() === 'Review coverage').click());
  await page.waitForFunction(() => document.querySelector('.scan-checks-panel')?.open);
  assert.ok(await page.evaluate(() => document.body.textContent.includes('Failed') && document.body.textContent.includes('Skipped')));
  role = 'member';
  await page.reload();
  await page.waitForFunction(() => document.body.textContent.includes('Completed with limited coverage'));
  assert.ok(!await page.evaluate(() => [...document.querySelectorAll('button')].some(button => button.getAttribute('aria-label') === 'Start scan')), 'Member is not offered admin-only scan launch');
  role = 'owner';
  domain.verification_status = 'pending';
  await page.reload();
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.getAttribute('aria-label') === 'Verify domain'));
  assert.deepEqual(errors, []);
  console.log('PASS: score refresh/history, full mobile logo, partial coverage, and role/verification-aware scan launch');
} finally {
  if (browser) await browser.close();
  await server.close();
}
