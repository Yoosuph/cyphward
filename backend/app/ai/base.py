"""
Cyphward AI Provider Interface
Defines the required contract for AI remediation, explanation, and executive reporting.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List


class AIProvider(ABC):
    """Abstract interface for Cyphward AI security interpretation layer."""

    @abstractmethod
    async def explain_finding(self, finding: Dict[str, Any]) -> Dict[str, Any]:
        """
        Explain finding in plain language with deep technical precision:
        - What is this?
        - Why does it matter?
        - What is the evidence?
        - What happens if ignored?
        """
        pass

    @abstractmethod
    async def generate_remediation(
        self,
        finding: Dict[str, Any],
        target_stack: str = "nginx"
    ) -> Dict[str, Any]:
        """
        Generate actionable step-by-step fix guide with ready-to-use code snippets
        for the specified target stack (Nginx, Apache, Cloudflare, AWS, etc.).
        """
        pass

    @abstractmethod
    async def generate_executive_summary(
        self,
        org_name: str,
        score_data: Dict[str, Any],
        findings: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Synthesize board-level executive security assessment and posture verdict.
        """
        pass

    @abstractmethod
    async def chat(
        self,
        message: str,
        history: List[Dict[str, str]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Interactive conversational AI analysis with enclave telemetry and regulatory grounding.
        """
        pass
