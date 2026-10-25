"""Guard safety-relevant advice emitted by the real detector, with no network."""
import asyncio
import pytest

from backend.app.scanner.security_checks import run_security_checks
from test_dns_query_coverage import observation, records_with


def test_missing_dmarc_starts_with_monitoring_and_sender_inventory():
    dns = observation(records_with({"DMARC": "no_data"}))
    rows = asyncio.run(run_security_checks("example.test", dns, {}))
    row = next(r for r in rows if r["title"] == "Missing Email DMARC Authentication Policy")
    advice = row["remediation"]
    assert "v=DMARC1; p=none" in advice
    assert "every legitimate sender" in advice
    assert "block legitimate email" in advice
    assert "creating a reporting mailbox" in advice
    assert "p=reject;" not in advice
    assert "does not test actual message delivery" in row["description"]


def test_header_advice_requires_staging_and_respects_subdomains_and_embeds(monkeypatch):
    # The detector also has a robots probe; stub it at its actual public-IP guard.
    from backend.app.scanner import security_checks
    monkeypatch.setattr(security_checks.ip_guard, "resolve_connect_ip", lambda host: (_ for _ in ()).throw(ValueError("no fixture network")))
    rows = asyncio.run(run_security_checks("example.test", {}, {"http_status": 200}))
    by_title = {r["title"]: r for r in rows}
    hsts = by_title["Strict-Transport-Security (HSTS) Header Missing"]["remediation"]
    assert "short max-age" in hsts and "every subdomain" in hsts and "removal delay" in hsts
    csp = by_title["Missing Content-Security-Policy (CSP) Header"]["remediation"]
    assert "Content-Security-Policy-Report-Only" in csp and "staging" in csp
    xfo = by_title["Missing X-Frame-Options (Clickjacking Protection)"]["remediation"]
    assert "legitimate customers" in xfo and "blanket DENY can break" in xfo


@pytest.mark.parametrize("title", ["Missing Email DMARC Authentication Policy", "Missing SPF Record", "HSTS Header Missing", "Missing CSP", "Missing X-Frame-Options"])
def test_cloud_configuration_guides_use_curated_path_even_with_model_keys(monkeypatch, title):
    from backend.app.ai.llm_provider import CloudLLMProvider
    provider = CloudLLMProvider()
    provider.gemini_key = "synthetic-not-a-key"
    async def fail(*args, **kwargs): pytest.fail("Configuration advice must not be replaced by model output")
    monkeypatch.setattr(provider, "_call_llm", fail)
    guide = asyncio.run(provider.generate_remediation({"title": title}, "nginx"))
    assert guide["estimated_time_minutes"] is None
    assert guide["prerequisites"]
    combined = str(guide)
    assert "p=reject;" not in combined and "includeSubDomains; preload" not in combined
    assert "forensic" not in combined


@pytest.mark.parametrize("message", ["How do I enable DMARC?", "Help with HSTS", "Show CSP config", "What NDPA duties apply?", "Write a board report"])
def test_chat_stream_and_nonstream_keep_curated_scope_without_external_calls(monkeypatch, message):
    from backend.app.ai.llm_provider import CloudLLMProvider
    import backend.app.ai.heuristic_provider as heuristics
    provider = CloudLLMProvider()
    provider.gemini_key = "synthetic-not-a-key"
    class NoNetwork:
        def __init__(self, *args, **kwargs): pytest.fail("Curated chat must not invoke an external model")
    monkeypatch.setattr("backend.app.ai.llm_provider.httpx.AsyncClient", NoNetwork)
    async def no_sleep(_): pass
    monkeypatch.setattr(heuristics.asyncio, "sleep", no_sleep)
    context = {"org_name": "No invented mailbox Ltd", "score": None, "findings": []}
    result = asyncio.run(provider.chat(message, [], context))
    async def stream():
        return [chunk async for chunk in provider.chat_stream(message, [], context)]
    chunks = asyncio.run(stream())
    answer = "".join(chunk.get("token", "") for chunk in chunks)
    assert chunks[-1]["done"] is True
    assert result["answer"].strip() == answer.strip()
    assert "security@" not in answer and "Encryption is strong" not in answer and "p=reject;" not in answer
    assert "no **DMARC policy**" not in answer


def test_configuration_followup_cannot_escape_to_model(monkeypatch):
    from backend.app.ai.llm_provider import CloudLLMProvider
    provider = CloudLLMProvider()
    provider.gemini_key = "synthetic-not-a-key"
    class NoNetwork:
        def __init__(self, *args, **kwargs): pytest.fail("A follow-up must retain the preceding guide's safeguards")
    monkeypatch.setattr("backend.app.ai.llm_provider.httpx.AsyncClient", NoNetwork)
    answer = asyncio.run(provider.chat("Give me the commands", [{"role": "user", "content": "Configure DMARC"}], {"score": None}))
    assert "p=reject;" not in answer["answer"]
