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
  let delayed;
  await page.setRequestInterception(true);
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) {
      let body = {};
      let status = 200;
      if (url.pathname.endsWith('/auth/bootstrap')) body = { user, email_verified: true, memberships: [{ org, role: 'owner', domains: [domain] }] };
      else if (url.pathname.endsWith('/domains')) body = [domain];
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

  for (const width of [320, 390, 1280]) {
    await page.setViewport({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `No horizontal overflow at ${width}px`);
  }
  assert.deepEqual(errors, []);
  console.log('PASS: decimal/zero scores, historical scope labels, missing history, failed refresh, recovery, negative trend, response ordering, and 320/390/1280px layouts');
} finally {
  if (browser) await browser.close();
  await server.close();
}
