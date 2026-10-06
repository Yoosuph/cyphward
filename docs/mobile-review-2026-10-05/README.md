# CYPHWARD mobile review

**Reviewed:** 5 October 2026  
**Scope:** Public landing, login and signup; the authenticated overview, domains, findings and remediation pages; setup verification, team settings, representative dialogs and drawers; tablet and landscape navigation.  
**Method:** Chromium touch and viewport emulation with the production web fonts and synthetic accounts, organizations, domains and findings. No customer session or live API was used. Twenty-one screen captures and viewport measurements are in this directory. The run used the repository state at the time of review. This was not a native iOS/Android or physical-device test.

## Findings

### P1 — Navigation vanishes at tablet widths

The public landing page hides its section links below 900 px but also hides its menu button from 768 px up. The app hides its side navigation from 901 px down; its bottom dock remains visible through 900 px, but the dock’s More Pages panel is hidden from 768 px up. This leaves the 768–900 px range without working access to the other sections. It also affects phones held in landscape. At 820 px, Chromium displayed neither landing navigation option, and the app opened its More Pages state in React while CSS kept the panel invisible.

**Fix:** Give mobile/tablet navigation one shared breakpoint. Show a usable menu while the full navigation is hidden; make sure the selected section stays reachable at 820 px and landscape sizes around 844 × 390 px.

### P1 — Six-digit email verification is clipped on 320 px screens

The six code boxes are fixed at 46 px each with 10 px gaps. Their combined 326 px width exceeds the space in the setup card on a 320 px viewport. Chromium placed the first box at x = −3 px and the last at x = 277–323 px, cutting both edges off. At 360 and 390 px, the boxes fit the viewport but extend beyond the card's content area.

**Fix:** Size the boxes and gaps from the available card width, or use a single one-time-code input styled to look segmented. Preserve paste, numeric keyboard, automatic advance and accessible labeling.

### P2 — Operational tables require horizontal scrolling to reach important actions

On a 390 px viewport, the Domains table measured about 903 px in a 360 px container, the Remediation table about 893 px, and the Team table 560 px in a 312 px container. Asset, Scan and Report tables also set minimum widths of 760, 620 and 640 px. Their overflow containers do allow sideways scrolling, so columns are reachable; on a phone, however, status, assignee and row actions sit outside the first visible columns.

**Fix:** Show a short card or row summary on phones, with the principal action visible. Keep the full table for wide screens and offer horizontal scrolling for secondary details.

### P2 — Social buttons overlap landing-page text

The three fixed social controls remain on the right edge at mobile width. At 390 px, they covered words in the hero paragraph around y = 370–470. Their touch areas measure 30 × 30 px on small screens.

**Fix:** Remove the floating stack on narrow screens or move social links into the footer or mobile menu. Prefer larger touch areas for any controls that remain fixed on screen.

### P2 — The More Pages sheet does not act like a modal on mobile

At 390 px, opening the sheet did not stop the page behind it from scrolling: a scroll gesture moved the page to y = 300 while the sheet stayed open. Pressing Tab moved focus to the CyphBot button behind the sheet. The global Escape handler does close the menu.

**Fix:** Lock background scroll while the sheet is open, place initial focus inside it, keep keyboard focus within it, and restore focus to the Menu button when it closes. Label the dialog as modal only once those behaviors are implemented.

### P2 — Some phone controls are too small for comfortable tapping

Several mobile controls are only 30–38 px high: theme/sign-out buttons are 32 px, the landing menu button 32 px, floating social buttons 30 px, some filters 24–32 px, and the email-code resend button approximately 44 px wide. These can be difficult to tap accurately on a phone.

**Fix:** Raise frequently used controls to roughly 44 px high where the layout allows it, and increase icon button hit areas without enlarging the visible icons.

## What works well

At 390 px, the main page stays within the viewport, the score card and summary metrics adapt into a readable single-column/two-column layout, and the findings list becomes a usable card layout. Login, signup, domain details, the finding drawer and new-task dialog fit the screen. The finding drawer uses a bottom sheet on mobile. The custom font files loaded during the review, so these observations include the intended typography.

## Evidence

- [320 px email verification](320-email-verification.png)
- [390 px email verification](390-email-verification.png)
- [820 px app navigation](820-menu.png)
- [390 px domain list](390-domains.png)
- [390 px remediation tasks](390-remediation.png)
- [390 px finding detail sheet](390-finding-drawer.png)
- [390 px landing hero](390-public-landing.png)
- [390 px team settings](390-team.png)
- [Viewport and element measurements](measurements.json)

## Recommended implementation order

1. Fix the 768–900 px navigation gap and 320 px email-code input.
2. Make mobile domain, asset, scan, remediation, report and member lists expose key status and actions without requiring a wide table.
3. Remove the floating social overlap and improve touch target sizes.
4. Complete the More Pages sheet's focus and scroll behavior.
5. Add a maintained mobile viewport checklist around 320, 360, 390 and 430 px, 768 and 820 px, and phone landscape.

These are review findings. No product source code was changed.
