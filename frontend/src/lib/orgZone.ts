import { useAuth } from './auth';
import { resolveZone } from './datetime';

/** The organisation's display zone (organizations.display_timezone, from sign-in), or Africa/Lagos. */
export function useOrgZone(): string {
  const { organization } = useAuth();
  return resolveZone(organization?.display_timezone);
}
