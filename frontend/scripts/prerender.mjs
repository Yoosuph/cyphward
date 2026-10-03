/**
 * Post-build prerender: injects real HTML for the public pages into dist/.
 * Runs after `vite build`; uses Vite's SSR module loader (no extra dependencies).
 */
import { createServer } from 'vite';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

const PAGES = [
  { url: '/', file: 'index.html' },
  {
    url: '/privacy',
    file: 'privacy/index.html',
    title: 'Privacy Policy — Cyphward',
    canonical: 'https://cyphward.com/privacy',
  },
  {
    url: '/terms',
    file: 'terms/index.html',
    title: 'Terms of Service — Cyphward',
    canonical: 'https://cyphward.com/terms',
  },
];

const vite = await createServer({
  root,
  configFile: join(root, 'vite.config.ts'),
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'warn',
});

try {
  const { render } = await vite.ssrLoadModule('/src/prerender-entry.tsx');
  const template = readFileSync(join(root, 'dist', 'index.html'), 'utf8');

  // App shell: the pristine post-Vite HTML (asset tags intact, empty root),
  // saved BEFORE prerendering overwrites dist/index.html. SPA routes are
  // rewritten here so /login, /overview etc. boot the real app instead of
  // receiving the prerendered landing markup. Canonical/og:url point at /
  // in the template, so strip them — they would consolidate every app URL
  // onto the landing page in search results.
  const appShell = template
    .replace(/\s*<link rel="canonical" href="[^"]*" \/>/, '')
    .replace(/\s*<meta property="og:url" content="[^"]*" \/>/, '')
    // The template ships an index,follow robots meta for the marketing page;
    // the app shell must not carry it alongside the noindex below (conflicting
    // robots directives are ambiguous to crawlers).
    .replace(/\s*<meta name="robots" content="index, follow[^"]*" \/>/, '')
    .replace(
      '</head>',
      '  <meta name="robots" content="noindex, nofollow" />\n  </head>'
    );
  writeFileSync(join(root, 'dist', 'app.html'), appShell);
  console.log(`wrote dist/app.html (SPA shell, ${appShell.length} bytes)`);

  for (const page of PAGES) {
    const appHtml = render(page.url);
    if (!appHtml || appHtml.length < 500) {
      throw new Error(`prerender produced empty markup for ${page.url}`);
    }
    let html = template.replace('<div id="root"></div>', `<div id="root">${appHtml}</div>`);
    if (page.title && page.canonical) {
      html = html.replace(/<title>[^<]*<\/title>/, `<title>${page.title}</title>`);
      html = html.replace(
        /<link rel="canonical" href="[^"]*" \/>/,
        `<link rel="canonical" href="${page.canonical}" />`
      );
      html = html.replace(
        /<meta property="og:url" content="[^"]*" \/>/,
        `<meta property="og:url" content="${page.canonical}" />`
      );
    }
    const out = join(root, 'dist', page.file);
    mkdirSync(dirname(out), { recursive: true });
    writeFileSync(out, html);
    console.log(`prerendered ${page.url} -> dist/${page.file} (${html.length} bytes)`);
  }
} finally {
  await vite.close();
}
