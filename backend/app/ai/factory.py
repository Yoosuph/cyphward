"""
Cyphward AI Provider Factory
Selects the active AI Provider based on configuration and security policy.
"""
import os
from backend.app.ai.base import AIProvider
from backend.app.ai.heuristic_provider import HeuristicAIProvider
from backend.app.ai.llm_provider import CloudLLMProvider

_provider_instance = None


def get_ai_provider() -> AIProvider:
    """Return the active AI Provider instance."""
    global _provider_instance
    if _provider_instance is None:
        if os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY"):
            _provider_instance = CloudLLMProvider()
        else:
            _provider_instance = HeuristicAIProvider()
    return _provider_instance
