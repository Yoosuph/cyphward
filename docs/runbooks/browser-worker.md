# Browser worker runbook (packet C2b)

The browser worker is a small, separate service. It claims one job at a time from Core, loads a
verified domain's homepage once in headless Chromium with no clicks, and reports what a first visit
looked like: cookies set before any choice, requests to other hosts, whether a consent banner was
detected, and whether a reject control sits beside accept. Core stores that as `tool_observed`
evidence under the three existing consent requirements. It describes what the browser observed. It is
never a statement about whether a website follows the law.

Nothing in the repository creates a VM, pushes an image or deploys anything. This runbook is for the
founder to follow by hand. The feature stays off in Core until step 6.

## 1. What you are building

| Piece | Where | Notes |
| --- | --- | --- |
| Core queue and endpoints | `backend/app/core/browser_jobs.py`, `backend/app/api/browser_worker.py` | Table `privacy_browser_jobs`. Own API key. Off until `BROWSER_CONSENT_ENABLED=true`. |
| Worker | `browser_worker/` | Own image (`Dockerfile.browser`), own requirements, own entrypoint. |
| Scanner worker | `scanner/` | Unchanged. It cannot claim browser jobs (section 9). |

The browser worker never talks to the database. It only calls Core over HTTPS, outbound.

## 2. Create the VM (generic steps)

Any provider works. Use a **separate** VM from the scanner, so a browser problem can never starve the
scanners.

- **Minimum:** 1 vCPU, 1 GiB RAM, 10 GiB disk, Linux x86-64 (Debian 12 or Ubuntu 22.04/24.04), public IPv4 for outbound traffic.
- **Recommended limits for the container** (from the PR #37 measurements): memory **768 MiB**, `/dev/shm` at least **256 MiB**, Chromium `--renderer-process-limit=1`, no swap. PR #37 measured peak container memory of about 170 to 215 MiB for ordinary pages and about 290 to 335 MiB for a deliberately heavy synthetic page, with no out-of-memory kills in any configuration. 768 MiB leaves roughly twice the heaviest measured peak.
- **Inbound:** none needed. Close every inbound port except SSH from your own address. The worker polls Core; Core never calls it.
- **Outbound:** HTTPS to Core and HTTP/HTTPS (ports 80 and 443) to the public internet. See the egress firewall in section 8.
- Create a non-root login user, enable automatic security updates, install Docker (or Podman).

## 3. Build the image on the VM

```bash
git clone https://github.com/Yoosuph/cyphward.git && cd cyphward
git checkout <the release tag or commit you reviewed>
docker build -f Dockerfile.browser -t cyphward-browser:local .
```

The build installs Debian's Chromium and the pinned Playwright Python package; it downloads no
browser binary. Rebuild monthly (or when Debian publishes a Chromium security update) and restart.

Check the image before configuring anything:

```bash
docker run --rm cyphward-browser:local python -c "import browser_worker.runner; print('ok')"
docker run --rm cyphward-browser:local /usr/bin/chromium --version
docker run --rm cyphward-browser:local id    # must show uid=10001, not root
# Self-check with the production hardening: visits a tiny page it serves on loopback, no network, no Core.
docker run --rm --read-only --tmpfs /tmp:size=256m,mode=1777 --shm-size 256m --memory 768m --memory-swap 768m \
  --cap-drop ALL --security-opt no-new-privileges:true --init cyphward-browser:local python -m browser_worker.smoke
# expected: {"ok": true, "browser": "Chromium ...", "cookies": 1, ...}
```

## 4. Environment variables (names only)

Worker (`browser_worker/.env.example` lists them with comments). Put them in `/etc/cyphward-browser/env`
(`chmod 600`, owned by root). Never commit a populated copy.

| Name | Purpose |
| --- | --- |
| `BROWSER_CORE_URL` | Core base URL, `https://...` |
| `BROWSER_API_KEY` | The browser worker's key. Not the scanner key. |
| `BROWSER_WORKER_ID` | Name shown in Core's job rows, 64 characters at most. |
| `BROWSER_POLL_INTERVAL_SECONDS` | Idle poll interval (default 30). |
| `BROWSER_HEARTBEAT_SECONDS` | Lease heartbeat while working (default 20). |
| `BROWSER_CHROMIUM_PATH` | Chromium path inside the image (default `/usr/bin/chromium`). |
| `BROWSER_CHROMIUM_SANDBOX` | `1` turns Chromium's sandbox on. With `0` (default) the worker refuses to start unless the next variable is `1`. See section 8, "Sandbox". |
| `BROWSER_ACK_NO_SANDBOX_EGRESS_FIREWALL` | Set to `1` only after the mandatory egress firewall in section 8 is installed and checked. Required when the sandbox is off. |
| `BROWSER_LOG_LEVEL` | `INFO` by default. |

Core (set on the Core service, for example in Render):

| Name | Purpose |
| --- | --- |
| `BROWSER_WORKER_API_KEY` | Same secret as the worker's `BROWSER_API_KEY`. Generate a long random value, different from `SCANNER_API_KEY`. |
| `BROWSER_CONSENT_ENABLED` | Feature flag, default `false`. |
| `BROWSER_LEASE_SECONDS` | Job lease, default 180 (the job limit is 90). |
| `BROWSER_MAX_ATTEMPTS` | Expired leases before a job is failed, default 3. |
| `BROWSER_JOB_COOLDOWN_HOURS` | Minimum gap between automatic observations of a domain, default 20. |

## 5. Run it

Use the compose example (`browser_worker/deploy/docker-compose.example.yml`) or the systemd unit
(`browser_worker/deploy/cyphward-browser-worker.service`). Both apply the same limits:

```bash
docker run -d --name cyphward-browser --restart unless-stopped \
  --env-file /etc/cyphward-browser/env \
  --user 10001:10001 --read-only --tmpfs /tmp:size=256m,mode=1777,noexec,nosuid \
  --shm-size 256m --memory 768m --memory-swap 768m --cpus 1.0 --pids-limit 256 \
  --cap-drop ALL --security-opt no-new-privileges:true --init \
  cyphward-browser:local
docker logs -f cyphward-browser
```

While the Core flag is off the worker logs `claim failed: ... HTTP 503` every poll and does nothing.
That is expected.

## 6. Register the worker and switch the feature on

There is no registration table: a worker exists for Core when it presents the browser key and the
`privacy_browser` capability. In order:

1. Deploy the Core release that contains the migration and the API (Core first, worker second).
2. Apply `supabase/migrations/20261019300000_privacy_browser_jobs.sql`. It is additive and idempotent, with lock and statement timeouts at the top. Applying it changes nothing for customers.
3. Set `BROWSER_WORKER_API_KEY` on Core. Leave `BROWSER_CONSENT_ENABLED` unset (off).
4. Start the worker (section 5). It should log HTTP 503 on claim, which proves the key reaches Core and the feature is still off.
5. Set `BROWSER_CONSENT_ENABLED=true` on Core and redeploy. The 503s stop; the worker polls and gets "no job".
6. Observations are then queued after each completed scan (at most one per domain per `BROWSER_JOB_COOLDOWN_HOURS`), and an owner or admin can request one with `POST /api/v1/domains/{domain_id}/consent-observation`.

## 7. Verify with a test domain

Use a domain you have already verified in Cyphward, ideally one you control and can change.

1. Request an observation as an owner or admin: `POST /api/v1/domains/<domain id>/consent-observation` (returns 202 and a job id).
2. Watch the worker log: `job=... outcome=completed` within about 30 seconds.
3. In the database: `SELECT status, attempts, claimed_by, error_message FROM privacy_browser_jobs ORDER BY requested_at DESC LIMIT 5;` The job should be `completed`.
4. Open the Compliance page. The consent requirements show "Tool observed" with sentences such as "The browser observed N cookies set before any choice was made".
5. Try a site you control that sets a cookie before consent, then one that does not, and confirm the sentences change.
6. Negative check: a request for a domain that is not verified must return 400, and a job pointing at an unverified or revoked domain is never claimed.

## 8. Security

**What the worker is allowed to touch.** Only the verified domain's homepage and whatever that page
itself loads. The start URL must be https on the verified host. The main frame may never leave the
verified domain (a redirect to another site stops the visit). Sub-requests to other public hosts are
allowed because recording them is the point of the test.

**SSRF protection (stronger than the scanner).** Chromium's only way out is an in-process filtering
proxy. It resolves each host once, refuses the connection if **any** resolved address is not public
(loopback, private, link-local, cloud metadata, reserved, multicast), then connects to the address it
validated, so DNS rebinding cannot change the target after the check. Loopback is routed through the
proxy too, so `http://127.0.0.1/` and `http://localhost/` are refused like any private address. Only
ports 80 and 443 are allowed. Every request is also checked before it is sent (scheme, port,
credentials in URL, literal and number-spelled addresses, scope for the main frame). Redirect hops of
the main frame are checked as they happen.

**Browser hardening.** Clean profile per job (a new browser process each time, temp profile deleted on
exit). No downloads, no permission prompts granted, service workers blocked, pop-ups closed, dialogs
dismissed, no file is ever chosen, QUIC and non-proxied WebRTC UDP disabled. The worker clicks nothing.
User agent: `Cyphward-Consent-Observer/1.0 (+https://cyphward.com/scanner)`.

**Hard limits (not widenable by a job).** Page timeout 45 s, total job 90 s, at most 150 recorded
sub-requests, 25 MiB of response bytes per job (the proxy cuts the connection), 100 cookies, 100
third-party hosts, a result body of at most 64 KiB, and one job at a time.

**Container hardening.** Non-root user (uid 10001), read-only root filesystem, a 256 MiB tmpfs for
`/tmp` (the only writable path), all Linux capabilities dropped, `no-new-privileges`, 768 MiB memory
with no swap, 1 CPU, 256 processes, 256 MiB `/dev/shm`. The image holds no secrets; the key arrives
only through the env file.

**Sandbox (a decision, not a quiet default).** Chromium's own sandbox needs unprivileged user
namespaces, which Docker's default profile blocks for an unprivileged container. With the sandbox off, a
browser exploit would run as the same user (uid 10001) as the Python worker and could read the worker's
environment through `/proc`, including `BROWSER_API_KEY`. The worker therefore **refuses to start** with the
sandbox off unless `BROWSER_ACK_NO_SANDBOX_EGRESS_FIREWALL=1` says the mandatory firewall below is in place.
Better: set `BROWSER_CHROMIUM_SANDBOX=1` on a host that allows it (Podman rootless, or Docker with a seccomp
profile that permits `clone` with user namespaces) and keep everything else. Never add `--privileged` or
`SYS_ADMIN` to make the sandbox work. What the code does regardless: the worker removes the key from its
own environment after reading it, and Chromium is started with every variable that looks like a secret
(`KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `CREDENTIAL`) removed; the first is tested, the second is tested. The
process environment the kernel recorded at start-up is not erasable, so treat the key as exposed to a
browser exploit when the sandbox is off, keep it single-purpose (it can only claim and answer browser jobs),
and rotate it on any suspicion.

**Egress firewall (MANDATORY when the sandbox is off, recommended otherwise).** In-process checks refuse
private, loopback, link-local, metadata (including Azure's `168.63.129.16`) and reserved addresses, but
the host must refuse them as well. Install these before setting the acknowledgement variable, and persist
them across reboots with your distribution's tooling. Allow DNS and HTTPS to Core first if your resolver or
Core sit in a private range.

```bash
# IPv4 (Docker hosts): DOCKER-USER is evaluated before Docker's own rules
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10 168.63.129.16/32 192.0.0.0/24 198.18.0.0/15; do
  iptables -I DOCKER-USER -d "$net" -j DROP
done
# IPv6: unique-local (includes AWS fd00:ec2::254), link-local, site-local; if you do not use IPv6, disable it for the container instead
for net in fc00::/7 fe80::/10 fec0::/10 ::1/128; do
  ip6tables -I DOCKER-USER -d "$net" -j DROP
done
```

Check from inside a throwaway container with the same network: `curl -m 3 http://169.254.169.254/` and
`curl -m 3 http://168.63.129.16/` must time out or fail, and the same over IPv6 if enabled.

**What the observation can and cannot show.** A page controls what it serves, and the user agent names
Cyphward by design (site owners can see who visited), so a site can serve a different, cleaner page to this
browser than to other visitors, and the banner detection runs in the page's own context and could be made
to answer as a site wishes. Every "present" sentence therefore ends with "This is what the page showed
Cyphward's browser on one visit; a page can behave differently for other visitors", and the Compliance page
note says the same. Treat the observation as one dated data point, not a measurement of every visitor's
experience.

**Redirect hops.** The browser follows an off-scope redirect's first request before the worker sees it and
stops the visit; that one request goes to a public host only (the proxy refuses private addresses), and no
page content from it is recorded. A browser-internal list of hosts Chromium contacts in the background
(including `accounts.google.com` and `www.google.com`) is refused at the proxy; pages that rely on those
hosts for a feature (for example a Google CAPTCHA) will show those requests as failed in the browser, and
they still appear in the third-party host list.

**Secrets.** `BROWSER_API_KEY` is the only secret on the VM. Rotate it by changing it on Core and in
the env file, then restarting the container. It must differ from `SCANNER_API_KEY` (Core refuses to start
otherwise), the scanner key cannot authenticate to the browser endpoints, and the browser key cannot
authenticate to the scanner endpoints.

## 9. How the two workers stay apart

- Browser jobs are rows in `privacy_browser_jobs`. The scanner's claim query reads `scans` only.
- The browser endpoints live under `/api/v1/browser-worker/`, need the browser key, and need the `privacy_browser` capability header. The scanner client never sends that capability.
- If a worker sends `privacy_browser` to the scanner claim endpoint, Core answers 204 and hands out no scan.
- The browser worker only calls `/api/v1/browser-worker/*`; its code has no path to a scan claim.

## 10. What the worker stores

Nothing persistent. The root filesystem is read-only and `/tmp` is a tmpfs that disappears on
restart. Cookie **values** are never read into the report: only names, domain, flags, a lifetime bucket
and a third-party flag. Final URLs are stored without query strings or fragments. Core keeps the
validated result in `privacy_browser_jobs.result` and the evidence rows in `compliance_evidence`.

## 11. Monitoring

- Worker: `docker logs --since 1h cyphward-browser | grep -E "outcome|failed"`. Expect `outcome=completed`; occasional `failed` with `refused_address`, `off_scope_redirect` or `timeout` reflects the site, not a fault.
- Container health: `docker stats --no-stream cyphward-browser` (memory should stay under about 400 MiB) and `docker inspect -f '{{.RestartCount}} {{.State.OOMKilled}}' cyphward-browser`. A non-zero OOMKilled means the limit is too low for the pages being visited.
- Core: `SELECT status, count(*) FROM privacy_browser_jobs WHERE requested_at > now() - interval '7 days' GROUP BY 1;` A growing `queued` count with no `running` rows means the worker is down.
- Failed jobs: `SELECT domain_id, error_message FROM privacy_browser_jobs WHERE status='failed' ORDER BY requested_at DESC LIMIT 20;`
- Disk: nothing grows except Docker logs (capped to 3 x 10 MiB in the examples).

## 12. Rolling back

- **Stop the feature immediately:** set `BROWSER_CONSENT_ENABLED=false` on Core. Endpoints answer 503/404, no job is queued, and the Compliance page reads as before. Existing browser evidence rows stay in the table but are not shown while the flag is off.
- **Stop the worker:** `docker stop cyphward-browser`. Queued jobs wait; running jobs lose their lease and fail after `BROWSER_MAX_ATTEMPTS`.
- **Remove the data (optional):** the migration is additive, so rollback never needs it dropped. To clear rows: `DELETE FROM compliance_evidence WHERE details->>'observation' = 'browser_consent_v1';` and `DELETE FROM privacy_browser_jobs;`, as the database owner.
- **Roll the worker back:** rebuild from the previous tag and restart; the protocol is versioned (`X-Browser-Protocol: 1`).

## 13. Cost notes

One small always-on VM (1 vCPU, 1 GiB) is the whole cost, typically a few US dollars a month on common
providers, plus negligible egress (a visit loads well under 25 MiB and runs about once per domain per
day). The worker is idle most of the time; one job takes roughly 5 to 15 seconds. If the VM is
stopped, nothing else in Cyphward is affected. Check your provider's current price; none is assumed here.

## 14. Known limits of the observation

- Heuristics: banners that use unusual markup, closed shadow DOM or an iframe can be missed. "Not detected" is stored as not assessed, never as a gap.
- One visit, no clicks: it does not test what happens after a visitor accepts or rejects.
- Only the homepage over https, from one location, on one occasion. A page that varies by country or by visitor can look different elsewhere.
- Cookie classification uses a fixed list of well-known analytics and advertising names and hosts; anything else is shown as unclassified for the owner to review.
- Sites on ports other than 80 and 443, or that need an http-only start, are refused.
