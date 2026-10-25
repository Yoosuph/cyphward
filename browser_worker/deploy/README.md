# Deploy examples

Nothing here is run or installed by the repository.

## `chromium-seccomp.json`

Chromium's own sandbox creates user and PID namespaces (`clone`/`unshare`). Docker's default seccomp profile
is an allow-list that blocks that for an unprivileged container, so the sandbox cannot start under it.
This profile is the smallest honest alternative that is kept in this repository (reviewable, versioned with
the code, not fetched from anywhere):

- **It is a deny-list, not Docker's allow-list.** Everything is allowed except syscalls a browser never
  needs and that matter for escaping a container or the host: `mount` and the new-mount API, `ptrace`,
  `process_vm_readv/writev`, `bpf`, `perf_event_open`, `keyctl` and friends, `kexec_*`, module loading,
  `reboot`, clock setting, `setns`, `personality`, `userfaultfd`, `open_by_handle_at`, swap, quotas.
- It is weaker than Docker's default for everything it does not name. Treat it as one layer next to the
  other ones: non-root user, all capabilities dropped (user namespaces then grant no capability outside
  their own namespace), `no-new-privileges`, read-only root filesystem, the in-process proxy and the host
  firewall.
- `ptrace` and `process_vm_*` are denied so the browser cannot read the worker's memory (where the key
  lives when it arrives on standard input).
- Install it as `/etc/cyphward-browser/chromium-seccomp.json` and pass
  `--security-opt seccomp=/etc/cyphward-browser/chromium-seccomp.json`.
- Prove it on your host: `docker run ... python -m browser_worker.smoke` without
  `-e BROWSER_CHROMIUM_SANDBOX=0` must print `"ok": true`. This repository could not run that test
  (no container engine was available when it was written).

If you prefer Docker's own allow-list, take its current default profile from the Moby repository for your
Docker version and add only the user-namespace rules; rootless Podman is the other route. Either way, a
host that cannot run the sandbox needs the documented acknowledgement and firewall.

## Secret file ownership

The key file mounted at `/run/secrets/browser_api_key` is read by uid 10001: `chown 10001 <file>` and
`chmod 400 <file>` on the host. With the systemd example the key is fed on standard input by root and no
file is visible inside the container.
