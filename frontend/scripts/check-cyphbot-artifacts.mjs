// Exercises the actual local app + backend + owned sample DB, never a deployed URL.
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import { mkdtemp, readdir, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const origin = process.env.CYPHBOT_LAB_URL || 'http://127.0.0.1:5173';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(origin).hostname), 'Only a local lab may be tested');
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
try {
  const page = await browser.newPage();
  page.setDefaultTimeout(100000);
  const downloadPath = await mkdtemp(join(tmpdir(), 'cyphbot-artifact-exports-'));
  const cdp = await page.createCDPSession();
  await cdp.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath });
  const downloaded = async suffix => {
    const start = Date.now();
    while (Date.now() - start < 10000) {
      const filename = (await readdir(downloadPath)).find(n => n.endsWith(suffix));
      if (filename) return readFile(join(downloadPath, filename));
      await new Promise(r => setTimeout(r, 100));
    }
    throw new Error(`Missing ${suffix} download`);
  };
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', msg => { if (msg.type() === 'error') process.stderr.write(`browser: ${msg.text()}\n`); });
  await page.setViewport({ width: 1440, height: 1000 });
  await page.evaluateOnNewDocument(() => {
    localStorage.setItem('cyphward-theme', 'light');
    localStorage.setItem('cyphward-cookie-consent', 'accepted');
  });
  const clickText = async text => {
    const found = await page.evaluate(text => {
      const el = [...document.querySelectorAll('button')].find(b => b.textContent.includes(text));
      el?.click(); return !!el;
    }, text);
    assert.ok(found, `button ${text}`);
  };
  await page.goto(`${origin}/login`, { waitUntil: 'networkidle0' });
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.includes('Try the demo')));
  await clickText('Try the demo');
  await page.waitForFunction(() => location.pathname === '/overview', { timeout: 20000 });
  // Test charts under a policy that explicitly omits unsafe-eval.
  await page.evaluate(() => {
    const meta = document.createElement('meta'); meta.httpEquiv = 'Content-Security-Policy';
    meta.content = "script-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'self'";
    document.head.append(meta);
  });
  await page.click('[aria-label="Open CyphBot"]');
  await page.waitForFunction(() => {
    const el = document.querySelector('.cyphbot-window');
    return el?.classList.contains('is-visible') && Number(getComputedStyle(el).opacity) === 1;
  });
  assert.match(await page.$eval('.cyphbot-window', el => getComputedStyle(el).transitionProperty), /transform/);
  let lastSend = 0;
  const send = async text => {
    await new Promise(r => setTimeout(r, Math.max(0, 35000 - (Date.now() - lastSend))));
    lastSend = Date.now();
    const count = await page.$$eval('[data-chat-role="assistant"]', list => list.length);
    await page.waitForSelector('textarea[placeholder="Ask CyphBot..."]', { visible: true });
    await page.type('textarea[placeholder="Ask CyphBot..."]', text);
    await page.keyboard.press('Enter');
    await page.waitForFunction(count => document.querySelectorAll('[data-chat-role="assistant"]').length > count && !document.body.innerText.includes('CyphBot is thinking'), {}, count);
  };
  const openLatestReport = () => page.$$eval('[data-open-report]', cards => cards.at(-1).click());
  await send('Generate a report with charts about the performance of our organisation over the last 90 days');
  assert.equal(await page.$('[aria-label="Organization performance report"]'), null, 'Report must wait for a preview click');
  await openLatestReport();
  await page.waitForSelector('[aria-label="Organization performance report"] svg.marks');
  await page.waitForFunction(() => document.querySelectorAll('svg.marks').length === 3);
  assert.equal(await page.$$eval('svg.marks', all => all.length), 3);
  await page.waitForFunction(() => !document.body.innerText.includes('CyphBot is thinking'));
  let text = await page.$eval('[aria-label="Organization performance report"]', el => el.innerText);
  assert.match(text, /SAMPLE DATA/);
  assert.match(text, /7 unresolved findings/);
  assert.match(text, /3 assessments completed/);
  assert.equal(await page.evaluate(() => window.VEGA_DEBUG), undefined);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: '/tmp/cyphbot-artifact-desktop.png' });
  // Tooltips must appear over actual marks, not just in a header readout.
  const inspect = async selector => {
    await page.waitForSelector(selector);
    const marks = await page.$$(selector);
    for (const mark of marks) {
      const box = await mark.boundingBox();
      if (box && box.height > 2 && box.width > 2) {
        await mark.evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        await mark.hover();
        await page.waitForSelector('[role="tooltip"]', { visible: true });
        assert.match(await page.$eval('[role="tooltip"]', el => el.innerText), /Score \/ 100|Findings/);
        return;
      }
    }
    throw new Error(`No hoverable marks: ${selector}`);
  };
  await inspect('[data-chart-id="scan-scores"] .mark-symbol path');
  assert.match(await page.$eval('[role="tooltip"]', el => el.innerText), /2026/);
  await page.screenshot({ path: '/tmp/cyphbot-artifact-tooltip.png' });
  await inspect('[data-chart-id="severity"] .mark-rect path');
  await inspect('[data-chart-id="resolution"] .mark-arc path');
  await page.mouse.move(2, 2);
  // An explanatory follow-up mentioning 'report' must be a live AI answer,
  // not another copy of the canned report summary or another artifact version.
  await send('Explain why this report cannot establish that our organisation is fully secure. Do not create a new report.');
  await page.waitForFunction(() => !document.body.innerText.includes('CyphBot is thinking'), { timeout: 60000 });
  const answer = await page.$$eval('[data-chat-role="assistant"]', entries => entries.at(-1).innerText);
  assert.match(answer, /Google Gemini/);
  assert.ok(answer.length > 100);
  assert.ok(!answer.includes('7 unresolved findings and 4 recorded as resolved. 3 assessments completed'));
  assert.equal(await page.$$eval('[aria-label="Report version"] option', all => all.length), 1);
  // Exit animation keeps the drawer mounted until it finishes, then reopens
  // the same conversation and report.
  await page.click('[aria-label="Minimize Chatbot"]');
  await page.waitForFunction(() => {
    const el = document.querySelector('.cyphbot-window'); return el && !el.classList.contains('is-visible');
  });
  await page.waitForFunction(() => !document.querySelector('.cyphbot-window'));
  await page.click('[aria-label="Open CyphBot"]');
  await page.waitForFunction(() => document.querySelector('.cyphbot-window')?.classList.contains('is-visible'));
  await page.click('[title="Download complete report JSON"]');
  const exported = JSON.parse((await downloaded('.json')).toString());
  assert.equal(exported.version, 1);
  assert.equal(exported.charts.length, 3);
  await page.click('[title="Download Recorded assessment scores as PNG"]');
  const png = await downloaded('.png');
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  const validation = await page.evaluate(async exported => {
    const { reportArtifactSchema, csvCell } = await import('/src/lib/reportArtifacts.ts');
    const withURL = structuredClone(exported); withURL.charts[0].url = 'https://example.test/exfil';
    const withHTML = structuredClone(exported); withHTML.charts[0].formatter = '<img onerror=alert(1)>';
    const withInfinity = structuredClone(exported); withInfinity.charts[0].points[0].value = Infinity;
    return {
      valid: reportArtifactSchema.safeParse(exported).success,
      url: reportArtifactSchema.safeParse(withURL).success,
      html: reportArtifactSchema.safeParse(withHTML).success,
      infinity: reportArtifactSchema.safeParse(withInfinity).success,
      formula: csvCell('=HYPERLINK("https://example.test")'),
    };
  }, exported);
  assert.deepEqual({ valid: validation.valid, url: validation.url, html: validation.html, infinity: validation.infinity }, { valid: true, url: false, html: false, infinity: false });
  assert.ok(validation.formula.startsWith('"\'='));
  await send('Use a bar chart instead for the last 30 days');
  await openLatestReport();
  await page.waitForFunction(() => document.querySelector('[aria-label="Report version"]')?.value === '2');
  await page.waitForSelector('svg.marks');
  text = await page.$eval('[aria-label="Organization performance report"]', el => el.innerText);
  assert.match(text, /30 DAYS/);
  assert.match(text, /1 assessments completed/);
  await page.select('[aria-label="Report version"]', '1');
  assert.match(await page.$eval('[aria-label="Organization performance report"]', el => el.innerText), /90 DAYS/);
  // Revising an earlier version appends V3, preserves V2.
  await send('Refresh this report');
  await openLatestReport();
  await page.waitForFunction(() => document.querySelector('[aria-label="Report version"]')?.value === '3');
  assert.equal(await page.$$eval('[aria-label="Report version"] option', all => all.length), 3);
  await page.setViewport({ width: 390, height: 844 });
  await page.waitForFunction(() => {
    const panel = document.querySelector('[aria-label="Organization performance report"]').getBoundingClientRect();
    return panel.width > 300 && panel.right <= innerWidth && panel.width <= innerWidth - 16;
  });
  await page.waitForFunction(() => [...document.querySelectorAll('svg.marks')].length === 3 && [...document.querySelectorAll('svg.marks')].every(el => el.getBoundingClientRect().right <= innerWidth));
  await page.screenshot({ path: '/tmp/cyphbot-artifact-mobile.png' });
  const touchPoint = await page.waitForSelector('[data-chart-id="scan-scores"] .mark-symbol path, [data-chart-id="scan-scores"] .mark-rect path', { visible: true });
  await touchPoint.evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const touchBox = await touchPoint.boundingBox();
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
  await page.touchscreen.tap(touchBox.x + touchBox.width / 2, touchBox.y + touchBox.height / 2);
  await page.waitForSelector('[role="tooltip"]', { visible: true });
  assert.match(await page.$eval('[role="tooltip"]', el => el.innerText), /Score \/ 100/);
  const overflow = await page.evaluate(() => [...document.querySelectorAll('body *')].filter(el => { const r = el.getBoundingClientRect(); return r.width && (r.left < -1 || r.right > innerWidth + 1); }).slice(0, 12).map(el => ({ tag: el.tagName, cls: String(el.className).slice(0, 100), width: el.getBoundingClientRect().width, left: el.getBoundingClientRect().left })));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, JSON.stringify(overflow));
  await page.click('[role="tab"][aria-selected="false"]');
  await page.waitForSelector('[data-report-scroll] table');
  assert.equal(await page.$$eval('[data-report-scroll] table', all => all.length), 5);
  await page.click('[title="Download Recorded assessment scores CSV"]');
  assert.match((await downloaded('.csv')).toString(), /Score \/ 100/);
  await page.screenshot({ path: '/tmp/cyphbot-artifact-mobile-data.png' });
  await page.click('[aria-label="Back to chat"]');
  await send('Show the last 7 days');
  await openLatestReport();
  await page.waitForFunction(() => document.querySelector('[aria-label="Report version"]')?.value === '4');
  assert.match(await page.$eval('[aria-label="Organization performance report"]', el => el.innerText), /7 DAYS/);
  await page.setViewport({ width: 320, height: 740 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.click('[aria-label="Back to chat"]');
  // Simulate a failed upstream AI request: show the error once, without
  // silently retrying through the non-streaming canned response.
  let failedCalls = 0;
  await page.setRequestInterception(true);
  page.on('request', req => {
    if (req.url().endsWith('/ai/chat/stream')) {
      failedCalls++;
      return req.respond({ status: 200, contentType: 'text/event-stream', body: 'data: {"error":"The AI provider is rate-limiting requests. Please retry shortly.","done":true}\n\n' });
    }
    if (req.url().endsWith('/ai/chat')) failedCalls++;
    return req.continue();
  });
  await send('How can I interpret the findings?');
  await page.waitForFunction(() => document.body.innerText.includes('AI provider is rate-limiting requests'));
  assert.equal(failedCalls, 1);
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  await page.waitForFunction(() => getComputedStyle(document.querySelector('.cyphbot-window')).transitionDuration === '0s');
  assert.deepEqual(errors, []);
  console.log('PASS: live AI explanation without report regeneration; line/bar/donut hover tooltips; enter/exit and reduced motion; explicit AI errors; report revisions; mobile 390/320; CSP; PNG/JSON/CSV exports; rejected unsafe payloads.');
} finally { await browser.close(); }
