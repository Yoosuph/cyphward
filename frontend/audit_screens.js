import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';

const CHROME_PATH = fs.existsSync('/home/consigliere/.local/bin/google-chrome-stable')
  ? '/home/consigliere/.local/bin/google-chrome-stable'
  : '/usr/sbin/chromium';

const ARTIFACTS_DIR = '/home/consigliere/.gemini/antigravity-cli/brain/fed9866c-50e0-4653-9e4f-cb441e094560';

async function run() {
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
    headless: 'new',
  });

  const page = await browser.newPage();

  // Helper to set theme
  const setTheme = async (theme) => {
    await page.evaluate((t) => {
      document.documentElement.setAttribute('data-theme', t);
      localStorage.setItem('cyphward-theme', t);
      window.dispatchEvent(new CustomEvent('cyphward:theme'));
    }, theme);
    await new Promise((r) => setTimeout(r, 300));
  };

  // Helper to wait for data loaded
  const waitForData = async () => {
    try {
      await page.waitForFunction(
        () => !document.querySelector('.animate-pulse') || document.body.textContent.includes('DataGrid Africa'),
        { timeout: 6000 }
      );
    } catch {
      // fallback timeout
    }
    await new Promise((r) => setTimeout(r, 600));
  };

  // Pre-seed authenticated session
  await page.evaluateOnNewDocument(() => {
    localStorage.setItem(
      'cyphward-tenant',
      JSON.stringify({
        id: 'a0000000-0000-0000-0000-000000000001',
        slug: 'datagrid-africa',
        name: 'DataGrid Africa',
        plan: 'Enterprise Defense',
        region: 'ng-lagos',
        email: 'security@datagrid-ng.com',
      })
    );
    localStorage.removeItem('cyphward-signed-out');
    localStorage.setItem('cyphward-onboarding', 'complete');
  });

  // ==================== 1. DESKTOP VIEW (1440x900) ====================
  console.log('Testing Desktop Views...');
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle2' });
  await page.waitForSelector('.shell-main', { timeout: 10000 });
  await setTheme('dark');
  await waitForData();

  // Desktop Dark Overview
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_desktop_dark.png') });
  console.log('Saved audit_desktop_dark.png');

  // Desktop Dark Drawer
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('header button')).find((b) =>
      b.textContent?.includes('CYPHBOT')
    );
    if (btn) btn.click();
  });
  await new Promise((r) => setTimeout(r, 600));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_desktop_dark_bot.png') });
  console.log('Saved audit_desktop_dark_bot.png');

  // Close desktop bot
  await page.keyboard.press('Escape');
  await new Promise((r) => setTimeout(r, 400));

  // Desktop Light Overview
  await setTheme('light');
  await waitForData();
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_desktop_light.png') });
  console.log('Saved audit_desktop_light.png');

  // Desktop Light Drawer
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('header button')).find((b) =>
      b.textContent?.includes('CYPHBOT')
    );
    if (btn) btn.click();
  });
  await new Promise((r) => setTimeout(r, 600));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_desktop_light_bot.png') });
  console.log('Saved audit_desktop_light_bot.png');

  // Close desktop bot
  await page.keyboard.press('Escape');
  await new Promise((r) => setTimeout(r, 400));

  // Desktop Analytics (Obsidian Graph)
  await page.goto('http://localhost:5173/analytics', { waitUntil: 'networkidle2' });
  await setTheme('dark');
  await new Promise((r) => setTimeout(r, 1200));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_desktop_dark_analytics.png') });
  console.log('Saved audit_desktop_dark_analytics.png');

  await setTheme('light');
  await new Promise((r) => setTimeout(r, 800));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_desktop_light_analytics.png') });
  console.log('Saved audit_desktop_light_analytics.png');

  // ==================== 2. MOBILE VIEW (390x844) ====================
  console.log('Testing Mobile Views (iPhone 14/15 390x844)...');
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle2' });
  await setTheme('dark');
  await waitForData();

  // Mobile Dark Overview
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_mobile_dark.png') });
  console.log('Saved audit_mobile_dark.png');

  // Mobile Dark Menu Sheet
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('.plate-btn')).find((b) =>
      b.textContent?.includes('MENU')
    );
    if (btn) btn.click();
  });
  await new Promise((r) => setTimeout(r, 500));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_mobile_dark_menu.png') });
  console.log('Saved audit_mobile_dark_menu.png');

  // Close menu sheet
  await page.keyboard.press('Escape');
  await new Promise((r) => setTimeout(r, 400));

  // Mobile Dark Chatbot (Floating small on side)
  await page.evaluate(() => {
    const btn = document.querySelector('button[aria-label="Open CyphBot Sovereign AI"]');
    if (btn) btn.click();
  });
  await new Promise((r) => setTimeout(r, 600));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_mobile_dark_bot.png') });
  console.log('Saved audit_mobile_dark_bot.png');

  // Close chatbot
  await page.keyboard.press('Escape');
  await new Promise((r) => setTimeout(r, 400));

  // Mobile Light Mode Overview
  await setTheme('light');
  await waitForData();
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_mobile_light.png') });
  console.log('Saved audit_mobile_light.png');

  // Mobile Light Menu Sheet
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('.plate-btn')).find((b) =>
      b.textContent?.includes('MENU')
    );
    if (btn) btn.click();
  });
  await new Promise((r) => setTimeout(r, 500));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_mobile_light_menu.png') });
  console.log('Saved audit_mobile_light_menu.png');

  // Close menu sheet
  await page.keyboard.press('Escape');
  await new Promise((r) => setTimeout(r, 400));

  // Mobile Light Chatbot (Floating small on side)
  await page.evaluate(() => {
    const btn = document.querySelector('button[aria-label="Open CyphBot Sovereign AI"]');
    if (btn) btn.click();
  });
  await new Promise((r) => setTimeout(r, 600));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_mobile_light_bot.png') });
  console.log('Saved audit_mobile_light_bot.png');

  // Close chatbot
  await page.keyboard.press('Escape');
  await new Promise((r) => setTimeout(r, 400));

  // Mobile Analytics (Obsidian Graph)
  await page.goto('http://localhost:5173/analytics', { waitUntil: 'networkidle2' });
  await setTheme('dark');
  await new Promise((r) => setTimeout(r, 1200));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_mobile_dark_analytics.png') });
  console.log('Saved audit_mobile_dark_analytics.png');

  await setTheme('light');
  await new Promise((r) => setTimeout(r, 800));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_mobile_light_analytics.png') });
  console.log('Saved audit_mobile_light_analytics.png');

  await browser.close();
  console.log('All audit screenshots captured successfully!');
}

run().catch((err) => {
  console.error('Audit script failed:', err);
  process.exit(1);
});
