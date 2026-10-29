"""Cyphward newsletter: consent, single opt-in, GrokBot drafts and send-once issues.

Rules (docs/newsletter/README.md):

* Off unless NEWSLETTER_ENABLED is on AND the list id, postal line, token secret and Brevo
  key are configured. Off means every /api/v1/newsletter endpoint returns 404.
* A subscriber row holds the normalised email, the consent record (time, wording version,
  source page) and only salted hashes of the confirm and unsubscribe tokens.
* Single opt-in: ticking the consent box and submitting subscribes the address at once
  (status 'confirmed'). One branded confirmation email says so; it has no link to click.
  Rows left 'pending' by the earlier double opt-in are upgraded on their next subscribe,
  and their old confirm links (random, 72 hours) keep working until then.
* The unsubscribe token is derived with HMAC from NEWSLETTER_TOKEN_SECRET, the subscriber
  id and a generation number, so the same one-click link works in the confirmation email
  and in every issue (it reaches campaigns through a Brevo contact attribute). A new
  subscription bumps the generation, which retires older links. The database stores a
  salted hash of it, never the token.
* Only confirmed subscribers, with their consent recorded, are ever put on the Brevo list.
  An issue is sent once: the claim is a single conditional UPDATE, written in the same
  transaction as its audit row.

Pure decision functions sit beside the PostgreSQL store so the unit tests' in-memory store
and the real store make the same choices.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.compliance.practitioner import violation as c6_violation
from backend.app.core import config, database

CONSENT_WORDING = (
    "I agree that Cyphward may email me news about its product and security and regulation updates. "
    "I can withdraw at any time."
)
CONSENT_WORDING_VERSION = "2026-10-26.v1"
SOURCES = ("landing_footer", "newsletter_page")
# Only for confirm links already sent under the earlier double opt-in (rows still 'pending').
CONFIRM_TTL = timedelta(hours=72)
CONFIRM_TTL_HOURS = 72
# At most one confirmation email per address in this many seconds for a new or upgraded address
# (api.newsletter enforces it). A re-subscribe after an unsubscribe is always notified.
CONFIRMATION_EMAIL_WINDOW_SECONDS = 24 * 3600
# What the confirmation email and the privacy policy promise about frequency.
SEND_FREQUENCY = "about once a month"
# Brevo keeps list 2 for the mailer's transactional campaign fallback; the newsletter list must differ.
RESERVED_BREVO_LIST_IDS = frozenset({2})


# ---------------------------------------------------------------------------
# Settings (read at call time so tests and operators can flip them)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    list_id: int
    postal_line: str
    base_url: str
    token_secret: str
    unsub_attribute: str
    sender: tuple


def settings() -> Optional[Settings]:
    """The live configuration, or None when the feature is off or incomplete (fails closed)."""
    if not config.NEWSLETTER_ENABLED:
        return None
    try:
        list_id = int(str(config.NEWSLETTER_BREVO_LIST_ID or "").strip())
    except ValueError:
        return None
    secret = config.NEWSLETTER_TOKEN_SECRET or ""
    base = (config.NEWSLETTER_PUBLIC_BASE_URL or "").rstrip("/")
    attribute = config.NEWSLETTER_BREVO_UNSUB_ATTRIBUTE or ""
    if (
        list_id <= 0
        or list_id in RESERVED_BREVO_LIST_IDS
        or not (config.NEWSLETTER_POSTAL_LINE or "").strip()
        or len(secret) < 32
        or not config.BREVO_API_KEY
        or not base.startswith("https://")
        or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,39}", attribute)
    ):
        return None
    return Settings(
        list_id=list_id,
        postal_line=config.NEWSLETTER_POSTAL_LINE.strip(),
        base_url=base,
        token_secret=secret,
        unsub_attribute=attribute,
        sender=tuple(config.NEWSLETTER_SENDER),
    )


def normalise_email(value: str) -> str:
    return (value or "").strip().lower()


def email_bucket(email: str) -> str:
    """Rate-limit key for an address: a hash, so the bucket table never holds the address."""
    return hashlib.sha256(normalise_email(email).encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Tokens: "<subscriber id hex>.<secret>"; stored only as "s1$<salt>$<sha256(salt:token)>"
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"^([0-9a-f]{32})\.([A-Za-z0-9_-]{40,64})$")
_UNSUB_CONTEXT = "cyphward-newsletter-unsubscribe:v1"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def new_confirm_token(subscriber_id: str) -> str:
    return f"{uuid.UUID(str(subscriber_id)).hex}.{secrets.token_urlsafe(32)}"


def unsubscribe_token(secret: str, subscriber_id: str, generation: int) -> str:
    sid = uuid.UUID(str(subscriber_id))
    mac = hmac.new(secret.encode("utf-8"), f"{_UNSUB_CONTEXT}:{sid}:{int(generation)}".encode("utf-8"),
                   hashlib.sha256).digest()
    return f"{sid.hex}.{_b64(mac)}"


def token_subscriber_id(token: str) -> Optional[str]:
    """The subscriber id a well-formed token names, or None for anything malformed."""
    if not isinstance(token, str) or len(token) > 200:
        return None
    m = _TOKEN_RE.match(token)
    return str(uuid.UUID(m.group(1))) if m else None


def hash_token(token: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{token}".encode("utf-8")).hexdigest()
    return f"s1${salt}${digest}"


def token_matches(token: str, stored: Optional[str]) -> bool:
    if not stored or not token:
        return False
    parts = stored.split("$")
    if len(parts) != 3 or parts[0] != "s1":
        return False
    digest = hashlib.sha256(f"{parts[1]}:{token}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, parts[2])


# ---------------------------------------------------------------------------
# Decisions shared by the PostgreSQL store and the unit tests' store
# ---------------------------------------------------------------------------
def subscribe_generation(row: Optional[Dict[str, Any]]) -> Optional[int]:
    """New token generation for a subscribe request, or None when nothing changes.

    Single opt-in: a new, pending (left by the earlier double opt-in) or unsubscribed address
    becomes confirmed with this generation. A confirmed address is left exactly as it is (no
    email, no list call, no new tokens), so the request looks the same from outside whether or
    not the address is subscribed.
    """
    if row is None:
        return 1
    if row["status"] == "confirmed":
        return None
    return int(row["token_generation"]) + 1


ConfirmOutcome = Literal["confirmed", "already", "expired", "invalid"]
UnsubscribeOutcome = Literal["unsubscribed", "already", "invalid"]


def confirm_decision(row: Optional[Dict[str, Any]], token: str, now: datetime) -> ConfirmOutcome:
    if row is None or not token_matches(token, row.get("confirm_token_hash")):
        return "invalid"
    if row["status"] == "confirmed":
        return "already"
    if row["status"] != "pending":
        return "invalid"
    expires = row.get("confirm_expires_at")
    if expires is None:
        return "invalid"
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return "expired" if expires <= now else "confirmed"


def unsubscribe_decision(row: Optional[Dict[str, Any]], token: str) -> UnsubscribeOutcome:
    if row is None or not token_matches(token, row.get("unsubscribe_token_hash")):
        return "invalid"
    return "already" if row["status"] == "unsubscribed" else "unsubscribed"


@dataclass(frozen=True)
class Subscribed:
    """An address a subscribe request just made confirmed; held only long enough to add it to the
    list and send the confirmation email. The token itself is never stored, only its hash."""
    subscriber_id: str
    email: str
    unsubscribe_token: str
    generation: int
    consent_wording_version: str
    # The row's status before this request: "new", "pending" (earlier double opt-in) or "unsubscribed".
    # A previously unsubscribed address always gets the notice (no 24-hour suppression), so a stranger
    # cannot quietly put an address that left back on the list.
    previous_status: str = "new"


@dataclass(frozen=True)
class ConfirmResult:
    outcome: ConfirmOutcome
    subscriber_id: Optional[str] = None
    email: Optional[str] = None
    generation: Optional[int] = None


@dataclass(frozen=True)
class UnsubscribeResult:
    outcome: UnsubscribeOutcome
    email: Optional[str] = None


# ---------------------------------------------------------------------------
# GrokBot draft schema (strict; extra fields rejected; every string screened)
# ---------------------------------------------------------------------------
BANNED_CLAIMS = (
    "compliant", "certified", "certification", "satisfies", "adequate", "guarantee", "passes audit",
    "compliance score", "meets the requirement", "is met", "fully compliant", "is compliant",
)


def _claim_pattern(phrase: str) -> str:
    words = r"\s+".join(re.escape(w) for w in phrase.split())
    # Whole words, allowing plain inflections ("guarantees", "guaranteed", "compliance scores").
    return rf"\b{words}(?:s|es|d|ed|ly)?\b"


_BANNED_RE = re.compile("|".join(_claim_pattern(p) for p in BANNED_CLAIMS), re.IGNORECASE)
_TAG_RE = re.compile(r"[<>]")
_TEMPLATE_RE = re.compile(r"\{\{|\}\}|\{%|%\}|\[\[|\]\]")
_MD_LINK_RE = re.compile(r"\]\s*\(|\[[^\]]*\]\s*\[|<https?:", re.IGNORECASE)
_URL_RE = re.compile(
    r"([a-z][a-z0-9+.-]*://)|(\bwww\.)|(\bmailto:)|(\bdata:)|(\bjavascript:)"
    r"|(\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|ng|io|co|gov|edu|info|biz|uk|eu|africa|ai|app|dev|me|ly|gl|link|site|xyz)\b)",
    re.IGNORECASE,
)


# Ordinary regulation-news wording that the shared C6 filter would otherwise refuse, set aside one TRIGGER WORD at a
# time (never a whole phrase), so C6 still reads every other word of the sentence:
#   "approved": only when a public body approved it ("The NDPC [has] approved [new] guidance") and the next noun
#               is a legal instrument. Never when a refused word follows ("approved your setup", "approved Cyphward").
#   "meet":     only the plain verb (not meets/meeting) before "the ... date/deadline/timeline", and never when the
#               subject is you, your, customers, Cyphward or an organisation ("Cyphward customers meet the ...").
_NEWS_WORD = re.compile(r"[A-Za-z0-9']+")
_PUBLIC_BODIES = frozenset({"ndpc", "nitda", "cbn", "sec", "ncc", "regulator", "regulators", "commission", "government",
                            "ministry", "minister", "assembly", "senate", "parliament", "court", "agency", "authority"})
_INSTRUMENTS = frozenset({"guidance", "guidelines", "regulation", "regulations", "rules", "framework", "code", "bill",
                          "act", "amendment", "amendments", "forms"})
_INSTRUMENT_MODIFIERS = frozenset({"a", "an", "the", "new", "updated", "revised", "draft", "final", "its", "their"})
_REFUSED_AFTER_APPROVED = frozenset({"you", "your", "yours", "cyphward", "organisation", "organisations", "organization",
                                     "organizations", "setup", "product", "products", "platform", "programme", "program",
                                     "customers", "customer"})
_REFUSED_MEET_SUBJECTS = frozenset({"you", "your", "yours", "customers", "customer", "cyphward", "organisation",
                                    "organisations", "organization", "organizations"})
_DATE_WORDS = frozenset({"date", "dates", "deadline", "deadlines", "timeline", "timelines"})


_MEET_FORMS = frozenset({"meet", "meets", "meeting", "met"})


def _meet_claim(text: str) -> Optional[str]:
    """Newsletter-only: any form of "meet" with the reader, Cyphward's customers or an organisation as its subject
    is a claim, whatever follows ("Cyphward customers meet the NDPC filing deadline")."""
    low = [w.group(0).lower() for w in _NEWS_WORD.finditer(text)]
    for i, word in enumerate(low):
        if word in _MEET_FORMS and set(low[max(0, i - 3):i]) & _REFUSED_MEET_SUBJECTS:
            return word
    return None


def _set_aside_news_wording(text: str) -> str:
    words = list(_NEWS_WORD.finditer(text))
    low = [w.group(0).lower() for w in words]
    drop = []
    for i, word in enumerate(low):
        if word == "approved":
            j = i - 1
            if j >= 0 and low[j] in ("has", "have", "had"):
                j -= 1
            if j < 0 or low[j] not in _PUBLIC_BODIES:
                continue
            k = i + 1
            while k < len(low) and k - i <= 2 and low[k] in _INSTRUMENT_MODIFIERS:
                k += 1
            if k < len(low) and low[k] in _INSTRUMENTS and not set(low[i + 1:k + 1]) & _REFUSED_AFTER_APPROVED:
                drop.append(words[i].span())
        elif word == "meet":
            if set(low[max(0, i - 3):i]) & _REFUSED_MEET_SUBJECTS:
                continue
            if i + 1 < len(low) and low[i + 1] == "the" and set(low[i + 2:i + 6]) & _DATE_WORDS:
                drop.append(words[i].span())
    for a, b in reversed(drop):
        text = text[:a] + " " + text[b:]
    return text


def banned_claim(text: str) -> Optional[str]:
    """The claim wording in this text, or None.

    Two checks: the brief's list as whole words, then the product's shared C6 filter (practitioner.violation),
    which also catches complies/conforms/approved/sufficient and disguises such as accents, look-alike letters,
    digits for letters and split-up words. Before the C6 pass, the newsletter allow-list (_set_aside_news_wording)
    removes only the trigger word of two ordinary regulation-news shapes; every other word is still checked.
    """
    normalised = unicodedata.normalize("NFKC", text or "")
    m = _BANNED_RE.search(normalised)
    if m:
        return m.group(0)
    return _meet_claim(normalised) or c6_violation(_set_aside_news_wording(normalised))


def _screen_text(value: str, *, multiline: bool = False) -> str:
    """Reject HTML, control/format characters, template syntax and claim wording."""
    for ch in value:
        cat = unicodedata.category(ch)
        if ch == "\n" and multiline:
            continue
        if cat in ("Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"):
            raise ValueError("control or invisible characters are not allowed")
    normalised = unicodedata.normalize("NFKC", value)
    if _TAG_RE.search(normalised):
        raise ValueError("HTML is not allowed (no < or > characters)")
    if _TEMPLATE_RE.search(normalised):
        raise ValueError("template markers such as {{ }} are not allowed")
    hit = banned_claim(normalised)
    if hit:
        raise ValueError(f"claim wording is not allowed: {hit.lower()!r}")
    if not normalised.strip():
        raise ValueError("must not be blank")
    return value


def _screen_url(value: str) -> str:
    if any(c.isspace() or unicodedata.category(c)[0] == "C" for c in value) or not value.isascii():
        raise ValueError("URL must be plain ASCII without spaces")
    if any(c in value for c in "\"'<>\\`{}|^"):
        raise ValueError("URL contains characters that are not allowed")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("only https:// links are allowed")
    if "@" in parts.netloc or parts.port not in (None, 443):
        raise ValueError("links must not carry credentials or a custom port")
    host = (parts.hostname or "").lower()
    if "." not in host or re.fullmatch(r"[0-9.]+", host) or host in ("localhost",) or host.endswith(".local"):
        raise ValueError("links must point at a public host name")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=False)


class DraftLink(_Strict):
    label: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=12, max_length=300)

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        v = _screen_text(v)
        if _URL_RE.search(v) or _MD_LINK_RE.search(v):
            raise ValueError("link labels must be words, not addresses")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _screen_url(v)


class DraftSource(_Strict):
    title: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=12, max_length=300)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = _screen_text(v)
        if _MD_LINK_RE.search(v):
            raise ValueError("source titles must not contain Markdown links")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _screen_url(v)


class DraftSection(_Strict):
    type: Literal["product", "security_tip", "regulation"]
    heading: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=1500)
    links: List[DraftLink] = Field(default_factory=list, max_length=3)
    sources: List[DraftSource] = Field(default_factory=list, max_length=5)

    @field_validator("heading")
    @classmethod
    def _heading(cls, v: str) -> str:
        v = _screen_text(v)
        if _URL_RE.search(v) or _MD_LINK_RE.search(v):
            raise ValueError("headings must not contain links")
        return v

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        v = _screen_text(v, multiline=True)
        if _MD_LINK_RE.search(v):
            raise ValueError("the body must not contain Markdown links")
        if _URL_RE.search(unicodedata.normalize("NFKC", v)):
            raise ValueError("the body must not contain URLs; put them in links or sources")
        return v

    @model_validator(mode="after")
    def _regulation_needs_sources(self) -> "DraftSection":
        if self.type == "regulation" and not self.sources:
            raise ValueError("every regulation item needs at least one source (title and https url)")
        return self


class DraftIn(_Strict):
    subject: str = Field(min_length=1, max_length=120)
    preview: str = Field(min_length=1, max_length=160)
    sections: List[DraftSection] = Field(min_length=1, max_length=5)

    @field_validator("subject", "preview")
    @classmethod
    def _line(cls, v: str) -> str:
        v = _screen_text(v)
        if _URL_RE.search(v) or _MD_LINK_RE.search(v):
            raise ValueError("must not contain links")
        return v


# ---------------------------------------------------------------------------
# Rendering: one branded wrapper for the confirmation email and every issue.
# Inline styles only; no images, no SVG, no remote fonts, no scripts, no tracking of our own.
# Every interpolated value is escaped. Colours are the dark tokens in frontend/src/index.css.
# ---------------------------------------------------------------------------
SECTION_LABELS = {"product": "Product", "security_tip": "Security tip", "regulation": "Regulation"}

BRAND = {
    "bg": "#0A0907",          # --bg (dark)
    "raised": "#14130F",      # --raised (dark)
    "line": "#24211A",        # --line (dark)
    "ink": "#F5F2EB",         # --ink (dark)
    "soft": "#A8A190",        # --soft (dark)
    "accent": "#E5532B",      # --accent (dark): the brand orange
    "accent_ink": "#F27350",  # --accent-ink (dark): links on the dark card
}
_FONT = "'Helvetica Neue',Helvetica,Arial,sans-serif"  # system fonts only
NOT_A_LAW_FIRM = "Cyphward is not a law firm. Regulation updates are general information, not legal advice."


def confirm_url(s: Settings, token: str) -> str:
    return f"{s.base_url}/api/v1/newsletter/confirm?token={token}"


def unsubscribe_url(s: Settings, token: str) -> str:
    return f"{s.base_url}/api/v1/newsletter/unsubscribe?token={token}"


def campaign_unsubscribe_url(s: Settings) -> str:
    # Brevo replaces the contact attribute per recipient when it sends the campaign.
    return f"{s.base_url}/api/v1/newsletter/unsubscribe?token={{{{ contact.{s.unsub_attribute} }}}}"


def _p(text: str, style: str = "margin:0 0 12px") -> str:
    return f'<p style="{style}">{escape(text)}</p>'


def _logo_html() -> str:
    """The Cyphward mark as text: an orange tile with a C, then the wordmark. Never an image."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td width="28" height="28" align="center" valign="middle" style="width:28px;height:28px;'
        f'background:{BRAND["accent"]};border-radius:6px;color:{BRAND["bg"]};font-size:16px;font-weight:bold;'
        f'line-height:28px;font-family:{_FONT}">C</td>'
        f'<td style="padding-left:10px;font-size:15px;font-weight:bold;letter-spacing:.18em;color:{BRAND["ink"]};'
        f'font-family:{_FONT}">CYPHWARD</td>'
        "</tr></table>"
    )


def _footer_html(s: Settings, unsub_href: str, reason: str) -> str:
    """The one place the unsubscribe link appears in the HTML part."""
    soft = f"margin:0 0 8px;color:{BRAND['soft']}"
    return (
        f'<tr><td style="padding:20px 28px 28px;border-top:1px solid {BRAND["line"]};font-size:12px;line-height:1.6;'
        f'color:{BRAND["soft"]}">'
        + _p(reason, soft)
        + f'<p style="{soft}"><a href="{escape(unsub_href, quote=True)}" style="color:{BRAND["accent_ink"]};'
          'text-decoration:underline">Unsubscribe in one click</a> (no sign-in needed).</p>'
        + _p(NOT_A_LAW_FIRM, soft)
        + _p(s.postal_line, f"margin:0;color:{BRAND['soft']}")
        + "</td></tr>"
    )


def _shell(title: str, preheader: str, rows: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark">'
        f"<title>{escape(title)}</title></head>"
        f'<body style="margin:0;padding:0;background:{BRAND["bg"]};font-family:{_FONT};color:{BRAND["ink"]}">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{escape(preheader)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{BRAND["bg"]}">'
        '<tr><td align="center" style="padding:24px 12px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="max-width:600px;background:{BRAND["raised"]};border:1px solid {BRAND["line"]};border-radius:8px">'
        f'<tr><td style="height:4px;line-height:4px;font-size:4px;background:{BRAND["accent"]};'
        'border-radius:8px 8px 0 0">&nbsp;</td></tr>'
        '<tr><td style="padding:22px 28px 8px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0"><tr><td>{_logo_html()}</td>'
        f'<td align="right" style="font-size:11px;letter-spacing:.2em;color:{BRAND["soft"]};font-family:{_FONT}">UPDATES</td>'
        "</tr></table></td></tr>"
        f"{rows}"
        "</table></td></tr></table></body></html>"
    )


CONFIRMATION_SUBJECT = "You are subscribed to Cyphward updates"
CONFIRMATION_RECEIVE = "Product news, practical security tips and regulation updates for software teams in Nigeria."
CONFIRMATION_LEAVE = ("Every email, this one included, has a one-click unsubscribe link at the bottom. "
                      "No sign-in is needed.")
CONFIRMATION_NOT_YOU = "Did not ask for this? Use the unsubscribe link and nothing more will be sent."
CONFIRMATION_INTRO = "Thank you. This address now receives Cyphward updates. There is nothing more to do."
CONFIRMATION_INTRO_AGAIN = ("This address had unsubscribed and has just been subscribed again on cyphward.com. "
                            "If that was you, there is nothing more to do.")


def render_confirmation(s: Settings, sub: Subscribed) -> Dict[str, str]:
    """The one email a new subscriber gets: they are subscribed already, so there is no link to click."""
    u_url = unsubscribe_url(s, sub.unsubscribe_token)
    often = f"{SEND_FREQUENCY[0].upper()}{SEND_FREQUENCY[1:]}, from {s.sender[1]}."
    consent = (f"You ticked a box agreeing to this wording (version {sub.consent_wording_version}): "
               f"“{CONSENT_WORDING}”")
    preheader = f"Product, security and regulation updates, {SEND_FREQUENCY}. Unsubscribe in one click."
    intro = CONFIRMATION_INTRO_AGAIN if sub.previous_status == "unsubscribed" else CONFIRMATION_INTRO
    label = f"margin:0 0 2px;font-size:11px;letter-spacing:.16em;color:{BRAND['soft']}"
    body = f"margin:0 0 16px;color:{BRAND['ink']}"
    rows = (
        f'<tr><td style="padding:12px 28px 4px;font-size:24px;line-height:1.3;font-weight:bold;color:{BRAND["ink"]}">'
        "You are subscribed</td></tr>"
        f'<tr><td style="padding:8px 28px 12px;font-size:15px;line-height:1.6;color:{BRAND["ink"]}">'
        + _p(intro, body)
        + _p("WHAT YOU WILL RECEIVE", label) + _p(CONFIRMATION_RECEIVE, body)
        + _p("HOW OFTEN", label) + _p(often, body)
        + _p("LEAVING", label) + _p(CONFIRMATION_LEAVE, body)
        + _p("YOUR CONSENT", label) + _p(consent, body)
        + _p(CONFIRMATION_NOT_YOU, f"margin:0;font-size:13px;color:{BRAND['soft']}")
        + "</td></tr>"
        + _footer_html(s, u_url, "You are getting this because this address was subscribed on cyphward.com.")
    )
    text = (
        f"{CONFIRMATION_SUBJECT}.\n{intro}\n\n"
        f"What you will receive: {CONFIRMATION_RECEIVE}\n"
        f"How often: {often}\n"
        f"Leaving: {CONFIRMATION_LEAVE}\n"
        f"Your consent: {consent}\n\n"
        f"{CONFIRMATION_NOT_YOU}\n"
        f"Unsubscribe in one click: {u_url}\n\n"
        f"{NOT_A_LAW_FIRM}\n{s.postal_line}\n"
    )
    return {"subject": CONFIRMATION_SUBJECT, "html": _shell(CONFIRMATION_SUBJECT, preheader, rows), "text": text,
            "headers": list_unsubscribe_headers(u_url)}


def list_unsubscribe_headers(unsub_url: str) -> Dict[str, str]:
    """RFC 8058 one-click: mail providers POST "List-Unsubscribe=One-Click" to this URL."""
    return {"List-Unsubscribe": f"<{unsub_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}


def render_issue(s: Settings, draft: Dict[str, Any], unsub_href: Optional[str] = None) -> Dict[str, str]:
    """HTML and text for an issue. `unsub_href` defaults to the per-recipient Brevo placeholder."""
    d = DraftIn.model_validate(draft)  # stored drafts are re-checked before they are shown or sent
    href = unsub_href or campaign_unsubscribe_url(s)
    link = f"color:{BRAND['accent_ink']};text-decoration:underline"
    label_style = f"margin:0 0 4px;font-size:11px;letter-spacing:.16em;color:{BRAND['accent']}"
    rows, text = [], [d.subject, "", d.preview, ""]
    for sec in d.sections:
        label = SECTION_LABELS[sec.type]
        paras = [p.strip() for p in sec.body.split("\n") if p.strip()]
        body_html = "".join(_p(p) for p in paras)
        extra = ""
        if sec.links:
            items = "".join(
                f'<li style="margin:0 0 6px"><a href="{escape(l.url, quote=True)}" style="{link}">{escape(l.label)}</a></li>'
                for l in sec.links)
            extra += f'<ul style="margin:0 0 12px;padding-left:18px">{items}</ul>'
        if sec.sources:
            items = "".join(
                f'<li style="margin:0 0 6px"><a href="{escape(src.url, quote=True)}" style="{link}">{escape(src.title)}</a></li>'
                for src in sec.sources)
            extra += (_p("SOURCES", f"margin:0 0 6px;font-size:11px;letter-spacing:.16em;color:{BRAND['soft']}")
                      + f'<ul style="margin:0 0 12px;padding-left:18px;font-size:13px">{items}</ul>')
        rows.append(
            f'<tr><td style="padding:16px 28px 4px;border-top:1px solid {BRAND["line"]}">'
            + _p(label.upper(), label_style)
            + f'<h2 style="margin:0 0 10px;font-size:18px;line-height:1.35;color:{BRAND["ink"]}">{escape(sec.heading)}</h2>'
            f'<div style="font-size:15px;line-height:1.6;color:{BRAND["ink"]}">{body_html}{extra}</div></td></tr>'
        )
        text += [f"{label.upper()}: {sec.heading}", "", *paras]
        text += [f"- {l.label}: {l.url}" for l in sec.links]
        text += [f"Source: {src.title}: {src.url}" for src in sec.sources]
        text.append("")
    reason = "You are receiving this because you subscribed to Cyphward updates."
    html_body = _shell(
        d.subject, d.preview,
        f'<tr><td style="padding:12px 28px 12px;font-size:24px;line-height:1.3;font-weight:bold;color:{BRAND["ink"]}">'
        f"{escape(d.subject)}</td></tr>"
        + "".join(rows) + _footer_html(s, href, reason),
    )
    text += [reason, f"Unsubscribe in one click: {href}", NOT_A_LAW_FIRM, s.postal_line]
    return {"subject": d.subject, "preview": d.preview, "html": html_body, "text": "\n".join(text)}


# ---------------------------------------------------------------------------
# PostgreSQL store (short transactions on the shared pool; never held across HTTP calls)
# ---------------------------------------------------------------------------
def _audit(cur, user_id: Optional[str], action: str, resource_id: Optional[str], metadata: Dict[str, Any]) -> None:
    cur.execute(
        "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
        "VALUES (NULL, %s, %s, 'newsletter_issue', %s, %s::jsonb)",
        (user_id, action, resource_id, json.dumps(metadata, default=str)),
    )


_ISSUE_COLUMNS = ("id, status, subject, preview, body_json, created_by, created_at, sent_at, brevo_campaign_id, "
                  "approved_by, approved_at, send_claimed_at, send_error")


class PostgresNewsletterStore:
    """Every method opens one pooled connection, runs one transaction and returns it."""

    # -- subscribers ---------------------------------------------------------
    def subscribe(self, email: str, consent_version: str, source: str, secret: str) -> Optional[Subscribed]:
        """Single opt-in: record the consent and make the address confirmed, in one transaction.

        None when nothing changed: already confirmed, or a concurrent request created the row (that
        request adds it to the list and sends the email).
        """
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "SELECT id, status, token_generation FROM newsletter_subscribers "
                "WHERE email_normalised = %s FOR UPDATE",
                (email,),
            )
            row = cur.fetchone()
            generation = subscribe_generation(row)
            if generation is None:
                return None
            sid = str(row["id"]) if row else str(uuid.uuid4())
            unsub = unsubscribe_token(secret, sid, generation)
            if row is None:
                cur.execute(
                    "INSERT INTO newsletter_subscribers (id, email_normalised, status, consent_at, "
                    "consent_wording_version, source, token_generation, unsubscribe_token_hash, confirmed_at) "
                    "VALUES (%s, %s, 'confirmed', now(), %s, %s, %s, %s, now()) "
                    "ON CONFLICT (email_normalised) DO NOTHING RETURNING id",
                    (sid, email, consent_version, source, generation, hash_token(unsub)),
                )
                if cur.fetchone() is None:
                    return None
            else:
                # Pending (left by the earlier double opt-in) or unsubscribed: confirmed now, with the
                # fresh consent; the new generation retires every older link.
                cur.execute(
                    "UPDATE newsletter_subscribers SET status = 'confirmed', consent_at = now(), "
                    "consent_wording_version = %s, source = %s, token_generation = %s, confirm_token_hash = NULL, "
                    "confirm_expires_at = NULL, unsubscribe_token_hash = %s, confirmed_at = now(), "
                    "unsubscribed_at = NULL, updated_at = now() WHERE id = %s",
                    (consent_version, source, generation, hash_token(unsub), sid),
                )
            return Subscribed(sid, email, unsub, generation, consent_version,
                              str(row["status"]) if row else "new")

    def confirm(self, token: str) -> ConfirmResult:
        sid = token_subscriber_id(token)
        if sid is None:
            return ConfirmResult("invalid")
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "SELECT id, email_normalised, status, token_generation, confirm_token_hash, confirm_expires_at, "
                "now() AS db_now FROM newsletter_subscribers WHERE id = %s FOR UPDATE",
                (sid,),
            )
            row = cur.fetchone()
            outcome = confirm_decision(row, token, row["db_now"] if row else datetime.now(timezone.utc))
            if outcome == "confirmed":
                cur.execute(
                    "UPDATE newsletter_subscribers SET status = 'confirmed', confirmed_at = now(), "
                    "updated_at = now() WHERE id = %s AND status = 'pending'",
                    (sid,),
                )
            if outcome in ("confirmed", "already"):
                return ConfirmResult(outcome, sid, row["email_normalised"], int(row["token_generation"]))
            return ConfirmResult(outcome)

    def unsubscribe(self, token: str) -> UnsubscribeResult:
        sid = token_subscriber_id(token)
        if sid is None:
            return UnsubscribeResult("invalid")
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "SELECT id, email_normalised, status, unsubscribe_token_hash FROM newsletter_subscribers "
                "WHERE id = %s FOR UPDATE",
                (sid,),
            )
            row = cur.fetchone()
            outcome = unsubscribe_decision(row, token)
            if outcome == "unsubscribed":
                cur.execute(
                    "UPDATE newsletter_subscribers SET status = 'unsubscribed', unsubscribed_at = now(), "
                    "confirm_token_hash = NULL, confirm_expires_at = NULL, updated_at = now() WHERE id = %s",
                    (sid,),
                )
            return UnsubscribeResult(outcome, row["email_normalised"] if outcome != "invalid" else None)

    def confirmed_subscribers(self) -> List[Dict[str, Any]]:
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "SELECT id, email_normalised, token_generation FROM newsletter_subscribers "
                "WHERE status = 'confirmed' ORDER BY confirmed_at, id"
            )
            return [dict(r) for r in cur.fetchall()]

    def count_confirmed(self) -> int:
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM newsletter_subscribers WHERE status = 'confirmed'")
            return int(cur.fetchone()["n"])

    def subscriber_counts(self) -> Dict[str, int]:
        """How many subscribers are in each state; numbers only, never an address."""
        counts = {"confirmed": 0, "unsubscribed": 0, "pending": 0}
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT status, count(*) AS n FROM newsletter_subscribers GROUP BY status")
            for row in cur.fetchall():
                if row["status"] in counts:
                    counts[row["status"]] = int(row["n"])
        return counts

    def mark_unsubscribed(self, emails: List[str]) -> int:
        """Addresses Brevo reports as unsubscribed or blocked become unsubscribed here too."""
        if not emails:
            return 0
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "UPDATE newsletter_subscribers SET status = 'unsubscribed', unsubscribed_at = now(), "
                "confirm_token_hash = NULL, confirm_expires_at = NULL, updated_at = now() "
                "WHERE email_normalised = ANY(%s) AND status <> 'unsubscribed' RETURNING id",
                ([normalise_email(e) for e in emails],),
            )
            return len(cur.fetchall())

    # -- issues --------------------------------------------------------------
    def create_issue(self, draft: Dict[str, Any], created_by: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "INSERT INTO newsletter_issues (subject, preview, body_json, created_by) "
                f"VALUES (%s, %s, %s::jsonb, %s) RETURNING {_ISSUE_COLUMNS}",
                (draft["subject"], draft["preview"], json.dumps(draft), created_by),
            )
            row = dict(cur.fetchone())
            _audit(cur, None, "newsletter.draft_created", str(row["id"]), {"author": created_by, **metadata})
            return row

    def list_issues(self, limit: int = 50) -> List[Dict[str, Any]]:
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(f"SELECT {_ISSUE_COLUMNS} FROM newsletter_issues ORDER BY created_at DESC LIMIT %s",
                        (limit,))
            return [dict(r) for r in cur.fetchall()]

    def get_issue(self, issue_id: str) -> Optional[Dict[str, Any]]:
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(f"SELECT {_ISSUE_COLUMNS} FROM newsletter_issues WHERE id = %s", (issue_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def claim_issue(self, issue_id: str, actor: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The one send attempt: succeeds once per issue, recorded with its approval audit row."""
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "UPDATE newsletter_issues SET send_claimed_at = now(), approved_at = now(), approved_by = %s "
                f"WHERE id = %s AND status = 'draft' AND send_claimed_at IS NULL RETURNING {_ISSUE_COLUMNS}",
                (actor["user_id"], issue_id),
            )
            row = cur.fetchone()
            if row is None:
                return None
            _audit(cur, actor["user_id"], "newsletter.send_approved", issue_id,
                   {"actor": actor["kind"], "subject": row["subject"]})
            return dict(row)

    def record_campaign(self, issue_id: str, campaign_id: str, actor: Dict[str, Any], metadata: Dict[str, Any]) -> None:
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "UPDATE newsletter_issues SET brevo_campaign_id = %s WHERE id = %s AND status = 'draft' "
                "AND send_claimed_at IS NOT NULL AND brevo_campaign_id IS NULL",
                (campaign_id, issue_id),
            )
            _audit(cur, actor["user_id"], "newsletter.campaign_created", issue_id,
                   {"actor": actor["kind"], "brevo_campaign_id": campaign_id, **metadata})

    def mark_sent(self, issue_id: str, actor: Dict[str, Any]) -> Dict[str, Any]:
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "UPDATE newsletter_issues SET status = 'sent', sent_at = now() WHERE id = %s AND status = 'draft' "
                f"AND send_claimed_at IS NOT NULL AND brevo_campaign_id IS NOT NULL RETURNING {_ISSUE_COLUMNS}",
                (issue_id,),
            )
            row = cur.fetchone()
            _audit(cur, actor["user_id"], "newsletter.sent", issue_id,
                   {"actor": actor["kind"], "brevo_campaign_id": row["brevo_campaign_id"] if row else None})
            return dict(row) if row else {}

    def record_failure(self, issue_id: str, actor: Dict[str, Any], error: str) -> None:
        with database.get_db() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("UPDATE newsletter_issues SET send_error = %s WHERE id = %s", (error[:600], issue_id))
            _audit(cur, actor["user_id"], "newsletter.send_failed", issue_id, {"actor": actor["kind"], "error": error[:600]})


_STORE: Any = PostgresNewsletterStore()


def store() -> Any:
    """The active store (tests swap `_STORE` for an in-memory one)."""
    return _STORE
