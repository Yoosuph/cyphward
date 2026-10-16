# Owner console runbook

The platform owner console (`admin.cyphward.com`) gives the owner of the Cyphward platform a view of every customer. It is a separate app from the customer product, with its own sign-in. The access model is in `backend/app/core/owner.py`; the tables are created by `supabase/migrations/20261016120000_owner_console.sql`.

## Who can sign in

An account can sign in when all of the following are true:

1. It has a row in `platform_owners`. The application's database role can only **read** this table, so owners can only be added or removed by an operator with direct database access.
2. It has a password. Google sign-in does not open the console; use "Forgot password" to set one.
3. It has an authenticator app enrolled: Settings → Security → Authenticator app.

Every sign-in needs email + password + the current authenticator code, and each code works only once. Sessions end after 30 minutes without activity, and after 8 hours at most. Resetting the password, or switching the authenticator off or on again, ends all owner sessions.

## Dedicated admin login (recommended)

A console-only login exists only for this console. It can't sign in to the customer app, Google sign-in doesn't work for it, and "Forgot password" never emails it, so a compromised mailbox can't take it over. The operator creates it with a **setup password** that opens a 24-hour, single-use setup. At first sign-in (leave the code empty), the owner chooses a new password (12+ characters) and scans the authenticator QR code. The setup password then stops working.

```sql
-- as postgres; replace the email and hash (bcrypt/argon2 as produced by backend hash_password)
WITH p AS (
  INSERT INTO profiles (email, full_name, role, password_hash, provider, email_verified_at)
  VALUES ('admin@example.com', 'Cyphward Admin', 'Member', '<hash of the setup password>', 'email', now())
  RETURNING id)
INSERT INTO platform_owners (user_id, note, console_only) SELECT id, 'dedicated admin login', true FROM p;
INSERT INTO owner_setups (user_id, expires_at)
SELECT id, now() + interval '24 hours' FROM profiles WHERE email = 'admin@example.com';
```

**Recovery** (lost phone or forgotten password): set a new setup password hash, clear the authenticator, and open a new setup window:

```sql
UPDATE profiles SET password_hash = '<new setup hash>', totp_secret_enc = NULL, totp_enrolled_at = NULL
WHERE email = 'admin@example.com';
INSERT INTO owner_setups (user_id, expires_at)
SELECT id, now() + interval '24 hours' FROM profiles WHERE email = 'admin@example.com'
ON CONFLICT (user_id) DO UPDATE SET expires_at = EXCLUDED.expires_at, completed_at = NULL;
```

## Add or remove the owner (operator SQL)

Run these as the database owner (`postgres`), never through the application:

```sql
-- add (the account must already have a password and an enrolled authenticator)
INSERT INTO platform_owners (user_id, note)
SELECT id, 'platform owner' FROM profiles WHERE email = 'owner@example.com'
ON CONFLICT (user_id) DO NOTHING;

-- remove (takes effect on the next request; open sessions stop working)
DELETE FROM platform_owners WHERE user_id = (SELECT id FROM profiles WHERE email = 'owner@example.com');
```

## Domain setup (once)

1. DNS (Namecheap → cyphward.com → Advanced DNS): add a `CNAME` with host `admin` and value `cname.vercel-dns.com`.
2. Vercel → the Cyphward project → Settings → Domains: add `admin.cyphward.com`.

`vercel.json` keeps the console out of search engines: `X-Robots-Tag: noindex` and a noindex `robots.txt`. It also sends `/admin` on the customer hosts to the console. On localhost the console runs at `http://127.0.0.1:5181/admin`.

## What the console shows (read-only)

- Overview: users, organizations, domains, 24-hour scans, the queue, expired claims, subscriptions, sign-ups, recorded invoices and recent activity.
- Organizations and Users: searchable lists, plus details (members, domains, plan and billing, scans, open findings, sessions, activity).
- Subscriptions: plans, renewal and trial dates, and invoices. Invoices are records, not proof of payment.
- Scans: every scan with a real state (queued, delayed over 10 minutes, running, worker stopped, completed, failed), plus per-stage results and failed or omitted hosts.
- Logs: customer events (`audit_log`) and owner console events (`owner_audit`).
- System: database, background jobs, deployed commit, scanner activity, scheduled runs and integrations.

Secrets are never selected: password hashes, authenticator secrets, token hashes, claim tokens and DNS verification tokens.

## Audit

`owner_audit` records every sign-in attempt (success, denied with a reason, throttled), every sign-out and every console view, including what was opened. The app role can only insert and read it. It has no foreign keys, so deleting a customer leaves it intact. If an audit write fails, the request fails and returns no data.
