const puppeteer = require('puppeteer-core');

async function testMobileDeep() {
  console.log('=== RUNNING AGGRESSIVE MOBILE DEEP BREAK SUITE ===\n');

  const browser = await puppeteer.launch({
    executablePath: '/usr/sbin/chromium',
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 375, height: 812, deviceScaleFactor: 2 });
  const BASE = 'http://127.0.0.1:5174';

  const errors = [];

  // Setup auth
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
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

  async function waitForPageReady() {
    await page.waitForFunction(() => {
      return !document.querySelector('.skeleton') && document.querySelector('.content-fade-in');
    }, { timeout: 8000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 400));
  }

  async function checkPageOverflow(contextName) {
    const res = await page.evaluate(() => {
      const winW = window.innerWidth;
      const docW = document.documentElement.scrollWidth;
      const bodyW = document.body.scrollWidth;
      return { winW, docW, bodyW, hasOverflow: docW > winW || bodyW > winW, diff: Math.max(docW - winW, bodyW - winW) };
    });

    console.log(`[Check: ${contextName}] winW=${res.winW}, docW=${res.docW}, bodyW=${res.bodyW}, diff=${res.diff}px`);
    if (res.hasOverflow) {
      errors.push(`Page horizontal overflow in [${contextName}]: diff=${res.diff}px`);
    }
  }

  // 1. Overview Page & Modals
  console.log('\n--- 1. OVERVIEW & MODALS ---');
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await waitForPageReady();
  await checkPageOverflow('Overview Default');

  // Open Launch Scan Modal
  const launchBtn = await page.$('button ::-p-text(START SCAN)');
  if (launchBtn) {
    await launchBtn.click();
    await new Promise(r => setTimeout(r, 400));
    await checkPageOverflow('Launch Scan Modal Open');
    const closeBtn = await page.$('.modal-panel button[aria-label="Close dialog"]');
    if (closeBtn) await closeBtn.click();
    await new Promise(r => setTimeout(r, 300));
  }

  // Open Board Report Modal
  const boardBtn = await page.$('button ::-p-text(GENERATE BOARD REPORT)');
  if (boardBtn) {
    await boardBtn.click();
    await new Promise(r => setTimeout(r, 600));
    await checkPageOverflow('Board Report Modal Open');
    const closeBtn = await page.$('.modal-panel button[aria-label="Close dialog"]');
    if (closeBtn) await closeBtn.click();
    await new Promise(r => setTimeout(r, 300));
  }

  // 2. Assets Page & Table / Drawer / Topology
  console.log('\n--- 2. ASSETS & DRAWERS ---');
  await page.goto(BASE + '/assets', { waitUntil: 'domcontentloaded' });
  await waitForPageReady();
  await checkPageOverflow('Assets Default Table');

  // Click first row to open Asset Drawer
  const firstAssetRow = await page.$('tbody tr.stagger-row');
  if (firstAssetRow) {
    await firstAssetRow.click();
    await new Promise(r => setTimeout(r, 600));
    await checkPageOverflow('Asset Detail Drawer Open');

    const drawerVisible = await page.evaluate(() => {
      const d = document.querySelector('.drawer.open');
      return !!d;
    });
    console.log('  Asset detail drawer open state:', drawerVisible);

    const closeDrawerBtn = await page.$('.drawer.open .drawer-head button');
    if (closeDrawerBtn) await closeDrawerBtn.click();
    await new Promise(r => setTimeout(r, 400));
  }

  // Switch to Topology Graph mode
  const topoBtn = await page.$('button[data-testid="view-mode-topology"]');
  if (topoBtn) {
    await topoBtn.click();
    await new Promise(r => setTimeout(r, 600));
    await checkPageOverflow('Assets Topology Graph Mode');
  }

  // 3. Findings Page & Explanations / Remediation
  console.log('\n--- 3. FINDINGS & REMEDIATION ---');
  await page.goto(BASE + '/findings', { waitUntil: 'domcontentloaded' });
  await waitForPageReady();
  await checkPageOverflow('Findings Default');

  // Click Fix Guide button
  const fixBtn = await page.$('button ::-p-text(How to fix)');
  if (fixBtn) {
    await fixBtn.click();
    await new Promise(r => setTimeout(r, 500));
    await checkPageOverflow('Remediation Blueprint Drawer Open');
    const closeFixDrawer = await page.$('.drawer.open .drawer-head button');
    if (closeFixDrawer) await closeFixDrawer.click();
    await new Promise(r => setTimeout(r, 400));
  }

  // Click Explain button
  const explainBtn = await page.$('button[title*="Ask CyphBot"]');
  if (explainBtn) {
    await explainBtn.click();
    await new Promise(r => setTimeout(r, 500));
    await checkPageOverflow('AI Finding Explanation Modal Open');
    const closeExplain = await page.$('.modal-panel button[aria-label="Close dialog"]');
    if (closeExplain) await closeExplain.click();
    await new Promise(r => setTimeout(r, 400));
  }

  // 4. Domains Page & Modals
  console.log('\n--- 4. DOMAINS & MODALS ---');
  await page.goto(BASE + '/domains', { waitUntil: 'domcontentloaded' });
  await waitForPageReady();
  await checkPageOverflow('Domains Default');

  const addDomBtn = await page.$('button ::-p-text(ADD DOMAIN)');
  if (addDomBtn) {
    await addDomBtn.click();
    await new Promise(r => setTimeout(r, 400));
    await checkPageOverflow('Add Domain Modal Open');
    const closeAddDom = await page.$('.modal-panel button[aria-label="Close dialog"]');
    if (closeAddDom) await closeAddDom.click();
    await new Promise(r => setTimeout(r, 400));
  }

  // Open DNS instructions modal
  const viewInstrBtn = await page.$('button[title="View Setup Instructions"]');
  if (viewInstrBtn) {
    await viewInstrBtn.click();
    await new Promise(r => setTimeout(r, 400));
    await checkPageOverflow('DNS Setup Instructions Modal Open');
    const closeInstr = await page.$('.modal-panel button[aria-label="Close dialog"]');
    if (closeInstr) await closeInstr.click();
    await new Promise(r => setTimeout(r, 400));
  }

  // 5. Settings Page & Tabs / Modals
  console.log('\n--- 5. SETTINGS & TABS ---');
  await page.goto(BASE + '/settings', { waitUntil: 'domcontentloaded' });
  await waitForPageReady();
  await checkPageOverflow('Settings General Tab');

  // Team tab
  const teamTab = await page.$('button ::-p-text(TEAM & ROLES)');
  if (teamTab) {
    await teamTab.click();
    await new Promise(r => setTimeout(r, 400));
    await checkPageOverflow('Settings Team Tab');
    // Open Invite Member Modal
    const inviteBtn = await page.$('button ::-p-text(Invite Officer)');
    if (inviteBtn) {
      await inviteBtn.click();
      await new Promise(r => setTimeout(r, 400));
      await checkPageOverflow('Invite Member Modal Open');
      const closeInvite = await page.$('.modal-panel button[aria-label="Close dialog"]');
      if (closeInvite) await closeInvite.click();
      await new Promise(r => setTimeout(r, 400));
    }
  }

  // API tab
  const apiTab = await page.$('button ::-p-text(API & WEBHOOKS)');
  if (apiTab) {
    await apiTab.click();
    await new Promise(r => setTimeout(r, 400));
    await checkPageOverflow('Settings API Tab');
  }

  // Compliance tab
  const compTab = await page.$('button ::-p-text(SECURITY & COMPLIANCE)');
  if (compTab) {
    await compTab.click();
    await new Promise(r => setTimeout(r, 400));
    await checkPageOverflow('Settings Compliance Tab');
  }

  // 6. Analytics Page
  console.log('\n--- 6. ANALYTICS ---');
  await page.goto(BASE + '/analytics', { waitUntil: 'domcontentloaded' });
  await waitForPageReady();
  await checkPageOverflow('Analytics Page');

  // 7. Command Palette
  console.log('\n--- 7. COMMAND PALETTE ---');
  await page.keyboard.down('Control');
  await page.keyboard.press('k');
  await page.keyboard.up('Control');
  await new Promise(r => setTimeout(r, 400));
  await checkPageOverflow('Command Palette Open');

  await browser.close();

  console.log('\n=== SUITE COMPLETE ===');
  if (errors.length > 0) {
    console.error('FAILURES DETECTED:');
    errors.forEach(e => console.error('  - ' + e));
    process.exit(1);
  } else {
    console.log('ALL DEEP SCENARIOS PASSED WITH ZERO HORIZONTAL OVERFLOW!');
  }
}

testMobileDeep().catch(err => {
  console.error(err);
  process.exit(1);
});
