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
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });

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

  // 1. Board Report Modal on Overview (Desktop Dark)
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 1000));

  // Click GENERATE BOARD REPORT button
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b =>
      b.textContent?.includes('GENERATE BOARD REPORT')
    );
    if (btn) btn.click();
  });
  await new Promise(r => setTimeout(r, 1000));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_desktop_modal_board_report_dark.png') });
  console.log('Saved audit_desktop_modal_board_report_dark.png');

  // Test toggling EMAIL REPORT button inside the modal
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b =>
      b.textContent?.includes('EMAIL REPORT')
    );
    if (btn) btn.click();
  });
  await new Promise(r => setTimeout(r, 400));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_desktop_modal_board_report_email.png') });
  console.log('Saved audit_desktop_modal_board_report_email.png');

  // Switch to Light mode
  await page.evaluate(() => {
    document.documentElement.setAttribute('data-theme', 'light');
    localStorage.setItem('cyphward-theme', 'light');
    window.dispatchEvent(new CustomEvent('cyphward:theme'));
  });
  await new Promise(r => setTimeout(r, 400));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_desktop_modal_board_report_light.png') });
  console.log('Saved audit_desktop_modal_board_report_light.png');

  // Close modal
  await page.keyboard.press('Escape');
  await new Promise(r => setTimeout(r, 400));

  // 2. Launch Scan Modal on Scans page (Desktop Dark)
  await page.goto('http://localhost:5173/scans', { waitUntil: 'networkidle2' });
  await page.evaluate(() => {
    document.documentElement.setAttribute('data-theme', 'dark');
    localStorage.setItem('cyphward-theme', 'dark');
    window.dispatchEvent(new CustomEvent('cyphward:theme'));
  });
  await new Promise(r => setTimeout(r, 1000));

  // Click Launch Scan button
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b =>
      b.textContent?.includes('LAUNCH SCAN')
    );
    if (btn) btn.click();
  });
  await new Promise(r => setTimeout(r, 600));
  await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'audit_desktop_modal_scan_launch.png') });
  console.log('Saved audit_desktop_modal_scan_launch.png');

  await browser.close();
  console.log('Desktop modal audit completed!');
}

run().catch(err => {
  console.error('Audit failed:', err);
  process.exit(1);
});
