"""
Cyphward scanner worker package (spec §13/§15).

Outbound-only worker: polls Core over HTTPS, claims a queued scan, runs recon
stages, submits progress + raw observations, and hands off to Core finalize.
Never accepts inbound connections and never talks to the database directly.

Run:
    python -m scanner.runner          # daemon (systemd)
    python -m scanner.runner --once   # claim at most one job, then exit
"""
