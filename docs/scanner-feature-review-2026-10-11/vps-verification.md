# VPS scanner verification — 11 October 2026

**Confirmed: recon scans use the VPS worker.** This check used direct SSH,
read-only database queries, deployment evidence and authenticated guard probes.
No scan was launched, service restarted, configuration changed or customer
observation written. Key values and customer domains are omitted.

## Running worker

- Host: `20.164.35.81`; SSH user: `cyphward`.
- Worker identity: `az-scanner-01`.
- `cyphward-scanner.service`: **active/running**.
- Container: `cyphward-scanner`, running, image `cyphward-scanner:latest`.
- Container/service started: **11 October 2026, 13:46:46 UTC**.
- Core URL: `https://cyphward-core.onrender.com`.
- Poll interval: **30 seconds**.
- Subfinder, Naabu, ProjectDiscovery httpx, SSLyze and Nuclei: all executable paths present.
- VPS checkout: `5cd622ad0843c0c2ac85e48d10d52f3a0839b349`.
- Running image: `sha256:f26f17a66cd479e15452fb2d3826c0e0f810dd5c394789860f65277f8576ccfe`.

The latest [VPS deployment](https://github.com/Yoosuph/cyphward/actions/runs/38144468831)
succeeded at **13:47:01 UTC** for commit `5cd622a`. Its built image ID matches the
running container. The workflow checks systemd state, container presence and
worker startup. This deployment completed during this verification, superseding
the initially observed 7 October deployment.

## End-to-end evidence

| Scan ID | VPS journal | Database |
|---|---|---|
| `7ac84de9-f49a-4a43-a10a-497fbbed8189` | Claimed 06:00:05 UTC; recon finished 06:24:02 UTC. Five DNS/HTTP/TLS observations and ten port observations. | Completed 06:24:06 UTC. |
| `bc3346a8-171d-4a8d-aae7-f45007225773` | Claimed 06:24:07 UTC; recon finished 06:43:10 UTC. Four DNS/HTTP/TLS observations and ten port observations. | Completed 06:43:15 UTC. |

Both jobs ran on this VPS **before** the latest deployment. A manual scan on
10 October also recorded `dispatch: scanner_queue` in the database audit log.
These observations establish actual processing, not merely remote configuration.

The live scanner interface accepted authenticated requests and reached its job
guard: a nonexistent scan returned 404; a completed scan under a diagnostic
identity returned 409 before mutation. The same nonexistent-job guard check
from inside the running container returned authenticated 404. In current source,
the interface is disabled unless Core uses remote mode and has a scanner key.

No queued or running scans were present when queried. The worker was polling
normally after restart without a fresh job to process; no new job was created
for this check.

## What runs where

VPS: discovery, DNS, HTTP, port scanning, dedicated TLS scanning and Nuclei.
Core on Render: security checks/finalization, inventory, finding reconciliation,
scoring and AI summaries. Some additional target requests still occur in Core;
this is not an architecture where every scanning-related operation runs on the VPS.

## Limits and follow-up

- The latest worker build is deployed. Its new successful-host/failure handling
  still needs a controlled authorized scan; today's completed jobs used the older
  worker and have attempted-only Nuclei observations.
- Those earlier jobs recorded zero Nuclei findings after roughly 18–23 minutes
  in that stage. Zero does not independently prove a completed clean evaluation.
  Inspect the next scan's `successful_hosts`, `failed_hosts` and stage outcomes.
- Tool availability does not certify template completeness, network policy or
  scanner accuracy. The broader [readiness review](README.md) remains applicable.
- Core health is healthy/DB-connected, but its public version is static. This
  check does not independently establish which application commit Render runs.
- No private key or API-key value is included in this report.
