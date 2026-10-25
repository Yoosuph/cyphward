// Isolated layout and filtering checks; no live customer data or writes.
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import puppeteer from 'puppeteer-core';
import { fileURLToPath } from 'node:url';
import { user, org, domain, overview, freshQuestions, members, DISCLAIMER, ORG_ZONE } from './lib/compliance-fixtures.mjs';
const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), server: { host: '127.0.0.1', port: 0 } });
let browser;
try {
 await server.listen(); browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
 const page = await browser.newPage(); const errors = []; page.on('pageerror', e => errors.push(e.message));
 await page.evaluateOnNewDocument(user => {
  localStorage.setItem('cyphward-session', JSON.stringify({ access_token: 'mock', refresh_token: 'mock', user, _expires_at: Date.now() + 3600000 }));
  localStorage.setItem(`cyphward-tour-v1:${user.id}`, 'done'); localStorage.setItem('cyphward-cookie-consent', 'accepted'); localStorage.setItem('cyphward-welcome-sent', user.id);
 }, user);
 let failQuestions = false;
 await page.setRequestInterception(true); page.on('request', r => {
  const p = new URL(r.url()).pathname; if (!p.startsWith('/api/')) return void r.continue();
  if (failQuestions && p.endsWith('/compliance/questionnaire')) return void r.respond({ status:500, contentType:'application/json', body:'{"detail":"Unavailable"}' });
  const body = p.endsWith('/auth/bootstrap') ? { user, email_verified: true, memberships: [{ org, role: 'owner', domains: [domain] }] }
   : p.endsWith('/compliance/overview') ? overview('growth') : p.endsWith('/compliance/questionnaire') ? { disclaimer: DISCLAIMER, version: 'fixture', display_timezone: ORG_ZONE, answered: 1, questions: freshQuestions() }
   : p.endsWith('/members') ? members : p.endsWith('/domains') ? [domain] : p.includes('/notifications') ? { notifications: [], unread_count: 0 } : {};
  void r.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
 });
 for (const width of [1440, 390, 320]) {
  await page.setViewport({ width, height: 1000 }); await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/comply`, { waitUntil: 'networkidle0' });
  await page.waitForSelector('[data-testid="readiness-line"]');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  assert.ok(await page.$$eval('[role="tab"]', tabs => tabs.every(tab => {
    const box = tab.getBoundingClientRect();
    return box.left >= 0 && box.right <= innerWidth && box.height >= 44;
  })), `${width}: every compliance section is visible and has a touch target`);
  await page.screenshot({ path: `/tmp/compliance-after-${width}.png`, fullPage: true });
  await page.type('[aria-label="Search requirements"]', 'anti-spoofing');
  assert.equal(await page.$$eval('[data-requirement-row]', all => all.length), 1);
  await page.select('[aria-label="Filter by evidence status"]', 'present');
  await page.waitForSelector('[data-testid="requirements-empty"]');
  await page.click('[data-testid="clear-requirement-filters"]');
  assert.ok(await page.$$eval('[data-requirement-row]', all => all.length) > 1);
  await page.select('[aria-label="Filter by requirement group"]', 'security');
  assert.equal(await page.$$eval('[data-requirement-group]', all => all.length), 1);
  await page.click('[data-testid="clear-requirement-filters"]');
  await page.click('[aria-label="Filter requirements: gaps"]');
  assert.equal(await page.$eval('[aria-label="Filter by evidence status"]', select => select.value), 'gap');
  await page.click('[data-testid="clear-requirement-filters"]');
  await page.click('[data-requirement-row] button[aria-expanded]');
  assert.ok(await page.$eval('[data-requirement-row] button[aria-expanded="true"]', button => Boolean(document.getElementById(button.getAttribute('aria-controls')))), 'requirement details are associated with the trigger');
  await page.focus('#tab-readiness'); await page.keyboard.press('ArrowRight');
  await page.waitForSelector('#tab-questions[aria-selected="true"]');
  assert.equal(await page.$eval('#tab-questions', el => el.getAttribute('aria-selected')), 'true');
  assert.equal(new URL(page.url()).searchParams.get('section'), 'questions');
  await page.reload({ waitUntil:'networkidle0' });
  await page.waitForSelector('#tab-questions[aria-selected="true"]');
  await page.goBack({ waitUntil:'networkidle0' });
  await page.waitForSelector('#tab-readiness[aria-selected="true"]');
  await page.goForward({ waitUntil:'networkidle0' });
  await page.waitForSelector('[data-testid="questionnaire"]');
  failQuestions = true;
  await page.click('[aria-label="Refresh"]');
  await page.waitForFunction(() => document.body.textContent.includes('Your questions were not refreshed'));
  assert.ok(await page.$('[data-testid="questionnaire"]'), 'a failed refresh preserves the existing questionnaire');
  failQuestions = false;
 }
 assert.deepEqual(errors, []); console.log('PASS: compliance layout, search, combined filters, empty/reset and keyboard tabs at 1440/390/320px');
} finally { await browser?.close(); await server.close(); }
