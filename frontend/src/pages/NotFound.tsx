import { Link } from 'react-router-dom';
import PublicShell from '../components/PublicShell';
import { useAuth } from '../lib/auth';

/**
 * Catch-all unknown route. Signed-in visitors get a way back to the
 * workspace; everyone else goes home. Not prerendered, not in the
 * sitemap — there is nothing to index here.
 */
export default function NotFound() {
  let home = '/';
  let label = 'BACK TO HOME';
  try {
    const { tenant } = useAuth();
    if (tenant) {
      home = '/overview';
      label = 'BACK TO OVERVIEW';
    }
  } catch {
    /* outside auth context — stay public */
  }

  return (
    <PublicShell
      eyebrow="NOT FOUND"
      title={<>Nothing lives <em>here.</em></>}
      lede="The page you asked for does not exist or moved. If you typed the address, check the spelling."
    >
      <div className="flex items-center gap-3">
        <Link to={home} className="btn btn-solid justify-center">
          {label}
        </Link>
        <span className="mono text-[11px] text-soft">Error 404</span>
      </div>
    </PublicShell>
  );
}
