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
