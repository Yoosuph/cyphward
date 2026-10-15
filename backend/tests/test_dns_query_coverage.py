"""Failures, negative answers and successful policy checks must stay distinct."""
import asyncio

import dns.exception
import dns.rdata
import dns.rdataclass
import dns.resolver
import pytest

from backend.app.scanner import dns_resolver as resolver
from backend.app.scanner.dns_coverage import query_evaluated
from backend.app.scanner.security_checks import run_security_checks

HOST = "acme.test"


def records_with(outcomes):
    records = resolver._empty_records()
    for key, status in outcomes.items():
        records["query_coverage"]["queries"][key] = resolver._outcome(
            HOST, key, "test", resolver._now(), status)
    return records


def observation(records):
    return {"hostname": HOST, "records": records, "primary_ip": "8.8.8.8",
            "spf_record": records["SPF"], "dmarc_record": records["DMARC"]}


def fake_native(monkeypatch, responses):
    class Resolver:
        def resolve(self, name, record_type):
            result = responses.get((name, record_type), dns.resolver.NoAnswer())
            if isinstance(result, Exception):
                raise result
            return [dns.rdata.from_text(dns.rdataclass.IN, record_type, value) for value in result]
    monkeypatch.setattr(resolver.dns.resolver, "Resolver", Resolver)


def fake_doh(monkeypatch, responses):
    seen = []
    class Response:
        def __init__(self, data):
            self.data = data
        def raise_for_status(self):
            pass
        def json(self):
            return self.data
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, params, headers):
            seen.append((params["name"], params["type"]))
            return Response(responses[(params["name"], params["type"])])
    monkeypatch.setattr(resolver.httpx, "AsyncClient", Client)
    return seen


def test_native_answers_negative_answers_and_timeouts_remain_distinct(monkeypatch):
    fake_native(monkeypatch, {
        (HOST, "TXT"): ['"v=spf1 " "-all"'],
        (HOST, "AAAA"): dns.exception.Timeout(),
        (f"_dmarc.{HOST}", "TXT"): dns.resolver.NXDOMAIN(),
    })
    records = resolver.resolve_with_dnspython(HOST)
    outcomes = records["query_coverage"]["queries"]
    assert records["SPF"] == "v=spf1 -all"
    assert outcomes["TXT"]["status"] == "answered"
    assert outcomes["MX"]["status"] == "no_data"
    assert outcomes["DMARC"]["status"] == "nxdomain"
    assert outcomes["AAAA"]["status"] == "failed"
    assert outcomes["AAAA"]["error"] == "Timeout"
    assert all(outcome["started_at"] <= outcome["completed_at"] for outcome in outcomes.values())


def test_fallback_retries_only_failed_question_without_losing_native_email_evidence(monkeypatch):
    fake_native(monkeypatch, {
        (HOST, "A"): ["8.8.8.8"],
        (HOST, "TXT"): ['"v=spf1 -all"'],
        (f"_dmarc.{HOST}", "TXT"): ['"v=DMARC1; p=reject"'],
        (HOST, "AAAA"): dns.exception.Timeout(),
    })
    seen = fake_doh(monkeypatch, {(HOST, "AAAA"): {
        "Status": 0, "Answer": [{"type": 28, "data": "2606:4700:4700::1111"}]}})
    monkeypatch.setattr(resolver.socket, "gethostbyname", lambda host: "8.8.8.8")
    data = asyncio.run(resolver.resolve_host_dns(HOST))
    assert seen == [(HOST, "AAAA")]
    assert data["spf_record"] == "v=spf1 -all"
    assert data["dmarc_record"] == "v=DMARC1; p=reject"
    assert data["records"]["AAAA"] == ["2606:4700:4700::1111"]
    outcome = data["records"]["query_coverage"]["queries"]["AAAA"]
    assert outcome["status"] == "answered"
    assert outcome["prior_attempts"][0]["status"] == "failed"
    assert query_evaluated(data, "DMARC")


def test_doh_rejects_servfail_missing_status_and_malformed_txt(monkeypatch):
    fake_doh(monkeypatch, {
        (HOST, "A"): {"Status": 2},
        (HOST, "MX"): {"Answer": []},
        (HOST, "TXT"): {"Status": 0, "Answer": [{"type": 16, "data": '"unterminated'}]},
    })
    records = asyncio.run(resolver.resolve_with_doh(HOST, ["A", "MX", "TXT"]))
    assert all(v["status"] == "failed" for v in records["query_coverage"]["queries"].values())
    assert records["A"] == records["TXT"] == []


def test_doh_filters_cnames_and_joins_txt_segments(monkeypatch):
    fake_doh(monkeypatch, {
        (HOST, "A"): {"Status": 0, "Answer": [{"type": 5, "data": "cdn.example."},
                                                 {"type": 1, "data": "8.8.8.8"}]},
        (HOST, "TXT"): {"Status": 0, "Answer": [{"type": 16, "data": '"v=spf1 " "-all"'}]},
        (f"_dmarc.{HOST}", "TXT"): {"Status": 3},
    })
    records = asyncio.run(resolver.resolve_with_doh(HOST, ["A", "TXT", "DMARC"]))
    assert records["A"] == ["8.8.8.8"]
    assert records["SPF"] == "v=spf1 -all"
    assert query_evaluated(observation(records), "DMARC")


@pytest.mark.parametrize("status", ["failed", "skipped", "unknown"])
def test_failed_email_questions_do_not_manufacture_missing_policy_findings(status):
    data = observation(records_with({"A": "answered", "TXT": status, "DMARC": status}))
    assert asyncio.run(run_security_checks(HOST, data, {})) == []


def test_legacy_records_are_not_proof_of_missing_policy_or_successful_check():
    data = observation(resolver._empty_records())
    data["records"].pop("query_coverage")
    assert not query_evaluated(data, "TXT")
    assert asyncio.run(run_security_checks(HOST, data, {})) == []


def test_successful_negative_answers_produce_missing_policies_independently():
    data = observation(records_with({"TXT": "no_data", "DMARC": "failed"}))
    findings = asyncio.run(run_security_checks(HOST, data, {}))
    assert [f["title"] for f in findings] == ["Missing Sender Policy Framework (SPF) Record"]
    data = observation(records_with({"TXT": "failed", "DMARC": "nxdomain"}))
    findings = asyncio.run(run_security_checks(HOST, data, {}))
    assert [f["title"] for f in findings] == ["Missing Email DMARC Authentication Policy"]


def test_other_name_or_record_type_cannot_certify_email_check():
    data = observation(records_with({"TXT": "answered", "DMARC": "answered"}))
    queries = data["records"]["query_coverage"]["queries"]
    queries["TXT"]["name"] = "another.test"
    queries["DMARC"]["record_type"] = "A"
    assert not query_evaluated(data, "TXT")
    assert not query_evaluated(data, "DMARC")


def test_partial_dns_batch_retains_evidence_but_does_not_report_host_fully_assessed():
    from backend.app.scanner.dns_coverage import DNS_QUERIES, collect_dns_results
    partial = observation(records_with({key: "no_data" for key in DNS_QUERIES}))
    partial["records"]["query_coverage"]["queries"]["TXT"]["status"] = "failed"
    batch = collect_dns_results([HOST], [partial])
    assert batch == [partial]
    assert batch.successful_hosts == []
    assert batch.progress()["status"] == "failed"
    assert "TXT" in batch.failed_hosts[HOST]
    assert query_evaluated(batch[0], "DMARC")
    complete = observation(records_with({key: "no_data" for key in DNS_QUERIES}))
    batch = collect_dns_results([HOST], [complete])
    assert batch.successful_hosts == [HOST]
    assert batch.progress()["status"] == "completed"


@pytest.mark.parametrize("status,expected", [("failed", "inconclusive"),
                                             ("answered", "verified")])
def test_remediation_requires_matching_dns_question(client, auth_headers, store, monkeypatch, status, expected):
    from conftest import ALICE, FINDING_A2
    from test_remediation_verify import _seed_task, _mock_probes
    finding = next(f for f in store.findings if f["id"] == FINDING_A2)
    finding["title"] = "Missing Email DMARC Authentication Policy"
    _seed_task(store, FINDING_A2)
    _mock_probes(monkeypatch)
    async def resolve(hostname):
        data = observation(records_with({"A": "answered", "TXT": "answered", "DMARC": status}))
        data["hostname"] = hostname
        for key, outcome in data["records"]["query_coverage"]["queries"].items():
            outcome["name"] = f"_dmarc.{hostname}" if key == "DMARC" else hostname
        return data
    async def checks(*args, **kwargs):
        return []
    async def no_http(*args, **kwargs):
        raise AssertionError("DNS verification must not depend on an HTTP probe")
    monkeypatch.setattr("backend.app.api.remediation.probe_http_service", no_http)
    monkeypatch.setattr("backend.app.api.remediation.resolve_host_dns", resolve)
    monkeypatch.setattr("backend.app.api.remediation.run_security_checks", checks)
    response = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert response.status_code == 200
    assert response.json()["result"] == expected
    assert finding["status"] == ("resolved" if expected == "verified" else "open")


@pytest.mark.parametrize("dmarc_status,txt_status,expected", [
    ("failed", "answered", "open"),
    ("answered", "failed", "resolved"),
    ("unknown", "answered", "open"),
])
def test_finalizer_only_resolves_matching_email_check(store, monkeypatch, dmarc_status, txt_status, expected):
    from conftest import FINDING_A1
    from test_baseline_coverage import _obs, _finalize
    # Make the existing asset/finding the domain apex for this scan.
    store.assets[0]["hostname"] = HOST
    finding = next(f for f in store.findings if f["id"] == FINDING_A1)
    finding["hostname"] = HOST
    finding["title"] = "Missing Email DMARC Authentication Policy"
    finding["category"] = "DNS & Email Security"
    obs = _obs()
    obs["discovery"]["discovered_hosts"] = [HOST]
    obs["dns"]["dns_records"] = [observation(records_with({"TXT": txt_status, "DMARC": dmarc_status}))]
    obs["http"]["http_probes"] = []
    _finalize(store, monkeypatch, obs)
    assert finding["status"] == expected


@pytest.mark.parametrize("result", [None, [], {"hostname": "other.test"}])
def test_invalid_dns_result_cannot_become_success_or_inject_another_target(result):
    from backend.app.scanner.dns_coverage import collect_dns_results
    batch = collect_dns_results([HOST], [result])
    assert batch == []
    assert batch.successful_hosts == []
    assert HOST in batch.failed_hosts


def test_truncated_doh_answer_is_not_absence_proof(monkeypatch):
    fake_doh(monkeypatch, {(HOST, "TXT"): {"Status": 0, "TC": True}})
    data = observation(asyncio.run(resolver.resolve_with_doh(HOST, ["TXT"])))
    assert not query_evaluated(data, "TXT")


def test_double_failure_preserves_both_attempts_and_unrelated_answers(monkeypatch):
    fake_native(monkeypatch, {(HOST, "A"): ["8.8.8.8"], (HOST, "TXT"): dns.exception.Timeout()})
    fake_doh(monkeypatch, {(HOST, "TXT"): {"Status": 2}})
    monkeypatch.setattr(resolver.socket, "gethostbyname", lambda host: "8.8.8.8")
    data = asyncio.run(resolver.resolve_host_dns(HOST))
    assert data["records"]["A"] == ["8.8.8.8"]
    outcome = data["records"]["query_coverage"]["queries"]["TXT"]
    assert outcome["status"] == outcome["prior_attempts"][0]["status"] == "failed"
    assert not query_evaluated(data, "TXT")
