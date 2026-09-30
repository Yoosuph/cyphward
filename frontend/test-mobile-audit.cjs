const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const SCREENSHOT_DIR = path.join(__dirname, 'mobile-audit-screenshots');
if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function runAudit() {
  const browser = await puppeteer.launch({
    executablePath: '/usr/sbin/chromium',
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 375, height: 812, deviceScaleFactor: 2 });

  // 1. Visit root to set local storage auth
  await page.goto('http://127.0.0.1:5174/', { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    localStorage.removeItem('cyphward-signed-out');
    localStorage.setItem('cyphward-tenant', JSON.stringify({
      id: 'a0000000-0000-0000-0000-000000000001',
      slug: 'datagrid-africa',
      name: 'DataGrid Africa',
      plan: 'Enterprise Defense',
      region: 'ng-lagos'
    }));
    localStorage.setItem('cyphward-org-id', 'a0000000-0000-0000-0000-000000000001');
  });

  const routes = [
    { path: '/', name: 'overview' },
    { path: '/assets', name: 'assets' },
    { path: '/findings', name: 'findings' },
    { path: '/scans', name: 'scans' },
    { path: '/domains', name: 'domains' },
    { path: '/analytics', name: 'analytics' },
    { path: '/comply', name: 'comply' },
    { path: '/settings', name: 'settings' },
    { path: '/academy', name: 'academy' },
    { path: '/detect', name: 'detect' }
  ];

  const report = [];

  for (const r of routes) {
    try {
      await page.goto('http://127.0.0.1:5174' + r.path, { waitUntil: 'domcontentloaded' });
      await new Promise(resolve => setTimeout(resolve, 800));

      // Check overflow
      const metrics = await page.evaluate(() => {
        const winW = window.innerWidth;
        const docW = document.documentElement.scrollWidth;
        const bodyW = document.body.scrollWidth;
        const overflowing = [];

        document.querySelectorAll('*').forEach(el => {
          const rect = el.getBoundingClientRect();
          if (rect.right > winW + 2) {
            overflowing.push({
              tag: el.tagName.toLowerCase(),
              className: (el.className || '').toString().slice(0, 70),
              right: Math.round(rect.right),
              width: Math.round(rect.width),
              textSnippet: (el.innerText || '').slice(0, 30).trim()
            });
          }
        });

        return {
          winW,
          docW,
          bodyW,
          hasOverflow: docW > winW || bodyW > winW,
          diff: Math.max(docW - winW, bodyW - winW),
          overflowing: overflowing.slice(0, 6)
        };
      });

      // Take screenshot
      const shotPath = path.join(SCREENSHOT_DIR, `${r.name}-375px.png`);
      await page.screenshot({ path: shotPath, fullPage: false });

      report.push({
        route: r.path,
        name: r.name,
        ...metrics,
        screenshot: shotPath
      });
      console.log(`[${r.name}] Diff: ${metrics.diff}px, HasOverflow: ${metrics.hasOverflow}`);
    } catch (e) {
      console.error(`Error auditing ${r.path}:`, e.message);
    }
  }

  await browser.close();
  console.log('\n--- AUDIT SUMMARY ---');
  console.log(JSON.stringify(report, null, 2));
}

runAudit().catch(err => {
  console.error(err);
  process.exit(1);
});
