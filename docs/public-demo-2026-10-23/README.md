# Public demo sessions

The demo button can open an explicitly configured existing account without a password or verification code. Public sessions are limited to one workspace with effective member permissions. Normal owner and staff sessions retain their existing permissions and MFA policy. No database migration, password reset, membership change or MFA exemption is needed.

Configure the backend with all three identity pins, plus the enable flag:

```
DEMO_LOGIN_ENABLED=true
DEMO_LOGIN_USER_ID=<profile UUID>
DEMO_LOGIN_ORG_ID=<workspace UUID>
DEMO_LOGIN_EMAIL=<verified account email>
```

The account must have exactly one workspace membership, a verified email, no enrolled MFA/TOTP and no platform-owner grant. Owner membership and platform-staff grants can remain on the normal account; they do not become available to a public demo session. A partial or invalid target configuration disables demo entry rather than falling back to the old sample identity.

## Permission boundaries

- A signed access-token claim binds demo sessions to the configured workspace. Bootstrap and workspace listings show only that workspace and report the effective role as member.
- All authenticated write requests are blocked except the existing evidence interpretation and chat endpoints. AI use retains the shared demo account quota.
- Platform-staff routes reject public demo sessions independently of the account's grants. The owner console uses its own authentication and the demo endpoint refuses platform-owner identities.
- Refresh tokens carry a scoped prefix whose entire value is hashed in the existing session table. Removing or altering the prefix invalidates the token; each rotation preserves the scope. No new session schema is required.
- Existing per-session revocation, expiry and refresh replay checks apply. Enabling an MFA factor or changing/disabling the configured target makes public session validation fail.
- The customer app labels these sessions as view-only. No password is sent to or embedded in the browser. The login copy no longer claims that the selected workspace is synthetic.

With no public identity pins, the legacy sample account path keeps its existing password and role checks. Its seed IDs remain fixed; configuring a public target does not repurpose the sample seed or deletion scripts. The old sample account is retained until separately removed.

## Verification

122 focused backend checks passed across public demo sessions, ordinary authentication, MFA, Google step-up, platform-staff access, the owner console and core API behavior. Coverage includes refresh scope preservation, stripped refresh-token rejection, replay rejection, write denial, cross-workspace denial after a new membership, platform access denial and independent normal-owner sessions.

Frontend production build and prerender passed.

Live cutover verification on 23 October 2026 passed: the production demo endpoint selected the pinned account and InnovaTech workspace, issued no MFA challenge and exposed only member access. Staff access, owner export and an invalid domain write were denied. Token refresh retained the restriction; replay of the previous refresh token was denied. The verification session was logged out.

An anonymous Chromium browser at 390 × 844 clicked the production login page's demo button and reached the app dashboard as the selected account, with the view-only banner, without entering any credentials or verification code. That browser's session was also logged out. The account already had no enrolled MFA/TOTP; no factor, password, ownership or staff-grant record was changed. The old synthetic demo account remains intact.

Render configuration uses its [individual environment-variable endpoint](https://api-docs.render.com/reference/update-env-var), preserving unrelated settings. Environment changes need a deployment before the running service uses them.
