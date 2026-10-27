# Cyphward newsletter

Double opt-in sign-up, GrokBot drafts, and admin-approved sends through Brevo. The feature is off by default. With `NEWSLETTER_ENABLED` off, every `/api/v1/newsletter/*` endpoint answers 404 and the site shows no form.

| Piece | Where |
| --- | --- |
| Migration | `supabase/migrations/20261026100000_newsletter.sql` |
| Rules, tokens, draft schema, rendering, store | `backend/app/core/newsletter.py` |
| Endpoints | `backend/app/api/newsletter.py` |
| Brevo list and campaign calls | `backend/app/services/newsletter_brevo.py` |
| Sign-up form | `frontend/src/components/NewsletterSubscribe.tsx` (landing footer), `frontend/src/pages/Newsletter.tsx` (`/newsletter`) |
| Result pages | `frontend/src/pages/NewsletterResult.tsx` (`/newsletter/confirmed`, `/newsletter/unsubscribed`) |
| Tests | `backend/tests/test_newsletter.py`, `backend/tests/test_newsletter_postgres.py`, `frontend/scripts/check-newsletter.mjs` (`npm run test:newsletter-ui`) |

## How it works

1. **Subscribe** (`POST /api/v1/newsletter/subscribe`). The visitor enters an email address and ticks the consent box, which starts unticked. The box carries this wording, version `2026-10-26.v1`:
   > I agree that Cyphward may email me news about its product and security and regulation updates. I can withdraw at any time.

   The server stores the address in lower case, the consent time, the wording version and the source page (`landing_footer` or `newsletter_page`). It also stores a salted hash of each token, never the token itself. The answer is always the same 202 message, padded to the same minimum time, whatever state the address is in. The confirmation email goes out after the response. An address that is already confirmed is left alone and gets no email.

   Rate limits: 10 requests per hour per IP, which returns 429. Three confirmation emails per hour per address; beyond that the request is dropped silently and still gets the same 202. Bucket keys hold hashes, not addresses or IPs.

2. **Confirmation email.** It is sent from `news@cyphward.com` through the existing mailer, with the sender passed as a parameter and the mailer's list-2 campaign fallback switched off. It carries:
   - the confirm link, valid for 72 hours;
   - an unsubscribe link;
   - the postal line;
   - RFC 8058 `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` headers pointing at the unsubscribe endpoint.

   It adds no images and no tracking.

   **Links never act on a GET.** Mail scanners and link previews open links, so a GET on a confirm or unsubscribe link changes nothing. It shows a small page whose button POSTs the token in the form body, and the POST does the work. The page sends `Cache-Control: no-store`, `Referrer-Policy: no-referrer` and a CSP without scripts. Access logs mask `token=` values.

3. **Confirm** (`GET` page, then `POST /api/v1/newsletter/confirm` with the token in the body). The address becomes `confirmed` and is added to the Brevo newsletter list, with its unsubscribe token in the contact attribute. The visitor is redirected to `/newsletter/confirmed?result=ok|expired|invalid`. An unconfirmed address is never put on the list.

   Rate limits: 30 requests per hour per IP, which returns 429. Ten attempts per hour per subscriber; beyond that the link reads as not working, with no 429 that would point at the address.

4. **Unsubscribe** (`GET` page, then `POST /api/v1/newsletter/unsubscribe`). One button, no sign-in. Mail providers using RFC 8058 POST `List-Unsubscribe=One-Click` to the same URL, with the token in its query string, and get a plain 200. One-click requests have no per-IP limit, because providers send them from a few shared servers and the token authorises each one. A global ceiling of 20,000 per hour applies. The button on the page keeps a limit of 60 per hour per IP. The address becomes `unsubscribed` at once and is removed from the Brevo list. The visitor is redirected to `/newsletter/unsubscribed?result=ok|invalid`. The address receives nothing more unless it subscribes again; a new subscription starts a new double opt-in and retires the old links.

   The unsubscribe token is derived with HMAC from `NEWSLETTER_TOKEN_SECRET`, the subscriber id and a generation number. The same link therefore works in the confirmation email and in every issue. Issues get it through the Brevo contact attribute (`{{ contact.CW_UNSUB_TOKEN }}`).

   **Mail headers on issues.** Brevo's campaign API has no option for custom mail headers; it offers only `header`/`footer` HTML and `unsubscriptionPageId`. Cyphward therefore cannot put its own `List-Unsubscribe` header on campaigns. Brevo adds its own List-Unsubscribe to marketing campaigns, pointing at Brevo's unsubscribe. A Brevo-side unsubscribe blocks the contact in Brevo at once, and the next send's reconciliation marks it unsubscribed here. Check the actual headers on the first test-send.

5. **Drafts.** GrokBot creates drafts with `POST /api/v1/newsletter/drafts`. The draft key can create drafts and do nothing else.

6. **Preview and send** (admins only; see below).
   - `GET /api/v1/newsletter/drafts` lists the drafts, each with a rendered preview, plus the confirmed-subscriber count.
   - `POST /api/v1/newsletter/drafts/{id}/send` with `{"approve": true, "subject": "<the draft's exact subject>"}`:
     1. claims the issue, once only, in the same transaction as its audit row;
     2. reconciles the Brevo list with the database;
     3. creates the campaign to that list and sends it.

   A second send attempt gets 409. If anything fails after the claim, the issue stays unsendable, so it can never go out twice. Ask GrokBot for a new draft instead.

   **Reconciliation:**
   - It removes every list member who is not confirmed here.
   - It adds any confirmed subscriber who is missing from the list.
   - It rewrites the unsubscribe attribute of any confirmed contact whose value is stale or missing.
   - Any address that Brevo reports as unsubscribed or blocked is marked unsubscribed here too.
   - It then reads the list again and refuses to create the campaign unless every member is confirmed here and carries its correct unsubscribe token. The admin sees *"Nothing was sent"*.

   **Who counts as an admin:**
   - the platform owner, signed in to the owner console (cookie session; sending also requires the console Origin);
   - platform staff with a live grant carrying the new scope `platform:newsletter` (bearer token).

   `platform:read` is not enough.

7. **Audit.** Every action is written to `audit_log`, with `resource_type = 'newsletter_issue'`:
   - `newsletter.draft_created`
   - `newsletter.send_approved`
   - `newsletter.campaign_created`
   - `newsletter.sent`
   - `newsletter.send_failed`

## Setup (founder; nothing here has been done)

1. **Brevo.**
   - Confirm that `news@cyphward.com` is a verified sender. It is already verified, according to the brief.
   - Create a new contact list for the newsletter and note its id. Do not use list 2, which the transactional mailer's campaign fallback writes to; the server refuses list 2.
   - Create the contact attribute `CW_UNSUB_TOKEN` (type: text), or pick another name and set `NEWSLETTER_BREVO_UNSUB_ATTRIBUTE` to it (capitals, digits and `_` only). Without it, every send is refused before a campaign is created.
   - In Brevo, check what campaign footer and unsubscribe handling Brevo adds by default. Every issue already carries Cyphward's own one-click link. Brevo-side unsubscribes are pulled back into the database before each send.
2. **Database.** Apply `supabase/migrations/20261026100000_newsletter.sql`. It is additive and idempotent, and it starts with `lock_timeout 5s` and `statement_timeout 60s`.
3. **Environment.** Set these on the API service. Leaving any of them unset keeps the feature off.

   | Variable | Value |
   | --- | --- |
   | `NEWSLETTER_DRAFT_API_KEY` | 32+ random characters, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Give it only to GrokBot. |
   | `NEWSLETTER_TOKEN_SECRET` | 32+ random characters, generated the same way. Never change it casually (see the runbook). |
   | `NEWSLETTER_BREVO_LIST_ID` | the new list's id |
   | `NEWSLETTER_BREVO_UNSUB_ATTRIBUTE` | `CW_UNSUB_TOKEN` (default) |
   | `NEWSLETTER_POSTAL_LINE` | the postal/contact line printed in every email, e.g. the registered company name, RC number, address and contact address |
   | `NEWSLETTER_PUBLIC_BASE_URL` | `https://cyphward.com` (default). The links point at `<base>/api/v1/newsletter/...`, which the site proxies to the API, and the API redirects to `<base>/newsletter/...`. |
   | `BREVO_API_KEY` | already set for the mailer |
   | `NEWSLETTER_ENABLED` | `true`, set last |

4. **Admins.** Grant `platform:newsletter` to any staff member who may send. The owner console owner can send without it.
5. **Check before the first real issue.**
   - Subscribe a mailbox you control, confirm it, and check that the confirmation email shows the postal line and both links.
   - Use Brevo's own test-send on the first campaign to confirm that `{{ contact.CW_UNSUB_TOKEN }}` is filled in.

The site needs no `vercel.json` change: `/newsletter*` is served by the existing SPA fallback, and `/api/*` is already proxied.

## GrokBot request format

```
POST https://cyphward.com/api/v1/newsletter/drafts
Authorization: Bearer <NEWSLETTER_DRAFT_API_KEY>
Content-Type: application/json
```

```json
{
  "subject": "Cyphward notes for November",
  "preview": "A product change, one security tip and a regulation update.",
  "sections": [
    {
      "type": "product",
      "heading": "Reports now show the scan date",
      "body": "Every report now shows when the scan that produced it ran.",
      "links": [{ "label": "See pricing", "url": "https://cyphward.com/pricing" }]
    },
    {
      "type": "security_tip",
      "heading": "Publish a DMARC record",
      "body": "Start with p=none and read the aggregate reports for two weeks.\nThen move to quarantine."
    },
    {
      "type": "regulation",
      "heading": "Guidance note on breach reporting",
      "body": "The regulator published a guidance note on how and when to report a personal data breach.",
      "sources": [{ "title": "NDPC guidance note", "url": "https://ndpc.gov.ng/" }]
    }
  ]
}
```

A successful request returns `201 {"id": "<uuid>", "status": "draft", "created_at": "..."}`. A request without a valid key gets 401. With the feature off, it gets 404.

**Rules.** The schema is strict. Breaking any rule below returns 422 and stores nothing.

- **Fields:** extra fields are rejected and types must match exactly.
- **Subject and preview:**
  - `subject`: up to 120 characters.
  - `preview`: up to 160 characters.
  - No links in either.
- **Sections:** 1 to 5, each with:
  - `type`: one of `product`, `security_tip`, `regulation`;
  - `heading`: up to 100 characters;
  - `body`: plain text, up to 1500 characters. Line breaks become paragraphs. No HTML, no Markdown links, and no URLs or bare domain names; put those in `links` or `sources`.
- **`links`:** up to 3, each with:
  - `label`: up to 60 characters;
  - `url`: `https://` only, up to 300 characters, a public host name, no credentials, no custom port.
- **`sources`:** required for every `regulation` item, each with a `title` and an `https://` URL.
- **Every text field:**
  - No `<` or `>`.
  - No control or invisible characters, such as zero-width or bidi controls.
  - No template markers (`{{ }}`, `{% %}`).
  - None of these claim words or phrases, matched as whole words, in any case, with plain inflections: compliant, certified, certification, satisfies, adequate, guarantee, passes audit, compliance score, meets the requirement, is met, fully compliant, is compliant.
  - Nothing that the product's shared C6 filter (`backend/app/compliance/practitioner.py`) refuses. That filter also catches, among others, complies, conforms, approved, sufficient, "in line with" and "NDPA ready". It sees through accents, look-alike letters, digits used as letters and split-up words.
  - A newsletter-only allow-list (`_set_aside_news_wording` in `backend/app/core/newsletter.py`) lets two ordinary regulation-news shapes past the C6 check. It removes only the trigger word, so C6 still checks every other word:
    - **"approved"** passes only when a public body approved it and the next noun is an instrument: guidance, guidelines, regulation(s), rules, framework, code, bill, act, amendment or forms. An example is "The NDPC approved new guidance".
    - **"meet"** passes only as the plain verb before "the … date/deadline/timeline", and never with you, your, customers, Cyphward or an organisation as the subject. An example is "How to meet the NDPA filing date".

    "The NDPC approved your setup", "Regulators approved this product", "meets the NDPA" and "Cyphward customers meet the NDPC filing deadline" stay refused.

    Separately, the newsletter also refuses any form of "meet" whose subject is you, your, customers, Cyphward or an organisation, whatever follows.

## Operations runbook

**Unsubscribe someone by hand.** Use this when someone asks by email. Run it as the database owner, not the app role:

```sql
UPDATE newsletter_subscribers
SET status = 'unsubscribed', unsubscribed_at = now(), confirm_token_hash = NULL,
    confirm_expires_at = NULL, updated_at = now()
WHERE email_normalised = lower(btrim('person@example.com')) AND status <> 'unsubscribed';
```

Then remove the address from the newsletter list in Brevo, in Contacts, then the list. If you forget, the next send removes it anyway: reconciliation runs before every campaign. Reply to the person to confirm.

**Rotate the GrokBot draft key.** Do this when it may have leaked, and routinely.

1. Generate a new value with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. Set `NEWSLETTER_DRAFT_API_KEY` to it on the API service and redeploy. The old key stops working as soon as the new process serves.
3. Give the new key to GrokBot.
4. Check `audit_log` for `newsletter.draft_created` rows created since the suspected leak, and do not send drafts you did not expect.

A leaked draft key can create drafts and nothing else. It cannot send, read subscribers or change the sender.

**`NEWSLETTER_TOKEN_SECRET`.** Rotating it retires every unsubscribe link already delivered. Only rotate it if it has leaked. The next send's reconciliation rewrites every contact's attribute with the new token. People holding older emails will need the link in the newest issue, or can write in.

**A send failed.**
- *"Nothing was sent: the mailing list could not be prepared"*: no campaign exists. Fix the cause (Brevo key, list id, attribute), then ask GrokBot to resubmit the draft and send the new one.
- *"Brevo did not confirm the send of campaign N"*: open campaign N in Brevo first. It may have gone out. Never send a copy until you know.

In both cases `send_error` on the issue and the `newsletter.send_failed` audit row hold the details.

**Pausing.** Do not switch `NEWSLETTER_ENABLED` off while confirmed subscribers exist. With the flag off, the unsubscribe links in issues already sent return 404. To pause, simply do not send.
