// Regression checks for PR 71 review: exercise real hooks and API/auth entry points in Chromium.
// ONLY_RULE=<name> runs one group for the documented one-at-a-time mutation checks.
import assert from 'node:assert/strict';
import { startHarness, settle, sleep } from './lib/ui-refine-harness.mjs';
import { ownerRoute } from './lib/motion-cache-harness.mjs';

const h = await startHarness();
let checks = 0;
const check = (value, message) => { assert.ok(value, message); checks++; };
const only = process.env.ONLY_RULE;
const run = async (name, fn) => {
  if (only && only !== name) return;
  h.state.route = (p) => ownerRoute(p);
  const tab = await h.newPage();
  try {
    await tab.page.goto(`${h.origin}/findings`, { waitUntil: 'domcontentloaded' });
    await tab.page.waitForFunction(() => !!localStorage.getItem('cyphward-org-id') && document.querySelector('main')?.innerText.includes('Missing Email DMARC'));
    await settle(tab.page, 100);
    // A small independent React root exercises the production hooks without replacing app exports.
    await tab.page.evaluate(async () => {
      const { default: React } = await import('/node_modules/.vite/deps/react.js');
      const { default: { createRoot } } = await import('/node_modules/.vite/deps/react-dom_client.js');
      const q = await import('/src/lib/queryCache.ts');
      window.__q = q;
      window.__React = React;
      window.__probeRoot = createRoot(document.body.appendChild(document.createElement('div')));
      window.__mount = (component) => window.__probeRoot.render(React.createElement(component));
      window.__clock = Date.now();
      Date.now = () => window.__clock;
      window.__advance = (ms) => { window.__clock += ms; };
      q.clearQueryCache();
    });
    await fn(tab.page);
    check(tab.errors.length === 0, `${name}: no browser errors: ${tab.errors.join('; ')}`);
    console.log(`cache review: ${name} passed`);
  } finally { await tab.close(); }
};

try {
  await run('writes', async (page) => {
    for (const fail of [false, true]) {
      h.state.failures = new Set(fail ? ['/findings/f1/status'] : []);
      const r = await page.evaluate(async () => {
        const q = window.__q;
        const api = await import('/src/lib/api.ts');
        const seeded = q.writeQueryCache('sentinel', 'cached before write', q.cacheTicket());
        const ticket = q.cacheTicket();
        try { await api.updateFindingStatus('f1', 'resolved'); } catch { /* a failed write also invalidates */ }
        return { seeded, size: q.queryCacheSize(), accepted: q.writeQueryCache('late', 'old read', ticket) };
      });
      check(r.seeded && r.size === 0 && !r.accepted, `writes: ${fail ? 'failed' : 'successful'} customer write clears entries and old tickets`);
    }
    h.state.failures.clear();
    const r = await page.evaluate(async () => {
      const q = window.__q;
      q.setOwnerScope('owner@example.test');
      const seeded = q.writeQueryCache('sentinel', 'owner read', q.cacheTicket('owner'));
      const t = q.cacheTicket('owner');
      await (await import('/src/owner/ownerApi.ts')).ownerPost('/organizations/o1/suspend', { reason: 'fixture' });
      return { seeded, size: q.queryCacheSize(), accepted: q.writeQueryCache('late', 'old read', t) };
    });
    check(r.seeded && r.size === 0 && !r.accepted, 'writes: owner write clears entries and old tickets');
  });

  await run('focus', async (page) => {
    await page.evaluate(() => {
      const { useCachedQuery, useRevalidateOnFocus } = window.__q;
      window.__calls = { query: 0, page: 0 };
      window.__mount(() => {
        useCachedQuery('focus-probe', async () => ++window.__calls.query);
        useRevalidateOnFocus(() => { window.__calls.page++; });
        return null;
      });
    });
    await page.waitForFunction(() => window.__calls.query === 1);
    const focus = (ms, event = 'focus') => page.evaluate(({ ms, event }) => {
      window.__advance(ms);
      (event === 'focus' ? window : document).dispatchEvent(new Event(event));
    }, { ms, event });
    await focus(29_999);
    await sleep(80);
    check(await page.evaluate(() => window.__calls.query === 1 && window.__calls.page === 0), 'focus: no refetch before 30 seconds');
    await focus(1);
    await page.waitForFunction(() => window.__calls.query === 2 && window.__calls.page === 1);
    await focus(0, 'visibilitychange');
    await focus(29_999);
    await sleep(80);
    check(await page.evaluate(() => window.__calls.query === 2 && window.__calls.page === 1), 'focus: visibility and repeated focus share the 30-second throttle');
    await focus(1, 'visibilitychange');
    await page.waitForFunction(() => window.__calls.query === 3 && window.__calls.page === 2);
    check(true, 'focus: both hooks refresh at the 30-second boundary');
  });

  await run('owner-focus', async (page) => {
    let reads = 0;
    h.state.route = (p) => { if (p.endsWith('/owner/logs')) reads++; return ownerRoute(p); };
    await page.evaluate(async () => {
      const { useOwnerView } = await import('/src/owner/ui.tsx');
      window.__q.setOwnerScope('owner@example.test');
      window.__mount(() => { window.__view = useOwnerView('/logs'); return null; });
    });
    await page.waitForFunction(() => window.__view?.data !== null && !window.__view.loading);
    const before = reads;
    await page.evaluate(() => {
      window.__advance(60_000);
      window.dispatchEvent(new Event('focus'));
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await sleep(150);
    check(reads === before, 'owner-focus: no audited view reads on focus or visibility change');
  });

  await run('auth', async (page) => {
    await page.evaluate(async () => {
      const { AuthProvider, useAuth } = await import('/src/lib/auth.tsx');
      function Child() { window.__auth = useAuth(); return null; }
      window.__mount(() => window.__React.createElement(AuthProvider, null, window.__React.createElement(Child)));
    });
    await page.waitForFunction(() => window.__auth?.user && !window.__auth.loading);
    // Exercise the actual invitation refresh, with no preceding API write to mask a missing org-change clear.
    h.state.route = (p) => {
      if (p.endsWith('/auth/bootstrap')) return [200, {
        user: { id: 'c1-user', email: 'c1@example.test', full_name: 'Compliance Review' }, email_verified: true,
        memberships: [{ org: { id: 'org-next', name: 'Next workspace', slug: 'next', plan: 'growth' }, role: 'owner', domains: [] }],
      }];
      return ownerRoute(p);
    };
    const switched = await page.evaluate(async () => {
      const q = window.__q;
      const seeded = q.writeQueryCache('sentinel', 'old workspace', q.cacheTicket());
      const before = q.cacheTicket();
      await window.__auth.refreshAfterInviteAccept('org-next');
      return { seeded, size: q.queryCacheSize(), before: before.gen, after: q.cacheTicket().gen };
    });
    check(switched.seeded && switched.size === 0 && switched.after > switched.before, 'auth: org switch empties the store and invalidates generations');
    const signedOut = await page.evaluate(async () => {
      const q = window.__q;
      const seeded = q.writeQueryCache('sentinel', 'before sign-out', q.cacheTicket());
      const before = q.cacheTicket();
      await window.__auth.signOut();
      return { seeded, size: q.queryCacheSize(), before: before.gen, after: q.cacheTicket().gen };
    });
    check(signedOut.seeded && signedOut.size === 0 && signedOut.after > signedOut.before, 'auth: sign-out empties the store and invalidates generations');
  });

  await run('owner-policy', async (page) => {
    await page.evaluate(async () => {
      window.__ownerUI = await import('/src/owner/ui.tsx');
      window.__q.setOwnerScope('owner@example.test');
      window.__path = '/overview';
      window.__params = {};
      window.__renderOwner = () => window.__mount(() => {
        window.__view = window.__ownerUI.useOwnerView(window.__path, window.__params);
        return null;
      });
    });
    for (const path of ['/overview', '/subscriptions', '/organizations/o1', '/organizations', '/users', '/users/u1', '/scans', '/scans/sc1', '/logs', '/system', '/analytics/summary', '/analytics/timeseries']) {
      await page.evaluate((path) => { window.__q.clearQueryCache(); window.__view = null; window.__path = path; window.__renderOwner(); }, path);
      await page.waitForFunction(() => window.__view?.data !== null && !window.__view.loading);
      check(await page.evaluate(() => window.__q.queryCacheSize() === 0), `owner-policy: ${path} never enters the cache`);
    }
  });

  await run('idle-signout', async (page) => {
    const seeded = await page.evaluate(() => window.__q.writeQueryCache('idle-sentinel', 'private', window.__q.cacheTicket()));
    check(seeded, 'idle-signout: the signed-in cache has an entry');
    await page.evaluate(() => {
      window.__advance(10 * 60_000 + 1);
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await page.waitForFunction(() => !localStorage.getItem('cyphward-session'));
    check(await page.evaluate(() => window.__q.queryCacheSize() === 0 && localStorage.getItem('cyphward-idle-timeout') === '1'), 'idle-signout: returning after idle timeout clears cached data');
  });

  await run('owner-session', async (page) => {
    for (const end of ['sign-out', '401']) {
      await page.goto(`${h.origin}/admin/newsletter`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => document.querySelector('main')?.innerText.includes('Cyphward notes n1'));
      check(await page.evaluate(async () => !!(await import('/src/lib/queryCache.ts')).readQueryCache('newsletter:drafts', 'owner')), `owner-session: cache seeded before ${end}`);
      if (end === 'sign-out') {
        await page.evaluate(() => document.querySelector('button.side-out').click());
      } else {
        h.state.failures.add('/owner/users');
        h.state.failStatus = 401;
        await page.evaluate(() => { history.pushState({}, '', '/admin/users'); dispatchEvent(new PopStateEvent('popstate')); });
      }
      await page.waitForFunction(async () => (await import('/src/lib/queryCache.ts')).currentScope('owner') === null);
      check(await page.evaluate(async () => (await import('/src/lib/queryCache.ts')).queryCacheSize() === 0), `owner-session: ${end} clears cached owner data`);
      h.state.failures.clear();
      h.state.failStatus = 500;
    }
  });

  await run('filter-error', async (page) => {
    await page.evaluate(async () => {
      const { useOwnerView } = await import('/src/owner/ui.tsx');
      const { useState } = window.__React;
      window.__q.setOwnerScope('owner@example.test');
      window.__mount(() => {
        const [search, setSearch] = useState('');
        window.__setFilter = setSearch;
        window.__view = useOwnerView('/logs', { q: search });
        return null;
      });
    });
    await page.waitForFunction(() => window.__view?.data !== null && !window.__view.loading);
    h.state.failures.add('/owner/logs');
    await page.evaluate(() => window.__setFilter('no-such-row'));
    await page.waitForFunction(() => !!window.__view?.error && !window.__view.loading);
    check(await page.evaluate(() => window.__view.data === null && !window.__view.placeholder), 'filter-error: failed new filter never displays previous filter rows');
    h.state.failures.clear();
  });

  await run('races', async (page) => {
    await page.evaluate(() => {
      const { useCachedQuery } = window.__q;
      window.__pending = [];
      window.__mount(() => {
        window.__view = useCachedQuery('race', () => new Promise((resolve, reject) => window.__pending.push({ resolve, reject })));
        return null;
      });
    });
    await page.waitForFunction(() => window.__pending.length === 1);
    await page.evaluate(() => { void window.__view.reload(); });
    await page.waitForFunction(() => window.__pending.length === 2);
    await page.evaluate(() => window.__pending[1].resolve('newest'));
    await page.waitForFunction(() => window.__view.data === 'newest');
    await page.evaluate(() => window.__pending[0].resolve('oldest'));
    await sleep(60);
    check(await page.evaluate(() => window.__view.data === 'newest' && window.__q.readQueryCache('race').data === 'newest'), 'races: older success cannot replace newer success or cache');
    await page.evaluate(() => { void window.__view.reload(); });
    await page.waitForFunction(() => window.__pending.length === 3);
    await page.evaluate(() => { void window.__view.reload(); });
    await page.waitForFunction(() => window.__pending.length === 4);
    await page.evaluate(() => window.__pending[2].reject(new Error('old failure')));
    await sleep(60);
    check(await page.evaluate(() => !window.__view.error && window.__view.refreshing), 'races: old failure/finally cannot end the current refresh');
    await page.evaluate(() => window.__pending[3].resolve('current'));
    await page.waitForFunction(() => window.__view.data === 'current');
    await page.evaluate(() => { void window.__view.reload(); });
    await page.waitForFunction(() => window.__pending.length === 5);
    await page.evaluate(() => { window.__q.clearQueryCache(); window.__pending[4].resolve('before write'); });
    await sleep(60);
    check(await page.evaluate(() => window.__view.data === 'current' && !window.__q.readQueryCache('race')), 'races: generation invalidation blocks stale on-screen data as well as cache writes');
    await page.waitForFunction(() => window.__pending.length === 6);
    await page.evaluate(() => window.__pending[5].resolve('after write'));
    await page.waitForFunction(() => window.__view.data === 'after write' && !window.__view.refreshing);
    check(true, 'races: invalidated active request retries with a new ticket and finishes');
    // Own-loader guard independently verifies every condition (including cleanup).
    const guarded = await page.evaluate(async () => {
      const { useRequestGuard } = window.__q;
      window.__mount(() => { window.__begin = useRequestGuard(); return null; });
      await new Promise((r) => setTimeout(r, 30));
      const a = window.__begin();
      const b = window.__begin();
      const superseded = !a.isCurrent() && b.isCurrent();
      window.__q.clearQueryCache();
      const invalidated = !b.isCurrent();
      const c = window.__begin();
      window.__probeRoot.unmount();
      return { superseded, invalidated, unmounted: !c.isCurrent() };
    });
    check(guarded.superseded && guarded.invalidated && guarded.unmounted, 'races: page-loader guard rejects superseded, invalidated and unmounted requests');
  });

  await run('settings-edit', async (page) => {
    await page.goto(`${h.origin}/settings`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#settings-company-name');
    const go = (to) => page.evaluate((to) => { history.pushState({}, '', to); dispatchEvent(new PopStateEvent('popstate')); }, to);
    await go('/findings');
    await page.waitForFunction(() => !document.querySelector('#settings-company-name'));
    let release;
    const held = new Promise((r) => { release = r; });
    h.state.route = async (p, method) => {
      if (p.endsWith('/settings') && method === 'GET') await held;
      return ownerRoute(p);
    };
    await go('/settings');
    await page.waitForSelector('#settings-company-name');
    await page.$eval('#settings-company-name', (el) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, 'Unsaved company edit');
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
    check(await page.$eval('#settings-company-name', (el) => el.value === 'Unsaved company edit'), 'settings-edit: cached profile can be edited during refresh');
    release();
    await settle(page, 100);
    check(await page.$eval('#settings-company-name', (el) => el.value === 'Unsaved company edit'), 'settings-edit: refresh preserves the unsaved profile');
  });

  await run('search-draft', async (page) => {
    for (const [route, selector, loaded] of [
      ['/assets', '[aria-label="Search hostname or IP"]', 'host0.acme.ng'],
      ['/findings', '[aria-label="Search issues"]', 'Missing Email DMARC'],
    ]) {
      h.state.route = (p) => ownerRoute(p);
      await page.goto(`${h.origin}${route}`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction((text) => document.querySelector('main')?.innerText.includes(text), {}, loaded);
      let release;
      let reads = 0;
      const held = new Promise((r) => { release = r; });
      h.state.route = async (p) => {
        if (p.endsWith(`/api/v1${route}`)) {
          reads++;
          await held;
          if (route === '/assets') {
            const [status, body] = ownerRoute(p);
            return [status, { ...body, assets: body.assets.map((a) => ({ ...a, hostname: 'draft-guard.example.test' })) }];
          }
          return [200, { findings: [{ id: 'draft-guard', title: 'Draft guard response', severity: 'high', category: 'DNS & Email Security',
            status: 'open', hostname: 'example.test', created_at: '2026-10-16T09:00:00Z' }], total: 1, categories: {} }];
        }
        return ownerRoute(p);
      };
      await page.evaluate(() => [...document.querySelectorAll('.chip-row button')].find((b) => b.textContent.trim() !== 'all').click());
      for (let n = 0; n < 100 && !reads; n++) await sleep(10);
      check(reads === 1, `search-draft ${route}: filter read is pending`);
      await page.type(selector, 'unsubmitted');
      check(reads === 1, `search-draft ${route}: typing does not submit a read`);
      release();
      const arrived = await page.waitForFunction(() => /draft-guard.example.test|Draft guard response/.test(document.querySelector('main')?.innerText || ''), { timeout: 2000 }).then(() => true, () => false);
      check(arrived, `search-draft ${route}: typing a draft does not cancel the pending filter response`);
      check(await page.$eval(selector, (el) => el.value === 'unsubmitted'), `search-draft ${route}: draft text is preserved`);
    }
  });

  await run('reviewer-policy', async (page) => {
    await page.goto(`${h.origin}/comply?section=reviewers`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.querySelector('main')?.innerText.includes('Reviewer access'));
    await settle(page, 100);
    const cached = await page.evaluate(async () => (await import('/src/lib/queryCache.ts')).readQueryCache('comply:reviewers'));
    check(cached === undefined, 'reviewer-policy: grant and audit reads are never cached');
  });
} finally {
  h.state.failures.clear();
  await h.close();
}
console.log(`cache review: ${checks} checks passed`);
