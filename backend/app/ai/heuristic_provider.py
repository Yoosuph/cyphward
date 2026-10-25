"""
Cyphward Heuristic Sovereign AI Provider
Evidence-first expert cybersecurity intelligence engine.
Provides deterministic, high-accuracy security explanations, stack-specific remediation
blueprints, and board-level executive summaries without external data exfiltration.
"""
from typing import Dict, Any, List
import json
import asyncio
from backend.app.ai.base import AIProvider
from backend.app.ai.privacy import sanitize_for_ai
from backend.app.ai.safe_guidance import configuration_guide, configuration_topic


class HeuristicAIProvider(AIProvider):
    """Sovereign security intelligence provider adhering to Evidence First, AI Second."""

    async def explain_finding(self, finding: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = sanitize_for_ai(finding)
        title = sanitized.get("title", "Security Finding")
        category = sanitized.get("category", "General Security")
        severity = sanitized.get("severity", "medium").upper()
        evidence = sanitized.get("evidence", {})
        evidence_str = json.dumps(evidence, indent=2) if evidence else "Observed through automated probe telemetry."

        # Specialized synthesis based on vulnerability type
        if configuration_topic(title):
            what = f"Recorded configuration finding: {title}."
            why = "Review the observed configuration and the service's actual use before changing enforcement. Missing safeguards can increase exposure, but this observation does not prove exploitation."
            evidence_analysis = f"Recorded evidence only: {evidence_str}. Missing fields remain unknown."
            ignored = "The recorded configuration may remain exposed; impact depends on the application and mail flows. Use a staged, provider-specific review rather than assuming an outage or legal violation."
        elif "Server" in title or "Banner" in title or "Powered-By" in title:
            what = "Software banner disclosure occurs when the web server or application runtime advertises its exact product name and minor version in HTTP response headers."
            why = "Publicizing build versions provides reconnaissance intelligence to threat scanners, allowing adversaries to look up published zero-days and 1-day CVEs tailored to your exact stack."
            evidence_analysis = f"Disclosed banner identified in headers: '{evidence.get('disclosed_banner', evidence.get('server_header', 'Banner exposed'))}'. Reproducible via curl inspection."
            ignored = "Targeted automated exploitation by malicious botnets sweeping for specific unpatched web server vulnerabilities."
        elif "Content-Security-Policy" in title or "CSP" in title:
            what = "Content-Security-Policy (CSP) is a foundational defense-in-depth HTTP header that specifies approved sources for JavaScript, styles, images, and embedded objects."
            why = "A properly configured CSP mitigates Cross-Site Scripting (XSS) and data exfiltration by refusing to execute scripts injected by unauthorized third parties."
            evidence_analysis = "Automated inspection confirmed that no 'Content-Security-Policy' header is declared on HTTP responses."
            ignored = "Severe exposure to client-side injection, credential scraping, keylogging, and unauthorized third-party tracking scripts."
        elif "Certificate" in title or "TLS" in title or "SSL" in title:
            days = evidence.get("days_remaining", "few")
            what = "TLS Certificate Lifecycle & Cryptographic Protocol Status represents the health of the public key infrastructure safeguarding your encrypted perimeter."
            why = f"The server certificate is slated to expire or lacks renewal safeguards ({days} days remaining). Modern browsers enforce hard failure stops on invalid certificates."
            evidence_analysis = f"Certificate expiration audit for {evidence.get('hostname', 'host')}: Valid to {evidence.get('valid_to', 'soon')} with {days} days remaining."
            ignored = "Immediate outage of customer-facing portals, broken mobile app API integration, and prominent browser security warnings that destroy user trust."
        else:
            what = f"{title} represents an exposed attack surface or configuration vulnerability categorized under {category}."
            why = f"Classified at {severity} severity, this vulnerability directly degrades the enterprise attack surface boundary and invites adversarial exploitation."
            evidence_analysis = f"Deterministic probe evidence recorded: {evidence_str}."
            ignored = "Compromised perimeter integrity, increased lateral movement risk, and potential statutory regulatory sanctions."

        return {
            "title": title,
            "severity": severity,
            "category": category,
            "what_is_this": what,
            "why_it_matters": why,
            "evidence_analysis": evidence_analysis,
            "what_happens_if_ignored": ignored,
            "sovereign_advisory": "Cyphward Sovereign Intelligence recommends implementing the remediation blueprint in staging prior to production reload."
        }

    async def generate_remediation(
        self,
        finding: Dict[str, Any],
        target_stack: str = "nginx"
    ) -> Dict[str, Any]:
        sanitized = sanitize_for_ai(finding)
        title = sanitized.get("title", "")
        stack = target_stack.lower().strip()

        steps = []
        code_snippet = ""
        verification_cmd = "curl -sI https://example.com | head -n 20"

        curated = configuration_guide(sanitized, stack)
        if curated:
            return curated

        # 3. Server Version Disclosed
        if "Server" in title or "Banner" in title:
            if stack == "nginx":
                steps = [
                    "Open /etc/nginx/nginx.conf",
                    "Locate the http { ... } block",
                    "Add or set 'server_tokens off;'",
                    "Test config and reload Nginx: sudo nginx -t && sudo systemctl reload nginx"
                ]
                code_snippet = (
                    "# /etc/nginx/nginx.conf\n"
                    "http {\n"
                    "    server_tokens off;\n"
                    "    # ... rest of config ...\n"
                    "}"
                )
            elif stack == "apache":
                steps = [
                    "Open /etc/apache2/conf-available/security.conf",
                    "Set ServerTokens Prod and ServerSignature Off",
                    "Restart Apache: sudo systemctl restart apache2"
                ]
                code_snippet = (
                    "# /etc/apache2/conf-available/security.conf\n"
                    "ServerTokens Prod\n"
                    "ServerSignature Off"
                )
            else:
                steps = [
                    "Strip server headers at edge load balancer or CDN",
                    "For Cloudflare: Create a Transform Rule > Modify Response Header > Remove 'Server'"
                ]
                code_snippet = (
                    "# Cloudflare Transform Rule\n"
                    "When incoming request matches: (http.host eq \"yourdomain.com\")\n"
                    "Action: Modify Response Header\n"
                    "Operation: Remove\n"
                    "Header name: Server"
                )
            verification_cmd = "curl -sI https://yourdomain.com | grep -i server"

        # Fallback generic
        else:
            steps = [
                f"Review {title} recommendations with the infrastructure engineering team",
                "Apply the recommended fix in a staging environment",
                "Run verification commands and confirm error elimination",
                "Deploy changes to production and trigger a Cyphward rescan"
            ]
            code_snippet = (
                f"# Cyphward Remediation Script for {title}\n"
                f"# Target: {sanitized.get('category', 'Perimeter')}\n"
                f"# Please consult Cyphward security engineering docs for customized parameters."
            )

        return {
            "finding_id": sanitized.get("id"),
            "title": title,
            "target_stack": stack,
            "summary": f"Step-by-step remediation guide for {title} tailored to {stack.upper()}.",
            "prerequisites": [
                "Root or sudo administrative access to the web server / reverse proxy",
                "Ability to edit DNS zones or reverse proxy virtual hosts",
                "Active Cyphward account to verify remediation via rescan"
            ],
            "steps": steps,
            "code_snippet": code_snippet,
            "verification_command": verification_cmd,
            "estimated_time_minutes": 15
        }

    async def generate_executive_summary(
        self,
        org_name: str,
        score_data: Dict[str, Any],
        findings: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        score = score_data.get("score")
        grade = score_data.get("grade")
        posture = score_data.get("posture_label") or "Not assessed"
        active = [finding for finding in findings if finding.get("status") != "resolved"]
        priority = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        active.sort(key=lambda finding: (priority.get(finding.get("severity"), 4), finding.get("title", "")))
        headline = f"Known-risk score for {org_name}: {score}/100 — {posture}" if score is not None else f"Security Score for {org_name}: {posture}"
        narrative = (
            f"{org_name} has {len(active)} recorded open findings. "
            + (f"Its known-risk score is {score}/100. " if score is not None else "There is insufficient evaluated evidence for a security score. ")
            + "Only evaluated checks support these results; other areas remain unknown. "
            "A domain assessment does not establish whole-organization security."
        )
        return {
            "org_name": org_name, "score": score, "grade": grade,
            "posture_label": posture, "executive_headline": headline,
            "board_summary": narrative, "key_strengths": [],
            "critical_action_items": [{
                "priority": str(finding.get("severity") or "medium").upper(),
                "title": finding.get("title") or "Review recorded finding",
                "impact": finding.get("description") or "Review the recorded evidence and remediation.",
                "owner": "Assign an owner",
            } for finding in active[:3]],
            "compliance_verdict": (
                "This is technical evidence, not a compliance certification or filing. "
                "Cyphward does not determine legal compliance."
            ),
            "generated_at": "Live Telemetry",
        }

    async def chat(
        self,
        message: str,
        history: List[Dict[str, str]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Contextual heuristic conversation engine for sovereign African cybersecurity."""
        q_lower = message.lower()
        org_name = context.get("org_name", "Enterprise Enclave")
        score = context.get("score")
        open_findings = context.get("findings", [])
        
        if configuration_topic(message):
            topic = configuration_topic(message)
            topic_title = {"email": "DMARC" if "dmarc" in q_lower or "spoof" in q_lower else "SPF / DKIM", "transport": "HSTS / TLS", "browser_policy": "CSP / clickjacking"}[topic]
            guide = configuration_guide({"title": topic_title})
            answer = "This is general rollout guidance, not a new assessment of your domain.\n\n" + "\n".join(f"- {step}" for step in guide["steps"])
            sources = [{"id": "curated_guidance", "label": "Curated configuration guidance; provider prerequisites required"}]
        elif "ndpa" in q_lower or "compliance" in q_lower or "cbn" in q_lower or "law" in q_lower:
            answer = (
                "Cyphward's Compliance page organises technical observations, customer answers and reviewer notes. "
                "These records support preparation; they do not establish legal compliance or replace a Compliance Audit Return. "
                "Requirement references are pending professional review. Ask a qualified Nigerian adviser or licensed DPCO "
                "to confirm which duties apply to your business and the evidence/filing needed."
            )
            sources = [{"id": "compliance_scope", "label": "Cyphward readiness scope; professional review required"}]
        elif any(word in q_lower for word in ("board", "briefing", "executive", "report")):
            known = "Not assessed" if score is None else f"{score}/100 within the recorded assessment scope"
            titles = [str(f.get("title") or "Recorded finding") for f in open_findings[:3] if f.get("status") != "resolved"]
            answer = (
                f"Recorded score for **{org_name}**: {known}. "
                + ("Recorded open findings: " + "; ".join(titles) + ". " if titles else "No open finding details were supplied in this context; that is not proof of a clean assessment. ")
                + "Use the dated assessment/report for coverage, limitations and provenance. No TLS strength, closed-port result or compliance conclusion can be inferred from the score alone."
            )
            sources = [{"id": "recorded_context", "label": "Recorded assessment context"}]
        elif "domain" in q_lower:
            domains = context.get("domains") or (
                [{"domain": context.get("domain", ""), "verified": True}] if context.get("domain") else []
            )
            if domains:
                rows = "\n".join(
                    f"- **{d.get('domain')}** — {'verified' if d.get('verified') else 'not verified yet'}"
                    for d in domains
                )
                answer = (
                    f"You have **{len(domains)}** monitored domains on **{org_name}**:\n\n"
                    f"{rows}"
                )
                pending = [
                    d for d in domains
                    if not d.get("verified") and d.get("verification_token")
                ]
                if "verif" in q_lower and pending:
                    d0 = pending[0]
                    answer += (
                        f"\n\nTo verify **{d0.get('domain')}**, add this TXT record at your DNS provider:\n\n"
                        f"```dns\n"
                        f"Host:  @\n"
                        f"Type:  TXT\n"
                        f"Value: {d0.get('verification_token')}\n"
                        f"```\n\n"
                        f"DNS changes take a few minutes to a few hours. Then hit **Verify** on the Domains page."
                    )
                elif pending:
                    answer += "\n\nWant to verify the unverified one, or check something specific?"
                else:
                    answer += "\n\nWant me to check something specific on one of them?"
            else:
                answer = f"No domains are added to **{org_name}** yet. Add one under **Domains** to start monitoring."
            sources = [
                {"id": "s_inventory", "label": "Cyphward Asset Inventory"},
                {"id": "s_telemetry", "label": f"{org_name} Live Perimeter Telemetry"},
            ]
        else:
            if score is None:
                answer = (
                    f"Hi, I'm **CyphBot**. {org_name} hasn't completed a scan yet, so there's "
                    f"no security score to show.\n\n"
                    f"Start one from the Overview page — I'll have DNS, web app, email security, "
                    f"and encryption results to walk you through once it finishes."
                )
            else:
                answer = (
                    f"Hi, I'm **CyphBot**. {org_name}'s security score is **{score}/100** right now.\n\n"
                    f"What would you like to know?"
                )
            sources = [
                {"id": "s_core", "label": "Cyphward Defense Knowledge Core"},
                {"id": "s_telemetry", "label": f"{org_name} Live Perimeter Telemetry"},
            ]

        return {
            "answer": answer,
            "sources": sources,
            "actions": [
                {"label": "View Related Controls", "kind": "solid", "path": "/comply"},
                {"label": "Inspect Assets", "kind": "ghost", "path": "/assets"},
            ]
        }

    async def chat_stream(
        self,
        message: str,
        history: List[Dict[str, str]],
        context: Dict[str, Any]
    ):
        """Yields words progressively to emulate Claude natural surfacing."""
        res = await self.chat(message, history, context)
        answer = res["answer"]
        # Split text into small progressive chunks (words and punctuation)
        words = answer.split(" ")
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            yield {
                "token": token,
                "done": False,
            }
            await asyncio.sleep(0.015)

        yield {
            "token": "",
            "done": True,
            "sources": res.get("sources", []),
            "actions": res.get("actions", []),
        }
