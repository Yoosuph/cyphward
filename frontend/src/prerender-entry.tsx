/**
 * Build-time entry used by scripts/prerender.mjs (NOT part of the client bundle).
 * Renders the public pages to HTML strings so search engines and first paints
 * receive real content instead of "Loading your workspace…".
 */
import { renderToString } from 'react-dom/server';
import { Route, Routes } from 'react-router-dom';
import { StaticRouter } from 'react-router-dom/server';
import Landing from './pages/Landing';
import Privacy from './pages/Privacy';
import Terms from './pages/Terms';
import Pricing from './pages/Pricing';
import About from './pages/About';

export function render(url: string): string {
  return renderToString(
    <StaticRouter location={url}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </StaticRouter>
  );
}
