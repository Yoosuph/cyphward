"""
Connect-time IP safety — the SSRF boundary for every outbound probe.

An in-scope hostname is not enough: customer-controlled DNS can point it at
loopback, private, link-local/cloud-metadata or otherwise non-public
addresses, and redirects can pivot the probe elsewhere. Every stage that
opens a socket validates the resolved address here first, and connects only
to an approved public IP (rebinding revalidated immediately before each
request). Hostname-based tools (sslyze/nuclei need SNI/vhost) validate here
and connect by name; naabu connects by the validated IP itself.

Full network egress policy (blocking metadata/private ranges at the
firewall) belongs to deployment config — this module is the in-process
backstop.
"""
import ipaddress
import socket
from typing import Any, List, Optional


def is_public_ip(ip: Any) -> bool:
    """True only for globally routable unicast addresses."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(str(ip).strip().strip("[]"))
    except ValueError:
        return False
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return bool(
        addr.is_global
        and not addr.is_multicast
        and not addr.is_link_local
        and not addr.is_loopback
        and not addr.is_private
        and not addr.is_reserved
        and not addr.is_unspecified
    )


def resolve_connect_ips(hostname: str) -> List[str]:
    """
    Resolve a host (or IP literal) to its approved public IPs, in resolver
    order, de-duplicated. Empty list = never connect.
    """
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return []
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
        return [str(literal)] if is_public_ip(literal) else []
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    ips: List[str] = []
    for info in infos:
        ip = info[4][0]
        if is_public_ip(ip) and ip not in ips:
            ips.append(ip)
    return ips


def resolve_connect_ip(hostname: str) -> Optional[str]:
    """First approved public IP for a host, or None (unresolved/unsafe)."""
    ips = resolve_connect_ips(hostname)
    return ips[0] if ips else None


def pinned_url(scheme: str, ip: str) -> str:
    """
    URL addressed by the validated IP (connection pin). Pair with a Host
    header and an sni_hostname request extension carrying the real hostname.
    """
    netloc = f"[{ip}]" if ":" in ip else ip
    return f"{scheme}://{netloc}/"


def hostname_in_scope(hostname: str, scope) -> bool:
    """
    Suffix scope match with dot boundary (same rule as the worker's
    scope.py) — used to authorize redirect hops before connecting.
    """
    if not hostname or not scope:
        return False
    host = hostname.strip().lower().rstrip(".")
    if not host:
        return False
    for suffix in scope:
        s = (suffix or "").strip().lower().rstrip(".")
        if not s:
            continue
        if host == s or host.endswith("." + s):
            return True
    return False
