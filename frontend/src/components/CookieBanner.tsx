import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

const STORAGE_KEY = 'cyphward-cookie-consent';

/**
 * Bottom-left cookie notice. Essential storage only (sign-in session,
 * display preferences) — matches Privacy §09; no ad trackers either way.
 */
export default function CookieBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      if (!localStorage.getItem(STORAGE_KEY)) setVisible(true);
    } catch {
      /* storage blocked — stay hidden */
    }
  }, []);

  const decide = (value: 'accepted' | 'essential') => {
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch {
      /* ignore */
    }
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <aside className="cookie-banner" role="region" aria-label="Cookie notice">
      <p>
        <strong className="cookie-banner-title">COOKIES</strong>
        We store essential cookies only — your sign-in session and display
        preferences. No ad trackers, ever.{' '}
        <Link to="/privacy">READ THE PRIVACY POLICY ↗</Link>
      </p>
      <div className="cookie-banner-actions">
        <button type="button" className="btn-mini" onClick={() => decide('essential')}>
          ESSENTIAL ONLY
        </button>
        <button
          type="button"
          className="btn btn-solid btn-mini"
          onClick={() => decide('accepted')}
        >
          ACCEPT
        </button>
      </div>
    </aside>
  );
}
