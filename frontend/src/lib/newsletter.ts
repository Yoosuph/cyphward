import { useEffect, useState } from 'react';

/**
 * Newsletter client (docs/newsletter/README.md). The consent wording must match the server's
 * CONSENT_WORDING exactly (backend/tests/test_newsletter.py checks it); the version is stored with
 * every subscription.
 */
export const CONSENT_WORDING =
  'I agree that Cyphward may email me news about its product and security and regulation updates. I can withdraw at any time.';
export const CONSENT_WORDING_VERSION = '2026-10-26.v1';

export type NewsletterSource = 'landing_footer' | 'newsletter_page';

let statusRequest: Promise<boolean> | null = null;

/** True only when the server says the newsletter is on (it answers 404 while the flag is off). */
export function newsletterEnabled(): Promise<boolean> {
  if (!statusRequest) {
    statusRequest = fetch('/api/v1/newsletter/status', { headers: { Accept: 'application/json' } })
      .then(async (res) => res.ok && (await res.json().catch(() => null))?.enabled === true)
      .catch(() => false);
  }
  return statusRequest;
}

/** null while the status is loading; never true during prerender. */
export function useNewsletterEnabled(): boolean | null {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    newsletterEnabled().then((on) => { if (live) setEnabled(on); });
    return () => { live = false; };
  }, []);
  return enabled;
}

export class SubscribeError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

/** The server's answer (the same for every address): single opt-in, nothing left to confirm. */
export const SUBSCRIBED_MESSAGE = 'You are subscribed. We have sent a confirmation email with an unsubscribe link.';

/** Sends the subscription. The server answers the same way for every address. */
export async function subscribeToNewsletter(email: string, source: NewsletterSource, website = ''): Promise<string> {
  const res = await fetch('/api/v1/newsletter/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      email: email.trim(),
      consent: true,
      consent_wording_version: CONSENT_WORDING_VERSION,
      source,
      website,
    }),
  });
  if (res.status === 422) throw new SubscribeError('Check the email address and try again.', 422);
  if (!res.ok) throw new SubscribeError('We could not take your subscription just now.', res.status);
  const body = await res.json().catch(() => ({}));
  return typeof body.message === 'string' ? body.message : SUBSCRIBED_MESSAGE;
}
