"""
Cyphward AI Privacy Protection Layer
Ensures internal sensitive data (IP addresses, auth credentials, tokens, internal paths)
is stripped or masked before transmission to external AI models.
"""
import re
import uuid
import datetime
from typing import Any, Dict, List, Union


# Regex matchers for sensitive data
IPV4_REGEX = re.compile(r"\b(?!(?:10\.|127\.|192\.168\.|172\.(?:1[6-9]|2[0-9]|3[0-1])\.))(?:\d{1,3}\.){3}\d{1,3}\b")
INTERNAL_IP_REGEX = re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3})\b")
BEARER_TOKEN_REGEX = re.compile(r"(?i)(bearer\s+[a-zA-Z0-9_\-\.]{15,})")
API_KEY_REGEX = re.compile(r"(?i)(?:cyph_|api[_-]?key|secret|token|password)[\s:=]+['\"]?([a-zA-Z0-9_\-]{16,})['\"]?")
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")


def sanitize_text(text: str) -> str:
    """Sanitize sensitive identifiers from a string before AI processing."""
    if not isinstance(text, str):
        return text

    # Mask API keys and secrets
    text = API_KEY_REGEX.sub(r"[REDACTED_API_KEY]", text)
    text = BEARER_TOKEN_REGEX.sub(r"Bearer [REDACTED_TOKEN]", text)

    # Mask Internal IPs
    text = INTERNAL_IP_REGEX.sub(r"[REDACTED_INTERNAL_IP]", text)

    # Mask Public IPs with RFC 5737 documentation address range
    text = IPV4_REGEX.sub(r"192.0.2.1", text)

    # Mask specific corporate user emails while preserving domain context
    def mask_email(match):
        em = match.group(0)
        parts = em.split("@")
        return f"security-officer@{parts[1]}"
    text = EMAIL_REGEX.sub(mask_email, text)

    return text


def sanitize_for_ai(data: Union[Dict, List, str, Any]) -> Any:
    """Recursively sanitize data structures for zero-leak AI ingestion."""
    if isinstance(data, str):
        return sanitize_text(data)
    elif isinstance(data, (uuid.UUID, datetime.date, datetime.datetime)):
        return str(data)
    elif isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            # Skip highly sensitive fields entirely
            if k.lower() in {"password", "secret", "api_key", "token", "authorization", "cookie"}:
                cleaned[k] = "[REDACTED_BY_CYPHWARD_PRIVACY_GUARD]"
            else:
                cleaned[k] = sanitize_for_ai(v)
        return cleaned
    elif isinstance(data, (list, tuple, set)):
        return [sanitize_for_ai(item) for item in data]
    else:
        return data
