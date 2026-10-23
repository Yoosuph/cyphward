// Real local demo navigation; no AI calls or production writes.
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
const origin = process.env.CYPHBOT_LAB_URL || 'http://127.0.0.1:5173';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(origin).hostname));
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
let page;
try {
  page = await browser.newPage(); page.setDefaultTimeout(15000);
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.evaluateOnNewDocument(() => localStorage.setItem('cyphward-cookie-consent', 'accepted'));
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  await page.goto(`${origin}/login`, { waitUntil: 'networkidle0' });
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.includes('Try the demo')));
  await page.evaluate(() => [...document.querySelectorAll('button')].find(b => b.textContent.includes('Try the demo')).click());
  await page.waitForFunction(() => location.pathname === '/overview');
  await page.waitForSelector('[data-tour="checklist"] button');
  await page.waitForSelector('[data-tour="score"]');
  const start = () => page.evaluate(async () => (await import('/src/lib/tour.ts')).startTour());
  const fits = () => page.waitForFunction(() => {
    const r = document.querySelector('.tour-card')?.getBoundingClientRect();
    return r && r.left >= 8 && r.right <= innerWidth - 8 && r.top >= 8 && r.bottom <= innerHeight - 8;
  });
  const spotCovers = selector => page.evaluate(selector => {
    const spot = document.querySelector('.tour-spot')?.getBoundingClientRect();
    const target = [...document.querySelectorAll(selector)].map(e => e.getBoundingClientRect()).find(r => r.width && r.left >= 0 && r.right <= innerWidth);
    return !!spot && !!target && spot.left <= target.left + 1 && spot.right >= target.right - 1 && spot.top <= target.top + 1 && spot.bottom >= target.bottom - 1;
  }, selector);
  for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }, { width: 320, height: 568 }, { width: 844, height: 390 }]) {
    await page.setViewport(viewport);
    if (viewport.width === 390) {
      await page.click('[aria-label="Open menu"]');
      await page.waitForSelector('[aria-label="More pages menu"]');
    }
    await start(); await page.waitForSelector('.tour-card'); await fits();
    assert.equal(await page.$eval('.tour-root', e => e.dataset.tourStep), 'welcome');
    assert.equal(await page.$('[aria-label="More pages menu"]'), null, 'Starting a tour closes competing menus');
    assert.equal(await page.evaluate(() => document.activeElement.hasAttribute('data-tour-primary')), true);
    const visited = [];
    for (let count = 0; count < 14; count++) {
      await fits();
      const step = await page.$eval('.tour-root', e => e.dataset.tourStep);
      visited.push(step);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.$eval('.tour-card', el => document.elementFromPoint(el.getBoundingClientRect().left + 20, el.getBoundingClientRect().top + 20)?.closest('.tour-card') === el), true);
      if (step === 'domains') {
        await page.waitForSelector('.tour-spot');
        await page.waitForFunction(() => document.querySelector('.tour-spot')?.getBoundingClientRect().width > 0);
        await new Promise(resolve => setTimeout(resolve, 300));
        assert.equal(await spotCovers(viewport.width < 901 ? '[data-tour="plate-menu"]' : '[data-tour="nav-domains"]'), true);
        if (viewport.width < 901) assert.match(await page.$eval('#tour-body', el => el.innerText), /Menu.*Domains.*Remediation.*Reports.*Compliance/);
        if (viewport.width === 320) await page.screenshot({ path: '/tmp/cyphward-tour-small-mobile.png' });
      }
      if (step === 'cyphbot') {
        assert.match(await page.$eval('#tour-body', e => e.innerText), viewport.width < 901 ? /small window.*expand icon/ : /recorded/);
        await page.waitForSelector('.tour-spot');
        if (viewport.width === 390) await page.screenshot({ path: '/tmp/cyphward-tour-cyphbot-mobile.png' });
      }
      const last = await page.$eval('[data-tour-primary]', e => e.textContent.trim() === 'FINISH');
      if (last) { await page.click('[data-tour-primary]'); break; }
      const hit = await page.$eval('[data-tour-primary]', el => {
        const r = el.getBoundingClientRect(), target = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return { clickable: el.contains(target), target: target?.outerHTML.slice(0, 180), top: r.top, left: r.left };
      });
      assert.equal(hit.clickable, true, JSON.stringify({ step, viewport, hit }));
      await page.click('[data-tour-primary]');
      await page.waitForFunction(previous => document.querySelector('.tour-root')?.dataset.tourStep !== previous, {}, step);
    }
    await page.waitForFunction(() => !document.querySelector('.tour-root'));
    assert.ok(visited.includes('cyphbot') && visited.includes('palette'));
    assert.equal(visited.includes('compliance'), viewport.width >= 901);
    assert.equal(await page.evaluate(() => document.body.classList.contains('scroll-locked')), false);
  }
  await page.setViewport({ width: 390, height: 844 });
  await page.evaluate(() => [...document.querySelectorAll('[aria-label="Open CyphBot"]')].find(button => button.getClientRects().length)?.click());
  await page.waitForSelector('.cyphbot-window');
  await start(); await page.waitForFunction(() => !document.querySelector('.cyphbot-window'));
  await page.keyboard.press('ArrowRight');
  await page.waitForFunction(() => document.querySelector('.tour-root')?.dataset.tourStep !== 'welcome');
  await page.keyboard.press('ArrowLeft');
  await page.waitForFunction(() => document.querySelector('.tour-root')?.dataset.tourStep === 'welcome');
  await page.keyboard.press('Escape'); await page.waitForFunction(() => !document.querySelector('.tour-root'));
  assert.equal(await page.evaluate(() => document.body.classList.contains('scroll-locked')), false);
  assert.deepEqual(errors, []);
  console.log('PASS: full desktop/mobile tours; real mobile Menu target; current content; 320px and landscape fit; reachable controls; CyphBot/menu coexistence; keyboard/back/skip/finish; scroll unlock. No AI calls.');
} catch (error) {
  if (page) { console.error((await page.$eval('body', e => e.innerText)).slice(-2200)); await page.screenshot({ path: '/tmp/cyphward-tour-failure.png' }); }
  throw error;
} finally { await browser.close(); }
