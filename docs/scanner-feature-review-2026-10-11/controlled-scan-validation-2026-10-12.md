# Controlled production scan and scanner corrections — 12 October 2026

Payment activation remains deferred. The user authorized the controlled scan and
scanner corrections. No VM sizing, Docker memory limit or billing change was needed.

## Controlled scan

The existing verified `cyphward.com` domain was assessed by VPS worker
`az-scanner-01` at `20.164.35.81`. Scan
`126a59a0-14f7-4b26-8d8d-9f4b7b0003da` was queued at
2026-10-11 14:14:26 UTC, claimed at 14:15:01 and completed at 14:21:51.
The operator enqueue checked verified ownership, quota and overlapping work, and
recorded an operator audit event without impersonating a customer account.

Discovery, DNS and HTTP covered five hosts; the port stage recorded ten
observations and successful coverage for all five hosts. TLS and Nuclei failed
on all five. The job completing therefore did not establish complete assessment
coverage. Existing failed-stage records were preserved.

Organization score remained **35.2**, risk points **184**, and unresolved
organization findings **31**. The authoritative `scan.completed` audit reported
18 findings processed, **0 new, 0 reopened and 0 resolved**. A diagnostic
comparison mixed UUID objects and string IDs; its apparent new/resolved counts
were discarded in favor of the completion audit. No customer records were
changed by that comparison.

## TLS correction

SSLyze includes optional, unrequested command nodes marked `NOT_SCHEDULED`.
The validator mistakenly required these commands to complete too. It now checks
only the requested certificate and TLS 1.0/1.1/1.2/1.3 commands, still rejecting
missing or failed requested results. TLS 1.0 parsing supports the current
`tls_1_0_cipher_suites` field and the older `tls_1_cipher_suites` field.

A focused real probe against `cyphward.com` succeeded with TLS 1.2 and 1.3
supported, TLS 1.0 and 1.1 unsupported, and no failed host. This was validation
of patched code in a separate process; deployment verification is recorded below.

## Nuclei correction

The controlled run's Nuclei processes exited with SIGKILL. Container cgroup
counters and kernel logs confirmed five OOM kills against its **640 MiB** hard
limit. The host has approximately 892 MiB RAM. Its existing swap is unavailable
to this container because memory and memory-plus-swap limits are equal.
Other scheduled runs completed successfully on the same worker, so the defect
was intermittent resource exhaustion rather than proof that every run failed.

The runner now defaults to one concurrent Nuclei process, template concurrency
four, and low payload/JavaScript/template-loading concurrency. Both full scans
and template rechecks use these settings. It keeps the same HTTP template
selection. Child processes receive a minimal environment without the worker's
Core key, application signing secret or database credentials. SIGKILL is
reported with an actionable memory-limit diagnostic.

Go settings default to `GOMEMLIMIT=384MiB`, `GOGC=50` and `GOMAXPROCS=1`.
The Go memory setting is a soft runtime limit, not a substitute for Docker's
hard limit. These choices follow [Nuclei's resource guidance](https://docs.projectdiscovery.io/opensource/nuclei/mass-scanning-cli)
and the [Go garbage collector guide](https://go.dev/doc/gc-guide).

The focused live test with patched code completed in **292.7 seconds**, with
**305,640 KiB peak RSS (about 299 MiB)** and **zero new OOM kills**. It returned
exit zero and no matching findings. The [captured summary](nuclei-memory-validation-2026-10-12.json)
is process-level validation for one host, not evidence that every possible
template or every discovered host was evaluated. At nearly five minutes it
also leaves limited margin within the default per-host timeout.

## Credential cleanup

An embedded PAT was removed from the fork remote and submitted to GitHub's
[credential revocation endpoint](https://docs.github.com/en/rest/credentials/revoke?apiVersion=2022-11-28).
Revocation returned HTTP 202; subsequent authentication with that credential
returned HTTP 401. Existing separate GitHub CLI authentication remains usable.
Neither Git remote now embeds a credential. No replacement token was created.

## Validation and rollout

The full backend suite passed: **378 passed, 16 skipped**. Regressions exercise
actual subprocess arguments and environment for scans and rechecks, SIGKILL
handling, optional SSLyze nodes, missing requested results, and both TLS 1.0
field layouts. `git diff --check` passed. No database migration is required.
Frontend source was unchanged during these corrections.

Rollout uses the existing scanner deployment workflow after an idle-queue
check. Final installed revision, service health and TLS verification are added
after deployment; the original production scan remains a record of the
pre-correction failures.

## Remaining limits

The operator scan did not test interactive customer authentication or the
manual-launch API. There were no prior Nuclei findings in this live check to
prove failure-gated closure; regression tests cover that behavior. Per-rule
evaluation provenance, unified deadlines/scope policy, atomic lease writes,
launch idempotency and richer worker telemetry remain the foundations listed
in the [scanner review](README.md). A successful empty tool result does not
establish a perfect security posture.
