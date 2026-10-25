"""In-page detection of a consent banner and its first-level controls.

Runs in the page after it has settled, with no clicks. It reads layout and button
labels only and returns a small fixed-shape object: marker names and booleans,
never page text. Open shadow roots are searched; closed ones and iframes are not,
which is a stated limit of the observation.
"""

BANNER_SCRIPT = r"""
() => {
  const MARKERS = [
    ["onetrust", "#onetrust-banner-sdk, #onetrust-consent-sdk"],
    ["cookiebot", "#CybotCookiebotDialog"],
    ["usercentrics", "#usercentrics-root, #usercentrics-cmp"],
    ["didomi", "#didomi-host, .didomi-popup-container"],
    ["quantcast", ".qc-cmp2-container, #qc-cmp2-ui"],
    ["trustarc", "#truste-consent-track, #teconsent"],
    ["cookieyes", ".cky-consent-container, .cky-consent-bar"],
    ["osano", ".osano-cm-window, .osano-cm-dialog"],
    ["complianz", "#cmplz-cookiebanner-container, .cmplz-cookiebanner"],
    ["iubenda", "#iubenda-cs-banner"],
    ["cookie_law_info", "#cookie-law-info-bar"],
    ["klaro", ".klaro .cookie-notice, .klaro .cookie-modal"],
    ["termly", "#termly-code-snippet-support"],
  ];
  const TOPIC = /cookie|consent|tracking|privacy (choices|preferences|settings)/i;
  const ACCEPT = /^(accept|agree|allow|ok|okay|got it|i agree|i understand|yes|continue)\b|accept all|allow all|agree (and|&)/i;
  const REJECT = /\b(reject|decline|deny|refuse|disagree|no,? thanks)\b|(only|just) (necessary|essential)|(necessary|essential) (cookies )?only|continue without (accepting|agreeing)/i;
  const vw = window.innerWidth, vh = window.innerHeight;

  function* walk(root) {
    const stack = [root];
    while (stack.length) {
      const node = stack.pop();
      if (node.nodeType === 1) {
        yield node;
        if (node.shadowRoot) stack.push(node.shadowRoot);
      }
      const kids = node.children || node.childNodes || [];
      for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
    }
  }
  function visible(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    return s.display !== "none" && s.visibility !== "hidden" && parseFloat(s.opacity || "1") > 0.05;
  }
  function area(el) { const r = el.getBoundingClientRect(); return r.width * r.height; }
  function inView(el) {
    const r = el.getBoundingClientRect();
    return r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw;
  }
  function label(el) {
    return (el.innerText || el.value || el.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 60);
  }
  function qsa(root, selector) {
    const out = [];
    for (const el of walk(root)) { try { if (el.matches(selector)) out.push(el); } catch (e) {} }
    return out;
  }

  let marker = null, container = null;
  for (const [name, selector] of MARKERS) {
    const hit = qsa(document, selector);
    if (hit.length) {
      marker = marker || name;
      const shown = hit.find(visible);
      if (shown) { marker = name; container = shown; break; }
    }
  }
  if (!container) {
    let best = null;
    for (const el of walk(document.documentElement)) {
      const s = getComputedStyle(el);
      const pos = s.position;
      const dialog = el.getAttribute("role") === "dialog" || el.getAttribute("aria-modal") === "true" || el.tagName === "DIALOG";
      if (!(pos === "fixed" || pos === "sticky" || dialog) || !visible(el)) continue;
      const text = (el.innerText || "").slice(0, 1500);
      if (!TOPIC.test(text) || text.length > 1400) continue;
      if (!el.querySelector("button, [role=button], a, input[type=button], input[type=submit]")) continue;
      if (!best || area(el) < area(best)) best = el;
    }
    if (best) { container = best; marker = marker || "generic_dialog"; }
  }
  if (!container) {
    return {detected: false, in_first_view: false, cms_marker: marker, accept_control: false, reject_control: "not_detected"};
  }
  const controls = qsa(container, "button, [role=button], a, input[type=button], input[type=submit]").filter(visible);
  let accept = null, reject = null;
  for (const el of controls) {
    const text = label(el);
    if (!text) continue;
    if (REJECT.test(text)) { if (!reject || area(el) > area(reject)) reject = el; }
    else if (ACCEPT.test(text)) { if (!accept || area(el) > area(accept)) accept = el; }
  }
  let level = "not_detected";
  if (reject) {
    const real = (el) => el.tagName === "BUTTON" || el.tagName === "INPUT" || el.getAttribute("role") === "button";
    level = accept && real(reject) && area(reject) >= 0.5 * area(accept) ? "same_level" : "less_prominent";
    if (!accept) level = "less_prominent";
  }
  return {detected: true, in_first_view: inView(container), cms_marker: marker, accept_control: !!accept, reject_control: level};
}
"""
