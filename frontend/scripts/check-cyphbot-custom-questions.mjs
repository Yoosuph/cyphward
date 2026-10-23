// Real model + real local API + sample database acceptance checks.
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';

const origin = process.env.CYPHBOT_LAB_URL || 'http://127.0.0.1:5173';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(origin).hostname));
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
let page;
try {
  page = await browser.newPage();
  page.setDefaultTimeout(100000);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.setViewport({ width: 1440, height: 1000 });
  await page.evaluateOnNewDocument(() => {
    localStorage.setItem('cyphward-cookie-consent', 'accepted');
    localStorage.setItem('cyphward-theme', 'light');
    window.__labReports = [];
    const originalFetch = window.fetch;
    window.fetch = async (...args) => {
      const response = await originalFetch(...args);
      if (response.url.endsWith('/ai/chat/stream')) {
        response.clone().text().then(body => {
          for (const line of body.split('\n')) {
            if (!line.startsWith('data:')) continue;
            const event = JSON.parse(line.slice(5));
            if (event.artifact) window.__labReports.push(event.artifact);
          }
        });
      }
      return response;
    };
  });
  await page.goto(`${origin}/login`, { waitUntil: 'networkidle0' });
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.includes('Try the demo')));
  await page.evaluate(() => [...document.querySelectorAll('button')].find(b => b.textContent.includes('Try the demo')).click());
  await page.waitForFunction(() => location.pathname === '/overview');
  await page.click('[aria-label="Open CyphBot"]');
  let lastSend = 0;
  const send = async message => {
    // Two model calls may serve one report. Pace this live acceptance suite
    // for the provider's development quota; this is not application retry logic.
    await new Promise(r => setTimeout(r, Math.max(0, 35000 - (Date.now() - lastSend))));
    lastSend = Date.now();
    const count = await page.$$eval('[data-chat-role="assistant"]', list => list.length);
    await page.waitForSelector('textarea[placeholder="Ask CyphBot..."]', { visible: true });
    await page.type('textarea[placeholder="Ask CyphBot..."]', message);
    await page.keyboard.press('Enter');
    await page.waitForFunction(count => document.querySelectorAll('[data-chat-role="assistant"]').length > count && !document.body.innerText.includes('CyphBot is thinking'), {}, count);
  };
  const currentReport = () => page.evaluate(() => window.__labReports.at(-1));
  const openLatestReport = () => page.$$eval('[data-open-report]', cards => cards.at(-1).click());
  await send('Draw ONLY one line graph showing the performance of my organisation for the last 90 days. No summary cards or supporting tables.');
  assert.equal(await page.$('[aria-label="Organization performance report"]'), null);
  await openLatestReport();
  await page.waitForFunction(() => document.querySelectorAll('[data-chart-id] svg.marks').length === 1);
  await page.waitForFunction(() => document.querySelector('[aria-label="Report version"]')?.value === '1');
  // Response observer can complete just after the UI consumes the last chunk.
  await page.waitForFunction(() => window.__labReports.length === 1);
  assert.deepEqual((await currentReport()).charts.map(c => [c.metric, c.kind]), [['assessment_scores', 'line']]);
  assert.deepEqual((await currentReport()).metrics, []);
  assert.deepEqual((await currentReport()).tables, []);
  await page.screenshot({ path: '/tmp/cyphbot-custom-line-only.png' });
  await send('How many assessments completed in the last 14 days? Give the number and explain it briefly. Answer in chat without creating or modifying the report.');
  let answer = await page.$$eval('[data-chat-role="assistant"]', list => list.at(-1).innerText);
  assert.match(answer, /\b1\b|\bone\b/i);
  assert.match(answer, /14|fourteen/i);
  assert.match(answer, /Google Gemini/);
  assert.equal(await page.$eval('[aria-label="Report version"]', el => el.value), '1');
  await send('Keep my existing line graph and add a bar chart of completed assessment activity beside it. Keep the 90-day report period.');
  await openLatestReport();
  await page.waitForFunction(() => document.querySelector('[aria-label="Report version"]')?.value === '2');
  await page.waitForFunction(() => document.querySelectorAll('[data-chart-id] svg.marks').length === 2);
  await page.waitForFunction(() => window.__labReports.length === 2);
  assert.deepEqual((await currentReport()).charts.map(c => [c.metric, c.kind]), [['assessment_scores', 'line'], ['scan_volume', 'bar']]);
  assert.equal((await currentReport()).days, 90);
  await send('Replace the view with ONLY a bar chart of current unresolved HIGH and CRITICAL findings. Remove the other charts and keep cards and tables hidden.');
  await openLatestReport();
  await page.waitForFunction(() => document.querySelector('[aria-label="Report version"]')?.value === '3');
  await page.waitForFunction(() => window.__labReports.length === 3);
  assert.deepEqual((await currentReport()).charts.map(c => [c.metric, c.kind]), [['severity', 'bar']]);
  assert.deepEqual([...(await currentReport()).severities].sort(), ['critical', 'high']);
  assert.ok((await currentReport()).charts[0].points.every(p => ['Critical', 'High'].includes(p.label)));
  await send('Draw a graph of our monthly revenue and profit.');
  answer = await page.$$eval('[data-chat-role="assistant"]', list => list.at(-1).innerText);
  assert.match(answer, /revenue|profit/i);
  assert.match(answer, /not|no |don't|cannot|unavailable|doesn't|do not/i);
  assert.equal(await page.$eval('[aria-label="Report version"]', el => el.value), '3');
  await page.setViewport({ width: 390, height: 844 });
  await page.waitForFunction(() => document.querySelector('[aria-label="Organization performance report"]').getBoundingClientRect().right <= innerWidth);
  await page.waitForFunction(() => [...document.querySelectorAll('svg.marks')].every(el => el.getBoundingClientRect().right <= innerWidth));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: '/tmp/cyphbot-custom-filter-mobile.png' });
  assert.deepEqual(errors, []);
  console.log('PASS: exactly one line; no extra cards/tables; live scoped 14-day question; additive chart revision; severity filter; unavailable financial data refused; mobile layout.');
} catch (error) {
  if (page) {
    console.error(await page.$eval('body', el => el.innerText));
    await page.screenshot({ path: '/tmp/cyphbot-custom-failure.png' });
  }
  throw error;
} finally { await browser.close(); }
