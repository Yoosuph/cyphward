"""Newsletter endpoints (docs/newsletter/README.md). Every route returns 404 while the feature is off.

Public:   POST /subscribe (always the same 202), GET /confirm, GET /unsubscribe (one click), GET /status
GrokBot:  POST /drafts with NEWSLETTER_DRAFT_API_KEY (creates drafts; nothing else)
Admin:    GET /drafts (preview) and POST /drafts/{id}/send (explicit approval, once) for the platform owner
          (console cookie) or platform staff holding the platform:newsletter scope.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator
from starlette.concurrency import run_in_threadpool

from backend.app.core import config
from backend.app.core import newsletter as nl
from backend.app.core import owner as owner_mod
from backend.app.core.auth import get_current_user
from backend.app.core.platform import require_platform_staff
from backend.app.core.rate_limit import check_rate_limit
from backend.app.services import newsletter_brevo
from backend.app.services.mailer import send_email_async

logger = logging.getLogger("cyphward.newsletter")

router = APIRouter(prefix="/api/v1/newsletter", tags=["Newsletter"])


class _RedactTokens(logging.Filter):
    """Access logs record the request line; newsletter links carry their token in the query, so it is masked."""
    _pattern = re.compile(r"(/api/v1/newsletter/[a-z]+\?(?:[^ \"]*&)?token=)[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and record.args:
            record.args = tuple(self._pattern.sub(r"\1REDACTED", a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = self._pattern.sub(r"\1REDACTED", record.msg)
        return True


ACCESS_LOG_FILTER = _RedactTokens()
if not any(isinstance(f, _RedactTokens) for f in logging.getLogger("uvicorn.access").filters):
    logging.getLogger("uvicorn.access").addFilter(ACCESS_LOG_FILTER)

NEWSLETTER_SCOPE = "platform:newsletter"
SUBSCRIBE_ACCEPTED = {
    "message": "Thank you. If this address can receive the newsletter, a confirmation email is on its way. "
               "Open the link in it within 72 hours to finish subscribing.",
}
# Subscribe and confirm answer no sooner than this, so a fast path cannot be told from a slow one.
MIN_RESPONSE_SECONDS = 0.35
_MAX_DRAFT_BYTES = 64 * 1024
# RFC 8058 one-click unsubscribes across all senders per hour (no per-IP cap; see unsubscribe()).
ONE_CLICK_HOURLY_CEILING = 20000


def require_enabled() -> nl.Settings:
    s = nl.settings()
    if s is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return s


async def _pad(started: float) -> None:
    remaining = MIN_RESPONSE_SECONDS - (time.monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)


def _ip_bucket(request: Request) -> str:
    ip = owner_mod.client_ip(request) or "unknown"
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Public: subscribe, confirm, unsubscribe
# ---------------------------------------------------------------------------
class SubscribeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)
    consent: StrictBool  # the JSON value true; 1, "true" and friends are refused
    consent_wording_version: Literal["2026-10-26.v1"]
    source: Literal["landing_footer", "newsletter_page"]
    website: str = Field(default="", max_length=200)  # hidden field: people leave it empty

    @field_validator("consent")
    @classmethod
    def _agreed(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("consent is required")
        return value


assert nl.CONSENT_WORDING_VERSION == "2026-10-26.v1"  # keep the Literal above in step


@router.get("/status")
def newsletter_status(s: nl.Settings = Depends(require_enabled)) -> Dict[str, Any]:
    return {"enabled": True, "consent_wording": nl.CONSENT_WORDING,
            "consent_wording_version": nl.CONSENT_WORDING_VERSION, "confirm_hours": nl.CONFIRM_TTL_HOURS}


async def _send_confirmation(s: nl.Settings, issued: nl.Issued) -> None:
    mail = nl.render_confirmation(s, issued)
    try:
        result = await send_email_async(
            issued.email, mail["subject"], mail["html"], mail["text"],
            recipient_name=issued.email.split("@")[0], sender=s.sender, allow_campaign_fallback=False,
            mail_headers=mail["headers"],
        )
        if not result.get("success"):
            logger.warning("newsletter confirmation not delivered (subscriber %s)", issued.subscriber_id)
    except Exception:
        logger.warning("newsletter confirmation failed (subscriber %s)", issued.subscriber_id)


@router.post("/subscribe", status_code=202)
async def subscribe(body: SubscribeIn, request: Request, background: BackgroundTasks,
                    s: nl.Settings = Depends(require_enabled)) -> Dict[str, str]:
    started = time.monotonic()
    # Per IP: an honest 429 (it says nothing about any address).
    await run_in_threadpool(check_rate_limit, f"newsletter:subscribe:ip:{_ip_bucket(request)}", 10, 3600)
    if not body.website.strip():
        email = nl.normalise_email(str(body.email))
        issued: Optional[nl.Issued] = None
        try:
            # Per address: silently dropped when exhausted, so the answer never differs by input.
            await run_in_threadpool(check_rate_limit, f"newsletter:subscribe:email:{nl.email_bucket(email)}", 3, 3600)
            issued = await run_in_threadpool(
                nl.store().subscribe, email, body.consent_wording_version, body.source, s.token_secret)
        except HTTPException as exc:
            if exc.status_code != 429:
                raise
        if issued is not None:
            background.add_task(_send_confirmation, s, issued)  # after the response: no timing signal
    await _pad(started)
    return SUBSCRIBE_ACCEPTED


def _result_redirect(s: nl.Settings, page: str, result: str) -> RedirectResponse:
    return RedirectResponse(f"{s.base_url}/newsletter/{page}?result={result}", status_code=303)


async def _add_to_list(s: nl.Settings, result: nl.ConfirmResult) -> None:
    try:
        client = newsletter_brevo.get_client(s.list_id, s.unsub_attribute)
        await client.upsert_list_contact(result.email,
                                         nl.unsubscribe_token(s.token_secret, result.subscriber_id, result.generation))
    except Exception as exc:
        # The list is reconciled before every send, so a confirmed address missed here is added then.
        logger.warning("newsletter: adding confirmed subscriber %s to the list failed: %s", result.subscriber_id, exc)


async def _remove_from_list(s: nl.Settings, email: str) -> None:
    try:
        client = newsletter_brevo.get_client(s.list_id, s.unsub_attribute)
        await client.remove_from_list([email])
    except Exception as exc:
        # Reconciled before every send: an unsubscribed address is removed before any campaign is created.
        logger.warning("newsletter: removing an unsubscribed address from the list failed: %s", exc)


# Email links are opened by mail scanners and link previewers, so a GET never changes anything: it shows a small
# page whose button POSTs the token in the form body. RFC 8058 one-click (List-Unsubscribe-Post) POSTs to the
# unsubscribe URL itself, with the token in its query string.
_PAGE_CSP = ("default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; "
             "base-uri 'none'")
_PAGE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex",
                 "Content-Security-Policy": _PAGE_CSP}
_PAGES = {
    "confirm": ("Confirm your subscription", "Press the button to start receiving the Cyphward newsletter.",
                "Confirm subscription"),
    "unsubscribe": ("Unsubscribe", "Press the button to stop the Cyphward newsletter for this address. "
                    "No sign-in is needed.", "Unsubscribe"),
}


def _action_page(kind: str, token: str) -> HTMLResponse:
    title, lede, button = _PAGES[kind]
    page = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"robots\" content=\"noindex\">"
        f"<title>{html.escape(title)} - Cyphward</title><style>"
        "body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#f3f4f6;color:#111827}"
        "main{max-width:480px;margin:12vh auto;padding:28px 24px;background:#fff;border-radius:8px}"
        "h1{font-size:22px;margin:0 0 12px}p{font-size:15px;line-height:1.6;margin:0 0 20px}"
        "button{min-height:44px;min-width:44px;padding:12px 20px;border:0;border-radius:6px;background:#111827;"
        "color:#fff;font-size:15px;font-weight:bold;cursor:pointer}"
        "button:focus-visible{outline:3px solid #c63a14;outline-offset:3px}"
        "</style></head><body><main>"
        f"<p style=\"font-size:12px;letter-spacing:.08em;color:#4b5563;margin:0 0 8px\">CYPHWARD NEWS</p>"
        f"<h1>{html.escape(title)}</h1><p>{html.escape(lede)}</p>"
        f"<form method=\"post\" action=\"/api/v1/newsletter/{kind}\">"
        f"<input type=\"hidden\" name=\"token\" value=\"{html.escape(token, quote=True)}\">"
        f"<button type=\"submit\">{html.escape(button)}</button></form>"
        "</main></body></html>"
    )
    return HTMLResponse(page, headers=_PAGE_HEADERS)


async def _form_fields(request: Request) -> Dict[str, str]:
    """application/x-www-form-urlencoded body, read without python-multipart; small bodies only."""
    raw = await request.body()
    if len(raw) > 2048:
        raise HTTPException(status_code=413, detail="Request too large.")
    fields = parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True, max_num_fields=8)
    return {k: v[0] for k, v in fields.items() if v}


@router.get("/confirm")
async def confirm_page(request: Request, token: str = Query("", max_length=200),
                       s: nl.Settings = Depends(require_enabled)):
    await run_in_threadpool(check_rate_limit, f"newsletter:page:ip:{_ip_bucket(request)}", 120, 3600)
    if nl.token_subscriber_id(token) is None:
        return _result_redirect(s, "confirmed", "invalid")
    return _action_page("confirm", token)  # no database change: the button POSTs


@router.post("/confirm")
async def confirm(request: Request, background: BackgroundTasks, s: nl.Settings = Depends(require_enabled)):
    started = time.monotonic()
    await run_in_threadpool(check_rate_limit, f"newsletter:confirm:ip:{_ip_bucket(request)}", 30, 3600)
    token = (await _form_fields(request)).get("token", "")
    result = nl.ConfirmResult("invalid")
    sid = nl.token_subscriber_id(token)
    if sid is not None:
        try:
            # Per subscriber (the address behind the token): over the limit, the link simply does not work.
            await run_in_threadpool(check_rate_limit, f"newsletter:confirm:sub:{nl.email_bucket(sid)}", 10, 3600)
            result = await run_in_threadpool(nl.store().confirm, token)
        except HTTPException as exc:
            if exc.status_code != 429:
                raise
    if result.outcome == "confirmed":
        background.add_task(_add_to_list, s, result)
    await _pad(started)
    page = {"confirmed": "ok", "already": "ok", "expired": "expired"}.get(result.outcome, "invalid")
    return _result_redirect(s, "confirmed", page)


@router.get("/unsubscribe")
async def unsubscribe_page(request: Request, token: str = Query("", max_length=200),
                           s: nl.Settings = Depends(require_enabled)):
    await run_in_threadpool(check_rate_limit, f"newsletter:page:ip:{_ip_bucket(request)}", 120, 3600)
    if nl.token_subscriber_id(token) is None:
        return _result_redirect(s, "unsubscribed", "invalid")
    return _action_page("unsubscribe", token)  # no database change: the button POSTs


@router.post("/unsubscribe")
async def unsubscribe(request: Request, background: BackgroundTasks, token: str = Query("", max_length=200),
                      s: nl.Settings = Depends(require_enabled)):
    """The page's button (token in the form body) or RFC 8058 one-click (token in the List-Unsubscribe URL)."""
    fields = await _form_fields(request)
    one_click = fields.get("List-Unsubscribe") == "One-Click"
    if one_click:
        # Mail providers send these from a few shared servers, so there is no per-IP cap: the token authorises the
        # request. A generous global ceiling still bounds the database work.
        await run_in_threadpool(check_rate_limit, "newsletter:unsubscribe:one-click:all", ONE_CLICK_HOURLY_CEILING, 3600)
    else:
        await run_in_threadpool(check_rate_limit, f"newsletter:unsubscribe:ip:{_ip_bucket(request)}", 60, 3600)
    result = await run_in_threadpool(nl.store().unsubscribe, fields.get("token") or token)
    if result.outcome in ("unsubscribed", "already") and result.email:
        background.add_task(_remove_from_list, s, result.email)
    ok = result.outcome != "invalid"
    if one_click:  # a mail provider, not a person: a plain answer, no redirect
        return PlainTextResponse("Unsubscribed." if ok else "Link not recognised.", status_code=200 if ok else 400,
                                 headers={"Cache-Control": "no-store"})
    return _result_redirect(s, "unsubscribed", "ok" if ok else "invalid")


# ---------------------------------------------------------------------------
# GrokBot: drafts only
# ---------------------------------------------------------------------------
def require_draft_key(request: Request, authorization: Optional[str] = Header(None)) -> None:
    expected = config.NEWSLETTER_DRAFT_API_KEY or ""
    supplied = ""
    if authorization and authorization[:7].lower() == "bearer ":
        supplied = authorization[7:].strip()
    # An unset or short key never matches, so an empty header can never pass.
    if len(expected) < 32 or not supplied or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="A valid draft key is required.")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > _MAX_DRAFT_BYTES:
        raise HTTPException(status_code=413, detail="Draft too large.")


@router.post("/drafts", status_code=201, dependencies=[Depends(require_enabled), Depends(require_draft_key)])
async def create_draft(body: nl.DraftIn, request: Request) -> Dict[str, Any]:
    await run_in_threadpool(check_rate_limit, f"newsletter:drafts:ip:{_ip_bucket(request)}", 30, 3600)
    row = await run_in_threadpool(nl.store().create_issue, body.model_dump(), "grokbot", {"sections": len(body.sections)})
    return {"id": str(row["id"]), "status": row["status"], "created_at": _iso(row.get("created_at"))}


# ---------------------------------------------------------------------------
# Admin: preview and send
# ---------------------------------------------------------------------------
def require_newsletter_admin(request: Request) -> Dict[str, Any]:
    """Platform staff (bearer token + platform:newsletter scope) or the platform owner (console cookie)."""
    authorization = request.headers.get("authorization")
    if authorization:
        user = get_current_user(authorization=authorization, request=request)
        staff = require_platform_staff(NEWSLETTER_SCOPE)(user)
        return {"kind": "platform_staff", "user_id": str(staff["user"]["id"])}
    owner = owner_mod.require_owner(request)
    return {"kind": "owner", "user_id": owner["user_id"]}


def require_newsletter_admin_mutation(request: Request,
                                      admin: Dict[str, Any] = Depends(require_newsletter_admin)) -> Dict[str, Any]:
    if admin["kind"] == "owner":
        owner_mod.require_console_origin(request)  # cookie-authenticated: exact console Origin only
    return admin


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _issue_out(s: nl.Settings, row: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: _iso(row.get(k)) for k in ("status", "subject", "preview", "created_by", "created_at", "sent_at",
                                         "brevo_campaign_id", "approved_at", "send_claimed_at", "send_error")}
    out["id"] = str(row["id"])
    out["sendable"] = row["status"] == "draft" and row.get("send_claimed_at") is None
    out["sections"] = (row.get("body_json") or {}).get("sections", [])
    try:
        rendered = nl.render_issue(s, row["body_json"], unsub_href=f"{s.base_url}/api/v1/newsletter/unsubscribe?token=PREVIEW")
        out["preview_html"], out["preview_text"] = rendered["html"], rendered["text"]
    except Exception:
        out["preview_html"] = out["preview_text"] = None
        out["sendable"] = False
    return out


@router.get("/drafts")
async def list_drafts(s: nl.Settings = Depends(require_enabled),
                      admin: Dict[str, Any] = Depends(require_newsletter_admin)) -> Dict[str, Any]:
    rows = await run_in_threadpool(nl.store().list_issues)
    confirmed = await run_in_threadpool(nl.store().count_confirmed)
    return {"issues": [_issue_out(s, r) for r in rows], "confirmed_subscribers": confirmed}


class SendIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    approve: Literal[True]
    subject: str = Field(min_length=1, max_length=120)  # must repeat the draft's subject exactly


async def _reconcile(s: nl.Settings, client: Any) -> Dict[str, int]:
    """Make the Brevo list equal the confirmed subscribers, each with a working unsubscribe token, or refuse."""
    confirmed = {r["email_normalised"]: r for r in await run_in_threadpool(nl.store().confirmed_subscribers)}
    contacts = await client.list_contacts()
    blocked = sorted({c["email"] for c in contacts if c["blocked"]})
    if blocked:
        # Unsubscribed or blocked in Brevo: unsubscribed here too, immediately and for good.
        await run_in_threadpool(nl.store().mark_unsubscribed, blocked)
        for email in blocked:
            confirmed.pop(email, None)
    on_list = {c["email"] for c in contacts}
    stray = sorted(e for e in on_list if e not in confirmed)
    if stray:
        await client.remove_from_list(stray)
    expected = {e: nl.unsubscribe_token(s.token_secret, str(r["id"]), int(r["token_generation"]))
                for e, r in confirmed.items()}
    current = {c["email"]: c.get("unsub", "") for c in contacts}
    missing = [e for e in confirmed if e not in on_list]
    stale = [e for e in confirmed if e in on_list and current.get(e) != expected[e]]
    for e in missing + stale:
        await client.upsert_list_contact(e, expected[e])
    # Fail closed: every recipient must be confirmed here and carry a working unsubscribe link.
    after = {c["email"]: c for c in await client.list_contacts()}
    problems = sorted(e for e, c in after.items() if e not in confirmed or c["blocked"]) + \
        sorted(e for e in confirmed if e not in after or after[e].get("unsub", "") != expected[e])
    if problems:
        raise RuntimeError(f"list check failed for {len(problems)} contact(s): not confirmed here or "
                           f"missing a matching {s.unsub_attribute} attribute")
    return {"confirmed": len(confirmed), "removed": len(stray), "added": len(missing), "refreshed": len(stale),
            "blocked": len(blocked)}


@router.post("/drafts/{issue_id}/send")
async def send_draft(issue_id: str, body: SendIn, s: nl.Settings = Depends(require_enabled),
                     admin: Dict[str, Any] = Depends(require_newsletter_admin_mutation)) -> Dict[str, Any]:
    try:
        issue_id = str(uuid.UUID(issue_id))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Not Found")
    issue = await run_in_threadpool(nl.store().get_issue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Not Found")
    if issue["status"] != "draft" or issue.get("send_claimed_at") is not None:
        raise HTTPException(status_code=409, detail="This issue has already been sent or a send was already attempted.")
    if body.subject != issue["subject"]:
        raise HTTPException(status_code=422, detail="Type the draft's subject exactly to approve sending it.")
    try:
        rendered = nl.render_issue(s, issue["body_json"])
    except Exception:
        raise HTTPException(status_code=422, detail="This draft no longer passes the draft rules and cannot be sent.")

    claimed = await run_in_threadpool(nl.store().claim_issue, issue_id, admin)
    if claimed is None:
        raise HTTPException(status_code=409, detail="This issue has already been sent or a send was already attempted.")

    # From here the issue can never be sent again, whatever happens below.
    client = newsletter_brevo.get_client(s.list_id, s.unsub_attribute)
    try:
        counts = await _reconcile(s, client)
        campaign_id = await client.create_campaign(
            name=f"Cyphward news {datetime.now(timezone.utc):%Y-%m-%d} {issue_id[:8]}",
            subject=rendered["subject"], preview=rendered["preview"], html=rendered["html"], sender=s.sender)
    except Exception as exc:
        await run_in_threadpool(nl.store().record_failure, issue_id, admin, f"before campaign: {exc}")
        raise HTTPException(status_code=502, detail="Nothing was sent: the mailing list could not be prepared. "
                                                    "Ask for a new draft once the cause is fixed.")
    await run_in_threadpool(nl.store().record_campaign, issue_id, campaign_id, admin, counts)
    try:
        await client.send_campaign_now(campaign_id)
    except Exception as exc:
        await run_in_threadpool(nl.store().record_failure, issue_id, admin, f"send campaign {campaign_id}: {exc}")
        raise HTTPException(status_code=502, detail=f"Brevo did not confirm the send of campaign {campaign_id}. "
                                                    "Check it in Brevo before doing anything else.")
    row = await run_in_threadpool(nl.store().mark_sent, issue_id, admin)
    return {"id": issue_id, "status": "sent", "brevo_campaign_id": campaign_id,
            "sent_at": _iso(row.get("sent_at")), "recipients": counts["confirmed"]}
