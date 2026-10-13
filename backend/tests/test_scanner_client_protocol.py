"""Protocol compatibility and explicit per-job authority over transport retries."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from scanner.client import CoreClient, CoreError
from shared.contracts import ScanJob


def job(generation=1):
    return ScanJob(
        scan_id="scan-1",
        organization_id="org-1",
        domain_id="domain-1",
        target="example.test",
        scope=["example.test"],
        created_at="2026-10-13",
        lease_expires_at="2026-10-13",
        claim_generation=generation,
        claim_token=("token-" + str(generation)).ljust(40, "x"),
    )


def test_client_preserves_exact_attempt_on_retry_and_between_jobs(monkeypatch):
    received = []

    async def handle(request):
        received.append(dict(request.headers))
        return httpx.Response(503 if len(received) == 1 else 200, json={"ok": True})

    async def no_wait(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_wait)

    async def run():
        client = CoreClient(
            SimpleNamespace(
                core_url="https://core.test",
                api_key="test-key",
                scanner_id="same",
                http_timeout_seconds=5,
            )
        )
        await client._http.aclose()
        client._http = httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(handle)
        )
        try:
            await client.progress(job(1), "dns", "running")
            await client.progress(job(2), "dns", "running")
        finally:
            await client.aclose()

    asyncio.run(run())
    assert received[0]["x-scanner-protocol"] == "2"
    assert (
        received[0]["x-claim-token"]
        == received[1]["x-claim-token"]
        == job(1).claim_token
    )
    assert received[2]["x-claim-token"] == job(2).claim_token
    assert received[2]["x-claim-generation"] == "2"


def test_client_rejects_v1_payload_without_logging_authority():
    async def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json={"version": 2})
        return httpx.Response(200, json={**job().model_dump(), "version": 1})

    async def run():
        client = CoreClient(
            SimpleNamespace(
                core_url="https://core.test",
                api_key="test-key",
                scanner_id="same",
                http_timeout_seconds=5,
            )
        )
        await client._http.aclose()
        client._http = httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(handle)
        )
        try:
            with pytest.raises(CoreError) as error:
                await client.claim()
            assert job().claim_token not in str(error.value)
        finally:
            await client.aclose()

    asyncio.run(run())


def test_tokens_are_omitted_from_model_representations():
    from backend.app.core.execution_fence import ExecutionClaim

    claim = ExecutionClaim("scan", "worker", 1, job().claim_token, 1, "worker")
    assert job().claim_token not in repr(claim)
    assert job().claim_token not in repr(job())


def test_protocol_negotiation_never_claims_from_old_api():
    methods = []

    async def handle(request):
        methods.append(request.method)
        return httpx.Response(404, json={"detail": "Not found"})

    async def run():
        client = CoreClient(
            SimpleNamespace(
                core_url="https://core.test",
                api_key="test-key",
                scanner_id="same",
                http_timeout_seconds=5,
            )
        )
        await client._http.aclose()
        client._http = httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(handle)
        )
        try:
            with pytest.raises(CoreError):
                await client.claim()
        finally:
            await client.aclose()

    asyncio.run(run())
    assert methods == ["GET"]
