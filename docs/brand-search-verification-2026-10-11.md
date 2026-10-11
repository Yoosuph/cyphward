# Cyphward brand-search check — 11 October 2026

Payment-system activation is deferred at the user's request. This pass checks
the supplied SEO advice and improves company identity on the public site.

## What the live check established

| Claim | Finding |
|---|---|
| Organization schema and social profiles already exist | Confirmed in the HTML returned by `https://cyphward.com/`. Organization and WebSite nodes use stable IDs and link the existing LinkedIn, X and Instagram profiles. |
| Square logo is live | Confirmed: `https://cyphward.com/logo-512.png` is reachable and measures 512 × 512 pixels. |
| About/Pricing are live and in the sitemap | Confirmed: both return HTTP 200, have their own canonicals and indexable server-rendered HTML, and appear in the five-URL sitemap. |
| Landing redirects to the homepage | Confirmed: `/landing` returns HTTP 308 with `Location: /`. Its removal/consolidation in search results depends on Google's recrawl. |
| Only two pages are indexed | Not independently established. Public search results cannot establish an exact count; use the property's Page indexing report and URL Inspection. |
| Google always autocorrects Cyphward to Skyward | Not independently established. The direct Google check reached an unusual-traffic challenge. Other search results surfaced company/founder LinkedIn posts under Cyphward, which shows some discoverable brand material but does not establish Google's spelling behavior. |
| Most remaining work is outside the website | Partly true: indexing and genuine third-party identity references matter, but the live schema/About page lacked the supplied RC number and Kano details. The homepage metadata also described future modules as existing features. |

Google explicitly says `site:` results are not exhaustive and should not be
used to establish how many URLs are indexed. [Google's site-operator guidance](https://developers.google.com/search/docs/monitor-debug/search-operators/all-search-site).

Organization metadata can help disambiguate a company, and consistent
Organization/WebSite names are recommended. This supports the proposed markup,
but it is not a documented switch for disabling search-query spelling correction.
[Google's Organization guidance](https://developers.google.com/search/docs/appearance/structured-data/organization),
[Google's site-name guidance](https://developers.google.com/search/docs/appearance/site-names).

## Company information used

The user confirmed these details from their certificate in this conversation.
They were not independently verified against CAC's registry:

- Brand: **Cyphward**.
- Exact legal name: **CYPHWARD LTD**.
- Registration: **RC 9921694**.
- Incorporation date: **8 October 2026**.
- Location: **Kano, Kano State, Nigeria**.
- Founder: **Yusuf Lawan Nuhu**, already named on the site and in a public founder post.
- Contact: **info@cyphward.com**.

No street address, postal code or telephone number was invented. City/region
fields represent the supplied company location rather than a full street address.

## Changes made locally

- `frontend/index.html`: exact legal name; matching alternate names on Organization
  and WebSite; CAC identifier; full formation date; Kano locality/region; accurate
  description of currently available features.
- `frontend/src/pages/About.tsx`: visible registration, incorporation date,
  Kano location, founder, contact and existing official social links.
- `frontend/scripts/prerender.mjs`: About metadata includes the legal company,
  RC number, location and founder.
- `frontend/public/sitemap.xml`: homepage/About modification dates updated for
  this actual content change.
- Homepage title/Open Graph/Twitter title now match the existing runtime title.

Build passed. The built homepage was submitted as a **code snippet** to the
[Schema Markup Validator](https://validator.schema.org/), which returned
**0 errors and 0 warnings**. Local checks parsed the JSON-LD in the built home,
About and Pricing pages and verified identity fields, visible About facts,
canonicals/indexability and the sitemap. This validates the unpublished build;
it does not mean the live site or Google index has changed.

## After deployment: Search Console work

1. Test the updated live homepage in Schema Markup Validator. Check Organization
   features with Google's Rich Results Test; site-name validation uses Schema
   Markup Validator because the Rich Results Test does not support site names.
2. In the verified `cyphward.com` Search Console property, inspect `/`, `/about`
   and `/pricing`. Record index status, selected canonical and last crawl date.
   Run a live test and request indexing once per changed/unindexed URL.
3. Submit or resubmit `https://cyphward.com/sitemap.xml` and confirm successful
   processing. Repeated submissions of the same URL do not speed crawling.
4. Monitor Page indexing and branded-query impressions. Treat spelling behavior,
   site-name presentation, indexing and ranking as separate outcomes.

Google says recrawling can take days to weeks and does not guarantee indexing.
There is no fixed weeks-to-months promise for brand recognition or the removal
of spelling suggestions. [Google's recrawl guidance](https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl).

No Search Console submission was made: this session had no authenticated access
to the site's property. No third-party listing or social profile was edited.

## Standard description for genuine company profiles

> Cyphward is a Nigerian cybersecurity platform that helps businesses monitor verified domains, understand external security risks, and follow practical remediation guidance.

Use **Cyphward** as the public brand, **CYPHWARD LTD** in legal-name fields,
**RC 9921694** in registration fields and `https://cyphward.com/` as the website.
Keep location, founder and dates consistent. Compliance and Academy are still
in development, so avoid presenting them as shipped features.

Start by checking the existing LinkedIn company page and its website field.
Use reputable company/startup profiles and real programme participation or
editorial coverage. Applying to a grant is not evidence of partnership or
programme membership. Directory submissions are optional, not a guaranteed
route to a knowledge panel; Google lists low-quality directory links among
link-spam examples. [Google's spam policies](https://developers.google.com/search/docs/essentials/spam-policies).

Maintain consistent branding for real audiences. Artificial branded searches,
bots and purchased clicks are not part of this plan.
