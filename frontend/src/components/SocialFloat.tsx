import { Twitter, Instagram, Linkedin } from 'lucide-react';

/**
 * Fixed side column of social links, stacked on every public page.
 * Shown on desktop and phones (the CSS sizes it down on small screens).
 */
export default function SocialFloat() {
  return (
    <div className="social-float" aria-label="Cyphward on social media">
      <a
        href="https://x.com/cyphward"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Cyphward on X"
        title="Cyphward on X"
        className="social-float-btn"
      >
        <Twitter size={14} />
      </a>
      <a
        href="https://www.instagram.com/cyphward_/"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Cyphward on Instagram"
        title="Cyphward on Instagram"
        className="social-float-btn"
      >
        <Instagram size={14} />
      </a>
      <a
        href="https://www.linkedin.com/company/cyphward/"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Cyphward on LinkedIn"
        title="Cyphward on LinkedIn"
        className="social-float-btn"
      >
        <Linkedin size={14} />
      </a>
    </div>
  );
}
