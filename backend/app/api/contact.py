"""Public contact form. No account required.

The address visitors see is info@cyphward.com. Messages are delivered to
CONTACT_INBOX so someone can reply from the company mailbox.
"""
import html
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.app.core.config import CONTACT_INBOX
from backend.app.services.mailer import send_email_async

router = APIRouter(prefix="/api/v1/contact", tags=["Contact"])

_HITS: dict[str, deque[float]] = defaultdict(deque)
_WINDOW_SECONDS = 3600
_MAX_PER_WINDOW = 5

TOPICS = {
    "general": "General",
    "product": "Product",
    "privacy": "Privacy",
    "security": "Security",
    "press": "Press",
}


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    organization: str = Field(default="", max_length=80)
    topic: str = "general"
    message: str = Field(min_length=10, max_length=4000)
    website: str = ""


def _throttle(ip: str) -> None:
    now = time.monotonic()
    hits = _HITS[ip]
    while hits and now - hits[0] > _WINDOW_SECONDS:
        hits.popleft()
    if len(hits) >= _MAX_PER_WINDOW:
        raise HTTPException(
            status_code=429,
            detail="Too many messages. Email info@cyphward.com instead.",
        )
    hits.append(now)


@router.post("")
async def submit_contact(body: ContactIn, request: Request):
    # Hidden field. A person leaves it empty; a bot often fills it.
    if body.website.strip():
        return {"ok": True}

    topic_key = body.topic if body.topic in TOPICS else "general"
    topic = TOPICS[topic_key]
    ip = request.client.host if request.client else "unknown"
    _throttle(ip)

    name = " ".join(body.name.split())
    organization = " ".join(body.organization.split())
    message = body.message.strip()
    visitor = str(body.email)
    subject = f"Cyphward contact · {topic} · {name}"[:180]

    text = (
        f"From: {name} <{visitor}>\n"
        f"Organization: {organization or '—'}\n"
        f"Topic: {topic}\n\n"
        f"{message}\n"
    )
    safe = html.escape
    html_body = (
        "<p><strong>From:</strong> "
        f"{safe(name)} &lt;{safe(visitor)}&gt;</p>"
        f"<p><strong>Organization:</strong> {safe(organization or '—')}</p>"
        f"<p><strong>Topic:</strong> {safe(topic)}</p>"
        f"<p>{safe(message).replace(chr(10), '<br>')}</p>"
    )

    try:
        result = await send_email_async(
            CONTACT_INBOX,
            subject,
            html_body,
            text,
            recipient_name="Cyphward",
            kind="general",
            reply_to=visitor,
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="We could not send that. Email info@cyphward.com.",
        )
    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail="We could not send that. Email info@cyphward.com.",
        )
    return {"ok": True}
