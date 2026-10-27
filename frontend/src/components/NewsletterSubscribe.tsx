import { useId, useRef, useState, type FormEvent } from 'react';
import { MailCheck } from 'lucide-react';
import { useToast } from './Toast';
import { ErrorPanel, humanError } from './ui/StatePanels';
import {
  CONSENT_WORDING,
  subscribeToNewsletter,
  useNewsletterEnabled,
  type NewsletterSource,
} from '../lib/newsletter';

/**
 * Newsletter sign-up: a labelled native email field, an unticked consent box with the exact wording,
 * and one button. Renders nothing while the server's newsletter flag is off (or still loading), so a
 * prerendered page never shows it.
 */
export default function NewsletterSubscribe({ source, heading = 'Newsletter' }: { source: NewsletterSource; heading?: string }) {
  const enabled = useNewsletterEnabled();
  const toast = useToast();
  const id = useId();
  const emailRef = useRef<HTMLInputElement>(null);
  const consentRef = useRef<HTMLInputElement>(null);
  const [email, setEmail] = useState('');
  const [consent, setConsent] = useState(false);
  const [website, setWebsite] = useState('');
  const [busy, setBusy] = useState(false);
  const [fieldError, setFieldError] = useState<'email' | 'consent' | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (enabled !== true) return null;

  // Sends what the form already validated; the error panel's retry calls this directly.
  const send = async () => {
    setFailure(null);
    setBusy(true);
    try {
      const message = await subscribeToNewsletter(email, source, website);
      setDone(message);
      toast('Check your inbox to confirm your subscription.');
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status === 422) {
        setFieldError('email');
        setTimeout(() => emailRef.current?.focus(), 0);
      } else {
        setFailure(humanError(err, 'We could not take your subscription just now. Try again in a moment.', { passDetail: false }));
        toast('Subscription not sent. Try again in a moment.');
      }
    } finally {
      setBusy(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!emailRef.current?.checkValidity() || !email.trim()) {
      setFieldError('email');
      emailRef.current?.focus();
      return;
    }
    if (!consent) {
      setFieldError('consent');
      consentRef.current?.focus();
      return;
    }
    setFieldError(null);
    void send();
  };

  const emailId = `${id}-email`;
  const consentId = `${id}-consent`;
  const errorId = `${id}-error`;

  if (done) {
    return (
      <section className="newsletter-box" aria-labelledby={`${id}-heading`} data-testid="newsletter-done">
        <h2 id={`${id}-heading`} className="newsletter-heading">{heading}</h2>
        <div className="newsletter-done" role="status">
          <MailCheck size={18} aria-hidden="true" className="text-accent" />
          <p>{done}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="newsletter-box" aria-labelledby={`${id}-heading`} data-testid="newsletter-form">
      <h2 id={`${id}-heading`} className="newsletter-heading">{heading}</h2>
      <p className="newsletter-lede">Product news, security tips and regulation updates. Confirm by email; leave with one click.</p>
      {failure ? (
        <ErrorPanel title="We could not sign you up" message={failure} onRetry={() => void send()} retrying={busy} />
      ) : (
        <form onSubmit={submit} noValidate className="newsletter-form">
          <label htmlFor={emailId} className="newsletter-label">Email address</label>
          <input
            ref={emailRef}
            id={emailId}
            type="email"
            name="email"
            autoComplete="email"
            inputMode="email"
            required
            maxLength={254}
            value={email}
            onChange={(e) => { setEmail(e.target.value); if (fieldError === 'email') setFieldError(null); }}
            aria-invalid={fieldError === 'email' || undefined}
            aria-describedby={fieldError === 'email' ? errorId : undefined}
            className="newsletter-input"
          />
          <label htmlFor={consentId} className="newsletter-consent">
            <input
              ref={consentRef}
              id={consentId}
              type="checkbox"
              checked={consent}
              onChange={(e) => { setConsent(e.target.checked); if (fieldError === 'consent') setFieldError(null); }}
              aria-invalid={fieldError === 'consent' || undefined}
              aria-describedby={fieldError === 'consent' ? errorId : undefined}
            />
            <span>{CONSENT_WORDING}</span>
          </label>
          <label className="contact-honey" aria-hidden="true">
            Website
            <input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
          </label>
          {fieldError && (
            <p id={errorId} role="alert" className="newsletter-error">
              {fieldError === 'email' ? 'Enter a valid email address.' : 'Tick the box to agree before subscribing.'}
            </p>
          )}
          <button type="submit" className="btn btn-solid touch-target newsletter-submit" disabled={busy}>
            {busy ? 'Sending…' : 'Subscribe'}
          </button>
        </form>
      )}
    </section>
  );
}
