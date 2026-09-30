"""
Scanner worker scope enforcement tests (spec §15/§40).
Pure functions — no DB, no network.
"""
import pytest

from scanner.scope import ScopeError, assert_job_in_scope, filter_hosts, host_in_scope
from shared.contracts import ScanJob


def _job(target: str, scope) -> ScanJob:
    return ScanJob(
        scan_id="s1", organization_id="o1", domain_id="d1",
        target=target, scope=list(scope),
        created_at="2026-01-01", lease_expires_at="2026-01-01",
    )


def test_exact_and_subdomain_match():
    assert host_in_scope("acme.test", ["acme.test"])
    assert host_in_scope("www.acme.test", ["acme.test"])
    assert host_in_scope("a.b.acme.test", ["acme.test"])


def test_dot_boundary_blocks_suffix_tricks():
    assert not host_in_scope("notacme.test", ["acme.test"])
    assert not host_in_scope("acme.test.evil.com", ["acme.test"])
    assert not host_in_scope("wwwacme.test", ["acme.test"])


def test_case_and_trailing_dot_normalization():
    assert host_in_scope("A.B.Acme.Test.", ["ACME.TEST"])
    assert host_in_scope("www.acme.test.", ["acme.test"])


def test_empty_inputs_rejected():
    assert not host_in_scope("", ["acme.test"])
    assert not host_in_scope("www.acme.test", [])
    assert not host_in_scope("www.acme.test", [""])


def test_filter_hosts_dedupes_scopes_and_caps():
    hosts = ["a.acme.test", "a.acme.test", "evil.com", "b.acme.test"]
    assert filter_hosts(hosts, ["acme.test"], 50) == ["a.acme.test", "b.acme.test"]
    assert len(filter_hosts([f"h{i}.acme.test" for i in range(100)], ["acme.test"], 10)) == 10


def test_job_target_must_be_in_scope():
    assert_job_in_scope(_job("acme.test", ["acme.test"]))
    with pytest.raises(ScopeError):
        assert_job_in_scope(_job("evil.com", ["acme.test"]))
