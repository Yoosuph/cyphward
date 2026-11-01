import { useState, type FormEvent } from 'react';
import StrataField from '../components/StrataField';
import PublicHeader from '../components/PublicHeader';
import PublicFooter from '../components/PublicFooter';
import SocialFloat from '../components/SocialFloat';
import { usePageMotion } from '../lib/usePageMotion';

const TOPICS = [
  { id: 'general', label: 'General' },
  { id: 'product', label: 'Product' },
  { id: 'privacy', label: 'Privacy' },
  { id: 'security', label: 'Security' },
  { id: 'press', label: 'Press' },
];

const DIRECT_LINES = [
  { label: 'PRIVACY', value: 'privacy@cyphward.com', href: 'mailto:privacy@cyphward.com' },
  { label: 'LEGAL', value: 'legal@cyphward.com', href: 'mailto:legal@cyphward.com' },
  { label: 'SECURITY', value: 'security@cyphward.com', href: 'mailto:security@cyphward.com' },
];

const PROFILES = [
  { label: 'X', href: 'https://x.com/cyphward' },
  { label: 'INSTAGRAM', href: 'https://www.instagram.com/cyphward_/' },
  { label: 'LINKEDIN', href: 'https://www.linkedin.com/company/cyphward/' },
];

export default function Contact() {
  const motionRef = usePageMotion<HTMLElement>();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [organization, setOrganization] = useState('');
  const [topic, setTopic] = useState('general');
  const [message, setMessage] = useState('');
  const [website, setWebsite] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    if (message.trim().length < 10) {
      setError('Write a little more so we know what you need.');
      return;
    }
    setBusy(true);
    try {
      const res = await fetch('/api/v1/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, organization, topic, message, website }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = typeof body.detail === 'string' ? body.detail : '';
        throw new Error(detail || 'We could not send that. Email info@cyphward.com.');
      }
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'We could not send that. Email info@cyphward.com.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="landing-wrap">
      <StrataField variant="hero" opacity={0.45} />
      <PublicHeader />
      <main ref={motionRef} className="landing-container relative z-10 subpage">
        <div className="contact-split">
          <aside className="contact-ink rise-in">
            <div>
              <p className="eyebrow mb-4">CONTACT</p>
              <h1 className="page-title">Write to <em>us.</em></h1>
              <a className="contact-mail" href="mailto:info@cyphward.com">info@cyphward.com</a>
            </div>
            <div className="contact-lines">
              <p className="eyebrow mb-3">DIRECT LINES</p>
              <ul>
                {DIRECT_LINES.map(line => (
                  <li key={line.href}>
                    <span>{line.label}</span>
                    <a href={line.href}>{line.value}</a>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="contact-facts">Kano, Nigeria<br />Cyphward Ltd · RC 9921694</p>
              <ul className="contact-socials">
                {PROFILES.map(profile => (
                  <li key={profile.href}>
                    <a href={profile.href} target="_blank" rel="noopener noreferrer">{profile.label}</a>
                  </li>
                ))}
              </ul>
            </div>
          </aside>

          <div className="contact-sheet rise-in rise-in-3">
            {sent ? (
              <div className="contact-sent">
                <p className="eyebrow mb-3">SENT</p>
                <h2>We have it.</h2>
                <p>A reply will come to {email}.</p>
              </div>
            ) : (
              <form onSubmit={onSubmit}>
                <p className="contact-prompt">Tell us what you need. We read every note.</p>
                <fieldset className="topic-picks">
                  <legend>TOPIC</legend>
                  {TOPICS.map(item => (
                    <button
                      key={item.id}
                      type="button"
                      className={topic === item.id ? 'on' : ''}
                      aria-pressed={topic === item.id}
                      onClick={() => setTopic(item.id)}
                    >
                      {item.label}
                    </button>
                  ))}
                </fieldset>
                <div className="contact-grid">
                  <label className="c-field">
                    <span>NAME</span>
                    <input required autoComplete="name" value={name} onChange={e => setName(e.target.value)} maxLength={80} />
                  </label>
                  <label className="c-field">
                    <span>EMAIL</span>
                    <input required type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} />
                  </label>
                  <label className="c-field field-wide">
                    <span>ORGANIZATION</span>
                    <input autoComplete="organization" value={organization} onChange={e => setOrganization(e.target.value)} maxLength={80} />
                  </label>
                  <label className="c-field field-wide">
                    <span>MESSAGE</span>
                    <textarea required rows={6} value={message} onChange={e => setMessage(e.target.value)} maxLength={4000} />
                  </label>
                </div>
                <label className="contact-honey" aria-hidden="true">
                  Website
                  <input tabIndex={-1} autoComplete="off" value={website} onChange={e => setWebsite(e.target.value)} />
                </label>
                {error && <p role="alert" className="contact-error">{error}</p>}
                <button type="submit" className="btn btn-solid" disabled={busy}>
                  {busy ? 'SENDING…' : 'SEND MESSAGE'}
                </button>
              </form>
            )}
          </div>
        </div>
      </main>
      <PublicFooter anchorPrefix="/" />
      <SocialFloat />
    </div>
  );
}
