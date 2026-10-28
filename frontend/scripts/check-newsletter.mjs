// Newsletter sign-up and result pages (docs/newsletter/README.md). Every API call is answered from fixtures.
//   flag off: no form on the landing footer, /newsletter is the 404 page
//   flag on: the audit (no overflow, 44px targets on phones, labels, names, focus rings, contrast, no claim wording)
//   on /newsletter and the landing at 1440/390/320 in both themes; the consent box starts unticked and is required;
//   a bad address or no consent sends nothing; keyboard-only subscribe; the success state and toast; the shared
//   error panel with a working retry; the confirm and unsubscribe result pages.
import assert from "node:assert/strict";
import { UI_BANNED, WIDTHS, audit, settle, startHarness } from "./lib/ui-refine-harness.mjs";

const SUBSCRIBED = "You are subscribed. We have sent a confirmation email with an unsubscribe link.";
const OLD_DOUBLE_OPT_IN = /check your inbox|confirm by email|confirm your address|within 72 hours|finish subscribing/i;
const CONSENT = "I agree that Cyphward may email me news about its product and security and regulation updates. I can withdraw at any time.";
const h = await startHarness();
const problems = [];
const posts = [];
let subscribeStatus = 202;
let enabled = false;

h.state.route = (p, method, request) => {
  if (p === "/api/v1/newsletter/status") return enabled ? [200, { enabled: true }] : [404, { detail: "Not Found" }];
  if (p === "/api/v1/newsletter/subscribe" && method === "POST") {
    posts.push(JSON.parse(request.postData() || "{}"));
    return subscribeStatus === 202
      ? [202, { message: SUBSCRIBED }]
      : [subscribeStatus, { detail: "Internal Server Error" }];
  }
  return undefined;
};

const check = (label, r) => {
  for (const key of ["small", "unlabelled", "nameless", "skips", "noRing", "lowContrast", "bannedHits", "landmarks", "pageErrors"]) {
    if (r[key]?.length) problems.push(`${label}: ${key} ${JSON.stringify(r[key].slice(0, 6))}`);
  }
  if (r.overflow > 0) problems.push(`${label}: horizontal overflow ${r.overflow}px`);
  if (r.h1 !== 1) problems.push(`${label}: ${r.h1} h1 headings (want 1)`);
};

async function open(route, { width = 390, height = 844, theme = "dark" } = {}) {
  const tab = await h.newPage({ theme, signedIn: false });
  await tab.page.setViewport({ width, height });
  await tab.page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
  await settle(tab.page, 600);
  return tab;
}

try {
  // 1. Flag off: nothing is exposed.
  {
    const { page, close } = await open("/");
    assert.equal(await page.$('[data-testid="newsletter-form"]'), null, "flag off: no form in the landing footer");
    await close();
    const nf = await open("/newsletter");
    const text = await nf.page.evaluate(() => document.body.innerText);
    assert.match(text, /Nothing lives/i, "flag off: /newsletter is the 404 page");
    assert.equal(await nf.page.$('[data-testid="newsletter-form"]'), null);
    await nf.close();
  }

  enabled = true;

  // 2. Audit the sign-up page and the landing footer.
  for (const [name, route] of [["newsletter", "/newsletter"], ["landing", "/"]]) {
    for (const theme of ["dark", "light"]) {
      const { page, errors, close } = await h.newPage({ theme, signedIn: false });
      for (const [label, width, height] of WIDTHS) {
        if (theme === "light" && label === "320") continue;
        await page.setViewport({ width, height });
        await page.goto(`${h.origin}${route}`, { waitUntil: "domcontentloaded" });
        await settle(page, 700);
        assert.ok(await page.$('[data-testid="newsletter-form"]'), `${name} ${theme} ${label}: the form shows when the flag is on`);
        await page.evaluate(() => document.querySelector('[data-testid="newsletter-form"]').scrollIntoView());
        const r = await audit(page, { mobile: width < 768, tabStops: name === "newsletter" && theme === "dark" ? 40 : 0 });
        check(`${name} ${theme} ${label}`, { ...r, pageErrors: errors.splice(0) });
        const sizes = await page.evaluate(() => {
          const form = document.querySelector('[data-testid="newsletter-form"]');
          const box = (el) => { const r = el.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; };
          return { input: box(form.querySelector('input[type="email"]')), consent: box(form.querySelector(".newsletter-consent")),
                   button: box(form.querySelector('button[type="submit"]')) };
        });
        for (const [k, [w, ht]] of Object.entries(sizes)) {
          if (ht < 44 || w < 44) problems.push(`${name} ${theme} ${label}: ${k} is ${w}x${ht}, under 44px`);
        }
      }
      await close();
    }
  }

  // 3. The form itself: labelled native email field, unticked consent with the exact wording.
  {
    const { page, close } = await open("/newsletter");
    assert.ok(!OLD_DOUBLE_OPT_IN.test(await page.evaluate(() => document.body.innerText)), "no 'confirm by email' wording on the form");
    const form = await page.evaluate(() => {
      const f = document.querySelector('[data-testid="newsletter-form"]');
      const email = f.querySelector('input[type="email"]');
      const box = f.querySelector('input[type="checkbox"]');
      return {
        emailLabel: document.querySelector(`label[for="${CSS.escape(email.id)}"]`)?.textContent,
        autocomplete: email.autocomplete,
        checked: box.checked,
        consentText: box.closest("label").textContent.trim(),
      };
    });
    assert.equal(form.emailLabel, "Email address");
    assert.equal(form.autocomplete, "email");
    assert.equal(form.checked, false, "the consent box starts unticked");
    assert.equal(form.consentText, CONSENT, "the consent wording is exact");

    // No consent: nothing is sent; the error is announced and focus moves to the box.
    await page.type('input[type="email"]', "reader@example.com");
    await page.click('button[type="submit"]');
    await settle(page, 200);
    assert.equal(posts.length, 0, "no request without consent");
    assert.match(await page.$eval('[role="alert"]', (n) => n.textContent), /Tick the box/);
    assert.equal(await page.evaluate(() => document.activeElement?.type), "checkbox");

    // A bad address: nothing is sent.
    await page.focus('input[type="email"]');
    await page.keyboard.down("Control");
    await page.keyboard.press("KeyA");
    await page.keyboard.up("Control");
    await page.keyboard.press("Backspace");
    await page.keyboard.type("not-an-address");
    assert.equal(await page.$eval('input[type="email"]', (n) => n.value), "not-an-address");
    await page.click(".newsletter-consent input");
    await page.click('button[type="submit"]');
    await settle(page, 200);
    assert.equal(posts.length, 0, "no request with an invalid address");
    assert.match(await page.$eval('[role="alert"]', (n) => n.textContent), /valid email/);
    await close();
  }

  // 4. Keyboard only: Tab to the field, type, Tab to the box, Space, Tab to the button, Enter.
  {
    const { page, close } = await open("/newsletter", { width: 1440, height: 900 });
    await page.focus('input[type="email"]');
    await page.keyboard.type("Reader@Example.com");
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement?.type), "checkbox", "Tab reaches the consent box");
    await page.keyboard.press("Space");
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("type")), "submit", "Tab reaches the button, skipping the hidden field");
    await page.keyboard.press("Enter");
    await settle(page, 400);
    assert.equal(posts.length, 1, "one request");
    assert.deepEqual(posts[0], { email: "Reader@Example.com", consent: true, consent_wording_version: "2026-10-26.v1", source: "newsletter_page", website: "" });
    const done = await page.evaluate(() => ({
      status: document.querySelector('[data-testid="newsletter-done"] [role="status"]')?.textContent || "",
      toast: document.querySelector(".toasts")?.textContent || "",
    }));
    assert.equal(done.status.trim(), SUBSCRIBED, "single opt-in: subscribed at once");
    assert.match(done.toast, /You are subscribed/);
    assert.ok(!OLD_DOUBLE_OPT_IN.test(await page.evaluate(() => document.body.innerText)), "no double opt-in wording");
    await close();
  }

  // 5. Footer form sends source=landing_footer.
  {
    const { page, close } = await open("/", { width: 390, height: 844 });
    await page.evaluate(() => document.querySelector('[data-testid="newsletter-form"]').scrollIntoView());
    await page.type('[data-testid="newsletter-form"] input[type="email"]', "footer@example.com");
    await page.click('[data-testid="newsletter-form"] .newsletter-consent input');
    await page.click('[data-testid="newsletter-form"] button[type="submit"]');
    await settle(page, 400);
    assert.equal(posts.at(-1).source, "landing_footer");
    await close();
  }

  // 6. Server failure: the shared error panel with a retry that works, no raw server wording.
  {
    subscribeStatus = 500;
    const { page, close } = await open("/newsletter");
    await page.type('input[type="email"]', "retry@example.com");
    await page.click(".newsletter-consent input");
    await page.click('button[type="submit"]');
    await settle(page, 400);
    assert.ok(await page.$('[data-testid="state-error"]'), "a failed subscribe shows the shared error panel");
    const text = await page.evaluate(() => document.body.innerText);
    assert.ok(!/internal server error|status \d{3}/i.test(text), "no raw server wording");
    subscribeStatus = 202;
    const before = posts.length;
    const retry = await page.$('[data-testid="state-error"] button');
    await retry.click();
    await settle(page, 400);
    assert.equal(posts.length, before + 1, "retry resends");
    assert.ok(await page.$('[data-testid="newsletter-done"]'), "retry reaches the success state");
    await close();
  }

  // 7. Result pages.
  const results = [
    ["/newsletter/confirmed?result=ok", /You are subscribed/],
    ["/newsletter/confirmed?result=expired", /expired/],
    ["/newsletter/confirmed?result=invalid", /did not work/],
    ["/newsletter/confirmed", /did not work/],
    ["/newsletter/unsubscribed?result=ok", /You are unsubscribed/],
    ["/newsletter/unsubscribed?result=invalid", /did not work/],
  ];
  for (const [route, expected] of results) {
    for (const [label, width, height] of [["1440", 1440, 900], ["320", 320, 720]]) {
      const { page, errors, close } = await open(route, { width, height });
      assert.match(await page.evaluate(() => document.querySelector("h1")?.textContent || ""), expected, route);
      const r = await audit(page, { mobile: width < 768, tabStops: 0 });
      check(`${route} ${label}`, { ...r, pageErrors: errors.splice(0) });
      await close();
    }
  }

  // 8. Privacy policy: the Newsletter section says what is collected, why, who processes it, how to leave,
  // how long it is kept, and that Cyphward is not a law firm; no claim wording.
  {
    const { page, errors, close } = await open("/privacy", { width: 390, height: 844 });
    const section = await page.evaluate(() => {
      const h = [...document.querySelectorAll("h2")].find((n) => n.textContent.trim() === "Newsletter");
      return h ? h.closest("section").innerText : "";
    });
    assert.ok(section, "the privacy policy has a Newsletter section");
    for (const needed of [/email address/, /wording version/, /source page/, /monthly/, /Brevo/, /unsubscribe link/,
                          /contact form/, /until you unsubscribe/, /honour the unsubscribe/, /not a law firm/,
                          /that it is unsubscribed/, /how many times/, /one-way hash of your last unsubscribe link/,
                          /contact that is off the mailing list/, /network \(IP\) address/, /24 hours/]) {
      assert.match(section, needed);
    }
    const lower = section.toLowerCase();
    for (const w of UI_BANNED) assert.ok(!lower.includes(w), `privacy newsletter section: ${w}`);
    const r = await audit(page, { mobile: true, tabStops: 0 });
    check("/privacy 390", { ...r, pageErrors: errors.splice(0) });
    await close();
  }

  const allText = posts.map((p) => JSON.stringify(p)).join(" ").toLowerCase();
  for (const w of UI_BANNED) assert.ok(!allText.includes(w));
} finally {
  await h.close();
}

if (problems.length) {
  console.error(`newsletter UI: ${problems.length} problem(s)\n` + problems.join("\n"));
  process.exit(1);
}
console.log("newsletter UI: flag gate, audit (3 widths, 2 themes), consent, keyboard, single opt-in success, error retry, result pages and privacy section pass");
