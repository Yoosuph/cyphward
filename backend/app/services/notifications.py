"""
Notification service — inserts in-app notifications (spec §31).
Email fanout happens in the workflow layer for critical events.
"""
import re
from typing import Any, Dict, Optional

from backend.app.core.database import execute_one


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "org"


def notify(
    org_id: str,
    type: str,
    title: str,
    body: Optional[str] = None,
    severity: str = "info",
    link: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Create an in-app notification for an organization (best-effort)."""
    try:
        return execute_one(
            """
            INSERT INTO notifications (org_id, type, title, body, severity, link)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (org_id, type, title, body, severity, link),
        )
    except Exception:
        return None
