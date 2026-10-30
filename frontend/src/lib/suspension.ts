/* Organisation suspension in the customer app (admin phase 2, backend core/suspension.py).
 *
 * While the owner has suspended an organisation, its members can sign in and read everything, but every change is
 * refused by the API with 403 and the code `organization_suspended`. The app shows a banner on every page and
 * disables the main write buttons. The flag comes from the sign-in bootstrap (`organization.suspended`); if a
 * suspension starts mid-session, the first refused write flips it through SUSPENDED_EVENT (lib/api.ts).
 */

export const SUSPENDED_CODE = 'organization_suspended';
export const SUSPENDED_EVENT = 'cyphward:organization-suspended';

/** Reviewed wording. Plain English, no claim language (backend/tests/test_ux_copy_claims.py). */
export const SUSPENDED_TITLE = 'This organisation is suspended.';
export const SUSPENDED_BODY =
  'Changes are paused: new scans, domains, settings, members, compliance records, documents, packs and snapshots. ' +
  'Scheduled scans are paused too and start again when the suspension is lifted. You can still sign in and read ' +
  'your dashboards, scans, findings, reports and compliance pages.';
/** Tooltip on a disabled write button. */
export const SUSPENDED_HINT = 'Paused while this organisation is suspended';

let flaggedOrg: string | null = null;

/** True once a write for this organisation was refused with the suspension code in this session. */
export function suspensionSeen(orgId?: string | null): boolean {
  return flaggedOrg !== null && (!orgId || flaggedOrg === '*' || flaggedOrg === orgId);
}

/** Called by the API client when a write is refused with the suspension code. */
export function flagSuspended(orgId: string | null): void {
  flaggedOrg = orgId || '*';
  try {
    window.dispatchEvent(new Event(SUSPENDED_EVENT));
  } catch {
    // no window (prerender)
  }
}

/** Props for a write button: disabled with an explanation while suspended. */
export function writeGuard(suspended: boolean, disabled = false): { disabled: boolean; title?: string; 'aria-describedby'?: string } {
  return suspended
    ? { disabled: true, title: SUSPENDED_HINT, 'aria-describedby': 'org-suspended-banner' }
    : { disabled };
}
