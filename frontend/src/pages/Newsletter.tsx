import PublicShell from '../components/PublicShell';
import NewsletterSubscribe from '../components/NewsletterSubscribe';
import { LoadingPanel } from '../components/ui/StatePanels';
import { useNewsletterEnabled } from '../lib/newsletter';
import NotFound from './NotFound';

/** /newsletter: the sign-up page. A 404 page while the server's newsletter flag is off. */
export default function Newsletter() {
  const enabled = useNewsletterEnabled();
  if (enabled === false) return <NotFound />;
  return (
    <PublicShell
      eyebrow="NEWSLETTER"
      title={<>News from <em>Cyphward.</em></>}
      lede="Occasional email about the product, practical security tips and regulation updates that matter to Nigerian software teams. We confirm your address first, and every email has a one-click unsubscribe link."
    >
      {enabled === null ? <LoadingPanel label="the sign-up form" lines={2} /> : <NewsletterSubscribe source="newsletter_page" heading="Subscribe" />}
    </PublicShell>
  );
}
