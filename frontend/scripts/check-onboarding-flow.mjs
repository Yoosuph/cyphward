// Browser regression for dashboard access before domain verification.
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
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const user = { id: 'new-user', email: 'new@example.test', full_name: 'New User' };
  const org = { id: 'new-org', name: 'New Workspace', slug: 'new-workspace', plan: 'growth' };
  let domains = [];
  let hasOrg = true;
  let emailVerified = true;
  let bootstrapUnavailable = false;
  let refreshUnavailable = false;
  let refreshRequests = 0;
  let delayRefresh = false;
  let delayedRefresh = null;
  const overview = () => ({
    organization: { ...org, domains_count: domains.length, verified_domains_count: 0 },
    score: null, max_score: 100, grade: null, posture_label: 'Not assessed',
    assessed: false, trend: null, risk_points: null, counts: {
      total_assets: 0, total_findings: 0, critical: 0, high: 0, medium: 0, low: 0,
    }, subscores: [], factors: [], recent_scans: [],
  });
  await page.setRequestInterception(true);
  page.on('request', request => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/')) return void request.continue();
    let body = {};
    let status = 200;
    if (url.pathname.endsWith('/auth/bootstrap')) {
      body = { user, email_verified: emailVerified, memberships: hasOrg ? [{ org, role: 'owner', domains }] : [] };
      if (bootstrapUnavailable) { status = 503; body = { detail: 'Temporary outage' }; }
    } else if (url.pathname.endsWith('/overview')) body = overview();
    else if (url.pathname.endsWith('/auth/refresh')) {
      refreshRequests++;
      body = { access_token: 'mock-token', refresh_token: 'mock-refresh', user, expires_in: 3600 };
      if (refreshUnavailable) { status = 503; body = { detail: 'Temporary refresh outage' }; }
      if (delayRefresh) { delayedRefresh = request; return; }
    }
    else if (url.pathname.endsWith('/members/invites/accept')) { status = 403; body = { detail: 'Verify first' }; }
    else if (url.pathname.endsWith('/auth/verification')) body = { email: user.email, verified: emailVerified };
    else if (url.pathname.endsWith('/auth/otp/send')) body = { sent: true, resend_after: 60 };
    else if (url.pathname.endsWith('/domains')) body = domains;
    else if (url.pathname.includes('/notifications')) body = { notifications: [], unread_count: 0 };
    void request.respond({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.evaluateOnNewDocument(user => {
    localStorage.setItem('cyphward-session', JSON.stringify({
      access_token: 'mock-token', refresh_token: 'mock-refresh', user,
      _expires_at: Date.now() + (location.search.includes('expired=1') ? -1000 : 3600000),
    }));
    localStorage.setItem('cyphward-welcome-sent', user.id);
    // Simulate cached progress from another account; bootstrap must override it.
    localStorage.setItem('cyphward-onboarding', 'verify_domain');
    localStorage.setItem('cyphward-tenant', JSON.stringify({ id: 'old-org', name: 'Old Workspace', slug: 'old-workspace' }));
    localStorage.setItem('cyphward-org-id', 'old-org');
    window.__copied = '';
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true, value: { writeText: async text => { window.__copied = text; } },
    });
  }, user);

  await page.goto(`${origin}/overview`);
  await page.waitForFunction(() => document.body.textContent.includes('Finish setting up domain monitoring'));
  assert.equal(new URL(page.url()).pathname, '/overview');
  assert.ok(!await page.evaluate(() => document.body.textContent.includes('Old Workspace')));
  assert.equal(await page.evaluate(() => localStorage.getItem('cyphward-org-id')), org.id);
  assert.ok(await page.evaluate(() => document.body.textContent.includes('Across 0 domains')));
  assert.ok(await page.evaluate(() => document.body.textContent.includes('Verification needed')));

  domains = [{ id: 'pending-domain', org_id: org.id, domain: 'mycompany.ng',
    verification_status: 'pending', verification_token: 'secret-token', created_at: '2026-10-11T00:00:00Z' }];
  await page.goto(`${origin}/overview`);
  await page.waitForFunction(() => document.body.textContent.includes('Verify mycompany.ng'));
  assert.equal(new URL(page.url()).pathname, '/overview');

  await page.goto(`${origin}/onboarding/verify-domain`);
  await page.waitForSelector('button[aria-label="Copy DNS host name"]');
  await page.click('button[aria-label="Copy DNS host name"]');
  assert.equal(await page.evaluate(() => window.__copied), '_cyphward');
  await page.click('button[aria-label="Copy DNS TXT value"]');
  assert.equal(await page.evaluate(() => window.__copied), 'cyphward-verification=secret-token');
  await page.setViewport({ width: 320, height: 900 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));

  // The relative host must include the subdomain when editing a parent zone.
  domains = [{ ...domains[0], domain: 'www.mycompany.ng' }];
  await page.goto(`${origin}/onboarding/verify-domain`);
  await page.waitForSelector('#dns-zone');
  await page.$eval('#dns-zone', input => { input.value = ''; });
  await page.type('#dns-zone', 'mycompany.ng');
  await page.click('button[aria-label="Copy DNS host name"]');
  assert.equal(await page.evaluate(() => window.__copied), '_cyphward.www');
  await page.$eval('button[aria-label="Copy full DNS record name"]', button => button.click());
  assert.equal(await page.evaluate(() => window.__copied), '_cyphward.www.mycompany.ng');
  await page.evaluate(() => [...document.querySelectorAll('button')].find(button => button.textContent.includes('COPY INSTRUCTIONS')).click());
  assert.ok(await page.evaluate(() => window.__copied.includes('TTL: 300') && window.__copied.includes('Name / Host: _cyphward.www')));
  await page.evaluate(() => { navigator.clipboard.writeText = async () => { throw new Error('Denied'); }; });
  await page.$eval('button[aria-label="Copy DNS TXT value"]', button => button.click());
  await page.waitForFunction(() => document.body.textContent.includes('Select and copy the text'));

  // Tablet navigation stays available while the desktop sidebar is hidden.
  await page.setViewport({ width: 820, height: 900 });
  await page.goto(`${origin}/overview`);
  await page.waitForSelector('nav[aria-label="Mobile navigation"] button[aria-label="Open menu"]');
  await page.click('nav[aria-label="Mobile navigation"] button[aria-label="Open menu"]');
  await page.waitForSelector('[role="dialog"][aria-label="More pages menu"]', { visible: true });
  assert.ok(await page.evaluate(() => document.body.classList.contains('scroll-locked')));
  await page.keyboard.down('Shift');
  await page.keyboard.press('Tab');
  await page.keyboard.up('Shift');
  assert.ok(await page.evaluate(() => document.querySelector('[aria-label="More pages menu"]').contains(document.activeElement)));
  await page.keyboard.press('Tab');
  assert.ok(await page.evaluate(() => document.querySelector('[aria-label="More pages menu"]').contains(document.activeElement)));
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => !document.body.classList.contains('scroll-locked'));
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Open menu');
  await page.goto(`${origin}/pricing`);
  await page.waitForSelector('button[aria-label="Open menu"]', { visible: true });
  await page.click('button[aria-label="Open menu"]');
  await page.waitForSelector('.landing-mobile-menu', { visible: true });

  hasOrg = false;
  await page.setViewport({ width: 320, height: 900 });
  await page.goto(`${origin}/overview`);
  await page.waitForFunction(() => location.pathname === '/onboarding/create-org');
  assert.ok(!await page.evaluate(() => document.body.textContent.includes('mycompany.ng')));
  assert.equal(await page.evaluate(() => localStorage.getItem('cyphward-org-id')), null);

  emailVerified = false;
  await page.goto(`${origin}/onboarding/verify-email`);
  await page.waitForSelector('.pin-input');
  assert.ok(await page.evaluate(() => [...document.querySelectorAll('.pin-input')].every(input => {
    const rect = input.getBoundingClientRect();
    const row = input.parentElement.getBoundingClientRect();
    return rect.left >= row.left && rect.right <= row.right;
  })), 'All six OTP fields fit inside their row at 320px');
  assert.ok(await page.evaluate(() => document.body.textContent.includes('Wrong email? Sign out')));

  emailVerified = true;
  hasOrg = true;
  bootstrapUnavailable = true;
  await page.goto(`${origin}/overview?invite=offline-invite`);
  await page.waitForFunction(() => document.body.textContent.includes('Reconnect to your workspace'));
  assert.ok(await page.evaluate(() => !!localStorage.getItem('cyphward-session')));
  assert.equal(new URL(page.url()).searchParams.get('invite'), 'offline-invite');
  bootstrapUnavailable = false;
  await page.evaluate(() => [...document.querySelectorAll('button')].find(button => button.textContent.includes('RETRY WORKSPACE')).click());
  await page.waitForFunction(() => document.body.textContent.includes('Finish setting up domain monitoring'));
  assert.equal(new URL(page.url()).searchParams.get('invite'), 'offline-invite');

  // An expired access token plus a refresh outage is not a revoked session.
  refreshUnavailable = true;
  await page.goto(`${origin}/overview?expired=1`);
  await page.waitForFunction(() => document.body.textContent.includes('Reconnect to your workspace'));
  assert.ok(await page.evaluate(() => !!localStorage.getItem('cyphward-session')));
  refreshUnavailable = false;
  await page.evaluate(() => [...document.querySelectorAll('button')].find(button => button.textContent.includes('RETRY WORKSPACE')).click());
  await page.waitForFunction(() => document.body.textContent.includes('Finish setting up domain monitoring'));

  const beforeRefresh = refreshRequests;
  await page.evaluate(async () => {
    const session = await import('/src/lib/session.ts');
    await Promise.all([session.refreshSession(true), session.refreshSession(true), session.refreshSession(true)]);
  });
  assert.equal(refreshRequests - beforeRefresh, 1, 'Concurrent callers share one refresh request');

  delayRefresh = true;
  await page.evaluate(() => {
    window.__lateRefreshStatus = null;
    void import('/src/lib/session.ts').then(session => session.refreshSession(true)).catch(error => { window.__lateRefreshStatus = error.status; });
  });
  const deadline = Date.now() + 5000;
  while (!delayedRefresh && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(delayedRefresh);
  await page.evaluate(async () => {
    const session = await import('/src/lib/session.ts');
    session.saveSession({ access_token: 'other-token', refresh_token: 'other-refresh', user: { id: 'other-user', email: 'other@example.test', full_name: 'Other' }, expires_in: 3600 });
  });
  await delayedRefresh.respond({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: 'late-token', refresh_token: 'late-refresh', user, expires_in: 3600 }) });
  await page.waitForFunction(() => window.__lateRefreshStatus === 409);
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('cyphward-session')).user.id), 'other-user');
  assert.deepEqual(errors, []);
  console.log('PASS: onboarding/DNS/mobile navigation, bootstrap and refresh outages, invitation preservation, concurrent refresh and late account-switch response');
} finally {
  if (browser) await browser.close();
  await server.close();
}
