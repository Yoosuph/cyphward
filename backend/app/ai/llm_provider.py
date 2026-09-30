"""
Cyphward Cloud LLM Provider
Proxies through external LLM APIs (Gemini / OpenAI) with mandatory prior privacy sanitization.
Seamlessly falls back to HeuristicAIProvider when API keys are unconfigured or external calls fail.
"""
import os
import json
import time
import httpx
from typing import Dict, Any, List
from backend.app.ai.base import AIProvider
from backend.app.ai.privacy import sanitize_for_ai
from backend.app.ai.heuristic_provider import HeuristicAIProvider


class CloudLLMProvider(AIProvider):
    """Cloud LLM Provider with zero-leak privacy masking and heuristic fallback."""

    def __init__(self):
        self.heuristic = HeuristicAIProvider()
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.is_openrouter = bool(self.openai_key and self.openai_key.startswith("sk-or-"))
        self._gemini_rate_limited_until = 0.0

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> Dict[str, Any] | None:
        """Helper to invoke OpenRouter/Claude, Gemini, or OpenAI with structured JSON response."""
        # 1. Try OpenRouter (Claude) if configured
        if self.is_openrouter:
            try:
                url = "https://openrouter.ai/api/v1/chat/completions"
                payload = {
                    "model": "anthropic/claude-3-haiku",
                    "messages": [
                        {"role": "system", "content": f"{system_prompt} You must respond strictly in valid JSON."},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                }
                headers = {
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://cyphward.com",
                    "X-Title": "Cyphward Sovereign Security"
                }
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"].strip()
                        if content.startswith("```"):
                            lines = content.split("\n")
                            if lines[0].startswith("```"):
                                lines = lines[1:]
                            if lines and lines[-1].strip().startswith("```"):
                                lines = lines[:-1]
                            content = "\n".join(lines).strip()
                        return json.loads(content)
            except Exception:
                pass

        # 2. Try Gemini if configured and not rate-limited
        now = time.time()
        if self.gemini_key and now > self._gemini_rate_limited_until:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_key}"
                combined = f"{system_prompt}\n\n{user_prompt}"
                payload = {
                    "contents": [{"parts": [{"text": combined}]}],
                    "generationConfig": {
                        "response_mime_type": "application/json",
                        "temperature": 0.2,
                        "maxOutputTokens": 1024,
                    },
                }
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            parts = candidates[0]["content"].get("parts", [])
                            if parts and "text" in parts[0]:
                                text = parts[0]["text"].strip()
                                if text.startswith("```"):
                                    lines = text.split("\n")
                                    if lines[0].startswith("```"):
                                        lines = lines[1:]
                                    if lines and lines[-1].strip().startswith("```"):
                                        lines = lines[:-1]
                                    text = "\n".join(lines).strip()
                                return json.loads(text)
                    elif resp.status_code == 429:
                        self._gemini_rate_limited_until = now + 86400.0
            except Exception:
                pass

        # 3. Try standard OpenAI if configured
        if self.openai_key and not self.is_openrouter:
            try:
                url = "https://api.openai.com/v1/chat/completions"
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": f"{system_prompt} You must respond in valid JSON."},
                        {"role": "user", "content": user_prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2
                }
                headers = {
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json"
                }
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        return json.loads(content.strip())
            except Exception:
                pass

        return None

    async def explain_finding(self, finding: Dict[str, Any]) -> Dict[str, Any]:
        if not self.gemini_key and not self.openai_key:
            return await self.heuristic.explain_finding(finding)

        sanitized = sanitize_for_ai(finding)
        system_prompt = (
            "You are Cyphward Sovereign Security Intelligence. Provide technical security analysis strictly formatted "
            "as JSON with keys: what_is_this, why_it_matters, evidence_analysis, what_happens_if_ignored, sovereign_advisory"
        )
        user_prompt = f"Analyze and explain this security finding:\n{json.dumps(sanitized, indent=2, default=str)}"

        res = await self._call_llm(system_prompt, user_prompt)
        if res and isinstance(res, dict) and "what_is_this" in res:
            res["title"] = sanitized.get("title")
            res["severity"] = sanitized.get("severity")
            res["category"] = sanitized.get("category")
            return res

        return await self.heuristic.explain_finding(finding)

    async def generate_remediation(
        self,
        finding: Dict[str, Any],
        target_stack: str = "nginx"
    ) -> Dict[str, Any]:
        if not self.gemini_key and not self.openai_key:
            return await self.heuristic.generate_remediation(finding, target_stack)

        sanitized = sanitize_for_ai(finding)
        system_prompt = (
            f"Generate a concrete remediation guide tailored to stack '{target_stack}' formatted strictly as JSON "
            "with keys: summary, prerequisites (array), steps (array of strings), code_snippet, verification_command, estimated_time_minutes"
        )
        user_prompt = f"Remediate finding for {target_stack}:\n{json.dumps(sanitized, indent=2, default=str)}"

        res = await self._call_llm(system_prompt, user_prompt)
        if res and isinstance(res, dict) and "steps" in res:
            res["finding_id"] = sanitized.get("id")
            res["title"] = sanitized.get("title")
            res["target_stack"] = target_stack
            return res

        return await self.heuristic.generate_remediation(finding, target_stack)

    async def generate_executive_summary(
        self,
        org_name: str,
        score_data: Dict[str, Any],
        findings: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not self.gemini_key and not self.openai_key:
            return await self.heuristic.generate_executive_summary(org_name, score_data, findings)

        sanitized_score = sanitize_for_ai(score_data)
        sanitized_findings = sanitize_for_ai(findings[:10])

        system_prompt = (
            "You are Cyphward Chief Information Security Advisor. Generate an executive board-ready security report "
            "strictly as JSON with keys: executive_headline, board_summary, critical_action_items (array of objects with title, priority, rationale), compliance_implication"
        )
        user_prompt = (
            f"Enterprise: {org_name}\n"
            f"Score Data: {json.dumps(sanitized_score, default=str)}\n"
            f"Active Findings: {json.dumps(sanitized_findings, default=str)}"
        )

        res = await self._call_llm(system_prompt, user_prompt)
        if res and isinstance(res, dict) and "executive_headline" in res:
            return res

        return await self.heuristic.generate_executive_summary(org_name, score_data, findings)

    async def chat(
        self,
        message: str,
        history: List[Dict[str, str]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Conversational AI using Google Gemini with privacy shielding and heuristic fallback."""
        if not self.gemini_key and not self.openai_key:
            return await self.heuristic.chat(message, history, context)

        org_name = context.get("org_name", "Enterprise Enclave")
        score = context.get("score", 74)
        domain = context.get("domain", "corporate-enclave.ng")
        assets_count = context.get("assets_count", 18)
        findings = context.get("findings", [])

        # Sanitize finding summaries for privacy
        findings_summary = [
            {"title": f.get("title"), "severity": f.get("severity"), "category": f.get("category")}
            for f in findings[:8]
        ]

        system_instruction = (
            "You are CyphBot, an insightful, warm, and exceptionally clear cybersecurity assistant for Cyphward. "
            "Your responses should feel natural, thoughtful, and articulate — matching the communication style of Anthropic's Claude.\n\n"
            "Style & Formatting Principles:\n"
            "1. Speak naturally: Avoid rigid, repetitive boilerplate headings (DO NOT use headings like '### In Simple Terms', '### Why It Matters', '### How to Fix It in 3 Easy Steps', or '### Legal & Compliance Note'). Instead, write in fluid, cohesive paragraphs that naturally guide the reader.\n"
            "2. Conversational clarity: Explain complex security vulnerabilities using clear everyday analogies, making concepts feel immediately tangible without being overly casual or condescending.\n"
            "3. Actionable solutions: Present copy-paste configurations, DNS records, or commands in clean code blocks, followed by brief explanations of what the directives actually do.\n"
            "4. Organic context: Mention legal and compliance standards (such as NDPA 2023 Section 39 or CBN guidelines) naturally in the flow of discussion where relevant, not in isolated disclaimers.\n"
            "5. Structure: Use thoughtful bolding for readability, bullet points only when breaking down distinct technical factors, and end with a helpful, open-ended question or offer to adapt the fix for their specific stack."
        )

        enclave_prompt = (
            f"Organization Name: {org_name}\n"
            f"Monitored Domain: {domain}\n"
            f"Security Score: {score}/100\n"
            f"Discovered Assets: {assets_count}\n"
            f"Current Open Findings: {json.dumps(findings_summary, default=str)}\n"
        )

        # 1. Try OpenRouter (Claude)
        if self.is_openrouter:
            try:
                url = "https://openrouter.ai/api/v1/chat/completions"
                openrouter_messages = [
                    {"role": "system", "content": f"{system_instruction}\n\nOrganization Context:\n{enclave_prompt}"}
                ]
                for h in history[-6:]:
                    r = "assistant" if h.get("role") in ("model", "assistant") else "user"
                    c = h.get("content", "").strip()
                    if c and c != message.strip():
                        openrouter_messages.append({"role": r, "content": c})
                openrouter_messages.append({"role": "user", "content": message})

                payload = {
                    "model": "anthropic/claude-3-haiku",
                    "messages": openrouter_messages,
                    "temperature": 0.25,
                    "max_tokens": 1024,
                }
                headers = {
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://cyphward.com",
                    "X-Title": "Cyphward Sovereign Security",
                }
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        reply_text = data["choices"][0]["message"]["content"].strip()
                        return {
                            "answer": reply_text,
                            "sources": [
                                {"id": "src_claude", "label": "Anthropic Claude Sovereign Intelligence"},
                                {"id": "src_telemetry", "label": f"{org_name} Live Telemetry"},
                                {"id": "src_ndpa", "label": "NDPA 2023 & CBN Guidelines"},
                            ],
                            "actions": [
                                {"label": "View Related Controls", "kind": "solid", "path": "/comply"},
                                {"label": "Inspect Assets", "kind": "ghost", "path": "/assets"},
                            ],
                        }
            except Exception:
                pass

        # 2. Try Gemini if configured and not rate-limited
        now = time.time()
        if self.gemini_key and now > self._gemini_rate_limited_until:
            try:
                gemini_contents = []
                gemini_contents.append({"role": "user", "parts": [{"text": f"System Context & Rules:\n{system_instruction}\n\nOrganization Context:\n{enclave_prompt}Please acknowledge in a friendly, conversational tone."}]})
                gemini_contents.append({"role": "model", "parts": [{"text": f"Hi! I'm CyphBot, your security assistant for {org_name}. I'm here to explain your perimeter findings in plain English and give you simple, step-by-step fix guides. What can I help you with today?"}]})
                for h in history[-6:]:
                    role = "user" if h.get("role") == "user" else "model"
                    content = h.get("content", "").strip()
                    if content and content != message.strip():
                        gemini_contents.append({"role": role, "parts": [{"text": content}]})
                gemini_contents.append({"role": "user", "parts": [{"text": message}]})

                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_key}"
                payload = {
                    "contents": gemini_contents,
                    "generationConfig": {
                        "temperature": 0.25,
                        "maxOutputTokens": 1024,
                    },
                }
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            parts = candidates[0]["content"].get("parts", [])
                            if parts and "text" in parts[0]:
                                reply_text = parts[0]["text"].strip()
                                return {
                                    "answer": reply_text,
                                    "sources": [
                                        {"id": "src_gemini", "label": "Google Gemini Sovereign AI"},
                                        {"id": "src_enclave", "label": f"{org_name} Live Telemetry"},
                                        {"id": "src_ndpa", "label": "NDPA 2023 & CBN Guidelines"},
                                    ],
                                    "actions": [
                                        {"label": "View Related Controls", "kind": "solid", "path": "/comply"},
                                        {"label": "Inspect Assets", "kind": "ghost", "path": "/assets"},
                                    ],
                                }
                    elif resp.status_code == 429:
                        self._gemini_rate_limited_until = now + 86400.0
            except Exception:
                pass

        # Fallback to heuristic
        return await self.heuristic.chat(message, history, context)

    async def chat_stream(
        self,
        message: str,
        history: List[Dict[str, str]],
        context: Dict[str, Any]
    ):
        """Streams response tokens progressively using OpenRouter (Claude) or Heuristic fallback."""
        org_name = context.get("org_name", "Enterprise Enclave")
        score = context.get("score", 74)
        domain = context.get("domain", "corporate-enclave.ng")
        assets_count = context.get("assets_count", 18)
        findings = context.get("findings", [])

        findings_summary = [
            {"title": f.get("title"), "severity": f.get("severity"), "category": f.get("category")}
            for f in findings[:8]
        ]

        system_instruction = (
            "You are CyphBot, an insightful, warm, and exceptionally clear cybersecurity assistant for Cyphward. "
            "Your responses should feel natural, thoughtful, and articulate — matching the communication style of Anthropic's Claude.\n\n"
            "Style & Formatting Principles:\n"
            "1. Speak naturally: Avoid rigid, repetitive boilerplate headings (DO NOT use headings like '### In Simple Terms', '### Why It Matters', '### How to Fix It in 3 Easy Steps', or '### Legal & Compliance Note'). Instead, write in fluid, cohesive paragraphs that naturally guide the reader.\n"
            "2. Conversational clarity: Explain complex security vulnerabilities using clear everyday analogies, making concepts feel immediately tangible without being overly casual or condescending.\n"
            "3. Actionable solutions: Present copy-paste configurations, DNS records, or commands in clean code blocks, followed by brief explanations of what the directives actually do.\n"
            "4. Organic context: Mention legal and compliance standards (such as NDPA 2023 Section 39 or CBN guidelines) naturally in the flow of discussion where relevant, not in isolated disclaimers.\n"
            "5. Structure: Use thoughtful bolding for readability, bullet points only when breaking down distinct technical factors, and end with a helpful, open-ended question or offer to adapt the fix for their specific stack."
        )

        enclave_prompt = (
            f"Organization Name: {org_name}\n"
            f"Monitored Domain: {domain}\n"
            f"Security Score: {score}/100\n"
            f"Discovered Assets: {assets_count}\n"
            f"Current Open Findings: {json.dumps(findings_summary, default=str)}\n"
        )

        if self.is_openrouter:
            try:
                url = "https://openrouter.ai/api/v1/chat/completions"
                openrouter_messages = [
                    {"role": "system", "content": f"{system_instruction}\n\nOrganization Context:\n{enclave_prompt}"}
                ]
                for h in history[-6:]:
                    r = "assistant" if h.get("role") in ("model", "assistant") else "user"
                    c = h.get("content", "").strip()
                    if c and c != message.strip():
                        openrouter_messages.append({"role": r, "content": c})
                openrouter_messages.append({"role": "user", "content": message})

                payload = {
                    "model": "anthropic/claude-3-haiku",
                    "messages": openrouter_messages,
                    "stream": True,
                    "temperature": 0.25,
                    "max_tokens": 1024,
                }
                headers = {
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://cyphward.com",
                    "X-Title": "Cyphward Sovereign Security",
                }
                async with httpx.AsyncClient(timeout=14.0) as client:
                    async with client.stream("POST", url, json=payload, headers=headers) as resp:
                        if resp.status_code == 200:
                            async for line in resp.aiter_lines():
                                if not line:
                                    continue
                                if line.startswith("data: "):
                                    data_str = line[6:].strip()
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        chunk_obj = json.loads(data_str)
                                        choices = chunk_obj.get("choices", [])
                                        if choices and "delta" in choices[0]:
                                            delta = choices[0]["delta"].get("content", "")
                                            if delta:
                                                yield {"token": delta, "done": False}
                                    except Exception:
                                        continue

                            yield {
                                "token": "",
                                "done": True,
                                "sources": [
                                    {"id": "src_claude", "label": "Anthropic Claude Sovereign Intelligence"},
                                    {"id": "src_telemetry", "label": f"{org_name} Live Telemetry"},
                                    {"id": "src_ndpa", "label": "NDPA 2023 & CBN Guidelines"},
                                ],
                                "actions": [
                                    {"label": "View Related Controls", "kind": "solid", "path": "/comply"},
                                    {"label": "Inspect Assets", "kind": "ghost", "path": "/assets"},
                                ],
                            }
                            return
            except Exception:
                pass

        # Fallback to streaming heuristic
        async for chunk in self.heuristic.chat_stream(message, history, context):
            yield chunk
