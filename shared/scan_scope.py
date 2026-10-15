"""Versioned target selection, shared by local recon and the VPS worker.

Selection is an intent record, never evidence that a check succeeded. It does
not enforce network egress; connection/tool guards remain separate boundaries.
"""
import re
from dataclasses import asdict, dataclass
from typing import Iterable


def canonical_host(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        host = value.strip().lower().rstrip(".").encode("idna").decode("ascii")
    except UnicodeError:
        return None
    labels = host.split(".")
    if len(host) > 253 or len(labels) < 2 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        return None
    return host


def in_scope(host: str, scope: Iterable[str]) -> bool:
    return any(host == suffix or host.endswith("." + suffix) for suffix in scope)


@dataclass(frozen=True)
class TargetSelection:
    version: int
    policy: str
    requested_hosts: list[str]
    selected_hosts: list[str]
    omitted_hosts: dict[str, str]
    limits: dict[str, int]

    def payload(self) -> dict:
        return asdict(self)


def select_targets(target: str, scope: Iterable[str], discovered: Iterable[str],
                   registered: Iterable[str], *, max_hosts: int, dns_max_hosts: int) -> TargetSelection:
    """Apex first, then sorted registered hosts, then sorted passive hosts.

    The verified target is always requested, even when passive sources miss it.
    Caps apply after validation; invalid/out-of-scope entries never consume a
    slot. Each distinct omitted candidate retains a reason.
    """
    if max_hosts < 1 or dns_max_hosts < 1:
        raise ValueError("target limits must be positive")
    allowed = [h for s in scope if (h := canonical_host(s))]
    apex = canonical_host(target)
    if apex is None or not in_scope(apex, allowed):
        raise ValueError("scan target is outside valid authorised scope")
    seeds, passive, omitted = set(), set(), {}
    for values, group in ((registered, seeds), (discovered, passive)):
        for value in values:
            host = canonical_host(value)
            if host is None:
                if isinstance(value, str):
                    omitted[value] = "invalid_hostname"
            elif not in_scope(host, allowed):
                omitted[host] = "outside_authorised_scope"
            else:
                group.add(host)
    requested = [apex] + sorted(seeds - {apex}) + sorted(passive - seeds - {apex})
    for i, host in enumerate(requested):
        if i >= max_hosts:
            omitted[host] = "max_hosts"
        elif i >= dns_max_hosts:
            omitted[host] = "dns_max_hosts"
    return TargetSelection(1, "apex_registered_passive", requested,
                           requested[:min(max_hosts, dns_max_hosts)],
                           omitted, {"max_hosts": max_hosts, "dns_max_hosts": dns_max_hosts})
