import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';

const CHROME_PATH = fs.existsSync('/home/consigliere/.local/bin/google-chrome-stable')
  ? '/home/consigliere/.local/bin/google-chrome-stable'
  : '/usr/sbin/chromium';

const ARTIFACTS_DIR = '/home/consigliere/.gemini/antigravity-cli/brain/fed9866c-50e0-4653-9e4f-cb441e094560';

async function run() {
  console.log('Launching browser with:', CHROME_PATH);
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
    headless: 'new',
  });

  const page = await browser.newPage();
  // iPhone 14 mobile viewport (390 x 844, dpr 2)
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });

  // Pre-seed authenticated session
  await page.evaluateOnNewDocument(() => {
    localStorage.setItem('cyphward-tenant', JSON.stringify({
      id: 'a0000000-0000-0000-0000-000000000001',
      slug: 'datagrid-africa',
      name: 'DataGrid Africa',
      plan: 'Enterprise Defense',
      region: 'ng-lagos',
      email: 'security@datagrid-ng.com',
    }));
    localStorage.removeItem('cyphward-signed-out');
    localStorage.setItem('cyphward-onboarding', 'complete');
  });

  console.log('Navigating to dashboard...');
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle2' });

  // Wait for overview command center
  await page.waitForSelector('.shell-main', { timeout: 10000 });
  await new Promise(r => setTimeout(r, 1200));

  // 1. Capture mobile default overview with header (shield logo + CYPH acronym) and floating AI button
  console.log('Capturing mobile header & overview view...');
  await page.screenshot({
    path: path.join(ARTIFACTS_DIR, 'mobile_header_view.png'),
    fullPage: false,
  });

  // 2. Click MENU in the bottom dock
  console.log('Clicking MENU button in floating dock...');
  await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll('.plate-btn'));
    const menuBtn = buttons.find(b => b.textContent?.includes('MENU'));
    if (menuBtn) menuBtn.click();
  });
  await new Promise(r => setTimeout(r, 600));

  console.log('Capturing mobile menu sheet with rest of pages...');
  await page.screenshot({
    path: path.join(ARTIFACTS_DIR, 'mobile_menu_sheet.png'),
    fullPage: false,
  });

  // 3. Reload page fresh for floating chatbot capture
  console.log('Reloading fresh page for floating chatbot...');
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle2' });
  await page.waitForSelector('.shell-main', { timeout: 10000 });
  await new Promise(r => setTimeout(r, 800));

  console.log('Clicking floating CYPHBOT button...');
  await page.evaluate(() => {
    const btn = document.querySelector('button[aria-label="Open CyphBot Sovereign AI"]') ||
      Array.from(document.querySelectorAll('button')).find(b => b.textContent?.includes('CYPHBOT'));
    if (btn) btn.click();
  });
  await new Promise(r => setTimeout(r, 800));

  console.log('Capturing floating chatbot window...');
  await page.screenshot({
    path: path.join(ARTIFACTS_DIR, 'mobile_floating_chatbot.png'),
    fullPage: false,
  });

  await browser.close();
  console.log('Done capturing all screenshots successfully!');
}

run().catch(err => {
  console.error('Error running capture:', err);
  process.exit(1);
});
