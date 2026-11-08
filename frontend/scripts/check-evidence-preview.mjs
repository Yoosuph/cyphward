// Evidence file upload and preview (docs/evidence-preview-2026-11-07) against a stubbed API. Nothing reaches a server.
//   1. drop zone: idle, drag-over, uploading and done states; a dropped file and a keyboard upload (Enter opens the
//      picker); progress driven by the request's upload events; Cancel aborts the request (by keyboard) and focus
//      comes back; a server error shows reviewed wording (never the raw server text) with a working retry
//   2. preview: PNG and JPG in an <img> from a blob URL fetched through the API with the session, PDF in an
//      <object type="application/pdf"> (or the fallback when the browser cannot show it), DOCX shows details and
//      Download only (no bytes fetched); a skeleton while loading; an error state with a retry; the blob URL is
//      revoked on close; Escape and the close button return focus to the row's Preview button; the Download button
//      uses the attachment-only link; no storage URL ever appears in the page and nothing requests the storage host
//   3. the production security policy (vercel.json) served on the page: images still preview; the PDF shows the
//      fallback text and Download instead of an empty box
//   4. layouts at 1440, 390 and 320: no horizontal scroll, the dialog full screen on phones with the close control
//      visible and 44px targets
//   5. reduced motion: the check, the new row, the progress bar and the dialog change instantly
//   6. no verdict language in any state
// EVIDENCE_PREVIEW_SHOTS=<dir> also saves JPEG screenshots of the dialog for PNG, PDF and DOCX at 390 and 320 there
// (each must be under 150 KB).
import assert from "node:assert/strict";
import { createServer } from "vite";
import puppeteer from "puppeteer-core";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";

const frontend = fileURLToPath(new URL("..", import.meta.url));
process.chdir(frontend);
import { DISCLAIMER, BANNED, ORG_ZONE, BROWSER_ZONE, user, org, domain, overview, members, freshQuestions } from "./lib/compliance-fixtures.mjs";

const CLAIM_WORDS = [...new Set([...BANNED, "compliant", "certified", "certification", "satisfies", "adequate", "guarantee",
  "passes audit", "compliance score", "meets the requirement"])];
const STORAGE_HOST = "files.example.test";
const SHOTS = process.env.EVIDENCE_PREVIEW_SHOTS ? path.resolve(frontend, "..", process.env.EVIDENCE_PREVIEW_SHOTS) : null;
const MAX_SHOT_BYTES = 150 * 1024;
const PROD_CSP = (() => {
  const conf = JSON.parse(fs.readFileSync(path.join(frontend, "..", "vercel.json"), "utf8"));
  for (const block of conf.headers || []) for (const h of block.headers || []) if (h.key === "Content-Security-Policy") return h.value;
  throw new Error("vercel.json has no Content-Security-Policy");
})();

// ── Real sample bytes ─────────────────────────────────────────────────────────
const CRC_TABLE = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
const crc32 = (buf) => { let c = 0xffffffff; for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, "latin1"), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function makePng(width, height) {
  const raw = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (width * 3 + 1)] = 0;
    for (let x = 0; x < width; x++) {
      const i = y * (width * 3 + 1) + 1 + x * 3;
      const band = y > height * 0.2 && y < height * 0.32 && x > width * 0.1 && x < width * 0.7;
      const line = y > height * 0.45 && (y % 18 < 4) && x > width * 0.1 && x < width * (0.9 - (y % 54) / 200);
      const [r, g, b] = band ? [198, 58, 20] : line ? [87, 82, 68] : [248, 246, 240];
      raw[i] = r; raw[i + 1] = g; raw[i + 2] = b;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}
function makePdf(text) {
  const stream = `BT /F1 20 Tf 60 720 Td (${text}) Tj ET`;
  const objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let out = "%PDF-1.4\n";
  const offsets = [];
  objs.forEach((o, i) => { offsets.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}
const PNG = makePng(480, 300);
const PDF = makePdf("DPO appointment letter (sample)");
const DOCX = Buffer.from("PK\x03\x04 sample word bytes the preview must never fetch", "latin1");
const BYTES = { "ef-png": [PNG, "image/png"], "ef-pdf": [PDF, "application/pdf"] };

const KEY = "dpo.designated";
const row = (id, name, content_type, type_label, size_bytes, uploaded_at) => ({ id, question_key: KEY, attestation_id: "a-dpo", display_name: name,
  content_type, type_label, size_bytes, sha256: "e".repeat(64), uploaded_at, uploaded_by: "Ada Obi" });
const freshFiles = () => [
  row("ef-png", "office-signage-photo.png", "image/png", "PNG image", PNG.length, "2026-10-21T09:00:00Z"),
  row("ef-pdf", "dpo-appointment-letter.pdf", "application/pdf", "PDF", PDF.length, "2026-10-17T09:00:00Z"),
  row("ef-docx", "board-minutes-october.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Word document (DOCX)", 48213, "2026-10-12T09:00:00Z"),
];
const KIND_OF = { pdf: ["application/pdf", "PDF"], png: ["image/png", "PNG image"], jpg: ["image/jpeg", "JPEG image"], jpeg: ["image/jpeg", "JPEG image"],
  docx: ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Word document (DOCX)"] };

let checks = 0;
const ok = (cond, msg) => { checks++; assert.ok(cond, msg); };
const eq = (a, b, msg) => { checks++; assert.deepEqual(a, b, msg); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const server = await createServer({ root: frontend, server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
let browser;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cyph-evidence-"));
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || "/usr/bin/chromium", headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  let files = freshFiles();
  const state = { uploadMode: "ok", pending: null, contentDelay: 0, failContent: 0, csp: false };
  const log = { content: [], download: [], uploads: [], storage: [] };
  const reset = () => { files = freshFiles(); Object.assign(state, { uploadMode: "ok", pending: null, contentDelay: 0, failContent: 0 }); for (const k of Object.keys(log)) log[k].length = 0; };
  const json = (request, status, body) => request.respond({ status, contentType: "application/json", body: JSON.stringify(body) }).catch(() => {});
  const saveUpload = (request, key, name) => {
    const ext = name.split(".").pop().toLowerCase();
    const [content_type, type_label] = KIND_OF[ext] || KIND_OF.pdf;
    const made = { ...row(`ef-new-${log.uploads.length}`, name, content_type, type_label, 14, new Date().toISOString()), question_key: key, uploaded_by: "Compliance Review" };
    files.unshift(made);
    return json(request, 201, made);
  };

  await page.setRequestInterception(true);
  page.on("request", async (request) => {
    const url = new URL(request.url());
    if (url.hostname === STORAGE_HOST) { log.storage.push(url.href); return void request.abort().catch(() => {}); }
    // Only web requests are stubbed: the browser's own PDF viewer loads its parts over chrome:, chrome-extension: and blob:.
    if (url.protocol !== "http:" && url.protocol !== "https:") return void request.continue().catch(() => {});
    if (!url.pathname.startsWith("/api/")) {
      if (url.origin !== origin) return void request.abort().catch(() => {});
      // The production page policy, served on the HTML document when asked (part 3).
      if (state.csp && request.isNavigationRequest() && request.resourceType() === "document") {
        const res = await fetch(url.href);
        return void request.respond({ status: res.status, contentType: "text/html", body: await res.text(), headers: { "Content-Security-Policy": PROD_CSP } }).catch(() => {});
      }
      return void request.continue().catch(() => {});
    }
    const method = request.method();
    const p = url.pathname;
    if (p.endsWith("/auth/bootstrap")) return json(request, 200, { user, email_verified: true, memberships: [{ org: { ...org, plan: "growth" }, role: "owner", domains: [domain] }] });
    if (p.endsWith("/compliance/overview")) return json(request, 200, overview("growth"));
    if (p.endsWith("/compliance/questionnaire")) {
      const questions = freshQuestions();
      return json(request, 200, { disclaimer: DISCLAIMER, version: "ndpa-gaid-questionnaire-v1", register_version: "x", display_timezone: ORG_ZONE,
        answered: questions.filter((q) => q.shown && q.answer_state !== "unanswered").length, questions });
    }
    if (p.includes("/compliance/evidence-files")) {
      const one = p.match(/\/evidence-files\/([^/]+)(\/download|\/content)?$/);
      if (!one && method === "GET") {
        return json(request, 200, { files, usage: { files: files.length, bytes: 1 }, uploads_available: true,
          limits: { max_bytes: 10 * 1024 * 1024, max_files: 100, max_total_bytes: 500 * 1024 * 1024, extensions: ["docx", "jpeg", "jpg", "pdf", "png"], label: "x" } });
      }
      if (!one && method === "POST") {
        const key = url.searchParams.get("question_key");
        const name = decodeURIComponent(request.headers()["x-file-name"] || "");
        log.uploads.push({ key, name, auth: request.headers().authorization });
        if (state.uploadMode === "hold") { state.pending = { request, key, name }; return; }
        if (state.uploadMode === "fail500") { state.uploadMode = "ok"; return json(request, 500, { detail: "Internal Server Error: psycopg.OperationalError at line 42" }); }
        if (state.uploadMode === "raw422") { state.uploadMode = "ok"; return json(request, 422, { detail: "Traceback (most recent call last): secret internals" }); }
        return void setTimeout(() => saveUpload(request, key, name), 150);
      }
      if (one && one[2] === "/content" && method === "GET") {
        log.content.push({ id: one[1], auth: request.headers().authorization, cache: request.headers()["cache-control"] || "" });
        const respond = () => {
          if (state.failContent > 0) { state.failContent--; return json(request, 502, { detail: "The preview could not be loaded. Try again." }); }
          const found = BYTES[one[1]];
          if (!found) return json(request, 415, { detail: "This type of file cannot be previewed. Download it instead." });
          return request.respond({ status: 200, contentType: found[1], body: found[0],
            headers: { "Content-Disposition": "attachment", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } }).catch(() => {});
        };
        return void (state.contentDelay ? setTimeout(respond, state.contentDelay) : respond());
      }
      if (one && one[2] === "/download" && method === "GET") {
        log.download.push(one[1]);
        const f = files.find((x) => x.id === one[1]);
        return json(request, 200, { url: `https://${STORAGE_HOST}/object/sign/${one[1]}?token=t&download=x`, expires_in: 60, display_name: f?.display_name || "x" });
      }
      if (one && method === "DELETE") { files = files.filter((f) => f.id !== one[1]); return json(request, 200, { id: one[1], removed: true }); }
    }
    if (p.endsWith("/api/v1/members")) return json(request, 200, members);
    if (p.endsWith("/remediation")) return json(request, 200, { tasks: [], total: 0 });
    if (p.endsWith("/domains")) return json(request, 200, [domain]);
    if (p.includes("/notifications")) return json(request, 200, { notifications: [], unread_count: 0 });
    if (p.includes("/platform/")) return json(request, 403, { detail: "no" });
    return json(request, 200, {});
  });

  await page.emulateTimezone(BROWSER_ZONE);
  await page.evaluateOnNewDocument((u) => {
    localStorage.setItem(`cyphward-tour-v1:${u.id}`, "done");
    localStorage.setItem("cyphward-session", JSON.stringify({ access_token: "t", refresh_token: "r", user: u, _expires_at: Date.now() + 864000000 }));
    localStorage.setItem("cyphward-welcome-sent", u.id);
    localStorage.setItem("cyphward-theme", "light");
    localStorage.setItem("cyphward-cookie-consent", "accepted");
    // Probes: blob URLs made and revoked, the upload request and its aborts, links the page follows.
    window.__blobs = { made: [], revoked: [] };
    const make = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = (b) => { const url = make(b); window.__blobs.made.push(url); return url; };
    URL.revokeObjectURL = (url) => { window.__blobs.revoked.push(url); return revoke(url); };
    window.__xhr = null; window.__aborts = 0;
    const send = XMLHttpRequest.prototype.send, abort = XMLHttpRequest.prototype.abort;
    XMLHttpRequest.prototype.send = function (...args) { window.__xhr = this; return send.apply(this, args); };
    XMLHttpRequest.prototype.abort = function () { window.__aborts++; return abort.call(this); };
    window.__followed = [];
    window.__violations = [];
    document.addEventListener("securitypolicyviolation", (e) => window.__violations.push([e.effectiveDirective, String(e.blockedURI).slice(0, 5)]));
    HTMLAnchorElement.prototype.click = function () { window.__followed.push([this.href, this.getAttribute("download")]); };
  }, user);

  const fq = `[data-testid="question-${KEY}"]`;
  const zone = `[data-testid="drop-zone-${KEY}"]`;
  const attach = `[data-testid="attach-${KEY}"]`;
  const dialogSel = '[role="dialog"]';
  const zoneState = () => page.$eval(zone, (z) => z.dataset.state);
  const active = () => page.evaluate(() => {
    const a = document.activeElement;
    return { testid: a?.getAttribute("data-testid") || "", focus: a?.getAttribute("data-focus") || "", previewFor: a?.getAttribute("data-preview-for") || "", inDialog: !!a?.closest('[role="dialog"]'), tag: a?.tagName };
  });
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  const noClaims = async (where) => {
    const text = (await page.evaluate(() => document.body.innerText)).toLowerCase();
    for (const phrase of CLAIM_WORDS) ok(!text.includes(phrase), `${where}: claim wording "${phrase}"`);
  };
  const noStorageUrlInPage = async (where) => {
    const hits = await page.evaluate((host) => {
      const found = [];
      for (const el of document.querySelectorAll("*")) {
        for (const attr of el.getAttributeNames()) {
          const v = el.getAttribute(attr) || "";
          if (v.includes(host) || /\/storage\/v1\/object/.test(v)) found.push(`${el.tagName}.${attr}`);
        }
      }
      return found.concat([...document.querySelectorAll("iframe, embed, frame")].map((e) => `${e.tagName} present`));
    }, STORAGE_HOST);
    eq(hits, [], `${where}: no storage URL (or frame) in the page`);
    eq(log.storage, [], `${where}: nothing requested from the storage host`);
  };
  const dropFile = (selector, name, body, type) => page.evaluate((sel, n, b, t) => {
    const target = document.querySelector(sel);
    const dt = new DataTransfer();
    dt.items.add(new File([b], n, { type: t }));
    for (const kind of ["dragenter", "dragover", "drop"]) target.dispatchEvent(new DragEvent(kind, { bubbles: true, cancelable: true, dataTransfer: dt }));
  }, selector, name, body, type);
  const tempFile = (name, bytes) => { const full = path.join(tmp, name); fs.writeFileSync(full, bytes); return full; };
  const keyboardUpload = async (name, bytes) => {
    await page.$eval(attach, (b) => b.focus());
    const [chooser] = await Promise.all([page.waitForFileChooser({ timeout: 5000 }), page.keyboard.press("Enter")]);
    await chooser.accept([tempFile(name, bytes)]);
  };
  const openComply = async () => {
    await page.goto(`${origin}/comply`, { waitUntil: "networkidle0" });
    await page.waitForSelector('[data-testid="compliance-disclaimer"]', { timeout: 10000 });
    await page.evaluate(() => [...document.querySelectorAll('[role="tab"]')].find((b) => b.getAttribute("aria-label") === "Answer questions")?.click());
    await page.waitForFunction(() => [...document.querySelectorAll('nav[aria-label="Question groups"] button')].some((b) => b.textContent.trim() === "2. Data protection officer"), { timeout: 10000 });
    await page.evaluate(() => [...document.querySelectorAll('nav[aria-label="Question groups"] button')].find((b) => b.textContent.trim() === "2. Data protection officer").click());
    await page.waitForSelector(`${fq} [data-testid="file-ef-png"]`, { timeout: 10000 });
  };
  const openPreviewByKeyboard = async (id) => {
    await page.$eval(`[data-preview-for="${id}"]`, (b) => { b.scrollIntoView({ block: "center" }); b.focus(); });
    await page.keyboard.press("Enter");
    await page.waitForSelector(`${dialogSel} [data-testid="evidence-preview"]`, { timeout: 5000 });
  };
  const waitClosed = () => page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 5000 });
  const shot = async (label, settleMs = 350) => {
    if (!SHOTS) return;
    fs.mkdirSync(SHOTS, { recursive: true });
    const file = path.join(SHOTS, `${label}.jpg`);
    await page.mouse.move(1, page.viewport().height - 1); // no hover state on the close button
    await sleep(settleMs); // let the dialog's entrance (and the PDF viewer) finish
    await page.screenshot({ path: file, type: "jpeg", quality: 72 });
    const size = fs.statSync(file).size;
    ok(size < MAX_SHOT_BYTES, `${label}: screenshot is ${size} bytes (limit ${MAX_SHOT_BYTES})`);
  };
  const results = {};

  for (const [name, width, height] of [["desktop", 1440, 900], ["mobile-390", 390, 844], ["mobile-320", 320, 640]]) {
    reset();
    await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "no-preference" }]);
    await page.setViewport({ width, height, isMobile: width < 768, hasTouch: width < 768 });
    await openComply();
    const phone = width < 768;

    // ── 1. Drop zone ────────────────────────────────────────────────────────
    const z = await page.$eval(attach, (b) => ({ tag: b.tagName, type: b.type, tab: b.tabIndex, text: b.textContent.replace(/\s+/g, " ").trim(),
      described: document.getElementById(b.getAttribute("aria-describedby") || "")?.textContent || "", h: b.getBoundingClientRect().height }));
    eq([z.tag, z.type, z.tab], ["BUTTON", "button", 0], `${name}: the drop zone is a real, focusable button`);
    ok(z.text.startsWith("ATTACH EVIDENCE") && /Drop a file here, or choose one/.test(z.text), `${name}: zone label and hint (${z.text})`);
    ok(/PDF, PNG, JPG or DOCX, up to 10\.0 MB/.test(z.described) && /does not read or review it/.test(z.described), `${name}: the zone is described by the limits`);
    ok(z.h >= 44, `${name}: zone is at least 44px tall (${z.h})`);
    eq(await zoneState(), "idle", `${name}: idle state`);
    // Drag over and leave.
    await page.evaluate((sel) => {
      const dt = new DataTransfer(); dt.items.add(new File(["%PDF-1.4"], "x.pdf", { type: "application/pdf" }));
      document.querySelector(sel).dispatchEvent(new DragEvent("dragenter", { bubbles: true, cancelable: true, dataTransfer: dt }));
    }, zone);
    await page.waitForFunction((sel) => document.querySelector(sel).dataset.state === "dragover", { timeout: 3000 }, zone);
    ok(/Release to attach this file/.test(await page.$eval(`${zone} [data-testid="drop-hint"]`, (e) => e.textContent)), `${name}: drag-over wording`);
    await page.evaluate((sel) => document.querySelector(sel).dispatchEvent(new DragEvent("dragleave", { bubbles: true, relatedTarget: null })), zone);
    await page.waitForFunction((sel) => document.querySelector(sel).dataset.state === "idle", { timeout: 3000 }, zone);
    ok(true, `${name}: drag leave returns to idle`);

    // Drop a file; progress follows the request's upload events; then done, the check and the new row.
    state.uploadMode = "hold";
    await dropFile(zone, "dropped-register.pdf", "%PDF-1.4 hello", "application/pdf");
    await page.waitForSelector(`${fq} [data-testid="upload-progress"]`, { timeout: 5000 });
    eq(await zoneState(), "uploading", `${name}: uploading state`);
    const up = await page.$eval(`${fq} [data-testid="upload-progress"]`, (e) => e.innerText.replace(/\s+/g, " "));
    ok(/Uploading dropped-register\.pdf/.test(up) && /PDF · 14 B/.test(up), `${name}: file name, type and size during upload (${up})`);
    await page.waitForFunction(() => !!window.__xhr, { timeout: 5000 });
    for (const [loaded, want] of [[3, "30"], [7, "70"]]) {
      await page.evaluate((l) => window.__xhr.upload.dispatchEvent(new ProgressEvent("progress", { lengthComputable: true, loaded: l, total: 10 })), loaded);
      await page.waitForFunction((sel, w) => document.querySelector(`${sel} [data-testid="upload-bar"]`)?.getAttribute("aria-valuenow") === w, { timeout: 3000 }, fq, want);
      ok((await page.$eval(`${fq} [data-testid="upload-percent"]`, (e) => e.textContent)).includes(`${want}%`), `${name}: ${want}% shown from a progress event`);
    }
    if (phone) {
      await page.$eval(`${fq} [data-testid="upload-progress"]`, (e) => e.scrollIntoView({ block: "center" }));
      await shot(`upload-progress-${width}`, 300);
    }
    const bar = await page.$eval(`${fq} [data-testid="upload-bar"] > span`, (s) => s.style.transform);
    eq(bar, "scaleX(0.7)", `${name}: the bar fills to the reported fraction`);
    await page.evaluate(() => window.__xhr.upload.dispatchEvent(new ProgressEvent("progress", { lengthComputable: true, loaded: 10, total: 10 })));
    await page.waitForFunction((sel) => /Checking the file/.test(document.querySelector(`${sel} [data-testid="upload-percent"]`)?.textContent || ""), { timeout: 3000 }, fq);
    ok(true, `${name}: all bytes sent shows "checking"`);
    state.uploadMode = "ok";
    await saveUpload(state.pending.request, state.pending.key, state.pending.name);
    await page.waitForFunction((sel) => document.querySelector(sel)?.dataset.state === "done", { timeout: 5000 }, zone);
    ok(await page.$(`${zone} .evf-check`) !== null, `${name}: the done state shows the check`);
    ok(/“dropped-register\.pdf” attached/.test(await page.$eval(`${zone} [data-testid="drop-hint"]`, (e) => e.textContent)), `${name}: done wording`);
    await page.waitForSelector(`${fq} li.evf-row-new`, { timeout: 5000 });
    ok(/dropped-register\.pdf/.test(await page.$eval(`${fq} li.evf-row-new`, (li) => li.textContent)), `${name}: the new row is the uploaded file`);
    const motion = await page.evaluate((sel) => {
      const rowStyle = getComputedStyle(document.querySelector(`${sel} li.evf-row-new`));
      const check = getComputedStyle(document.querySelector(".evf-check path"));
      return { row: [rowStyle.animationName, rowStyle.animationDuration], check: [check.animationName, check.animationDuration] };
    }, fq);
    eq(motion, { row: ["evfRowIn", "0.22s"], check: ["evfCheckDraw", "0.32s"] }, `${name}: the new row slides in and the check draws with the motion tokens`);
    ok((await page.$eval(`${fq} [data-testid="upload-announce"]`, (e) => e.textContent)) === "dropped-register.pdf attached.", `${name}: success is announced`);
    eq(log.uploads.at(-1), { key: KEY, name: "dropped-register.pdf", auth: "Bearer t" }, `${name}: the dropped file was sent with the session`);
    await page.waitForFunction((sel) => document.querySelector(sel)?.dataset.state === "idle", { timeout: 5000 }, zone);
    ok(true, `${name}: done settles back to idle`);

    // Keyboard upload, then Cancel by keyboard: the request is aborted and focus comes back to the zone.
    state.uploadMode = "hold";
    const abortsBefore = await page.evaluate(() => window.__aborts);
    await keyboardUpload("keyboard-upload.png", PNG);
    await page.waitForSelector(`${fq} [data-testid="upload-cancel"]`, { timeout: 5000 });
    eq((await active()).focus, "cancel", `${name}: focus moves to Cancel while uploading`);
    ok(/PNG image · \d+(\.\d)? KB/.test(await page.$eval(`${fq} [data-testid="upload-meta"]`, (e) => e.textContent)), `${name}: type and size for a keyboard upload`);
    await page.keyboard.press("Enter");
    await page.waitForFunction((sel) => document.querySelector(sel)?.dataset.state === "idle", { timeout: 5000 }, zone);
    eq(await page.evaluate(() => window.__aborts), abortsBefore + 1, `${name}: Cancel aborts the request`);
    eq((await active()).focus, "zone", `${name}: focus returns to the drop zone after Cancel`);
    ok(!(await page.$(`${fq} [data-testid="file-error"]`)), `${name}: a cancel is not an error`);
    eq(await page.$eval(`${fq} [data-testid="upload-announce"]`, (e) => e.textContent), "Upload cancelled.", `${name}: the cancel is announced`);
    if (state.pending) { state.pending.request.abort().catch(() => {}); state.pending = null; }
    state.uploadMode = "ok";

    // A server error: reviewed wording only, then a retry that works, by keyboard.
    for (const [mode, wording, control] of [["fail500", "The file could not be attached. Try again.", "upload-retry"],
      ["raw422", "This file was not accepted. Check the file, or choose another one.", "upload-choose-again"]]) {
      state.uploadMode = mode;
      await keyboardUpload(`retry-${mode}.pdf`, "%PDF-1.4 retry");
      await page.waitForSelector(`${fq} [data-testid="file-error"]`, { timeout: 5000 });
      const err = await page.$eval(`${fq} [data-testid="file-error-text"]`, (e) => e.textContent);
      eq(err, wording, `${name}: ${mode} shows the reviewed message, not the server's text`);
      const focused = await active();
      eq([focused.focus, focused.testid], ["retry", control], `${name}: focus moves to the recovery action after ${mode}`);
      if (control === "upload-retry") await page.keyboard.press("Enter"); // sends the same file again
      else {
        const [chooser] = await Promise.all([page.waitForFileChooser({ timeout: 5000 }), page.keyboard.press("Enter")]);
        await chooser.accept([tempFile("replacement.pdf", "%PDF-1.4 ok")]);
      }
      await page.waitForFunction((sel) => document.querySelector(sel)?.dataset.state === "done", { timeout: 5000 }, zone);
      ok(!(await page.$(`${fq} [data-testid="file-error"]`)), `${name}: recovery after ${mode} succeeds`);
      await page.waitForFunction((sel) => document.querySelector(sel)?.dataset.state === "idle", { timeout: 5000 }, zone);
    }
    // A refused type offers another file, not a pointless retry.
    await keyboardUpload("tool.exe", "MZ");
    await page.waitForSelector(`${fq} [data-testid="upload-choose-again"]`, { timeout: 5000 });
    ok(/Only PDF, PNG, JPG\/JPEG or DOCX/.test(await page.$eval(`${fq} [data-testid="file-error-text"]`, (e) => e.textContent)), `${name}: a refused type says why`);
    await noClaims(`${name} upload states`);
    ok(await overflow() <= 0, `${name}: no horizontal scroll with the upload states`);

    // ── 2. Preview ──────────────────────────────────────────────────────────
    const rowButtons = await page.$eval(`${fq} [data-testid="file-ef-png"]`, (li) => [...li.querySelectorAll("button")].map((b) => [b.textContent.trim(), Math.round(b.getBoundingClientRect().height)]));
    eq(rowButtons.map((b) => b[0]), ["PREVIEW", "DOWNLOAD", "REMOVE"], `${name}: row actions`);
    if (phone) ok(rowButtons.every((b) => b[1] >= 44), `${name}: row actions are 44px on phones (${JSON.stringify(rowButtons)})`);

    // PNG: skeleton, then the image from a blob URL fetched through the API.
    state.contentDelay = 600;
    await openPreviewByKeyboard("ef-png");
    ok(await page.$(`${dialogSel} [data-testid="state-loading"]`) !== null, `${name}: a skeleton while the preview loads`);
    await page.waitForFunction(() => document.querySelector('[data-testid="preview-image"]')?.complete && document.querySelector('[data-testid="preview-image"]').naturalWidth > 0, { timeout: 5000 });
    state.contentDelay = 0;
    const img = await page.$eval('[data-testid="preview-image"]', (i) => ({ src: i.getAttribute("src"), alt: i.alt, w: i.naturalWidth }));
    ok(img.src.startsWith("blob:") && img.alt === "office-signage-photo.png" && img.w === 480, `${name}: PNG shown from a blob URL with the file name as alt (${JSON.stringify(img)})`);
    eq(log.content.map((c) => [c.id, c.auth]), [["ef-png", "Bearer t"]], `${name}: the bytes came through the API with the session`);
    eq(log.download, [], `${name}: a preview never asks for a storage link`);
    const meta = await page.$eval('[data-testid="preview-meta"]', (e) => e.textContent);
    ok(/PNG image · \d+(\.\d)? KB · 21 Oct 2026/.test(meta), `${name}: preview shows type, size and date (${meta})`);
    await noStorageUrlInPage(`${name} PNG preview`);
    await noClaims(`${name} PNG preview`);
    const layout = await page.evaluate(() => {
      const panel = document.querySelector('[role="dialog"]').getBoundingClientRect();
      const close = document.querySelector('[role="dialog"] .dialog-close').getBoundingClientRect();
      const dl = document.querySelector('[data-testid="preview-download"]').getBoundingClientRect();
      const body = document.querySelector('[role="dialog"] .dialog-body');
      const imgBox = document.querySelector('[data-testid="preview-image"]').getBoundingClientRect();
      return { panel: [panel.left, panel.top, panel.width, panel.height], close: [close.top, close.bottom, close.width, close.height], dl: dl.height,
        bodyOverflow: body.scrollWidth - body.clientWidth, imgRight: imgBox.right, vw: innerWidth, vh: innerHeight, page: document.documentElement.scrollWidth - innerWidth };
    });
    if (phone) {
      eq(layout.panel.map(Math.round), [0, 0, width, height], `${name}: the dialog is full screen on a phone`);
    }
    ok(layout.close[0] >= 0 && layout.close[1] <= layout.vh && layout.close[2] >= 44 && layout.close[3] >= 44, `${name}: close control visible and 44px (${layout.close})`);
    ok(layout.dl >= 44, `${name}: Download is 44px tall (${layout.dl})`);
    ok(layout.bodyOverflow <= 0 && layout.page <= 0 && layout.imgRight <= layout.vw, `${name}: no horizontal scroll in the PNG preview (${JSON.stringify(layout)})`);
    if (phone) await shot(`preview-png-${width}`);
    // Escape closes, revokes the blob URL and gives focus back to the row's Preview button.
    await page.keyboard.press("Escape");
    await waitClosed();
    await page.waitForFunction(() => document.activeElement?.getAttribute("data-preview-for") === "ef-png", { timeout: 3000 });
    ok(true, `${name}: Escape returns focus to the PNG row's Preview button`);
    const revoked = await page.evaluate(async (src) => {
      let readable = true;
      try { await fetch(src); } catch { readable = false; }
      return { listed: window.__blobs.revoked.includes(src), readable };
    }, img.src);
    eq(revoked, { listed: true, readable: false }, `${name}: the PNG blob URL is revoked on close`);

    // Preview error and retry.
    state.failContent = 1;
    await openPreviewByKeyboard("ef-png");
    await page.waitForSelector(`${dialogSel} [data-testid="state-error"]`, { timeout: 5000 });
    const perr = await page.$eval(`${dialogSel} [data-testid="state-error"]`, (e) => e.innerText);
    ok(/The preview could not be loaded\. Try again, or download the file instead\./.test(perr), `${name}: preview error wording (${perr})`);
    await page.evaluate(() => document.querySelector('[role="dialog"] [data-testid="state-error"] button').click());
    await page.waitForSelector('[data-testid="preview-image"]', { timeout: 5000 });
    ok(true, `${name}: Try again loads the preview`);
    await page.click(`${dialogSel} .dialog-close`);
    await waitClosed();
    await page.waitForFunction(() => document.activeElement?.getAttribute("data-preview-for") === "ef-png", { timeout: 3000 });
    ok(true, `${name}: the close button returns focus to the Preview button`);

    // PDF: the same blob in an <object type="application/pdf">, or the fallback when the browser has no viewer.
    log.content.length = 0;
    await openPreviewByKeyboard("ef-pdf");
    const pdfViewer = await page.evaluate(() => navigator.pdfViewerEnabled);
    if (pdfViewer) {
      await page.waitForSelector('[data-testid="preview-pdf"]', { timeout: 5000 });
      const obj = await page.$eval('[data-testid="preview-pdf"]', (o) => ({ type: o.getAttribute("type"), data: o.getAttribute("data"), fallback: !!o.querySelector('[data-testid="preview-pdf-fallback"]') }));
      ok(obj.type === "application/pdf" && obj.data.startsWith("blob:") && obj.fallback, `${name}: PDF in an object from a blob URL, with fallback text inside (${JSON.stringify(obj)})`);
      eq(log.content.map((c) => c.id), ["ef-pdf"], `${name}: PDF bytes through the API`);
    } else {
      await page.waitForSelector('[data-testid="preview-pdf-fallback"]', { timeout: 5000 });
      ok(true, `${name}: no PDF viewer in this browser: fallback shown`);
    }
    ok(await page.$('[data-testid="preview-download"]') !== null, `${name}: the PDF preview offers Download`);
    await noStorageUrlInPage(`${name} PDF preview`);
    if (phone) await shot(`preview-pdf-${width}`, 4000);
    const pdfSrc = await page.evaluate(() => document.querySelector('[data-testid="preview-pdf"]')?.getAttribute("data") || null);
    await page.keyboard.press("Escape");
    await waitClosed();
    await page.waitForFunction(() => document.activeElement?.getAttribute("data-preview-for") === "ef-pdf", { timeout: 3000 });
    ok(true, `${name}: focus returns to the PDF row`);
    if (pdfSrc) ok(await page.evaluate((s) => window.__blobs.revoked.includes(s), pdfSrc), `${name}: the PDF blob URL is revoked on close`);
    results[name] = { pdfViewerEnabled: pdfViewer };

    // DOCX: details and Download only; no bytes are fetched; Download uses the attachment-only link.
    log.content.length = 0;
    await openPreviewByKeyboard("ef-docx");
    await page.waitForSelector('[data-testid="preview-docx"]', { timeout: 5000 });
    const docx = await page.evaluate(() => {
      const d = document.querySelector('[role="dialog"]');
      return { text: d.innerText.replace(/\s+/g, " "), media: d.querySelectorAll("img, object, iframe, embed, video").length,
        footer: [...d.querySelectorAll(".dialog-footer button")].map((b) => b.textContent.trim()), skeleton: !!d.querySelector('[data-testid="state-loading"]') };
    });
    ok(/board-minutes-october\.docx/.test(docx.text) && /Word document \(DOCX\) · 47 KB · 12 Oct 2026/.test(docx.text), `${name}: DOCX shows name, size and date (${docx.text})`);
    ok(/Word documents are not shown here/.test(docx.text) && /cannot be opened safely inside the page/.test(docx.text), `${name}: DOCX says why there is no preview`);
    eq([docx.media, docx.footer, docx.skeleton], [0, ["Download"], false], `${name}: DOCX shows no content and only Download`);
    eq(log.content, [], `${name}: no bytes fetched for a Word file`);
    if (phone) await shot(`preview-docx-${width}`);
    await noClaims(`${name} DOCX preview`);
    await page.click('[data-testid="preview-download"]');
    await page.waitForFunction(() => window.__followed.length > 0, { timeout: 5000 });
    const followed = await page.evaluate(() => window.__followed.at(-1));
    eq(log.download, ["ef-docx"], `${name}: Download asks the API for the attachment link`);
    ok(followed[0].startsWith(`https://${STORAGE_HOST}/object/sign/ef-docx`) && followed[1] === "board-minutes-october.docx", `${name}: the link is followed as a download`);
    await noStorageUrlInPage(`${name} after a download`);
    await page.keyboard.press("Escape");
    await waitClosed();
    await page.waitForFunction(() => document.activeElement?.getAttribute("data-preview-for") === "ef-docx", { timeout: 3000 });
    ok(true, `${name}: focus returns to the DOCX row`);

    // Focus is trapped inside the dialog.
    await openPreviewByKeyboard("ef-docx");
    const inside = [];
    for (let i = 0; i < 4; i++) { await page.keyboard.press("Tab"); inside.push((await active()).inDialog); }
    ok(inside.every(Boolean), `${name}: Tab stays inside the dialog`);
    await page.keyboard.press("Escape");
    await waitClosed();

    // No previews kept: nothing in storage, every blob made was revoked.
    const leftovers = await page.evaluate(() => ({
      unrevoked: window.__blobs.made.filter((u) => !window.__blobs.revoked.includes(u)),
      storage: JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }),
    }));
    eq(leftovers.unrevoked, [], `${name}: every preview blob URL was revoked`);
    ok(!/blob:|ef-png|ef-pdf/.test(leftovers.storage), `${name}: no preview kept in browser storage`);
    ok(await overflow() <= 0, `${name}: no horizontal scroll after the previews`);
    eq(errors, [], `${name}: no page errors`);
  }

  // ── 3. The production security policy ─────────────────────────────────────
  reset();
  state.csp = true;
  await page.setViewport({ width: 1440, height: 900 });
  await openComply();
  ok(await page.evaluate(() => true), "csp: the page loads under the production policy");
  await openPreviewByKeyboard("ef-png");
  await page.waitForFunction(() => document.querySelector('[data-testid="preview-image"]')?.naturalWidth > 0, { timeout: 5000 });
  ok(true, "csp: PNG preview renders under the production policy (img-src blob:)");
  await page.keyboard.press("Escape");
  await waitClosed();
  await openPreviewByKeyboard("ef-pdf");
  await page.waitForFunction(() => {
    const fb = document.querySelector('[data-testid="preview-pdf-fallback"]');
    return fb && fb.getClientRects().length > 0 && getComputedStyle(fb).visibility !== "hidden";
  }, { timeout: 5000 });
  ok(await page.$('[data-testid="preview-download"]') !== null, "csp: the PDF shows the fallback text and Download (object-src 'none' blocks the viewer)");
  const violations = await page.evaluate(() => window.__violations);
  ok(violations.some(([d, u]) => d === "object-src" && u === "blob"), `csp: the policy really was applied and refused the PDF object (${JSON.stringify(violations)})`);
  ok(!violations.some(([d]) => d === "img-src"), "csp: the image preview raised no violation");
  results.csp = { pdf: "fallback" };
  await page.keyboard.press("Escape");
  await waitClosed();
  state.csp = false;

  // ── 5. Reduced motion ─────────────────────────────────────────────────────
  reset();
  await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
  await openComply();
  const instant = (s) => s.animationName === "none" || parseFloat(s.animationDuration) <= 0.0001;
  const still = (s) => s.transitionProperty === "none" || s.transitionDuration.split(",").every((d) => parseFloat(d) <= 0.0001);
  const zoneMotion = await page.$eval(zone, (z) => { const s = getComputedStyle(z); return { transitionProperty: s.transitionProperty, transitionDuration: s.transitionDuration }; });
  ok(still(zoneMotion), `reduced motion: the drop zone changes state instantly (${JSON.stringify(zoneMotion)})`);
  state.uploadMode = "hold";
  await dropFile(zone, "calm.pdf", "%PDF-1.4 calm", "application/pdf");
  await page.waitForSelector(`${fq} [data-testid="upload-bar"] > span`, { timeout: 5000 });
  const barMotion = await page.$eval(`${fq} [data-testid="upload-bar"] > span`, (b) => { const s = getComputedStyle(b); return { transitionProperty: s.transitionProperty, transitionDuration: s.transitionDuration }; });
  ok(still(barMotion), `reduced motion: the progress bar jumps (${JSON.stringify(barMotion)})`);
  state.uploadMode = "ok";
  await saveUpload(state.pending.request, state.pending.key, state.pending.name);
  await page.waitForSelector(`${fq} .evf-row-new`, { timeout: 5000 });
  const calm = await page.evaluate(() => {
    const pick = (el) => { const s = getComputedStyle(el); return { animationName: s.animationName, animationDuration: s.animationDuration }; };
    return { row: pick(document.querySelector(".evf-row-new")), check: pick(document.querySelector(".evf-check path")) };
  });
  ok(instant(calm.row) && instant(calm.check), `reduced motion: no row slide and no check draw (${JSON.stringify(calm)})`);
  await openPreviewByKeyboard("ef-png");
  const dlg = await page.evaluate(() => {
    const pick = (el) => { const s = getComputedStyle(el); return { animationName: s.animationName, animationDuration: s.animationDuration }; };
    return { panel: pick(document.querySelector(".dialog-panel")), backdrop: pick(document.querySelector(".dialog-backdrop")) };
  });
  ok(instant(dlg.panel) && instant(dlg.backdrop), `reduced motion: the dialog opens instantly (${JSON.stringify(dlg)})`);
  await page.keyboard.press("Escape");
  await waitClosed();
  eq(errors, [], "no page errors overall");
  console.log(JSON.stringify(results));
  console.log(`evidence upload and preview: drop zone, progress and cancel, previews (PNG, PDF, DOCX), blob revoke, focus, storage URLs, production CSP, 1440/390/320 and reduced motion: ${checks} checks passed`);
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
  if (browser) await browser.close();
  await server.close();
}
