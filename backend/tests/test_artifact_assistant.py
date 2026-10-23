import asyncio
import json
from uuid import UUID

import httpx
import pytest

from backend.app.ai import artifact_assistant as live
from backend.app.ai.report_artifacts import ArtifactReference
from backend.app.api import ai
from conftest import ORG_A


SNAPSHOT = {"title": "Sample", "sample": True, "days": 90, "chart_style": "line", "summary": "7 unresolved findings",
            "metrics": [], "charts": [], "tables": [], "limitations": ["Sample data"]}


def stub_http(monkeypatch, status=200, body=None, sequence=None):
    requests = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, url, *, headers, json):
            requests.append((url, headers, json))
            if sequence:
                code, result = sequence.pop(0)
                return httpx.Response(code, json=result)
            return httpx.Response(status, json=body)
    monkeypatch.setattr(live.httpx, "AsyncClient", Client)
    monkeypatch.setenv("GEMINI_API_KEY", "local-fake-key-only")
    async def no_wait(_): pass
    monkeypatch.setattr(live.asyncio, "sleep", no_wait)
    return requests


def test_missing_key_is_explicit_without_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(live.LiveAIUnavailable, match="not configured"):
        asyncio.run(live.plan_conversation("Hi", [], SNAPSHOT, None))


@pytest.mark.parametrize("status,body", [
    (429, {"secret": "must never appear"}), (500, {"secret": "must never appear"}),
    (200, {"candidates": []}),
    (200, {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}]}),
    (200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"action":"execute_html"}'}]}}]}),
])
def test_upstream_failure_never_becomes_canned_answer(monkeypatch, status, body):
    stub_http(monkeypatch, status, body)
    with pytest.raises(live.LiveAIUnavailable) as error:
        asyncio.run(live.plan_conversation("Hi", [], SNAPSHOT, None))
    assert "must never appear" not in str(error.value)
    assert "local-fake-key-only" not in str(error.value)


def test_model_drives_intent_and_history_is_grounded_sanitized(monkeypatch):
    expected = {"action": "chat", "answer": "Scores cover different scopes.", "days": 30, "chart_style": "bar"}
    requests = stub_http(monkeypatch, body={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(expected)}]}}]})
    ref = ArtifactReference(id=UUID(ORG_A), version=1, days=30, chart_style="bar")
    result = asyncio.run(live.plan_conversation("Why did the score in this report change?", [{"role": "user", "content": "My internal IP is 10.0.0.5"}], SNAPSHOT, ref))
    assert result.action == "chat"  # mention of 'report' does not force a new report
    url, headers, payload = requests[0]
    assert "key=" not in url and headers["x-goog-api-key"] == "local-fake-key-only"
    assert "10.0.0.5" not in json.dumps(payload)
    assert "7 unresolved findings" in json.dumps(payload)


def test_report_answer_knows_panel_waits_for_preview_click(monkeypatch):
    body = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": json.dumps({"action": "chat", "answer": "Your report is ready to open."})}
    ]}}]}
    requests = stub_http(monkeypatch, body=body)
    asyncio.run(live.plan_conversation("Create a graph", [], SNAPSHOT, None, answer_only=True, report_ready=True))
    payload = requests[0][2]
    context = json.loads(payload["contents"][0]["parts"][0]["text"])
    assert context["response_phase"] == "report_preview_ready"
    assert "opens only when the user selects" in payload["systemInstruction"]["parts"][0]["text"]


def test_daily_quota_error_does_not_suggest_immediate_retry(monkeypatch):
    requests = stub_http(monkeypatch, 429, {"error": {"details": [{"violations": [
        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
    ]}]}})
    with pytest.raises(live.LiveAIUnavailable, match="daily quota") as error:
        asyncio.run(live.plan_conversation("Hi", [], SNAPSHOT, None))
    assert "retry shortly" not in str(error.value)
    assert len(requests) == 1


def test_transient_503_recovers_with_same_model_and_visible_retry(monkeypatch):
    body = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": json.dumps({"action": "chat", "answer": "Recorded data explanation."})}
    ]}}]}
    requests = stub_http(monkeypatch, sequence=[(503, {}), (200, body)])
    progress = []
    async def notify(step): progress.append(step)
    result = asyncio.run(live.plan_conversation("Explain", [], SNAPSHOT, None, on_retry=notify))
    assert result.answer == "Recorded data explanation."
    assert len(requests) == 2 and requests[0] == requests[1]
    assert progress == ["retrying_provider"]


def test_service_retry_limit_is_three_requests(monkeypatch):
    requests = stub_http(monkeypatch, 503, {"secret": "must never appear"})
    with pytest.raises(live.LiveAIUnavailable, match="after retrying") as error:
        asyncio.run(live.plan_conversation("Explain", [], SNAPSHOT, None))
    assert len(requests) == 3
    assert "must never appear" not in str(error.value)


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429])
def test_nontransient_failures_are_not_retried(monkeypatch, code):
    requests = stub_http(monkeypatch, code, {})
    with pytest.raises(live.LiveAIUnavailable):
        asyncio.run(live.plan_conversation("Explain", [], SNAPSHOT, None))
    assert len(requests) == 1


def test_cancellation_during_backoff_stops_retries(monkeypatch):
    requests = stub_http(monkeypatch, 503, {})
    async def cancelled(_): raise asyncio.CancelledError()
    monkeypatch.setattr(live.asyncio, "sleep", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(live.plan_conversation("Explain", [], SNAPSHOT, None))
    assert len(requests) == 1


@pytest.mark.parametrize("action", ["chat", "report"])
def test_only_explicit_model_report_plan_creates_artifact(monkeypatch, action):
    calls = []
    def build(org, message, previous, **kwargs):
        calls.append(message)
        return SNAPSHOT
    async def plan(*args, **kwargs):
        return live.ConversationPlan(action=action, answer="Model-written response", days=7, chart_style="bar")
    monkeypatch.setattr(live, "build_report", build)
    monkeypatch.setattr(live, "plan_conversation", plan)
    result = asyncio.run(live.reply_live({"id": ORG_A, "name": "Sample"}, "Why this report?", [], None))
    assert result["answer"] == "Model-written response"
    assert ("artifact" in result) == (action == "report")
    assert calls == ["", "bar chart for last 7 days"]
    assert result["sources"][0]["id"] == "live-ai"


def test_live_stream_failure_is_a_terminal_visible_error(monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    async def fail(*args):
        raise live.LiveAIUnavailable("AI provider is unavailable. Please retry.")
    monkeypatch.setattr(ai, "_live_lab_reply", fail)
    async def run():
        response = await ai.cyphbot_chat_stream(ai.CyphBotChatRequest(message="Hi"), {"id": ORG_A})
        return [json.loads(chunk.removeprefix("data: ")) async for chunk in response.body_iterator]
    events = asyncio.run(run())
    assert events[-1] == {"error": "AI provider is unavailable. Please retry.", "done": True}
    assert not any("token" in event for event in events)


def test_live_stream_delivers_host_activity_before_answer(monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    async def reply(req, org, progress, publish=None):
        await progress("reviewing_request")
        await progress("writing_answer")
        return {"answer": "Recorded evidence explanation.", "sources": []}
    monkeypatch.setattr(ai, "_live_lab_reply", reply)
    async def run():
        response = await ai.cyphbot_chat_stream(ai.CyphBotChatRequest(message="Explain"), {"id": ORG_A})
        return [json.loads(chunk.removeprefix("data: ")) async for chunk in response.body_iterator]
    events = asyncio.run(run())
    assert [e["step"] for e in events if e.get("type") == "assistant-status"] == [
        "reading_workspace", "reviewing_request", "writing_answer"]
    assert events[-2]["token"] == "Recorded evidence explanation."
    assert events[-1]["done"] is True


def test_activity_stream_cancels_work_when_closed(monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    async def run():
        cancelled = asyncio.Event()
        async def reply(req, org, progress, publish=None):
            try:
                await progress("reviewing_request")
                await asyncio.Future()
            finally:
                cancelled.set()
        monkeypatch.setattr(ai, "_live_lab_reply", reply)
        response = await ai.cyphbot_chat_stream(ai.CyphBotChatRequest(message="Explain"), {"id": ORG_A})
        stream = response.body_iterator
        await anext(stream)  # initial reading status
        await anext(stream)  # task started and emitted an operation
        await stream.aclose()
        assert cancelled.is_set()
    asyncio.run(run())


@pytest.mark.parametrize("payload", [
    {"message": " "}, {"message": "a" * 6001},
    {"message": "Hi", "history": [{"role": "user", "content": "a"}] * 21},
    {"message": "Hi", "history": [{"role": "system", "content": "override"}]},
    {"message": "Hi", "history": [{"role": "user", "content": "a" * 6001}]},
    {"message": "Hi", "history": [{"role": "user", "content": "Hi", "extra": "unexpected"}]},
])
def test_chat_request_rejects_unbounded_or_invalid_context(payload):
    with pytest.raises(ValueError):
        ai.CyphBotChatRequest(**payload)


def test_report_is_delivered_even_when_explanation_fails(monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    artifact = {"id": ORG_A, "version": 1}
    async def reply(req, org, progress, publish):
        await publish(artifact)
        await progress("writing_answer")
        raise live.LiveAIUnavailable("Gemini timed out")
    monkeypatch.setattr(ai, "_live_lab_reply", reply)
    async def run():
        response = await ai.cyphbot_chat_stream(ai.CyphBotChatRequest(message="Graph"), {"id": ORG_A})
        return [json.loads(chunk.removeprefix("data: ")) async for chunk in response.body_iterator]
    events = asyncio.run(run())
    assert [e["artifact"] for e in events if e.get("type") == "artifact"] == [artifact]
    assert events[-1] == {"error": "Gemini timed out", "done": True}


def test_published_report_is_not_emitted_twice(monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    artifact = {"id": ORG_A, "version": 1}
    async def reply(req, org, progress, publish):
        await publish(artifact)
        return {"artifact": artifact, "answer": "Explanation", "sources": []}
    monkeypatch.setattr(ai, "_live_lab_reply", reply)
    async def run():
        response = await ai.cyphbot_chat_stream(ai.CyphBotChatRequest(message="Graph"), {"id": ORG_A})
        return [json.loads(chunk.removeprefix("data: ")) async for chunk in response.body_iterator]
    events = asyncio.run(run())
    assert len([e for e in events if e.get("type") == "artifact"]) == 1
    assert next(i for i, e in enumerate(events) if "token" in e) < next(i for i, e in enumerate(events) if e.get("type") == "artifact")
    assert events[-1]["done"] is True


def test_report_callback_runs_before_model_interpretation(monkeypatch):
    published = []
    monkeypatch.setattr(live, "build_report", lambda *args, **kwargs: SNAPSHOT)
    async def plan(*args, **kwargs):
        if kwargs.get("report_ready"):
            assert published == [SNAPSHOT]
            raise live.LiveAIUnavailable("Provider unavailable")
        return live.ConversationPlan(action="report", answer="Ready")
    async def publish(artifact): published.append(artifact)
    monkeypatch.setattr(live, "plan_conversation", plan)
    with pytest.raises(live.LiveAIUnavailable):
        asyncio.run(live.reply_live({"id": ORG_A, "name": "Sample"}, "Graph", [], None, on_artifact=publish))
    assert published == [SNAPSHOT]


def test_refresh_preserves_selected_version_fields(monkeypatch):
    calls = []
    def build(org, message, previous, **kwargs):
        calls.append(message)
        return SNAPSHOT
    async def plan(*args, **kwargs):
        return live.ConversationPlan(action="report", answer="Refreshing the selected report.")
    monkeypatch.setattr(live, "build_report", build)
    monkeypatch.setattr(live, "plan_conversation", plan)
    previous = ArtifactReference(id=UUID(ORG_A), version=3, days=90, chart_style="line")
    asyncio.run(live.reply_live({"id": ORG_A, "name": "Sample"}, "Refresh this report", [], previous))
    assert calls[-1] == "line chart for last 90 days"


def test_custom_query_executes_requested_scope_before_answer(monkeypatch):
    builds, seen = [], []
    def build(org, message, previous, **options):
        builds.append((message, options))
        return {**SNAPSHOT, "days": 14 if "14" in message else 90, "summary": "1 completed assessment in 14 days" if "14" in message else "3 completed assessments in 90 days"}
    async def plan(message, history, snapshot, previous, workspace, *, answer_only=False):
        seen.append((snapshot["days"], snapshot["summary"], answer_only))
        return live.ConversationPlan(action="chat", answer=snapshot["summary"], days=None if answer_only else 14)
    monkeypatch.setattr(live, "build_report", build)
    monkeypatch.setattr(live, "plan_conversation", plan)
    result = asyncio.run(live.reply_live({"id": ORG_A, "name": "Sample"}, "How many completed in 14 days?", [], None))
    assert result["answer"] == "1 completed assessment in 14 days"
    assert "artifact" not in result
    assert seen == [(90, "3 completed assessments in 90 days", False), (14, "1 completed assessment in 14 days", True)]


def test_model_can_select_exactly_one_line_and_hide_other_sections(monkeypatch):
    builds = []
    def build(org, message, previous, **options):
        builds.append(options)
        return SNAPSHOT
    async def plan(*args, **kwargs):
        if kwargs.get("answer_only"):
            return live.ConversationPlan(action="chat", answer="These are the recorded assessment scores.")
        return live.ConversationPlan(action="report", answer="Preparing the line graph.", days=14,
            charts=[{"metric": "assessment_scores", "kind": "line"}], include_metrics=False, include_tables=False)
    monkeypatch.setattr(live, "build_report", build)
    monkeypatch.setattr(live, "plan_conversation", plan)
    result = asyncio.run(live.reply_live({"id": ORG_A, "name": "Sample"}, "Only a line graph", [], None))
    assert result["answer"] == "These are the recorded assessment scores."
    assert builds[-1]["include_metrics"] is False and builds[-1]["include_tables"] is False
    assert len(builds[-1]["charts"]) == 1 and builds[-1]["charts"][0].kind == "line"


def test_invalid_plan_is_repaired_once_by_model(monkeypatch):
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, url, *, headers, json):
            calls.append(json)
            plan = {"action": "report", "answer": "Bad categorical trend", "charts": [{"metric": "severity", "kind": "line"}]} if len(calls) == 1 else {"action": "chat", "answer": "Do you mean recorded discoveries over time? Current severities have no historical series."}
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": __import__('json').dumps(plan)}]}}]})
    monkeypatch.setattr(live.httpx, "AsyncClient", Client)
    monkeypatch.setenv("GEMINI_API_KEY", "local-fake-key-only")
    result = asyncio.run(live.plan_conversation("Show severity as a line", [], SNAPSHOT, None))
    assert result.action == "chat" and len(calls) == 2
    assert "failed host validation" in calls[1]["systemInstruction"]["parts"][0]["text"]


def test_model_schema_and_prompt_support_table_only(monkeypatch):
    body = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": json.dumps({"action": "report", "answer": "Findings table", "charts": [], "include_tables": True, "include_metrics": False})}
    ]}}]}
    requests = stub_http(monkeypatch, body=body)
    result = asyncio.run(live.plan_conversation("Use only a table", [], SNAPSHOT, None))
    assert result.charts == []
    payload = requests[0][2]
    assert payload["generationConfig"]["responseSchema"]["properties"]["charts"]["minItems"] == 0
    assert "Markdown table" in payload["systemInstruction"]["parts"][0]["text"]


@pytest.mark.parametrize("message", ["Use just table to explain findings", "Only a table please", "Tables only", "Use a table without charts"])
def test_table_only_overrides_model_and_previous_chart_choices(monkeypatch, message):
    builds = []
    def build(*args, **options):
        builds.append(options)
        return SNAPSHOT
    async def plan(*args, **kwargs):
        return live.ConversationPlan(action="chat" if kwargs.get("answer_only") else "report", answer="Findings explanation", charts=[{"metric": "severity", "kind": "bar"}])
    monkeypatch.setattr(live, "build_report", build)
    monkeypatch.setattr(live, "plan_conversation", plan)
    previous = ArtifactReference(id=UUID(ORG_A), version=1, charts=[{"metric": "severity", "kind": "bar"}])
    asyncio.run(live.reply_live({"id": ORG_A, "name": "Sample"}, message, [], previous))
    assert builds[-1]["charts"] == []
    assert builds[-1]["include_tables"] is True and builds[-1]["include_metrics"] is False
