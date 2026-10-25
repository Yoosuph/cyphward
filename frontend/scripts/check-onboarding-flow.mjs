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
  // Native browser dialogs are never acceptable; the app has a branded confirm.
  page.on('dialog', dialog => { errors.push(`native dialog: ${dialog.message()}`); void dialog.dismiss(); });
  const user = { id: 'new-user', email: 'new@example.test', full_name: 'New User' };
  const org = { id: 'new-org', name: 'New Workspace', slug: 'new-workspace', plan: 'growth' };
  let domains = [];
  let recentScans = [];
  const deleteCalls = [];
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
    }, subscores: [], factors: [], recent_scans: recentScans,
  });
  await page.setRequestInterception(true);
  page.on('request', request => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/')) return void request.continue();
    if (request.method() === 'DELETE' && /\/domains\/[^/]+$/.test(url.pathname)) {
      const id = url.pathname.split('/').pop();
      deleteCalls.push(id);
      domains = domains.filter(d => d.id !== id);
      return void request.respond({ status: 200, contentType: 'application/json', body: JSON.stringify({ deleted: true }) });
    }
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
    // The tour has its own section below; elsewhere it must not cover the page.
    if (!sessionStorage.getItem('tour-test')) localStorage.setItem(`cyphward-tour-v1:${user.id}`, 'done');
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
  await page.waitForFunction(() => document.body.textContent.includes('Get your first security score'));
  assert.equal(new URL(page.url()).pathname, '/overview');
  assert.ok(!await page.evaluate(() => document.body.textContent.includes('Old Workspace')));
  assert.equal(await page.evaluate(() => localStorage.getItem('cyphward-org-id')), org.id);
  assert.ok(await page.evaluate(() => document.body.textContent.includes('Across 0 domains')));
  assert.ok(await page.evaluate(() => document.body.textContent.includes('Verification needed')));

  domains = [{ id: 'pending-domain', org_id: org.id, domain: 'mycompany.ng',
    verification_status: 'pending', verification_token: 'secret-token', created_at: '2026-10-11T00:00:00Z' }];
  await page.goto(`${origin}/overview`);
  await page.waitForFunction(() => document.body.textContent.includes('Add one DNS TXT record for mycompany.ng'));
  assert.equal(new URL(page.url()).pathname, '/overview');

  // First-run tour: auto-starts once, spotlights real UI, Esc skips, replayable.
  await page.setViewport({ width: 1280, height: 900 });
  await page.evaluate(() => { sessionStorage.setItem('tour-test', '1'); localStorage.removeItem('cyphward-tour-v1:new-user'); });
  await page.goto(`${origin}/overview`);
  await page.waitForSelector('[role="dialog"][aria-labelledby="tour-title"]', { visible: true });
  const tourTitle = () => page.evaluate(() => document.querySelector('#tour-title')?.textContent);
  assert.equal(await tourTitle(), 'Welcome to Cyphward');
  assert.equal(await page.evaluate(() => document.activeElement?.textContent), 'START TOUR');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.querySelector('#tour-title')?.textContent === 'Your setup checklist');
  const spotCovers = selector => page.evaluate(sel => {
    const spot = document.querySelector('.tour-spot')?.getBoundingClientRect();
    const target = document.querySelector(sel)?.getBoundingClientRect();
    return !!spot && !!target && spot.left <= target.left && spot.right >= target.right && spot.top <= target.top + 1 && spot.bottom >= target.bottom - 1;
  }, selector);
  await page.waitForFunction(() => !!document.querySelector('.tour-spot'));
  await new Promise(resolve => setTimeout(resolve, 400)); // spotlight moves over 250ms
  assert.ok(await spotCovers('[data-tour="checklist"]'), 'Checklist step spotlights the checklist');
  await page.keyboard.press('ArrowRight');
  await page.waitForFunction(() => document.querySelector('#tour-title')?.textContent === 'Domains');
  await new Promise(resolve => setTimeout(resolve, 400));
  assert.ok(await spotCovers('[data-tour="nav-domains"]'), 'Domains step spotlights the sidebar item');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => !document.querySelector('[aria-labelledby="tour-title"]'));
  assert.equal(await page.evaluate(() => localStorage.getItem('cyphward-tour-v1:new-user')), 'skipped');
  await page.goto(`${origin}/overview`);
  await page.waitForSelector('[data-tour="checklist"]');
  await new Promise(resolve => setTimeout(resolve, 1500));
  assert.ok(!await page.$('[aria-labelledby="tour-title"]'), 'A skipped tour does not start again');
  await page.evaluate(() => [...document.querySelectorAll('button')].find(button => button.textContent.includes('TAKE THE TOUR')).click());
  await page.waitForFunction(() => document.querySelector('#tour-title')?.textContent === 'Welcome to Cyphward');
  await page.setViewport({ width: 390, height: 844 });
  for (let i = 0; i < 2; i++) await page.keyboard.press('ArrowRight');
  await page.waitForFunction(() => document.querySelector('#tour-title')?.textContent === 'Domains');
  await page.waitForFunction(() => document.querySelector('#tour-body')?.textContent.includes('tap Menu to find Domains'));
  await new Promise(resolve => setTimeout(resolve, 400)); // card glides to its new place over 250ms
  assert.ok(await page.evaluate(() => {
    const card = document.querySelector('.tour-card').getBoundingClientRect();
    return card.left >= 0 && card.right <= window.innerWidth && document.documentElement.scrollWidth <= window.innerWidth;
  }), 'Tour card fits a 390px screen');
  await page.keyboard.press('Escape');
  await page.evaluate(() => { sessionStorage.removeItem('tour-test'); localStorage.setItem('cyphward-tour-v1:new-user', 'done'); });
  await page.setViewport({ width: 800, height: 600 });

  // Regression (15 Oct): an established owner with completed scans must never get
  // the tour unprompted, and START SCAN must open the scan dialog.
  const previousDomains = domains;
  domains = [
    { id: 'verified-a', org_id: org.id, domain: 'cyphward.example', verification_status: 'verified', created_at: '2026-10-01T00:00:00Z' },
    { id: 'pending-b', org_id: org.id, domain: 'kansadco.example', verification_status: 'pending', verification_token: 't', created_at: '2026-10-14T00:00:00Z' },
  ];
  recentScans.push({ id: 'done-scan', domain: 'cyphward.example', status: 'completed', score: 35.2, stage_progress: {}, created_at: '2026-10-14T06:00:00Z' });
  await page.setViewport({ width: 1280, height: 900 });
  await page.evaluate(() => { sessionStorage.setItem('tour-test', '1'); localStorage.removeItem('cyphward-tour-v1:new-user'); });
  await page.goto(`${origin}/overview`);
  await page.waitForSelector('[data-tour="start-scan"]');
  await new Promise(resolve => setTimeout(resolve, 1800));
  assert.ok(!await page.$('[aria-labelledby="tour-title"]'), 'No unprompted tour for a workspace with completed scans');
  await page.click('[data-tour="start-scan"]');
  await page.waitForFunction(() => document.body.textContent.includes('Only your verified domains'));

  // Removing a domain uses the branded confirm: Cancel sends nothing, Remove sends one DELETE.
  await page.goto(`${origin}/domains`);
  await page.waitForSelector('button[aria-label="Remove kansadco.example"]');
  await page.click('button[aria-label="Remove kansadco.example"]');
  await page.waitForFunction(() => document.body.textContent.includes('Remove kansadco.example?'));
  await page.waitForFunction(() => document.activeElement?.textContent.trim().toUpperCase() === 'CANCEL', { timeout: 3000 }); // destructive confirm focuses Cancel
  await page.keyboard.press('Enter');
  await new Promise(resolve => setTimeout(resolve, 300));
  assert.deepEqual(deleteCalls, []);
  await page.click('button[aria-label="Remove kansadco.example"]');
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.trim().toUpperCase() === 'REMOVE DOMAIN'));
  await page.evaluate(() => [...document.querySelectorAll('button')].find(b => b.textContent.trim().toUpperCase() === 'REMOVE DOMAIN').click());
  await page.waitForFunction(() => document.body.textContent.includes('kansadco.example removed'));
  assert.deepEqual(deleteCalls, ['pending-b']);
  domains = previousDomains;
  recentScans.length = 0;
  await page.evaluate(() => { sessionStorage.removeItem('tour-test'); localStorage.setItem('cyphward-tour-v1:new-user', 'done'); });
  await page.setViewport({ width: 800, height: 600 });

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
  // At 320px the fixed cookie notice can cover this button; click it directly.
  await page.$eval('button[aria-label="Copy DNS host name"]', button => button.click());
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
  await page.waitForFunction(() => document.body.textContent.includes('Get your first security score'));
  assert.equal(new URL(page.url()).searchParams.get('invite'), 'offline-invite');

  // An expired access token plus a refresh outage is not a revoked session.
  refreshUnavailable = true;
  await page.goto(`${origin}/overview?expired=1`);
  await page.waitForFunction(() => document.body.textContent.includes('Reconnect to your workspace'));
  assert.ok(await page.evaluate(() => !!localStorage.getItem('cyphward-session')));
  refreshUnavailable = false;
  await page.evaluate(() => [...document.querySelectorAll('button')].find(button => button.textContent.includes('RETRY WORKSPACE')).click());
  await page.waitForFunction(() => document.body.textContent.includes('Get your first security score'));

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
  console.log('PASS: onboarding/DNS/mobile navigation, setup checklist, first-run tour (auto-start, spotlight, skip, replay, 390px, never for established workspaces), branded delete confirm, no native dialogs, bootstrap and refresh outages, invitation preservation, concurrent refresh and late account-switch response');
} finally {
  if (browser) await browser.close();
  await server.close();
}
