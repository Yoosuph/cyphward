// Public offer and owner billing UX; local Vite and mocked authenticated APIs.
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import puppeteer from 'puppeteer-core';
import { fileURLToPath } from 'node:url';
import { user, org, domain } from './lib/compliance-fixtures.mjs';

const root = fileURLToPath(new URL('..', import.meta.url));
const server = await createServer({ root, server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
let browser;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));
  await page.setRequestInterception(true);
  let authenticated = false;
  let aiFails = false;
  const writes = [];
  page.on('request', req => {
    const url = new URL(req.url());
    if (!url.pathname.startsWith('/api/')) return url.origin === origin ? void req.continue() : void req.abort();
    const respond = (status, data) => req.respond({ status, contentType: 'application/json', body: JSON.stringify(data) });
    if (req.method() !== 'GET') writes.push(url.pathname);
    if (url.pathname.endsWith('/auth/bootstrap')) return respond(authenticated ? 200 : 401, { user, email_verified: true, memberships: [{ org, role: 'owner', domains: [domain] }] });
    if (url.pathname.includes('/platform/')) return respond(403, {});
    if (url.pathname.endsWith('/notifications')) return respond(200, { notifications: [] });
    if (url.pathname.endsWith('/settings')) return respond(200, { organization: org, membership: { role: 'owner', user_id: user.id }, members: [] });
    if (url.pathname.endsWith('/billing/subscription')) return respond(200, { subscription: { plan: 'growth', status: 'trialing', current_period_end: '2026-12-01T00:00:00Z' }, effective_status: 'trialing', entitlements: { plan: 'growth' }, provider: 'manual', billing_mode: 'manual_confirmation' });
    if (url.pathname.endsWith('/billing/invoices')) return respond(200, { invoices: [] });
    if (url.pathname.endsWith('/auth/mfa/status')) return respond(200, { enrolled: true, email_verified: true, totp_enrolled: false });
    if (url.pathname.endsWith('/findings')) return respond(200, { findings: [{ id: 'f1', title: 'Missing Email DMARC Authentication Policy', description: 'Recorded DNS evidence.', severity: 'high', status: 'open', category: 'DNS & Email Security', hostname: 'acme.ng', evidence: {}, remediation: 'Review legitimate senders first.' }], categories: { 'DNS & Email Security': 1 }, total: 1 });
    if (url.pathname.endsWith('/ai/remediate')) return aiFails ? respond(503, { detail: 'Unavailable' }) : respond(200, { title: 'ONLY CURRENT GUIDE', target_stack: 'nginx', summary: 'Review before enforcement.', prerequisites: [], steps: ['Inventory legitimate senders.'], code_snippet: '# No universal production configuration.', verification_command: 'Review the actual service.', estimated_time_minutes: null });
    if (url.pathname.endsWith('/ai/explain')) return respond(503, { detail: 'Unavailable' });
    return respond(200, {});
  });
  const text = () => page.evaluate(() => document.body.innerText);
  const noOverflow = async label => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${label}: viewport overflow`);
  await page.evaluateOnNewDocument(() => {
    localStorage.setItem('cyphward-theme', 'light');
    localStorage.setItem('cyphward-cookie-consent', 'accepted');
  });
  for (const width of [1440, 390, 320]) {
    await page.setViewport({ width, height: 900 });
    await page.goto(origin, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.hero-h1', { timeout: 15000 });
    const home = await text();
    assert.match(home, /Find the weakness\. Verify the fix\./);
    assert.match(home, /Nigerian software teams/);
    assert.match(home, /Questionnaires with evidence owners/);
    assert.match(home, /30-DAY TRIAL/);
    for (const old of ['African networks', '6 Layers of Strata', 'APPLIES TO YOU', '₦450M', 'p=quarantine; pct=100']) assert.ok(!home.includes(old), `retired claim: ${old}`);
    await noOverflow(`home ${width}`);
    await page.waitForFunction(() => Number(getComputedStyle(document.querySelector('.hero-h1')).opacity) === 1);
    if (process.env.COMMERCIAL_SCREENSHOTS) await page.screenshot({ path: `/tmp/cyphward-commercial-home-${width}.png` });

    await page.goto(`${origin}/pricing`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.pricing-card', { timeout: 15000 });
    const pricing = await text();
    assert.match(pricing, /₦15,000/); assert.match(pricing, /₦25,000/);
    assert.match(pricing, /30 scans per calendar month/); assert.match(pricing, /300 scans per calendar month/);
    assert.match(pricing, /Compliance questionnaires/);
    assert.match(pricing, /no automatic charge or automatic paid renewal/i);
    assert.match(pricing, /open invoice is not payment confirmation/i);
    assert.match(pricing, /Scheduled and manually launched assessments share/);
    const ctas = await page.$$eval('.pricing-card a', links => links.map(a => a.getAttribute('href')));
    assert.deepEqual(ctas, ['/signup?plan=starter', '/signup?plan=growth']);
    await noOverflow(`pricing ${width}`);
    if (process.env.COMMERCIAL_SCREENSHOTS) await page.screenshot({ path: `/tmp/cyphward-commercial-pricing-${width}.png` });
  }
  authenticated = true;
  await page.evaluate(u => {
    localStorage.setItem('cyphward-session', JSON.stringify({ access_token: 'fixture', refresh_token: 'fixture', user: u, _expires_at: Date.now() + 86400000 }));
    localStorage.setItem(`cyphward-tour-v1:${u.id}`, 'done');
    localStorage.setItem('cyphward-welcome-sent', u.id);
  }, user);
  for (const width of [1440, 390, 320]) {
    await page.setViewport({ width, height: 900 });
    await page.goto(`${origin}/settings`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.body.innerText.includes('ARRANGE PAYMENT OR PLAN CHANGE'));
    const settings = await text();
    assert.ok(!settings.includes('RENEW 30 DAYS') && !settings.includes('SET PLAN'));
    assert.match(settings, /An open invoice does not confirm payment/);
    assert.equal(await page.$eval('a[href="/contact"]', a => a.textContent.trim()), 'ARRANGE PAYMENT OR PLAN CHANGE');
    await noOverflow(`settings ${width}`);
  }
  await page.setViewport({ width: 390, height: 900 });
  await page.goto(`${origin}/findings`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'How to fix'));
  await page.evaluate(() => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'How to fix').click());
  await page.waitForFunction(() => document.body.innerText.includes('ONLY CURRENT GUIDE'));
  assert.match(await text(), /Allow time for staging and observation/);
  aiFails = true;
  await page.evaluate(() => [...document.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'apache').click());
  await page.waitForFunction(() => document.body.innerText.includes('The guide could not be loaded'));
  assert.ok(!(await text()).includes('ONLY CURRENT GUIDE'), 'A failed new guide must not display the previous guide');
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => !document.body.innerText.includes('The guide could not be loaded'));
  await page.click('button[title="Ask CyphBot about this issue"]');
  await page.waitForFunction(() => document.body.innerText.includes('No new analysis was produced'));
  assert.ok(!(await text()).includes('Heightened risk of exploitation'), 'An outage must not fabricate a finding explanation');
  assert.ok(!writes.some(path => /billing\/subscription(?:\/renew)?$/.test(path)), 'Viewing billing must never activate/renew');
  assert.deepEqual(errors, []);
  console.log('Commercial UX passed: home/pricing/settings at 1440, 390 and 320px; explicit trial/scope/manual billing; finding-guide/explanation errors never fabricate advice or display a previous guide. APIs mocked.');
} finally {
  if (browser) await browser.close();
  await server.close();
}
