"""
Job scope enforcement (spec §15/§40).

Core validates authorization at claim time (verified domain + org ownership).
The worker re-validates EVERY host before touching it: a host is in scope only
if it equals an authorized suffix or is a subdomain of one (dot-boundary
required — "notacme.test" must NOT match scope "acme.test").
"""
from typing import Iterable, List

from shared.contracts import ScanJob


class ScopeError(Exception):
    """Raised when a job or host falls outside the authorized scope."""


def host_in_scope(hostname: str, scope: Iterable[str]) -> bool:
    if not hostname:
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


def filter_hosts(hosts: Iterable[str], scope: Iterable[str], max_hosts: int) -> List[str]:
    """Scope-filter, de-duplicate (order-preserving), and cap at max_hosts."""
    seen = set()
    out: List[str] = []
    scope_list = list(scope)
    for h in hosts:
        if not h:
            continue
        clean = h.strip().lower().rstrip(".")
        if not clean or clean in seen:
            continue
        if not host_in_scope(clean, scope_list):
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= max(1, max_hosts):
            break
    return out


def assert_job_in_scope(job: ScanJob) -> None:
    """Defense in depth: the job's own target must sit inside its scope."""
    if not host_in_scope(job.target, job.scope):
        raise ScopeError(
            f"job target {job.target!r} is outside authorized scope {job.scope!r}"
        )
