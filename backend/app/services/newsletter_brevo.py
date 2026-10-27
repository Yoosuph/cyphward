"""Brevo calls for the newsletter list and campaigns (docs/newsletter/README.md).

Kept apart from the transactional mailer: these calls touch only the newsletter list
(NEWSLETTER_BREVO_LIST_ID). They are always made outside any database transaction, with
no pooled connection held. Errors carry the HTTP status only, never a response body
(which can echo addresses).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from backend.app.core import config

logger = logging.getLogger("cyphward.newsletter.brevo")

BREVO_API = "https://api.brevo.com/v3"
_REMOVE_BATCH = 150
_PAGE = 500


class BrevoError(RuntimeError):
    def __init__(self, operation: str, status: int | None):
        super().__init__(f"Brevo {operation} failed (status {status})")
        self.operation = operation
        self.status = status


class BrevoNewsletterClient:
    def __init__(self, api_key: str, list_id: int, unsub_attribute: str, timeout: float = 15.0):
        self._headers = {"api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"}
        self.list_id = int(list_id)
        self.unsub_attribute = unsub_attribute
        self._timeout = timeout

    async def _request(self, operation: str, method: str, path: str, ok: tuple, **kw) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(method, f"{BREVO_API}{path}", headers=self._headers, **kw)
        except httpx.HTTPError as exc:
            raise BrevoError(operation, None) from exc
        if resp.status_code not in ok:
            raise BrevoError(operation, resp.status_code)
        return resp

    async def upsert_list_contact(self, email: str, unsub_token: str) -> None:
        """Create or update the contact, put it on the newsletter list and store its unsubscribe token."""
        await self._request(
            "add contact", "POST", "/contacts", (200, 201, 204),
            json={"email": email, "listIds": [self.list_id], "updateEnabled": True,
                  "attributes": {self.unsub_attribute: unsub_token}},
        )

    async def remove_from_list(self, emails: List[str]) -> None:
        for i in range(0, len(emails), _REMOVE_BATCH):
            batch = emails[i:i + _REMOVE_BATCH]
            try:
                await self._request("remove contacts", "POST", f"/contacts/lists/{self.list_id}/contacts/remove",
                                    (200, 201, 204), json={"emails": batch})
            except BrevoError as exc:
                # Brevo answers 400 when none of the addresses is on the list: nothing to remove.
                if exc.status != 400:
                    raise

    async def list_contacts(self) -> List[Dict[str, Any]]:
        """Every list member: address, whether Brevo blocks it, and its unsubscribe-token attribute."""
        out: List[Dict[str, Any]] = []
        offset = 0
        while True:
            resp = await self._request("list contacts", "GET", f"/contacts/lists/{self.list_id}/contacts", (200,),
                                       params={"limit": _PAGE, "offset": offset})
            data = resp.json() or {}
            page = data.get("contacts") or []
            out.extend({"email": str(c.get("email") or "").strip().lower(),
                        "blocked": bool(c.get("emailBlacklisted")),
                        "unsub": str((c.get("attributes") or {}).get(self.unsub_attribute) or "")}
                       for c in page if c.get("email"))
            offset += len(page)
            if not page or len(page) < _PAGE or offset >= int(data.get("count") or 0):
                return out

    async def create_campaign(self, *, name: str, subject: str, preview: str, html: str, sender: tuple) -> str:
        resp = await self._request(
            "create campaign", "POST", "/emailCampaigns", (200, 201),
            json={"name": name[:250], "subject": subject, "previewText": preview,
                  "sender": {"name": sender[0], "email": sender[1]}, "htmlContent": html,
                  "recipients": {"listIds": [self.list_id]}, "inlineImageActivation": False},
        )
        campaign_id = (resp.json() or {}).get("id")
        if campaign_id is None:
            raise BrevoError("create campaign", resp.status_code)
        return str(campaign_id)

    async def send_campaign_now(self, campaign_id: str) -> None:
        await self._request("send campaign", "POST", f"/emailCampaigns/{campaign_id}/sendNow", (200, 201, 204))


def get_client(list_id: int, unsub_attribute: str) -> BrevoNewsletterClient:
    """The live client. Tests replace this function with a stub; no test makes a real call."""
    return BrevoNewsletterClient(config.BREVO_API_KEY, list_id, unsub_attribute)
