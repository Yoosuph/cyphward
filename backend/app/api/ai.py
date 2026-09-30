"""
Cyphward AI Security Interpretation API Router
Evidence First, AI Second: Explanations, Step-by-step Remediation, and Executive Summaries.
"""
import json
import asyncio
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional, List

from backend.app.core.database import execute_one, execute_query
from backend.app.ai.factory import get_ai_provider
from backend.app.risk.engine import compute_risk_score
from backend.app.core.auth import get_current_org

router = APIRouter(prefix="/api/v1/ai", tags=["AI Security Layer"])


class ExplainRequest(BaseModel):
    finding_id: Optional[str] = None
    finding: Optional[Dict[str, Any]] = None


class RemediateRequest(BaseModel):
    finding_id: Optional[str] = None
    target_stack: Optional[str] = "nginx"
    finding: Optional[Dict[str, Any]] = None


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
    finding_data = req.finding
    if not finding_data and req.finding_id:
        finding_data = execute_one(
            "SELECT * FROM findings WHERE id = %s AND org_id = %s",
            (req.finding_id, org["id"]),
        )

    if not finding_data:
        raise HTTPException(status_code=400, detail="Must provide valid finding_id or finding object.")

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
    finding_data = req.finding
    if not finding_data and req.finding_id:
        finding_data = execute_one(
            "SELECT * FROM findings WHERE id = %s AND org_id = %s",
            (req.finding_id, org["id"]),
        )

    if not finding_data:
        raise HTTPException(status_code=400, detail="Must provide valid finding_id or finding object.")

    ai = get_ai_provider()
    guide = await ai.generate_remediation(finding_data, target_stack=req.target_stack or "nginx")
    return guide


@router.post("/executive-summary")
async def generate_executive_summary(
    req: ExecutiveSummaryRequest = ExecutiveSummaryRequest(),
    org: Dict[str, Any] = Depends(get_current_org)
) -> Dict[str, Any]:
    """
    Generate an AI-synthesized, board-ready executive security summary report.
    """
    org_id = org["id"]
    findings = execute_query("SELECT * FROM findings WHERE org_id = %s AND status = 'open'", (org_id,))
    score_data = compute_risk_score(findings)

    ai = get_ai_provider()
    summary = await ai.generate_executive_summary(org["name"], score_data, findings)
    return summary


class ChatMessage(BaseModel):
    role: str  # "user" | "model" | "assistant"
    content: str


class CyphBotChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, str]]] = []
    finding_id: Optional[str] = None


def _build_chat_context(org: Dict[str, Any]) -> Dict[str, Any]:
    """Ground CyphBot in live org telemetry — no hardcoded fallback values."""
    org_id = org["id"]
    findings = execute_query(
        "SELECT * FROM findings WHERE org_id = %s AND status != 'resolved' LIMIT 15",
        (org_id,),
    ) or []
    assets_count = (execute_one(
        "SELECT COUNT(*) as count FROM assets WHERE org_id = %s", (org_id,)
    ) or {}).get("count", 0)
    domain_row = execute_one(
        "SELECT domain FROM domains WHERE org_id = %s AND verification_status = 'verified' ORDER BY created_at ASC LIMIT 1",
        (org_id,),
    ) or {}
    score_data = compute_risk_score(
        execute_query("SELECT * FROM findings WHERE org_id = %s AND status != 'resolved'", (org_id,)) or []
    )
    return {
        "org_name": org.get("name", ""),
        "score": score_data.get("score", 100),
        "domain": domain_row.get("domain") or "",
        "assets_count": assets_count,
        "findings": findings,
    }


@router.post("/chat")
async def cyphbot_chat(
    req: CyphBotChatRequest,
    org: Dict[str, Any] = Depends(get_current_org)
) -> Dict[str, Any]:
    """
    CyphBot Interactive AI Security Assistant:
    Answers queries grounded in live scan telemetry and active findings.
    """
    context = _build_chat_context(org)
    ai = get_ai_provider()
    return await ai.chat(req.message, req.history or [], context)


@router.post("/chat/stream")
async def cyphbot_chat_stream(
    req: CyphBotChatRequest,
    org: Dict[str, Any] = Depends(get_current_org)
):
    """CyphBot streaming analyst: streams tokens progressively over SSE."""
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
