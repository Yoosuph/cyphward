// C2b step 0: measure headless Chromium memory/time on local fixture pages.
// Usage: node browser_memory_probe.mjs <fixtures_dir> [runs=5] [limit=640M] > results.json
// Needs: node >= 22, chromium, systemd user manager + cgroup v2 (systemd-run --user --scope -p MemoryMax).
// Not part of the scanner image; measurement only.
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';

const [fixDir, runsArg = '5', limit = '640M'] /* limit in MiB, e.g. 640M */ = process.argv.slice(2);
const RUNS = Number(runsArg);
const CHROME = process.env.CHROME || '/usr/bin/chromium';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Synthetic heavy page (stand-in for a marketing site): large inline script,
// 5000 DOM nodes, 12 canvas-drawn 1600x1000 images. Written to a temp dir.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'c2b-'));
fs.writeFileSync(path.join(tmp, 'synthetic_heavy.html'), `<!doctype html><html><head><title>Heavy</title></head><body>
<div id="banner" style="position:fixed;bottom:0">We use cookies <button>Accept</button> <button>Reject</button></div>
<div id="root"></div><script>
document.cookie='first=1; path=/';
const root=document.getElementById('root');
for(let i=0;i<5000;i++){const d=document.createElement('div');d.textContent='Item '+i+' '+'x'.repeat(40);root.appendChild(d);}
const junk=[];for(let i=0;i<200000;i++)junk.push({i,s:'v'+i});
for(let k=0;k<12;k++){const c=document.createElement('canvas');c.width=1600;c.height=1000;
const x=c.getContext('2d');x.fillStyle='#'+(k*77777%16777215).toString(16).padStart(6,'0');x.fillRect(0,0,1600,1000);
const im=new Image();im.src=c.toDataURL('image/png');document.body.appendChild(im);}
</script></body></html>`);

const SITES = [
  ['plain_home', fixDir, 'plain_home.html'],
  ['gtm_only', fixDir, 'gtm_only.html'],
  ['consent_blocked', fixDir, 'consent_blocked.html'],
  ['synthetic_heavy', tmp, 'synthetic_heavy.html'],
];
const BASE = ['--headless=new', '--no-sandbox', '--no-first-run', '--no-default-browser-check',
  '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'];
const CONFIGS = {
  default: [],
  disable_gpu: ['--disable-gpu'],
  disable_dev_shm: ['--disable-dev-shm-usage'],
  v8_heap_128: ['--js-flags=--max-old-space-size=128'],
  renderer_limit_1: ['--renderer-process-limit=1'],
  lowmem_combined: ['--disable-gpu', '--disable-dev-shm-usage', '--js-flags=--max-old-space-size=128',
    '--renderer-process-limit=1', '--disable-extensions', '--disable-background-networking',
    '--disable-component-update', '--mute-audio', '--disable-sync', '--no-zygote'],
};

const servers = new Map();
async function serve(dir) {
  if (servers.has(dir)) return servers.get(dir);
  const s = http.createServer((q, r) => {
    const f = path.join(dir, q.url === '/' ? '' : q.url.split('?')[0]);
    fs.readFile(f, (e, b) => { if (e) { r.writeHead(404); r.end(); } else { r.writeHead(200, { 'content-type': 'text/html' }); r.end(b); } });
  });
  await new Promise((r) => s.listen(0, '127.0.0.1', r));
  servers.set(dir, s.address().port);
  return s.address().port;
}

function readProcs(cg) {
  let rss = 0, pss = 0, n = 0;
  let pids = [];
  try { pids = fs.readFileSync(`/sys/fs/cgroup${cg}/cgroup.procs`, 'utf8').split('\n').filter(Boolean); } catch {}
  for (const p of pids) {
    try {
      const s = fs.readFileSync(`/proc/${p}/smaps_rollup`, 'utf8');
      rss += Number(/^Rss:\s+(\d+)/m.exec(s)[1]); pss += Number(/^Pss:\s+(\d+)/m.exec(s)[1]); n++;
    } catch {}
  }
  return { rssMiB: rss / 1024, pssMiB: pss / 1024, n };
}

async function cdp(port) {
  let ver;
  for (let i = 0; i < 100; i++) {
    try { ver = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json(); break; } catch { await sleep(50); }
  }
  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0; const pending = new Map(); const listeners = [];
  ws.onmessage = (m) => { const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } else listeners.forEach((l) => l(d)); };
  const send = (method, params = {}, sessionId) => new Promise((res) => { const i = ++id; pending.set(i, res);
    ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
  return { send, on: (l) => listeners.push(l), close: () => ws.close() };
}

async function one(cfgName, site, run, portBase) {
  const [name, dir, file] = site;
  const web = await serve(dir);
  const dbg = portBase;
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'c2b-udd-'));
  const args = ['--user', '--scope', '--quiet', '-p', `MemoryMax=${limit}`, '-p', 'MemorySwapMax=0',
    'env', 'DBUS_SESSION_BUS_ADDRESS=disabled:', CHROME, ...BASE, ...CONFIGS[cfgName], `--user-data-dir=${udd}`, `--remote-debugging-port=${dbg}`, 'about:blank'];
  const t0 = Date.now();
  const ch = spawn('systemd-run', args, { stdio: 'ignore' });
  const cdpc = await cdp(dbg);
  // Chromium would move its browser process into its own transient systemd scope (via the session
  // bus), escaping the wrapper scope and its MemoryMax; DBUS_SESSION_BUS_ADDRESS=disabled: prevents that.
  let cg = '';
  for (let i = 0; i < 100 && !/run-p/.test(cg); i++) { cg = fs.readFileSync(`/proc/${ch.pid}/cgroup`, 'utf8').trim().split(':').pop(); await sleep(20); }
  if (!/run-p/.test(cg)) throw new Error('chromium not in the capped scope: ' + cg);
  let peakRss = 0, peakPss = 0, peakProcs = 0, stop = false;
  const sampler = (async () => { while (!stop) { const m = readProcs(cg);
    peakRss = Math.max(peakRss, m.rssMiB); peakPss = Math.max(peakPss, m.pssMiB); peakProcs = Math.max(peakProcs, m.n); await sleep(50); } })();
  const { result: { targetId } } = (await cdpc.send('Target.createTarget', { url: 'about:blank' }));
  const { result: { sessionId } } = await cdpc.send('Target.attachToTarget', { targetId, flatten: true });
  const S = (m, p) => cdpc.send(m, p, sessionId);
  const reqs = []; let idle = null; let loaderId = null;
  cdpc.on((d) => { if (d.method === 'Network.requestWillBeSent') reqs.push(d.params.request.url);
    if (d.method === 'Page.lifecycleEvent' && d.params.name === 'networkIdle' && loaderId && d.params.loaderId === loaderId) idle = Date.now(); });
  await S('Page.enable'); await S('Network.enable'); await S('Page.setLifecycleEventsEnabled', { enabled: true });
  let idleBaseline = null;
  const tNav = Date.now();
  if (name === 'idle_baseline') { await sleep(3000); }
  else {
    loaderId = (await S('Page.navigate', { url: `http://127.0.0.1:${web}/${file}` })).result.loaderId;
    while (!idle && Date.now() - tNav < 30000) await sleep(20);
  }
  const loadMs = (idle || Date.now()) - tNav;
  await sleep(500); // settle
  let cookies = 0, banner = null;
  if (name !== 'idle_baseline') {
    cookies = ((await S('Network.getAllCookies')).result.cookies || []).length;
    banner = (await S('Runtime.evaluate', { expression:
      `[...document.querySelectorAll('div,section,aside,dialog,form')].some(e=>/cookie|consent/i.test(e.textContent||'')&&e.offsetHeight>0&&e.textContent.length<400)`,
      returnByValue: true })).result.result.value;
  }
  stop = true; await sampler;
  const cgPeak = Number(fs.readFileSync(`/sys/fs/cgroup${cg}/memory.peak`, 'utf8')) / 1048576;
  const events = fs.readFileSync(`/sys/fs/cgroup${cg}/memory.events`, 'utf8');
  const third = reqs.filter((u) => !u.startsWith(`http://127.0.0.1:${web}`)).length;
  cdpc.close(); ch.kill('SIGTERM'); await sleep(600);
  spawn('systemctl', ['--user', 'kill', '-s', 'KILL', path.basename(cg)], { stdio: 'ignore' });
  await sleep(200); fs.rmSync(udd, { recursive: true, force: true });
  return { cfg: cfgName, site: name, run, loadMs, peakRssMiB: +peakRss.toFixed(1), peakPssMiB: +peakPss.toFixed(1),
    cgroupPeakMiB: +cgPeak.toFixed(1), peakProcs, cookies, thirdPartyReqs: third, banner,
    oom: /oom_kill (\d+)/.exec(events)?.[1] !== '0', wallMs: Date.now() - t0 };
}

const out = []; let port = 9300;
const plan = [];
plan.push(['default', ['idle_baseline']]);
for (const c of Object.keys(CONFIGS)) plan.push([c, ['idle_baseline', ...SITES.map((s) => s[0])]]);
const seen = new Set();
for (const [cfg, names] of plan) for (const n of names) {
  if (seen.has(cfg + n)) continue; seen.add(cfg + n);
  const site = n === 'idle_baseline' ? ['idle_baseline', fixDir, 'plain_home.html'] : SITES.find((s) => s[0] === n);
  for (let r = 1; r <= RUNS; r++) { const res = await one(cfg, site, r, port++); out.push(res); console.error(JSON.stringify(res)); }
}
process.stdout.write(JSON.stringify(out, null, 1));
process.exit(0);
