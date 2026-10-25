import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import puppeteer from 'puppeteer-core';
const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), server: { host: '127.0.0.1', port: 0 } });
let browser;
try {
  await server.listen();
  browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  const user = { id: 'table-user', email: 'table@example.test', full_name: 'Table User' };
  const org = { id: 'c6100000-0000-4000-8000-000000000001', name: 'Table workspace', slug: 'tables', plan: 'growth' };
  let turn = 0;
  await page.evaluateOnNewDocument(user => {
    localStorage.setItem('cyphward-session', JSON.stringify({ access_token: 'mock', refresh_token: 'mock-refresh', user, _expires_at: Date.now() + 3600000 }));
    localStorage.setItem(`cyphward-tour-v1:${user.id}`, 'done');
    localStorage.setItem('cyphward-cookie-consent', 'accepted');
    localStorage.setItem('cyphward-welcome-sent', user.id);
  }, user);
  await page.setRequestInterception(true);
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return void request.continue();
    let body = {};
    if (path.endsWith('/auth/bootstrap')) body = { user, email_verified: true, memberships: [{ org, role: 'owner', domains: [] }] };
    else if (path.endsWith('/auth/verification')) body = { email: user.email, verified: true };
    else if (path.endsWith('/overview')) body = { organization: { ...org, domains_count: 0, verified_domains_count: 0 }, score: null, max_score: 100, grade: null, posture_label: 'Not assessed', assessed: false, trend: null, risk_points: null, counts: { total_assets: 0, total_findings: 0, critical: 0, high: 0, medium: 0, low: 0 }, subscores: [], factors: [], recent_scans: [] };
    else if (path.endsWith('/domains')) body = [];
    else if (path.includes('/notifications')) body = { notifications: [], unread_count: 0 };
    else if (path.endsWith('/ai/chat/stream')) {
      turn++;
      const artifact = { schema_version: 1, id: 'c6200000-0000-4000-8000-000000000001', org_id: org.id, version: turn,
        title: 'Recorded findings table', generated_at: new Date().toISOString(), days: 30, chart_style: 'line', severities: [], sample: true,
        summary: 'Recorded findings only.', metrics: [], charts: [], limitations: ['Display fixture'], sources: ['Display fixture'],
        tables: [{ title: 'Priority findings', columns: ['Finding', 'Severity'], rows: [['Missing DMARC', 'High']] }] };
      const events = [{ token: '| Finding | Meaning | Next step |\n| --- | --- | --- |\n| **Missing DMARC** | Email authentication policy absent | Inventory senders, then start monitoring |\n| Escaped \\| label | <img src=x onerror=alert(1)> | Test before enforcement |', done: false },
        ...(turn === 2 ? [{ type: 'artifact', artifact }] : []), { done: true, sources: [], actions: [] }];
      return void request.respond({ status: 200, contentType: 'text/event-stream', body: events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('') });
    }
    void request.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/overview`);
  await page.waitForFunction(() => localStorage.getItem('cyphward-org-id') === 'c6100000-0000-4000-8000-000000000001');
  await page.waitForSelector('[aria-label="Open CyphBot"]', { visible: true }); await page.click('[aria-label="Open CyphBot"]');
  const send = async message => {
    await page.type('[aria-label="Ask CyphBot"]', message); await page.keyboard.press('Enter');
    await page.waitForFunction(() => !document.querySelector('[aria-label="Stop response"]'));
  };
  await send('Use just a table to explain findings');
  await page.waitForSelector('.cyphbot-message table');
  assert.equal(await page.$$eval('.cyphbot-message th', all => all.length), 3);
  assert.equal(await page.$$eval('.cyphbot-message tbody tr', all => all.length), 2);
  assert.equal(await page.$$eval('.cyphbot-message img', all => all.length), 0);
  assert.equal(await page.$$eval('[data-open-report]', all => all.length), 0);
  assert.ok(await page.$eval('.cyphbot-message table', el => el.textContent.includes('Escaped | label')));
  await page.setViewport({ width: 390, height: 844 });
  await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth);
  assert.equal(await page.$eval('[aria-label="Findings explanation table"]', el => getComputedStyle(el).overflowX), 'auto');
  await send('Create a table-only report');
  await page.waitForSelector('[data-open-report]');
  assert.equal(await page.$$eval('[data-report-thumbnail]', all => all.length), 0);
  await page.click('[data-open-report]');
  const panel = '[aria-label="Organization performance report"]';
  await page.waitForSelector(`${panel} table`);
  assert.equal(await page.$eval(`${panel} [data-report-tab="data"]`, el => el.getAttribute('aria-selected')), 'true');
  assert.equal(await page.$$eval(`${panel} svg.marks`, all => all.length), 0);
  assert.ok(await page.$eval(`${panel} table`, el => el.textContent.includes('Missing DMARC')));
  assert.deepEqual(errors, []);
  console.log('PASS: table chat, safe cells, mobile overflow, table-only artifact and default Data view');
} finally { await browser?.close(); await server.close(); }
