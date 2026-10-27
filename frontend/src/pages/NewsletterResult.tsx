import { Link, useSearchParams } from 'react-router-dom';
import PublicShell from '../components/PublicShell';

type Kind = 'confirmed' | 'unsubscribed';

const COPY: Record<Kind, Record<string, { eyebrow: string; title: string; lede: string }>> = {
  confirmed: {
    ok: {
      eyebrow: 'SUBSCRIPTION CONFIRMED',
      title: 'You are subscribed.',
      lede: 'Thank you for confirming. The next issue will come from news@cyphward.com, and every issue has a one-click unsubscribe link.',
    },
    expired: {
      eyebrow: 'LINK EXPIRED',
      title: 'That link has expired.',
      lede: 'Confirmation links work for 72 hours. Subscribe again and we will send a new one.',
    },
    invalid: {
      eyebrow: 'LINK NOT RECOGNISED',
      title: 'That link did not work.',
      lede: 'It may have been replaced by a newer email or already used to unsubscribe. Subscribe again to get a fresh link.',
    },
  },
  unsubscribed: {
    ok: {
      eyebrow: 'UNSUBSCRIBED',
      title: 'You are unsubscribed.',
      lede: 'We will not send the newsletter to this address again unless you subscribe again.',
    },
    invalid: {
      eyebrow: 'LINK NOT RECOGNISED',
      title: 'That link did not work.',
      lede: 'It may come from an older email. To stop the newsletter, use the link in the most recent issue, or write to info@cyphward.com and we will remove the address.',
    },
  },
};

/** /newsletter/confirmed and /newsletter/unsubscribed: where the email links land (no sign-in). */
export default function NewsletterResult({ kind }: { kind: Kind }) {
  const [params] = useSearchParams();
  const result = params.get('result') || 'invalid';
  const copy = COPY[kind][result] || COPY[kind].invalid;
  const offerSubscribe = !(kind === 'confirmed' && result === 'ok');
  return (
    <PublicShell eyebrow={copy.eyebrow} centered title={copy.title} lede={copy.lede}>
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/" className="btn btn-solid touch-target justify-center">Back to home</Link>
        {offerSubscribe && <Link to="/newsletter" className="btn touch-target justify-center">Subscribe again</Link>}
      </div>
    </PublicShell>
  );
}
