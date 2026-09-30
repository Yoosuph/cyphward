const puppeteer = require('puppeteer-core');

async function testMobileInteractions() {
  console.log('--- STARTING COMPREHENSIVE MOBILE INTERACTIVE SUITE ---');

  const browser = await puppeteer.launch({
    executablePath: '/usr/sbin/chromium',
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
  });

  const page = await browser.newPage();
  
  // Set 375px width (iPhone standard base)
  await page.setViewport({ width: 375, height: 812, deviceScaleFactor: 2 });

  const BASE_URL = 'http://127.0.0.1:5174';

  // 1. Check Landing & Login viewports
  console.log('\n[1] Testing Public Pages (Landing & Login)');
  for (const p of ['/landing', '/login']) {
    await page.goto(BASE_URL + p, { waitUntil: 'domcontentloaded' });
    await new Promise(r => setTimeout(r, 600));
    const res = await page.evaluate(() => ({
      winW: window.innerWidth,
      docW: document.documentElement.scrollWidth,
      bodyW: document.body.scrollWidth,
    }));
    const overflow = res.docW > res.winW || res.bodyW > res.winW;
    console.log(`  Page ${p}: winW=${res.winW}, docW=${res.docW}, bodyW=${res.bodyW}, overflow=${overflow}`);
    if (overflow) throw new Error(`Overflow detected on ${p}`);
  }

  // 2. Set authenticated state
  await page.goto(BASE_URL + '/', { waitUntil: 'domcontentloaded' });
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

  // Reload to apply auth
  await page.goto(BASE_URL + '/', { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 800));

  // 3. Test Topbar Hamburger Button -> Sidebar opens & closes
  console.log('\n[2] Testing Topbar Hamburger Button & Sidebar Drawer');
  const hamburger = await page.$('button[aria-label="Open sovereign navigation menu"]');
  if (!hamburger) throw new Error('Hamburger button not found in Topbar on mobile');
  
  await hamburger.click();
  await new Promise(r => setTimeout(r, 400));

  // Check if sidebar has 'open' class
  let sidebarState = await page.evaluate(() => {
    const sb = document.querySelector('.sidebar');
    const scrim = document.querySelector('.side-scrim');
    const rect = sb ? sb.getBoundingClientRect() : null;
    return {
      isOpen: sb ? sb.classList.contains('open') : false,
      left: rect ? rect.left : null,
      width: rect ? rect.width : null,
      scrimVisible: scrim ? window.getComputedStyle(scrim).display !== 'none' : false
    };
  });
  console.log('  Sidebar after hamburger click:', sidebarState);
  if (!sidebarState.isOpen || sidebarState.left < 0) {
    throw new Error('Sidebar failed to slide open after hamburger click');
  }

  // Close sidebar via 'X' close button
  const closeBtn = await page.$('.sidebar-mobile-close');
  if (!closeBtn) throw new Error('Mobile sidebar close button not found');
  await closeBtn.click();
  await new Promise(r => setTimeout(r, 400));

  sidebarState = await page.evaluate(() => {
    const sb = document.querySelector('.sidebar');
    return { isOpen: sb ? sb.classList.contains('open') : false };
  });
  console.log('  Sidebar after close button click:', sidebarState);
  if (sidebarState.isOpen) throw new Error('Sidebar failed to close via close button');

  // 4. Test ButtonPlate 'MENU' button
  console.log('\n[3] Testing ButtonPlate MENU Trigger');
  const menuPlateBtn = await page.$('button[aria-label="Open Navigation Menu"]');
  if (!menuPlateBtn) throw new Error('ButtonPlate MENU button not found');
  await menuPlateBtn.click();
  await new Promise(r => setTimeout(r, 400));

  sidebarState = await page.evaluate(() => {
    const sb = document.querySelector('.sidebar');
    return { isOpen: sb ? sb.classList.contains('open') : false };
  });
  console.log('  Sidebar after ButtonPlate MENU click:', sidebarState);
  if (!sidebarState.isOpen) throw new Error('Sidebar failed to open via ButtonPlate');

  // Click a navigation link in sidebar (e.g. Findings)
  console.log('  Clicking FINDINGS link inside sidebar');
  const findingsLink = await page.$('a[href="/findings"]');
  if (!findingsLink) throw new Error('Findings nav link not found in sidebar');
  await findingsLink.click();
  await new Promise(r => setTimeout(r, 800));

  sidebarState = await page.evaluate(() => {
    const sb = document.querySelector('.sidebar');
    return {
      isOpen: sb ? sb.classList.contains('open') : false,
      url: window.location.pathname
    };
  });
  console.log('  After nav click:', sidebarState);
  if (!sidebarState.url.includes('/findings')) throw new Error(`Failed to navigate to /findings: ${sidebarState.url}`);
  if (sidebarState.isOpen) throw new Error('Sidebar did not auto-close upon route transition');

  // 5. Test ButtonPlate 'AI' CyphBot Trigger
  console.log('\n[4] Testing ButtonPlate AI CyphBot Drawer');
  const aiPlateBtn = await page.$('.button-plate button[aria-label="Open CyphBot Sovereign AI"]');
  if (!aiPlateBtn) throw new Error('ButtonPlate AI button not found');
  await aiPlateBtn.click();
  await new Promise(r => setTimeout(r, 500));

  const drawerState = await page.evaluate(() => {
    const drawer = document.querySelector('.fixed.inset-y-0.right-0') || document.querySelector('[role="dialog"]');
    const input = document.querySelector('textarea[placeholder*="Ask CyphBot"]');
    const dock = document.querySelector('.button-plate-wrapper');
    const drawerZ = drawer ? parseInt(window.getComputedStyle(drawer).zIndex) || 0 : 0;
    const dockZ = dock ? parseInt(window.getComputedStyle(dock).zIndex) || 0 : 0;
    return {
      hasDrawer: !!drawer,
      hasInput: !!input,
      drawerZ,
      dockZ,
      drawerAboveDock: drawerZ > dockZ
    };
  });
  console.log('  CyphBot Drawer state:', drawerState);
  if (!drawerState.hasDrawer || !drawerState.drawerAboveDock || !drawerState.hasInput) {
    throw new Error('CyphBot drawer is not properly rendered above ButtonPlate or input missing');
  }

  // Close CyphBot Drawer
  const closeCyphBot = await page.$('button[aria-label="Close Drawer"]');
  if (closeCyphBot) {
    await closeCyphBot.click();
    await new Promise(r => setTimeout(r, 400));
  }

  // 6. Test Multi-viewport Audit across 375px, 390px, 480px, 768px
  console.log('\n[5] Testing Multi-viewport Overflow across all core routes');
  const viewports = [
    { name: 'iPhone SE (375px)', width: 375, height: 667 },
    { name: 'iPhone 14 (390px)', width: 390, height: 844 },
    { name: 'Handset 480px', width: 480, height: 800 },
    { name: 'Tablet 768px', width: 768, height: 1024 }
  ];

  const testRoutes = ['/', '/assets', '/findings', '/scans', '/domains', '/analytics', '/comply', '/settings', '/academy', '/detect'];

  for (const vp of viewports) {
    await page.setViewport({ width: vp.width, height: vp.height, deviceScaleFactor: 2 });
    let vpPass = true;
    for (const route of testRoutes) {
      await page.goto(BASE_URL + route, { waitUntil: 'domcontentloaded' });
      await new Promise(r => setTimeout(r, 400));
      const m = await page.evaluate(() => {
        const winW = window.innerWidth;
        const docW = document.documentElement.scrollWidth;
        const bodyW = document.body.scrollWidth;
        return {
          diff: Math.max(docW - winW, bodyW - winW),
          hasOverflow: docW > winW || bodyW > winW
        };
      });
      if (m.hasOverflow) {
        console.error(`  FAIL: [${vp.name}] ${route} has overflow diff: ${m.diff}px`);
        vpPass = false;
      }
    }
    console.log(`  Viewport ${vp.name} (${vp.width}px): ${vpPass ? 'ALL ROUTES PASS (0px overflow)' : 'HAS FAILURES'}`);
    if (!vpPass) throw new Error(`Viewport ${vp.name} failed overflow checks`);
  }

  await browser.close();
  console.log('\n>>> ALL INTERACTIVE & VIEWPORT TESTS PASSED SUCCESSFULLY! <<<');
}

testMobileInteractions().catch(err => {
  console.error('\nTEST SUITE ERROR:', err);
  process.exit(1);
});
