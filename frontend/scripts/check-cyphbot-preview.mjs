// UI contract checks: actual local login, simulated report SSE, no model calls.
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';

const origin = process.env.CYPHBOT_LAB_URL || 'http://127.0.0.1:5173';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(origin).hostname));
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
let page;
try {
  page = await browser.newPage();
  page.setDefaultTimeout(20000);
  await page.setViewport({ width: 1440, height: 1000 });
  const errors = [], requests = [], resources = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error' && /unique.*key|same key/i.test(m.text())) errors.push(m.text()); });
  await page.evaluateOnNewDocument(() => localStorage.setItem('cyphward-cookie-consent', 'accepted'));
  await page.setRequestInterception(true);
  page.on('request', async req => {
    resources.push(req.url());
    if (!req.url().endsWith('/ai/chat/stream')) return req.continue();
    const body = JSON.parse(req.postData()); requests.push(body);
    const version = requests.length;
    const metric = version === 1 ? 'assessment_scores' : version === 2 ? 'severity' : 'finding_status';
    const kind = version === 1 ? 'line' : version === 2 ? 'bar' : 'donut';
    const artifact = {
      schema_version: 1, id: 'e1ac0000-0000-4000-8000-000000000001', version,
      org_id: req.headers()['x-organization-id'], title: 'Preview rendering fixture', generated_at: new Date().toISOString(),
      days: 90, chart_style: 'line', severities: [], sample: true, summary: 'Synthetic chart fixture for display checks.',
      metrics: [], tables: [], limitations: ['Rendering fixture; not production telemetry.'], sources: ['Display fixture'],
      charts: [{ id: 'preview-chart', title: version === 1 ? 'Assessment scores' : 'Finding inventory', metric, kind,
        x_type: version === 1 ? 'temporal' : 'ordinal', unit: version === 1 ? 'Score / 100' : 'Findings', note: 'Rendering fixture.',
        points: version === 1 ? [{ label: '2026-08-21', value: 42 }, { label: '2026-09-21', value: 60 }, { label: '2026-10-19', value: 78 }]
          : [{ label: 'High', value: 2 }, { label: 'Medium', value: 4 }, { label: 'Low', value: 3 }],
      }],
    };
    const content = '### Assessment overview\nYour **recorded scores** increased across these observations. Review the scope before interpreting this as a broader improvement.\n- Compare the same domain and assessment scope.\n- Inspect the `recorded score` and evidence.\n```text\ncopyable example\n```';
    const events = [
      { type: 'assistant-status', step: 'reading_workspace' },
      ...(version <= 3 ? [{ type: 'artifact', artifact }] : []),
      { token: content, done: false }, { done: true, sources: [{ id: 'fixture', label: 'Display test fixture' }], actions: [] },
    ];
    await req.respond({ status: 200, contentType: 'text/event-stream', body: events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('') });
  });
  await page.goto(`${origin}/login`, { waitUntil: 'networkidle0' });
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.includes('Try the demo')));
  await page.evaluate(() => [...document.querySelectorAll('button')].find(b => b.textContent.includes('Try the demo')).click());
  await page.waitForFunction(() => location.pathname === '/overview');
  await page.click('[aria-label="Open CyphBot"]');
  const send = async text => {
    const count = await page.$$eval('[data-chat-role="assistant"]', list => list.length);
    await page.type('textarea[placeholder="Ask CyphBot..."]', text); await page.keyboard.press('Enter');
    await page.waitForFunction(count => document.querySelectorAll('[data-chat-role="assistant"]').length > count && !document.body.innerText.includes('CyphBot is thinking'), {}, count);
  };
  const panel = '[aria-label="Organization performance report"]';
  await send('Make a line graph');
  assert.equal(await page.$(panel), null);
  assert.equal(await page.$$eval('[data-report-thumbnail]', all => all.length), 1);
  assert.equal(resources.some(url => url.includes('/CyphBotReportPanel.')), false, 'Full renderer loads only after click');
  const motion = await page.$$eval('[data-surface-word]', words => words.map(w => ({ name: getComputedStyle(w).animationName, delay: getComputedStyle(w).animationDelay, display: getComputedStyle(w).display })));
  assert.ok(motion.length > 20);
  assert.ok(motion.every(w => w.name === 'cyphbotWordRise' && w.display === 'inline-block'));
  assert.notEqual(motion[0].delay, motion[1].delay);
  await page.waitForFunction(() => [...document.querySelectorAll('[data-surface-word]')].every(w => getComputedStyle(w).opacity === '1'));
  await page.screenshot({ path: '/tmp/cyphbot-click-preview-desktop.png' });

  await send('Use a bar chart instead');
  assert.equal(requests[1].artifact_context.version, 1);
  assert.equal(requests[1].artifact_context.charts[0].metric, 'assessment_scores');
  assert.equal(await page.$(panel), null);
  await page.waitForSelector('[data-report-version="2"] [data-report-thumbnail] rect');
  await page.focus('[data-report-version="2"]'); await page.keyboard.press('Enter');
  await page.waitForSelector(`${panel} svg.marks`);
  assert.equal(await page.$eval('[aria-label="Report version"]', e => e.value), '2');
  await send('Make a donut revision');
  assert.equal(requests[2].artifact_context.version, 2);
  assert.equal(await page.$eval('[aria-label="Report version"]', e => e.value), '2', 'New artifact must not replace an open view');
  await page.waitForSelector('[data-report-version="3"] [data-report-thumbnail] circle');
  await page.click('[data-report-version="1"]');
  await page.waitForFunction(() => document.querySelector('[aria-label="Report version"]')?.value === '1');
  await page.click('[aria-label="Back to chat"]');
  await send('Explain that earlier view without creating anything');
  assert.equal(requests[3].artifact_context.version, 3, 'Revision counter retains newest version');
  assert.equal(requests[3].artifact_context.charts[0].metric, 'assessment_scores', 'Explicitly opened older view remains selected');
  assert.equal(await page.$(panel), null);
  await page.waitForFunction(() => [...document.querySelectorAll('[data-surface-word]')].every(w => getComputedStyle(w).opacity === '1'));
  await page.click('[aria-label="Minimize Chatbot"]');
  await page.waitForFunction(() => !document.querySelector('.cyphbot-window'));
  await page.click('[aria-label="Open CyphBot"]');
  await page.waitForSelector('[data-report-version="3"]');
  assert.equal(await page.$$eval('[data-surface-word]', all => all.length), 0, 'Old text must not replay its animation');

  await page.setViewport({ width: 390, height: 844 });
  await page.waitForFunction(() => {
    const r = document.querySelector('.cyphbot-window').getBoundingClientRect();
    return r.left >= 7 && r.right <= innerWidth - 7 && Math.abs(r.width - Math.min(340, innerWidth - 24)) < 1;
  });
  assert.equal(await page.$(panel), null);
  await page.$eval('[data-report-version="3"]', e => e.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: '/tmp/cyphbot-click-preview-mobile.png' });
  await page.click('[data-report-version="3"]');
  await page.waitForSelector(panel);
  await page.waitForFunction(() => document.querySelector('[aria-label="Organization performance report"]').getBoundingClientRect().right <= innerWidth);
  await page.click('[aria-label="Back to chat"]');
  assert.equal(await page.$(panel), null);
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  await send('Explain this with reduced motion');
  assert.equal(await page.$eval('[data-surface-word]', w => getComputedStyle(w).animationName), 'none');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
  console.log('PASS: no automatic panel; line/bar/donut previews; keyboard/click open; immutable selected view; closed-panel context; rising words without replay; mobile; reduced motion. SSE simulated; no Gemini request.');
} catch (error) {
  if (page) { console.error((await page.$eval('body', e => e.innerText)).slice(-4000)); await page.screenshot({ path: '/tmp/cyphbot-preview-failure.png' }); }
  throw error;
} finally { await browser.close(); }
