"""
CyphBot chat context: _build_chat_context must expose ALL monitored domains
(not just the first verified one), severity counts, and the latest scan so
the assistant can answer "what do you see?" completely.

Run: uv run --with pytest ... python -m pytest backend/tests/test_ai_context.py -q
"""
from backend.app.api.ai import _build_chat_context
from conftest import ORG_A


def test_chat_context_lists_all_domains(store):
    store.domains.append({
        "id": "d2", "org_id": ORG_A, "domain": "shop.acme.com",
        "verification_status": "pending", "verification_token": "tok-shop",
        "verified_at": None, "created_at": "2026-02-01T00:00:00",
    })

    ctx = _build_chat_context({"id": ORG_A, "name": "Acme Traders"})

    names = [d["domain"] for d in ctx["domains"]]
    assert set(names) == {"acme.test", "shop.acme.com"}
    # The verified domain stays primary even when a newer one is pending.
    assert ctx["domain"] == "acme.test"
    assert ctx["domains"][0] == {
        "domain": "acme.test",
        "verified": True,
        "verification_status": "verified",
    }
    # Unverified domains carry their DNS proof record so the bot can hand
    # it over when someone asks how to verify.
    assert ctx["domains"][1] == {
        "domain": "shop.acme.com",
        "verified": False,
        "verification_status": "pending",
        "verification_token": "tok-shop",
    }


def test_chat_context_counts_and_scan(store):
    ctx = _build_chat_context({"id": ORG_A, "name": "Acme Traders"})

    assert ctx["org_name"] == "Acme Traders"
    assert ctx["assets_count"] == 2
    assert ctx["open_findings_total"] == sum(ctx["severity_counts"].values())
    assert ctx["open_findings_total"] >= 1
    assert ctx["findings"]  # top findings for the prompt
    assert ctx["last_scan"] is not None
    assert ctx["last_scan"]["status"] == "completed"


def test_chat_context_without_domains_or_scans(store):
    store.domains = []
    store.scans = [s for s in store.scans if s["org_id"] != ORG_A]

    ctx = _build_chat_context({"id": ORG_A, "name": "Acme Traders"})

    assert ctx["domains"] == []
    assert ctx["domain"] == ""
    assert ctx["last_scan"] is None


def test_heuristic_lists_verified_state_and_verify_steps(store):
    """Fallback bot: 'which domains are verified' → status per domain and,
    for the unverified one, the exact DNS TXT record to paste."""
    import asyncio
    from backend.app.ai.heuristic_provider import HeuristicAIProvider

    store.domains.append({
        "id": "d2", "org_id": ORG_A, "domain": "shop.acme.com",
        "verification_status": "pending", "verification_token": "tok-shop",
        "verified_at": None, "created_at": "2026-02-01T00:00:00",
    })
    ctx = _build_chat_context({"id": ORG_A, "name": "Acme Traders"})

    res = asyncio.run(HeuristicAIProvider().chat(
        "which of our domains are verified, and how do I verify the other one?",
        [], ctx,
    ))
    answer = res["answer"]
    assert "**acme.test** — verified" in answer
    assert "**shop.acme.com** — not verified yet" in answer
    assert "tok-shop" in answer          # exact TXT record handed over
    assert "```dns" in answer
