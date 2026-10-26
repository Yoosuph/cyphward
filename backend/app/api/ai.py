"""
Cyphward AI Security Interpretation API Router
Evidence First, AI Second: Explanations, Step-by-step Remediation, and Executive Summaries.
"""
import json
import asyncio
import uuid
from uuid import uuid4
from backend.app.api.demo_login import limit_demo_ai
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from typing import Dict, Any, Literal, Optional, List

from backend.app.core.database import execute_one, execute_query
from backend.app.core.ai_limits import acquire_stream_slot, limit_ai, release_stream_slot
from backend.app.ai.factory import get_ai_provider
from backend.app.ai.heuristic_provider import HeuristicAIProvider
from backend.app.risk.engine import compute_risk_score, latest_assessment
from backend.app.core.auth import get_current_org
from backend.app.ai.report_artifacts import ArtifactReference, build_report, wants_report
from backend.app.ai.artifact_assistant import live_enabled, reply_live, LiveAIUnavailable

# The demo account's stricter cap runs first; every account then has per-user,
# per-organisation and upstream-attempt limits (backend/app/core/ai_limits.py).
router = APIRouter(prefix="/api/v1/ai", tags=["AI Security Layer"],
                   dependencies=[Depends(limit_demo_ai), Depends(limit_ai)])

# Short, fixed values only: the stack name reaches model prompts and guide titles.
TargetStack = Literal["nginx", "apache", "cloudflare", "aws", "none", "nodejs",
                      "python", "java", "php", "dotnet", "go", "other"]

FINDING_NOT_FOUND = "Finding not found."


class ExplainRequest(BaseModel):
    # Only the id is accepted. Any finding object a browser sends is ignored:
    # the explanation is always built from the stored, organisation-scoped row.
    finding_id: str = Field(max_length=64)


class RemediateRequest(BaseModel):
    finding_id: str = Field(max_length=64)
    target_stack: Optional[TargetStack] = "nginx"


def _stored_finding(finding_id: str, org_id: Any) -> Dict[str, Any]:
    try:
        parsed = uuid.UUID(finding_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail=FINDING_NOT_FOUND) from None
    finding = execute_one(
        "SELECT * FROM findings WHERE id = %s AND org_id = %s",
        (str(parsed), org_id),
    )
    if not finding:
        raise HTTPException(status_code=404, detail=FINDING_NOT_FOUND)
    return finding


class ExecutiveSummaryRequest(BaseModel):
    org_id: Optional[str] = None


@router.post("/explain")
async def explain_finding(
    req: ExplainRequest,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    """
    Explain finding in plain language with deep technical precision:
    - What is this?
    - Why does it matter?
    - What is the evidence?
    - What happens if ignored?
    """
    finding_data = _stored_finding(req.finding_id, org["id"])
    ai = get_ai_provider()
    explanation = await ai.explain_finding(finding_data)
    return explanation


@router.post("/remediate")
async def remediate_finding(
    req: RemediateRequest,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    """
    Generate actionable step-by-step fix guides tailored to the target technology stack
    (Nginx, Apache, Cloudflare, AWS CloudFront, etc.).
    """
    finding_data = _stored_finding(req.finding_id, org["id"])
    ai = get_ai_provider()
    guide = await ai.generate_remediation(finding_data, target_stack=req.target_stack or "nginx")
    return guide


class BoardActionItem(BaseModel):
    priority: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=300)
    impact: str = Field(max_length=2000)
    owner: str = Field(max_length=120)


class ExecutiveSummaryResponse(BaseModel):
    """The board report contract. Identity, score and scope always come from the
    server's own records; only the narrative fields come from the provider."""
    org_name: str = Field(max_length=200)
    score: Optional[float] = None
    grade: Optional[str] = Field(default=None, max_length=8)
    posture_label: str = Field(max_length=120)
    executive_headline: str = Field(min_length=1, max_length=500)
    board_summary: str = Field(min_length=1, max_length=6000)
    key_strengths: List[str] = Field(default_factory=list, max_length=10)
    critical_action_items: List[BoardActionItem] = Field(default_factory=list, max_length=10)
    compliance_verdict: str = Field(min_length=1, max_length=3000)
    generated_at: str = Field(max_length=80)
    scope_label: Optional[str] = Field(default=None, max_length=500)
    domain_coverage_line: Optional[str] = Field(default=None, max_length=1000)
    coverage: Optional[Dict[str, Any]] = None

    @field_validator("key_strengths")
    @classmethod
    def bounded_strengths(cls, value):
        if any(not isinstance(item, str) or len(item) > 500 for item in value):
            raise ValueError("Strengths must be short text.")
        return value


def _validated_summary(raw: Any, org: Dict[str, Any], score_data: Dict[str, Any]) -> ExecutiveSummaryResponse:
    raw = raw if isinstance(raw, dict) else {}
    items = raw.get("critical_action_items")
    return ExecutiveSummaryResponse(
        org_name=str(org.get("name") or "")[:200],
        score=score_data.get("score"),
        grade=score_data.get("grade"),
        posture_label=str(score_data.get("posture_label") or "Not assessed"),
        executive_headline=raw.get("executive_headline"),
        board_summary=raw.get("board_summary"),
        key_strengths=raw.get("key_strengths") or [],
        # The model path names these fields differently from the heuristic one.
        critical_action_items=[
            {
                "priority": item.get("priority"),
                "title": item.get("title"),
                "impact": item.get("impact") or item.get("rationale") or "",
                "owner": item.get("owner") or "Assign an owner",
            } if isinstance(item, dict) else item
            for item in (items if isinstance(items, list) else [])
        ],
        compliance_verdict=raw.get("compliance_verdict") or raw.get("compliance_implication"),
        generated_at=str(raw.get("generated_at") or "Live Telemetry"),
        scope_label=score_data.get("scope_label"),
        domain_coverage_line=score_data.get("domain_coverage_line"),
        coverage=(score_data.get("assessment") or {}).get("coverage"),
    )


@router.post("/executive-summary")
async def generate_executive_summary(
    req: ExecutiveSummaryRequest = ExecutiveSummaryRequest(),
    org: Dict[str, Any] = Depends(get_current_org)
) -> Dict[str, Any]:
    """
    Generate an AI-synthesized, board-ready executive security summary report.
    """
    org_id = org["id"]
    findings = execute_query("SELECT * FROM findings WHERE org_id = %s AND status != 'resolved'", (org_id,))
    score_data = compute_risk_score(findings, assessment=latest_assessment(org_id))

    ai = get_ai_provider()
    summary = await ai.generate_executive_summary(org["name"], score_data, findings)
    try:
        validated = _validated_summary(summary, org, score_data)
    except ValidationError:
        # A malformed model answer is replaced by the deterministic summary.
        fallback = await HeuristicAIProvider().generate_executive_summary(org["name"], score_data, findings)
        validated = _validated_summary(fallback, org, score_data)
    return validated.model_dump()


class ChatMessage(BaseModel):
    role: str  # "user" | "model" | "assistant"
    content: str


class CyphBotChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=6000)
    history: Optional[List[Dict[str, str]]] = Field(default_factory=list, max_length=20)
    finding_id: Optional[str] = None
    artifact_context: Optional[ArtifactReference] = None

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, value):
        if not value.strip():
            raise ValueError("Enter a question.")
        return value.strip()

    @field_validator("history")
    @classmethod
    def bounded_history(cls, value):
        for item in value or []:
            if set(item) != {"role", "content"} or item["role"] not in ("user", "assistant", "model") or len(item["content"]) > 6000:
                raise ValueError("History must contain bounded user and assistant messages.")
        return value


def _build_chat_context(org: Dict[str, Any]) -> Dict[str, Any]:
    """Ground CyphBot in live org telemetry — no hardcoded fallback values.

    Returns EVERY monitored domain (not just the first), severity counts,
    and the latest scan so the bot can answer "what do you see?" fully.
    """
    org_id = org["id"]
    unresolved = execute_query(
        "SELECT id, title, severity, category, status, description, remediation "
        "FROM findings WHERE org_id = %s AND status != 'resolved' "
        "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        "WHEN 'medium' THEN 2 ELSE 3 END",
        (org_id,),
    ) or []
    severity_counts: Dict[str, int] = {}
    for f in unresolved:
        sev = (f.get("severity") or "unknown").lower()
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
    assets_count = (execute_one(
        "SELECT count(*) as cnt FROM assets WHERE org_id = %s", (org_id,)
    ) or {}).get("cnt", 0)
    domains = execute_query(
        "SELECT * FROM domains WHERE org_id = %s ORDER BY created_at ASC",
        (org_id,),
    ) or []
    # Verified domains first (Python-side so the fake DB matches prod order).
    domains = sorted(domains, key=lambda d: d.get("verification_status") != "verified")
    primary_domain = next(
        (d.get("domain") for d in domains if d.get("verification_status") == "verified"),
        domains[0].get("domain", "") if domains else "",
    )
    score_data = compute_risk_score(unresolved, assessment=latest_assessment(org_id))
    recent_scans = execute_query(
        "SELECT * FROM scans WHERE org_id = %s ORDER BY created_at DESC LIMIT 5",
        (org_id,),
    ) or []
    last_scan = recent_scans[0] if recent_scans else None
    return {
        "org_name": org.get("name", ""),
        "score": score_data.get("score"),
        "score_assessed": score_data.get("assessed", False),
        "domain": primary_domain,
        "domains": [
            {
                "domain": d.get("domain"),
                "verified": d.get("verification_status") == "verified",
                "verification_status": d.get("verification_status") or "pending",
                # Only unverified domains need the DNS proof record — the bot
                # can hand it over verbatim when someone asks how to verify.
                **(
                    {}
                    if d.get("verification_status") == "verified"
                    else {"verification_token": d.get("verification_token")}
                ),
            }
            for d in domains
        ],
        "assets_count": assets_count,
        "findings": unresolved[:15],
        "severity_counts": severity_counts,
        "open_findings_total": len(unresolved),
        "last_scan": (
            {"status": last_scan.get("status"), "created_at": str(last_scan.get("created_at") or "")}
            if last_scan else None
        ),
    }


async def _live_lab_reply(req: CyphBotChatRequest, org: dict, on_progress=None, on_artifact=None) -> dict:
    context = await asyncio.to_thread(_build_chat_context, org)
    workspace = {
        "score": context.get("score"), "score_assessed": context.get("score_assessed"),
        "unresolved_findings_total": context.get("open_findings_total"), "severity_counts": context.get("severity_counts"),
        "domains": [{"domain": d.get("domain"), "verification_status": d.get("verification_status")} for d in context.get("domains", [])],
        "open_findings": [{k: str(f.get(k, ""))[:1500] for k in ("title", "severity", "category", "status", "description", "remediation")} for f in context.get("findings", [])[:15]],
    }
    return await reply_live(org, req.message, req.history or [], req.artifact_context, workspace, on_progress=on_progress, on_artifact=on_artifact)


@router.post("/chat")
async def cyphbot_chat(
    req: CyphBotChatRequest,
    org: Dict[str, Any] = Depends(get_current_org)
) -> Dict[str, Any]:
    """
    CyphBot Interactive AI Security Assistant:
    Answers queries grounded in live scan telemetry and active findings.
    """
    if live_enabled():
        try:
            return await _live_lab_reply(req, org)
        except LiveAIUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    if wants_report(req.message, req.artifact_context):
        artifact = await asyncio.to_thread(build_report, org, req.message, req.artifact_context)
        return {"answer": artifact["summary"], "artifact": artifact,
                "sources": [{"id": "report-data", "label": "Recorded workspace telemetry"}], "actions": []}
    context = _build_chat_context(org)
    ai = get_ai_provider()
    return await ai.chat(req.message, req.history or [], context)


async def _release_after(body, lease):
    """Hold the user's stream lease until the body finishes, fails or is closed."""
    try:
        async for chunk in body:
            yield chunk
    finally:
        # Synchronous on purpose: an await here could be cancelled with the stream.
        release_stream_slot(lease)


@router.post("/chat/stream")
async def cyphbot_chat_stream(
    req: CyphBotChatRequest,
    org: Dict[str, Any] = Depends(get_current_org)
):
    """CyphBot streaming analyst: streams tokens progressively over SSE.

    At most two streams per user are open at once (ai_limits.AI_MAX_CONCURRENT_STREAMS).
    """
    user_id = str(org.get("current_user_id") or "")
    if not user_id:
        # get_current_org always resolves the signed-in user; only in-process callers omit it.
        return await _chat_stream_response(req, org)
    lease = acquire_stream_slot(user_id)
    try:
        response = await _chat_stream_response(req, org)
    except BaseException:
        release_stream_slot(lease)
        raise
    response.body_iterator = _release_after(response.body_iterator, lease)
    return response


async def _chat_stream_response(req: CyphBotChatRequest, org: Dict[str, Any]) -> StreamingResponse:
    if live_enabled():
        async def live_events():
            # Only host operation names are exposed, never model thinking text.
            queue = asyncio.Queue()
            prepared_artifact = None
            async def progress(step):
                await queue.put({'type': 'assistant-status', 'status': 'thinking', 'step': step})
            async def remember_artifact(artifact):
                nonlocal prepared_artifact
                # Preserve completed data if narration fails, but do not display
                # the preview before the explanation.
                prepared_artifact = artifact
            async def publish_artifact():
                if prepared_artifact:
                    await queue.put({'type': 'artifact-status', 'id': prepared_artifact['id'], 'status': 'loading'})
                    await queue.put({'type': 'artifact', 'artifact': prepared_artifact})
            async def run():
                try:
                    result = await _live_lab_reply(req, org, progress, remember_artifact)
                    if result.get("artifact"):
                        await remember_artifact(result["artifact"])
                    await queue.put({'token': result['answer'], 'done': False})
                    await publish_artifact()
                    await queue.put({'done': True, 'sources': result['sources'], 'actions': []})
                except LiveAIUnavailable as exc:
                    if prepared_artifact:
                        await queue.put({'token': 'The requested report data is ready, but the AI explanation could not be completed.', 'done': False})
                        await publish_artifact()
                    await queue.put({'error': str(exc), 'done': True})
                except Exception:
                    if prepared_artifact:
                        await queue.put({'token': 'The requested report data is ready, but its explanation could not be completed.', 'done': False})
                        await publish_artifact()
                    await queue.put({'error': 'CyphBot could not read the report data. Please retry.', 'done': True})
                finally:
                    await queue.put(None)
            yield f"data: {json.dumps({'type': 'assistant-status', 'status': 'thinking', 'step': 'reading_workspace'})}\n\n"
            task = asyncio.create_task(run())
            try:
                while (event := await queue.get()) is not None:
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        return StreamingResponse(live_events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})
    if wants_report(req.message, req.artifact_context):
        async def report_events():
            # Keyed event stays separate from prose; no partial JSON is ever painted.
            artifact_id = req.artifact_context.id if req.artifact_context else uuid4()
            yield f"data: {json.dumps({'type': 'artifact-status', 'id': str(artifact_id), 'status': 'loading'})}\n\n"
            try:
                artifact = await asyncio.to_thread(build_report, org, req.message, req.artifact_context, artifact_id)
                yield f"data: {json.dumps({'token': artifact['summary'], 'done': False})}\n\n"
                yield f"data: {json.dumps({'type': 'artifact', 'artifact': artifact})}\n\n"
                yield f"data: {json.dumps({'done': True, 'sources': [{'id': 'report-data', 'label': 'Recorded workspace telemetry'}], 'actions': []})}\n\n"
            except Exception:
                yield f"data: {json.dumps({'error': 'Report could not be generated. Please retry; no report was saved.', 'done': True})}\n\n"
        return StreamingResponse(report_events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})
    context = _build_chat_context(org)
    ai = get_ai_provider()

    async def event_generator():
        if hasattr(ai, "chat_stream"):
            async for chunk in ai.chat_stream(req.message, req.history or [], context):
                yield f"data: {json.dumps(chunk)}\n\n"
        else:
            res = await ai.chat(req.message, req.history or [], context)
            words = res.get("answer", "").split(" ")
            for w in words:
                yield f"data: {json.dumps({'token': w + ' ', 'done': False})}\n\n"
                await asyncio.sleep(0.015)
            yield f"data: {json.dumps({'token': '', 'done': True, 'sources': res.get('sources', []), 'actions': res.get('actions', [])})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
