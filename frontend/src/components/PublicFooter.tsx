import { Link } from 'react-router-dom';
import { Twitter, Instagram, Linkedin } from 'lucide-react';
import CyphwardLogo from './CyphwardLogo';

/**
 * The full landing footer, shared by every public page so the bottom of
 * the site never drifts between routes. `anchorPrefix` is '' on the
 * landing itself and '/' everywhere else (e.g. /pricing links to /#layers).
 */
export default function PublicFooter({ anchorPrefix = '' }: { anchorPrefix?: string }) {
  const a = (hash: string) => `${anchorPrefix}${hash}`;
  return (
      <footer className="landing-footer">
        <div className="landing-container">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8 pb-12 border-b border-line">
            <div>
              <div className="mb-3">
                <CyphwardLogo variant="full" size={20} />
              </div>
              <p className="text-xs mono text-soft leading-relaxed">
                African-built cyber security platform.
                Technical evidence for your compliance programme, layer by layer defense for the continent.
              </p>
              <div className="flex items-center gap-2.5 mt-4">
                <a
                  href="https://x.com/cyphward"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Cyphward on X"
                  className="w-8 h-8 rounded border border-line bg-inset flex items-center justify-center text-soft hover:text-ink hover:border-accent transition-colors"
                >
                  <Twitter size={14} />
                </a>
                <a
                  href="https://www.instagram.com/cyphward_/"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Cyphward on Instagram"
                  className="w-8 h-8 rounded border border-line bg-inset flex items-center justify-center text-soft hover:text-ink hover:border-accent transition-colors"
                >
                  <Instagram size={14} />
                </a>
                <a
                  href="https://www.linkedin.com/company/cyphward/"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Cyphward on LinkedIn"
                  className="w-8 h-8 rounded border border-line bg-inset flex items-center justify-center text-soft hover:text-ink hover:border-accent transition-colors"
                >
                  <Linkedin size={14} />
                </a>
              </div>
            </div>

            <div>
              <p className="eyebrow mb-3">DEFENSE LAYERS</p>
              <ul className="space-y-2 text-xs mono text-soft">
                <li><a href={a('#layers')} className="hover:text-ink">Overview &amp; Score</a></li>
                <li><a href={a('#layers')} className="hover:text-ink">Assets &amp; Domains</a></li>
                <li><a href={a('#layers')} className="hover:text-ink">Findings &amp; Evidence</a></li>
                <li><a href={a('#layers')} className="hover:text-ink">Scans &amp; Reports</a></li>
                <li><a href={a('#layers')} className="hover:text-ink">Fixes</a></li>
              </ul>
            </div>

            <div>
              <p className="eyebrow mb-3">ACCESS</p>
              <ul className="space-y-2 text-xs mono text-soft">
                <li><Link to="/pricing" className="hover:text-ink">Pricing</Link></li>
                <li><Link to="/about" className="hover:text-ink">About</Link></li>
                <li><Link to="/login" className="hover:text-ink">Sign In</Link></li>
                <li><Link to="/signup" className="hover:text-ink">Create a Business Account</Link></li>
                <li><Link to="/forgot-password" className="hover:text-ink">Reset Password</Link></li>
              </ul>
            </div>

            <div>
              <p className="eyebrow mb-3">REGULATIONS WE BUILD FOR</p>
              <ul className="space-y-2 text-xs mono text-soft">
                <li>NDPA 2023 (Nigeria)</li>
                <li>CBN Cybersecurity Guidelines</li>
                <li>Kenya DPA 2019 / PoPIA ZA</li>
                <li>AU Malabo Convention</li>
              </ul>
            </div>
          </div>

          <div className="pt-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs mono text-soft">
            <div>
              © 2026 CYPHWARD LTD · ALL RIGHTS RESERVED · PLATFORM v0.1.0
            </div>
            <div className="flex items-center gap-4">
              <Link to="/terms" className="hover:text-ink transition-colors">TERMS</Link>
              <Link to="/privacy" className="hover:text-ink transition-colors">PRIVACY</Link>
              <Link to="/health" className="flex items-center gap-2 hover:text-ink transition-colors">
                <span className="live-dot" /> SYSTEM STATUS: OPERATIONAL
              </Link>
            </div>
          </div>
        </div>
      </footer>
  );
}
