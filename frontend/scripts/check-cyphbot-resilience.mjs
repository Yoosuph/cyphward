// Actual local login with controlled browser streams; no model requests.
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
const origin = process.env.CYPHBOT_LAB_URL || 'http://127.0.0.1:5173';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(origin).hostname));
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
let page;
try {
  page = await browser.newPage(); page.setDefaultTimeout(20000);
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.setViewport({ width: 1440, height: 1000 });
  await page.evaluateOnNewDocument(() => {
    localStorage.setItem('cyphward-cookie-consent', 'accepted');
    window.__lab = { requests: [], streams: [], cancelled: 0 };
    const original = window.fetch;
    window.fetch = async (url, options) => {
      if (!String(url).endsWith('/ai/chat/stream')) return original(url, options);
      const record = { body: JSON.parse(options.body), org: options.headers['X-Organization-Id'], aborted: false };
      window.__lab.requests.push(record);
      const stream = new ReadableStream({
        start(controller) {
          window.__lab.streams.push(controller);
          options.signal.addEventListener('abort', () => { record.aborted = true; try { controller.error(new DOMException('Aborted', 'AbortError')); } catch {} }, { once: true });
        },
        cancel() { window.__lab.cancelled++; },
      });
      return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
    };
    window.__emit = (index, event) => window.__lab.streams[index].enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
  });
  await page.goto(`${origin}/login`, { waitUntil: 'networkidle0' });
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.includes('Try the demo')));
  await page.evaluate(() => [...document.querySelectorAll('button')].find(b => b.textContent.includes('Try the demo')).click());
  await page.waitForFunction(() => location.pathname === '/overview'); await page.click('[aria-label="Open CyphBot"]');
  const input = 'textarea[placeholder="Ask CyphBot..."]';
  await page.waitForSelector(input, { visible: true });
  const send = async text => { await page.type(input, text); await page.keyboard.press('Enter'); };
  const emit = (index, event) => page.evaluate((index, event) => window.__emit(index, event), index, event);
  const waitRequests = count => page.waitForFunction(count => window.__lab.requests.length === count, {}, count);

  await page.type(input, 'Build a report');
  await page.$eval(input, el => { el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); });
  await waitRequests(1); await new Promise(r => setTimeout(r, 100));
  assert.equal(await page.evaluate(() => window.__lab.requests.length), 1, 'Rapid Enter must not duplicate a request');
  const org = await page.evaluate(() => window.__lab.requests[0].org);
  const artifact = {
    schema_version: 1, id: 'e1ac0000-0000-4000-8000-000000000002', version: 1, org_id: org,
    title: 'Recovery display fixture', generated_at: new Date().toISOString(), days: 90, chart_style: 'line', sample: true,
    summary: 'Display fixture, not production activity.', severities: [], metrics: [], tables: [], limitations: [], sources: [],
    charts: [{ id: 'recovery', metric: 'assessment_scores', kind: 'line', x_type: 'temporal', title: 'Recorded scores', unit: 'Score / 100', note: 'Fixture', points: [{ label: '2026-10-01', value: 40 }, { label: '2026-10-20', value: 70 }] }],
  };
  await emit(0, { type: 'artifact', artifact });
  await emit(0, { token: 'Partial evidence explanation.', done: false });
  await page.waitForSelector('[data-open-report]');
  assert.equal(await page.$('[aria-label="Organization performance report"]'), null);
  await emit(0, { error: 'Provider unavailable for this test.', done: true });
  await page.waitForSelector('[role="alert"]');
  assert.match(await page.$eval('[data-chat-scroll]', el => el.innerText), /Partial evidence explanation/);
  assert.match(await page.$eval('[role="alert"]', el => el.innerText), /report is ready/);
  assert.equal(await page.evaluate(() => window.__lab.cancelled), 1, 'Failed streams must be closed');
  await page.evaluate(() => [...document.querySelectorAll('button')].find(b => b.textContent.includes('Try again')).click());
  await waitRequests(2);
  assert.equal(await page.$$eval('[data-chat-role="user"]', list => list.length), 1, 'Retry must reuse the turn');
  assert.deepEqual(await page.evaluate(() => window.__lab.requests[1].body.history), []);
  await emit(1, { token: 'Recovered explanation.', done: false }); await emit(1, { done: true, sources: [], actions: [] });
  await page.waitForFunction(() => !document.querySelector('[aria-label="Stop response"]'));
  assert.equal(await page.$$eval('[data-open-report]', list => list.length), 1, 'Ready report survives retry');

  await send('Analyse slowly'); await waitRequests(3);
  await emit(2, { token: 'Stopped partial response.', done: false });
  await page.waitForFunction(() => document.body.innerText.includes('Stopped partial response.'));
  await page.click('[aria-label="Stop response"]');
  await page.waitForFunction(() => document.body.innerText.includes('Activity · stopped'));
  assert.equal(await page.evaluate(() => window.__lab.requests[2].aborted), true);
  assert.match(await page.$eval('[data-chat-scroll]', el => el.innerText), /Stopped partial response/);
  await send('Another question'); await waitRequests(4);
  assert.ok(!(await page.evaluate(() => window.__lab.requests[3].body.history)).some(h => h.content.includes('Stopped partial response')));
  await emit(3, { token: 'Recorded observation. '.repeat(250), done: false });
  await page.waitForFunction(() => document.querySelector('[data-chat-scroll]').scrollHeight > document.querySelector('[data-chat-scroll]').clientHeight + 300);
  await page.$eval('[data-chat-scroll]', el => { el.scrollTop = 0; el.dispatchEvent(new Event('scroll')); });
  await page.waitForSelector('[aria-label="Jump to latest message"]');
  await emit(3, { token: ' More recorded observations.', done: false });
  assert.ok(await page.$eval('[data-chat-scroll]', el => el.scrollTop) < 10, 'Reading older text must not force scroll');
  await page.click('[aria-label="Jump to latest message"]');
  await page.waitForFunction(() => { const el = document.querySelector('[data-chat-scroll]'); return el.scrollHeight - el.scrollTop - el.clientHeight < 80; });
  await emit(3, { done: true, sources: [], actions: [] });
  await page.waitForFunction(() => !document.querySelector('[aria-label="Stop response"]'));

  await page.type(input, 'Composition');
  await page.$eval(input, el => el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true })));
  assert.equal(await page.evaluate(() => window.__lab.requests.length), 4, 'IME confirmation must not submit');
  await page.focus(input); await page.keyboard.down('Shift'); await page.keyboard.press('Enter'); await page.keyboard.up('Shift');
  await page.type(input, 'Second line');
  assert.ok(await page.$eval(input, el => el.clientHeight) > 40, 'Composer should grow');
  await page.focus('[title="Reset Conversation"]'); await page.keyboard.down('Shift'); await page.keyboard.press('Tab'); await page.keyboard.up('Shift');
  assert.equal(await page.evaluate(() => document.querySelector('[aria-label="CyphBot chat"]').contains(document.activeElement)), true);
  await page.keyboard.press('Escape'); await page.waitForFunction(() => !document.querySelector('.cyphbot-window'));
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Open CyphBot');
  await page.click('[aria-label="Open CyphBot"]'); await page.setViewport({ width: 390, height: 844 });
  await page.waitForFunction(() => Math.abs(document.querySelector('.cyphbot-window').getBoundingClientRect().width - Math.min(340, innerWidth - 24)) < 1);
  const draft = await page.$eval(input, el => el.value);
  await page.screenshot({ path: '/tmp/cyphbot-mobile-compact.png' });
  await page.click('[aria-label="Enter full screen"]');
  await page.waitForFunction(() => Math.abs(document.querySelector('.cyphbot-window').getBoundingClientRect().width - (innerWidth - 16)) < 1);
  assert.equal(await page.$eval(input, el => el.value), draft);
  await page.screenshot({ path: '/tmp/cyphbot-mobile-fullscreen.png' });
  await page.click('[aria-label="Exit full screen"]');
  await page.waitForFunction(() => Math.abs(document.querySelector('.cyphbot-window').getBoundingClientRect().width - Math.min(340, innerWidth - 24)) < 1);
  await page.$eval('[data-chat-scroll]', el => {
    const start = new Event('touchstart', { bubbles: true }); Object.defineProperty(start, 'touches', { value: [{ clientY: 100 }] }); el.dispatchEvent(start);
    const end = new Event('touchend', { bubbles: true }); Object.defineProperty(end, 'changedTouches', { value: [{ clientY: 250 }] }); el.dispatchEvent(end);
  });
  assert.ok(await page.$('.cyphbot-window'), 'Scrolling gesture must not dismiss chat');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: '/tmp/cyphbot-fluid-mobile.png' });
  await page.setViewport({ width: 1440, height: 1000 });
  await page.screenshot({ path: '/tmp/cyphbot-fluid-desktop.png' });
  assert.deepEqual(errors, []);
  console.log('PASS: duplicate-submit guard; report and partial answer survive failure; retry reuses turn; stop aborts; clean history; smart scroll; IME/multiline composer; focus/Escape; mobile swipe and layout. No model calls.');
} catch (error) {
  if (page) { console.error((await page.$eval('body', el => el.innerText)).slice(-2200)); await page.screenshot({ path: '/tmp/cyphbot-resilience-failure.png' }); }
  throw error;
} finally { await browser.close(); }
