"""Newsletter rules (docs/newsletter/README.md), one test per rule, with an in-memory store and a Brevo stub.

Single opt-in: subscribing with consent confirms the address at once and sends one branded confirmation email
(at most one per address per 24 hours). Rows left pending by the earlier double opt-in are seeded with
FakeNewsletterStore.seed_legacy_pending to test the kept confirm endpoint and their upgrade.

No test makes a network call: the mailer is replaced, and Brevo is StubBrevo. The real SQL runs in
backend/tests/test_newsletter_postgres.py.
"""
import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import backend.app.api.newsletter as api
import backend.app.core.owner as owner_mod
from backend.app.core import config
from backend.app.core import newsletter as nl
from backend.app.services import newsletter_brevo
from backend.tests.newsletter_fakes import FakeNewsletterStore, StubBrevo, past
from conftest import ALICE, BOB

DRAFT_KEY = "grokbot-draft-key-for-tests-0123456789abcdef"
SECRET = "newsletter-token-secret-for-tests-0123456789"
BASE = "https://cyphward.test"
POSTAL = "Cyphward Ltd, RC 9921694, Kano, Nigeria. info@cyphward.com"
CONSENT = {"consent": True, "consent_wording_version": nl.CONSENT_WORDING_VERSION, "source": "newsletter_page"}
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


@pytest.fixture
def nlenv(monkeypatch, store):
    """Feature on and fully configured; in-memory store; Brevo stub; captured confirmation emails."""
    for name, value in {
        "NEWSLETTER_ENABLED": True, "NEWSLETTER_DRAFT_API_KEY": DRAFT_KEY, "NEWSLETTER_TOKEN_SECRET": SECRET,
        "NEWSLETTER_BREVO_LIST_ID": "7", "NEWSLETTER_POSTAL_LINE": POSTAL, "NEWSLETTER_PUBLIC_BASE_URL": BASE,
        "NEWSLETTER_BREVO_UNSUB_ATTRIBUTE": "CW_UNSUB_TOKEN", "BREVO_API_KEY": "test-brevo-key",
    }.items():
        monkeypatch.setattr(config, name, value)
    fake = FakeNewsletterStore()
    monkeypatch.setattr(nl, "_STORE", fake)
    brevo = StubBrevo()

    def get_client(list_id, attribute):
        brevo.list_ids.append(list_id)
        return brevo

    monkeypatch.setattr(newsletter_brevo, "get_client", get_client)
    sent = []

    async def fake_send(to_email, subject, html_content, text_content=None, recipient_name=None, kind="system",
                        reply_to=None, sender=None, allow_campaign_fallback=True, mail_headers=None):
        sent.append({"to": to_email, "subject": subject, "html": html_content, "text": text_content,
                     "sender": sender, "kind": kind, "allow_campaign_fallback": allow_campaign_fallback,
                     "headers": mail_headers})
        return {"success": True}

    monkeypatch.setattr(api, "send_email_async", fake_send)
    monkeypatch.setattr(api, "MIN_RESPONSE_SECONDS", 0)

    class Env:
        pass

    env = Env()
    env.store, env.brevo, env.sent, env.fake_db = fake, brevo, sent, store
    return env


def subscribe(client, email="Reader@Example.com", ip="198.51.100.7", **over):
    body = {"email": email, **CONSENT, **over}
    return client.post("/api/v1/newsletter/subscribe", json=body, headers={"X-Forwarded-For": ip})


def token_from(text, kind):
    m = re.search(rf"/api/v1/newsletter/{kind}\?token=([A-Za-z0-9._-]+)", text)
    return m.group(1) if m else None


def act(client, kind, token, ip=None):
    """Press the button on the confirm/unsubscribe page: a POST with the token in the form body."""
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post(f"/api/v1/newsletter/{kind}", data={"token": token}, headers=headers, follow_redirects=False)


def confirmed_reader(client, env, email="reader@example.com"):
    """Single opt-in: one subscribe request confirms the address and sends exactly one email."""
    before = len(env.sent)
    assert subscribe(client, email).status_code == 202
    assert len(env.sent) == before + 1
    assert env.store.by_email(email)["status"] == "confirmed"
    return env.sent[-1]


def legacy_pending(env, email="reader@example.com"):
    """A row left pending by the earlier double opt-in; returns its (confirm, unsubscribe) tokens."""
    return env.store.seed_legacy_pending(email, SECRET)


def age_buckets(env, *prefixes, hours=25):
    """Move matching rate-limit windows into the past, as if that much time had gone by."""
    for row in env.fake_db.rate_limits:
        if row["bucket_key"].startswith(prefixes):
            row["window_start"] = row["window_start"] - timedelta(hours=hours)


def good_draft(**over):
    draft = {
        "subject": "Cyphward notes for October",
        "preview": "A product change, one security tip and a regulation update.",
        "sections": [
            {"type": "product", "heading": "Reports show the scan date", "body": "Every report now shows when the scan ran.",
             "links": [{"label": "See pricing", "url": "https://cyphward.com/pricing"}]},
            {"type": "security_tip", "heading": "Publish a DMARC record", "body": "Start with p=none and read the reports.\nThen tighten it."},
            {"type": "regulation", "heading": "NDPC guidance note", "body": "The regulator published a guidance note on breach reporting.",
             "sources": [{"title": "NDPC guidance note", "url": "https://ndpc.gov.ng/guidance"}]},
        ],
    }
    draft.update(over)
    return draft


def post_draft(client, draft=None, key=DRAFT_KEY):
    headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
    return client.post("/api/v1/newsletter/drafts", json=draft if draft is not None else good_draft(), headers=headers)


def staff(store, auth_headers, uid=BOB, scopes=("platform:newsletter",)):
    store.profiles[uid]["email_verified_at"] = datetime.now(timezone.utc)
    store.staff_grants.append({"id": str(uuid.uuid4()), "user_id": uid, "scopes": list(scopes), "granted_by": None,
                               "reason": "newsletter", "expires_at": None, "revoked_at": None,
                               "created_at": datetime.now(timezone.utc)})
    return auth_headers(uid, email=f"{uid[:8]}@acme.test")


def send(client, headers, issue_id, subject="Cyphward notes for October", approve=True):
    return client.post(f"/api/v1/newsletter/drafts/{issue_id}/send", json={"approve": approve, "subject": subject},
                       headers=headers)


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------
def all_routes(client, headers=None):
    iid = str(uuid.uuid4())
    h = headers or {}
    return [
        client.get("/api/v1/newsletter/status"),
        subscribe(client),
        client.get("/api/v1/newsletter/confirm?token=x", follow_redirects=False),
        client.get("/api/v1/newsletter/unsubscribe?token=x", follow_redirects=False),
        act(client, "confirm", "x"),
        act(client, "unsubscribe", "x"),
        post_draft(client),
        client.get("/api/v1/newsletter/drafts", headers=h),
        send(client, h, iid),
        client.get("/api/v1/newsletter/stats", headers=h),
    ]


def test_flag_off_returns_404_everywhere(client, nlenv, auth_headers, monkeypatch):
    monkeypatch.setattr(config, "NEWSLETTER_ENABLED", False)
    for resp in all_routes(client, staff(nlenv.fake_db, auth_headers)):
        assert resp.status_code == 404, resp.request.url
    assert nlenv.sent == [] and nlenv.brevo.calls == [] and nlenv.store.issues == {}


def test_flag_off_is_the_default():
    import os
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if not k.startswith("NEWSLETTER_")}
    out = subprocess.run([sys.executable, "-c", "from backend.app.core import config; print(config.NEWSLETTER_ENABLED)"],
                         env=env, cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


@pytest.mark.parametrize("name,value", [
    ("NEWSLETTER_POSTAL_LINE", ""), ("NEWSLETTER_BREVO_LIST_ID", ""), ("NEWSLETTER_BREVO_LIST_ID", "2"),
    ("NEWSLETTER_BREVO_LIST_ID", "abc"), ("NEWSLETTER_TOKEN_SECRET", "short"), ("BREVO_API_KEY", ""),
    ("NEWSLETTER_PUBLIC_BASE_URL", "http://cyphward.com"), ("NEWSLETTER_BREVO_UNSUB_ATTRIBUTE", "bad attr"),
])
def test_incomplete_configuration_stays_off(client, nlenv, monkeypatch, name, value):
    monkeypatch.setattr(config, name, value)
    assert client.get("/api/v1/newsletter/status").status_code == 404
    assert subscribe(client).status_code == 404


def test_status_publishes_the_consent_wording(client, nlenv):
    body = client.get("/api/v1/newsletter/status").json()
    assert body["consent_wording"] == ("I agree that Cyphward may email me news about its product and security and "
                                       "regulation updates. I can withdraw at any time.")
    assert body["consent_wording_version"] == nl.CONSENT_WORDING_VERSION


# ---------------------------------------------------------------------------
# Consent and storage
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("over", [
    {"consent": False}, {"consent": None}, {"consent": "true"}, {"consent": 1}, {"consent": 1.0},
    {"consent_wording_version": "old"}, {"source": "elsewhere"}, {"extra": 1},
])
def test_consent_is_required(client, nlenv, over):
    body = {"email": "reader@example.com", **CONSENT, **over}
    resp = client.post("/api/v1/newsletter/subscribe", json=body)
    assert resp.status_code == 422
    assert nlenv.store.subscribers == {} and nlenv.sent == []


def test_missing_consent_field_is_rejected(client, nlenv):
    resp = client.post("/api/v1/newsletter/subscribe", json={"email": "reader@example.com", "source": "newsletter_page",
                                                              "consent_wording_version": nl.CONSENT_WORDING_VERSION})
    assert resp.status_code == 422 and nlenv.store.subscribers == {}


def test_subscribe_confirms_at_once_with_consent_and_only_token_hashes(client, nlenv):
    resp = subscribe(client, "  Reader@Example.COM ", source="landing_footer")
    assert resp.status_code == 202
    (row,) = nlenv.store.subscribers.values()
    assert row["email_normalised"] == "reader@example.com"
    assert row["status"] == "confirmed" and row["confirmed_at"] is not None
    assert row["consent_wording_version"] == nl.CONSENT_WORDING_VERSION
    assert row["source"] == "landing_footer" and row["consent_at"] is not None
    assert row["confirm_token_hash"] is None and row["confirm_expires_at"] is None  # nothing left to confirm
    (mail,) = nlenv.sent  # exactly one confirmation email
    assert token_from(mail["text"], "confirm") is None and "/newsletter/confirm" not in mail["html"]
    unsub = token_from(mail["text"], "unsubscribe")
    stored = json.dumps(row, default=str)
    assert unsub not in stored and unsub.split(".")[1] not in stored
    assert row["unsubscribe_token_hash"].startswith("s1$")
    assert set(row) <= {"id", "email_normalised", "status", "consent_at", "consent_wording_version", "source",
                        "token_generation", "confirm_token_hash", "confirm_expires_at", "unsubscribe_token_hash",
                        "confirmed_at", "unsubscribed_at", "created_at"}
    assert nlenv.brevo.calls == [("upsert", "reader@example.com")]  # on the list once, at subscribe time


def test_salted_hashes_differ_for_the_same_token():
    token = nl.new_confirm_token(str(uuid.uuid4()))
    a, b = nl.hash_token(token), nl.hash_token(token)
    assert a != b and nl.token_matches(token, a) and nl.token_matches(token, b)
    assert not nl.token_matches(token + "x", a) and not nl.token_matches(token, None)


# ---------------------------------------------------------------------------
# No leak of who is subscribed
# ---------------------------------------------------------------------------
def test_same_answer_for_every_address_state(client, nlenv):
    confirmed_reader(client, nlenv, "confirmed@example.com")
    legacy_pending(nlenv, "pending@example.com")
    gone = confirmed_reader(client, nlenv, "gone@example.com")
    act(client, "unsubscribe", token_from(gone['text'], 'unsubscribe'))
    nlenv.sent.clear()
    answers = {}
    for email in ("new@example.com", "pending@example.com", "confirmed@example.com", "gone@example.com"):
        resp = subscribe(client, email, ip=f"203.0.113.{len(answers) + 1}")
        answers[email] = (resp.status_code, resp.text,
                          tuple(sorted(k for k in resp.headers if k.lower() not in ("date", "content-length"))))
    assert len(set(answers.values())) == 1
    assert answers["new@example.com"][0] == 202
    assert answers["new@example.com"][1] == json.dumps(api.SUBSCRIBE_ACCEPTED, separators=(",", ":"))
    # Everyone is subscribed now. A confirmed address gets nothing and keeps its row; every other address,
    # including the one that had unsubscribed, gets the notice.
    assert all(nlenv.store.by_email(e)["status"] == "confirmed" for e in answers)
    assert sorted(m["to"] for m in nlenv.sent) == ["gone@example.com", "new@example.com", "pending@example.com"]


def test_honeypot_gets_the_same_answer_and_nothing_happens(client, nlenv):
    a = subscribe(client, "bot@example.com", website="https://spam.example")
    b = subscribe(client, "person@example.com")
    assert (a.status_code, a.json()) == (b.status_code, b.json())
    assert nlenv.store.by_email("bot@example.com") is None


def test_same_timing_band(client, nlenv, monkeypatch):
    monkeypatch.setattr(api, "MIN_RESPONSE_SECONDS", 0.25)
    confirmed_reader(client, nlenv, "confirmed@example.com")
    timings = {}
    for i, email in enumerate(["fresh@example.com", "confirmed@example.com"]):
        started = time.monotonic()
        assert subscribe(client, email, ip=f"192.0.2.{i + 10}").status_code == 202
        timings[email] = time.monotonic() - started
    assert all(t >= 0.25 for t in timings.values())
    assert abs(timings["fresh@example.com"] - timings["confirmed@example.com"]) < 0.15


def test_rate_limit_per_ip(client, nlenv):
    codes = [subscribe(client, f"r{i}@example.com", ip="198.51.100.99").status_code for i in range(11)]
    assert codes[:10] == [202] * 10 and codes[10] == 429


def test_rate_limit_per_email_is_silent(client, nlenv):
    answers = {subscribe(client, "same@example.com", ip=f"198.51.100.{i}").text for i in range(5)}
    assert len(answers) == 1  # never a 429 that would single out the address
    assert len(nlenv.sent) == 1  # one confirmation email; the repeats change nothing
    assert nlenv.brevo.calls == [("upsert", "same@example.com")]
    assert not any("same@example.com" in r["bucket_key"] for r in nlenv.fake_db.rate_limits)


def test_per_address_limit_drops_a_fourth_request_silently(client, nlenv):
    mail = confirmed_reader(client, nlenv, "loop@example.com")
    unsub = lambda: act(client, "unsubscribe", nl.unsubscribe_token(  # noqa: E731
        SECRET, nlenv.store.by_email("loop@example.com")["id"], nlenv.store.by_email("loop@example.com")["token_generation"]))
    assert token_from(mail["text"], "unsubscribe")
    for i in range(2):  # subscribe requests 2 and 3 in this hour still work
        unsub()
        assert subscribe(client, "loop@example.com", ip=f"198.51.100.{60 + i}").status_code == 202
        assert nlenv.store.by_email("loop@example.com")["status"] == "confirmed"
    unsub()
    resp = subscribe(client, "loop@example.com", ip="198.51.100.70")  # the fourth: dropped, same answer
    assert resp.status_code == 202 and resp.json() == api.SUBSCRIBE_ACCEPTED
    assert nlenv.store.by_email("loop@example.com")["status"] == "unsubscribed"
    assert len(nlenv.sent) == 3  # the first subscription and both re-subscribes were notified; the drop was not


def test_rate_limit_buckets_never_hold_the_address_or_ip(client, nlenv):
    subscribe(client, "private@example.com", ip="198.51.100.42")
    keys = " ".join(r["bucket_key"] for r in nlenv.fake_db.rate_limits)
    assert "private@example.com" not in keys and "198.51.100.42" not in keys


# ---------------------------------------------------------------------------
# Single opt-in and the one confirmation email
# ---------------------------------------------------------------------------
def test_confirmation_email_is_from_news_with_unsubscribe_and_postal_line(client, nlenv):
    subscribe(client)
    (mail,) = nlenv.sent
    assert mail["subject"] == "You are subscribed to Cyphward updates"
    assert mail["sender"] == ("Cyphward News", "news@cyphward.com")
    assert mail["allow_campaign_fallback"] is False  # never the list-2 campaign fallback
    for part in (mail["html"], mail["text"]):
        assert "/api/v1/newsletter/confirm" not in part  # nothing to click to finish subscribing
        assert f"{BASE}/api/v1/newsletter/unsubscribe?token=" in part
        assert POSTAL in part
        assert nl.CONSENT_WORDING_VERSION in part and "about once a month" in part.lower()
    assert "<img" not in mail["html"].lower()


def test_default_transactional_sender_is_unchanged():
    from backend.app.services.mailer import email_sender
    assert email_sender("system") == ("Cyphward", "no-reply@cyphward.com")
    assert email_sender("general") == ("Cyphward", "info@cyphward.com")
    assert "news@cyphward.com" not in {addr for _, addr in config.EMAIL_SENDERS.values()}


def test_subscribe_adds_to_list_once_with_the_unsubscribe_token(client, nlenv):
    mail = confirmed_reader(client, nlenv)
    assert nlenv.brevo.calls == [("upsert", "reader@example.com")] and nlenv.brevo.list_ids == [7]
    attr = nlenv.brevo.contacts["reader@example.com"]["attributes"]["CW_UNSUB_TOKEN"]
    assert attr == token_from(mail["text"], "unsubscribe")  # the same link works in every issue
    for i in range(2):  # repeat requests: no second list call, no second email
        subscribe(client, "reader@example.com", ip=f"198.51.100.{30 + i}")
    assert nlenv.brevo.calls == [("upsert", "reader@example.com")] and len(nlenv.sent) == 1


def test_resubscribe_after_unsubscribe_always_sends_a_notice(client, nlenv):
    first = confirmed_reader(client, nlenv)
    for cycle in (2, 3):  # well inside 24 hours, every time
        row = nlenv.store.by_email("reader@example.com")
        act(client, "unsubscribe", nl.unsubscribe_token(SECRET, row["id"], row["token_generation"]))
        assert row["status"] == "unsubscribed"
        subscribe(client, "reader@example.com", ip=f"198.51.100.{40 + cycle}")  # e.g. a stranger re-subscribes it
        assert row["status"] == "confirmed" and row["token_generation"] == cycle
        assert len(nlenv.sent) == cycle, "a re-subscribe after an unsubscribe must always notify the address"
        notice = nlenv.sent[-1]
        assert notice["to"] == "reader@example.com"
        assert nl.CONFIRMATION_INTRO_AGAIN in notice["text"] and "subscribed again" in notice["html"]
        assert token_from(notice["text"], "unsubscribe") == nl.unsubscribe_token(SECRET, row["id"], cycle)
        assert nlenv.brevo.contacts["reader@example.com"]["attributes"]["CW_UNSUB_TOKEN"] == \
            nl.unsubscribe_token(SECRET, row["id"], cycle)
    assert nl.CONFIRMATION_INTRO_AGAIN not in first["text"]


def _new_subscriber(email="window@example.com", previous="new"):
    sid = str(uuid.uuid4())
    return nl.Subscribed(sid, email, nl.unsubscribe_token(SECRET, sid, 1), 1, nl.CONSENT_WORDING_VERSION, previous)


def test_confirmation_window_is_24_hours(nlenv, monkeypatch):
    assert nl.CONFIRMATION_EMAIL_WINDOW_SECONDS == 24 * 3600
    windows = []
    real = api.check_rate_limit

    def recording(bucket, limit, window):
        if bucket.startswith("newsletter:confirmation:email:"):
            windows.append((limit, window))
        return real(bucket, limit, window)

    monkeypatch.setattr(api, "check_rate_limit", recording)
    sub = _new_subscriber()
    asyncio.run(api._send_confirmation(_settings(), sub))
    asyncio.run(api._send_confirmation(_settings(), sub))
    assert len(nlenv.sent) == 1  # the second within the window is suppressed
    assert windows == [(1, 86400), (1, 86400)]
    age_buckets(nlenv, "newsletter:confirmation:email:", hours=23 + 58 / 60)  # 23 h 58 min later
    asyncio.run(api._send_confirmation(_settings(), sub))
    assert len(nlenv.sent) == 1, "still inside 24 hours: no second email"
    age_buckets(nlenv, "newsletter:confirmation:email:", hours=3 / 60)  # 3 more minutes: 24 h 1 min after the first
    asyncio.run(api._send_confirmation(_settings(), sub))
    assert len(nlenv.sent) == 2


@pytest.mark.parametrize("failure", [RuntimeError("database unavailable"), api.HTTPException(status_code=503)])
def test_confirmation_limit_check_failure_sends_nothing(client, nlenv, monkeypatch, failure):
    real = api.check_rate_limit

    def failing(bucket, limit, window):
        if bucket.startswith("newsletter:confirmation:email:"):
            raise failure
        return real(bucket, limit, window)

    monkeypatch.setattr(api, "check_rate_limit", failing)
    assert subscribe(client).status_code == 202
    assert nlenv.store.by_email("reader@example.com")["status"] == "confirmed"  # subscribed either way
    assert nlenv.brevo.calls == [("upsert", "reader@example.com")]
    assert nlenv.sent == [], "fail closed: no email when the 24-hour check cannot run"


@pytest.mark.parametrize("previous", ["pending", "unsubscribed"])
def test_consent_is_recorded_afresh_when_a_row_is_upgraded(client, nlenv, previous):
    if previous == "pending":
        legacy_pending(nlenv)
    else:
        mail = confirmed_reader(client, nlenv)
        act(client, "unsubscribe", token_from(mail["text"], "unsubscribe"))
    row = nlenv.store.by_email("reader@example.com")
    assert row["status"] == previous
    row.update(consent_at=past(48), consent_wording_version="2026-01-01.v0", source="landing_footer")
    subscribe(client, source="newsletter_page", ip="198.51.100.77")
    assert row["status"] == "confirmed"
    assert datetime.now(timezone.utc) - row["consent_at"] < timedelta(minutes=1), "consent time must be refreshed"
    assert row["consent_wording_version"] == nl.CONSENT_WORDING_VERSION and row["source"] == "newsletter_page"


@pytest.mark.parametrize("over", [{"consent": False}, {"consent": "true"}, {"consent_wording_version": "old"},
                                  {"website": "https://spam.example"}])
def test_never_on_the_list_without_consent(client, nlenv, over):
    subscribe(client, "noconsent@example.com", **over)
    assert nlenv.brevo.calls == [] and nlenv.sent == []
    assert nlenv.store.by_email("noconsent@example.com") is None


def test_list_add_happens_only_after_the_consent_is_recorded(client, nlenv):
    seen = []
    nlenv.brevo.on_upsert = lambda email: seen.append(dict(nlenv.store.by_email(email)))
    subscribe(client, source="landing_footer")
    (row,) = seen
    assert row["status"] == "confirmed" and row["consent_at"] is not None
    assert row["consent_wording_version"] == nl.CONSENT_WORDING_VERSION and row["source"] == "landing_footer"


def test_legacy_pending_row_is_upgraded_on_the_next_subscribe(client, nlenv):
    confirm, old_unsub = legacy_pending(nlenv)
    before = dict(nlenv.store.by_email("reader@example.com"))
    subscribe(client, source="landing_footer")
    row = nlenv.store.by_email("reader@example.com")
    assert row["id"] == before["id"] and row["status"] == "confirmed" and row["confirmed_at"] is not None
    assert row["token_generation"] == 2 and row["confirm_token_hash"] is None and row["confirm_expires_at"] is None
    assert row["source"] == "landing_footer" and row["consent_at"] >= before["consent_at"]
    (mail,) = nlenv.sent
    assert nlenv.brevo.calls == [("upsert", "reader@example.com")]
    assert token_from(mail["text"], "unsubscribe") == nl.unsubscribe_token(SECRET, row["id"], 2)
    # The old links are retired; the old confirm link now reads as not working.
    assert act(client, "confirm", confirm).headers["location"].endswith("result=invalid")
    assert act(client, "unsubscribe", old_unsub).headers["location"].endswith("result=invalid")
    assert row["status"] == "confirmed"


def test_legacy_confirm_link_still_works_and_twice_is_harmless(client, nlenv):
    confirm, unsub = legacy_pending(nlenv)
    for _ in range(2):
        resp = act(client, "confirm", confirm)
        assert resp.status_code == 303 and resp.headers["location"] == f"{BASE}/newsletter/confirmed?result=ok"
    assert nlenv.store.by_email("reader@example.com")["status"] == "confirmed"
    assert nlenv.brevo.calls == [("upsert", "reader@example.com")]
    assert nlenv.brevo.contacts["reader@example.com"]["attributes"]["CW_UNSUB_TOKEN"] == unsub
    assert nlenv.sent == []  # the legacy confirm sends nothing


def test_legacy_confirm_link_expires(client, nlenv):
    confirm, _ = legacy_pending(nlenv)
    row = nlenv.store.by_email("reader@example.com")
    row["confirm_expires_at"] = past(1)
    resp = act(client, "confirm", confirm)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"{BASE}/newsletter/confirmed?result=expired"
    assert row["status"] == "pending" and nlenv.brevo.calls == []


@pytest.mark.parametrize("token", ["", "x", "0" * 32 + "." + "a" * 43, "../../etc", "a" * 300])
def test_bad_confirm_tokens(client, nlenv, token):
    resp = act(client, "confirm", token)
    assert resp.status_code == 303 and resp.headers["location"].endswith("result=invalid")
    page = client.get("/api/v1/newsletter/confirm", params={"token": token}, follow_redirects=False)
    # A malformed token redirects to "did not work"; a well-formed one gets the button page (which changes nothing).
    assert page.status_code in (200, 303, 422)
    if page.status_code == 303:
        assert page.headers["location"].endswith("result=invalid")


def test_tampered_confirm_token_is_refused(client, nlenv):
    token, _ = legacy_pending(nlenv)
    forged = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    resp = act(client, "confirm", forged)
    assert resp.headers["location"].endswith("result=invalid")
    assert nlenv.store.by_email("reader@example.com")["status"] == "pending"


def test_unsubscribe_token_cannot_confirm(client, nlenv):
    _, unsub = legacy_pending(nlenv)
    resp = act(client, "confirm", unsub)
    assert resp.headers["location"].endswith("result=invalid")
    assert nlenv.store.by_email("reader@example.com")["status"] == "pending"


def test_confirm_is_rate_limited_per_subscriber_without_a_429(client, nlenv):
    token, _ = legacy_pending(nlenv)
    forged = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    for i in range(10):
        r = act(client, "confirm", forged, ip=f"203.0.113.{i + 50}")
        assert r.headers["location"].endswith("result=invalid")
    # The real token now reads as not working too, for this hour; no 429 that names the subscriber.
    r = act(client, "confirm", token, ip="203.0.113.99")
    assert r.status_code == 303 and r.headers["location"].endswith("result=invalid")
    assert nlenv.store.by_email("reader@example.com")["status"] == "pending"


def test_confirm_is_rate_limited_per_ip(client, nlenv):
    codes = [act(client, "confirm", "x", ip="198.51.100.77").status_code for _ in range(31)]
    assert codes[:30] == [303] * 30 and codes[30] == 429


# ---------------------------------------------------------------------------
# One-click unsubscribe
# ---------------------------------------------------------------------------
def test_one_click_unsubscribe_without_login(client, nlenv):
    mail = confirmed_reader(client, nlenv)
    token = token_from(mail["text"], "unsubscribe")
    resp = act(client, "unsubscribe", token)  # no Authorization header, no cookie
    assert resp.status_code == 303 and resp.headers["location"] == f"{BASE}/newsletter/unsubscribed?result=ok"
    row = nlenv.store.by_email("reader@example.com")
    assert row["status"] == "unsubscribed" and row["unsubscribed_at"] is not None
    assert ("remove", ("reader@example.com",)) in nlenv.brevo.calls
    assert act(client, "unsubscribe", token).headers["location"].endswith("result=ok")  # repeat is fine


# ---------------------------------------------------------------------------
# Link scanners: a GET never changes anything
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["confirm", "unsubscribe"])
def test_a_get_shows_a_button_and_changes_nothing(client, nlenv, kind):
    if kind == "confirm":  # only legacy pending rows still have a confirm link
        token, before_status = legacy_pending(nlenv)[0], "pending"
    else:
        token, before_status = token_from(confirmed_reader(client, nlenv)["text"], kind), "confirmed"
    calls_before = list(nlenv.brevo.calls)
    for _ in range(3):  # a scanner, a preview and the person all open it
        resp = client.get(f"/api/v1/newsletter/{kind}?token={token}", follow_redirects=False)
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/html")
    assert nlenv.store.by_email("reader@example.com")["status"] == before_status
    assert nlenv.brevo.calls == calls_before
    page = resp.text
    assert f'<form method="post" action="/api/v1/newsletter/{kind}">' in page
    assert f'name="token" value="{token}"' in page and "<button" in page
    assert resp.headers["cache-control"] == "no-store" and resp.headers["referrer-policy"] == "no-referrer"
    assert "form-action 'self'" in resp.headers["content-security-policy"] and "script-src" not in resp.headers["content-security-policy"]
    assert "<script" not in page.lower()
    # The POST is what acts.
    after = "confirmed" if kind == "confirm" else "unsubscribed"
    act(client, kind, token)
    assert nlenv.store.by_email("reader@example.com")["status"] == after


def test_rfc8058_one_click_post_unsubscribes(client, nlenv):
    mail = confirmed_reader(client, nlenv)
    url = f"/api/v1/newsletter/unsubscribe?token={token_from(mail['text'], 'unsubscribe')}"
    resp = client.post(url, content=b"List-Unsubscribe=One-Click", follow_redirects=False,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert resp.status_code == 200 and resp.text == "Unsubscribed."
    assert nlenv.store.by_email("reader@example.com")["status"] == "unsubscribed"
    bad = client.post("/api/v1/newsletter/unsubscribe?token=" + "0" * 32 + "." + "a" * 43,
                      content=b"List-Unsubscribe=One-Click", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert bad.status_code == 400


def test_confirmation_email_carries_rfc8058_headers(client, nlenv):
    subscribe(client)
    (mail,) = nlenv.sent
    unsub = token_from(mail["text"], "unsubscribe")
    assert mail["headers"] == {"List-Unsubscribe": f"<{BASE}/api/v1/newsletter/unsubscribe?token={unsub}>",
                               "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}


def test_tokens_are_masked_in_access_logs():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "GET", "/api/v1/newsletter/unsubscribe?token=abc.def&x=1", "1.1", 200), None)
    assert api.ACCESS_LOG_FILTER.filter(rec)
    assert "abc.def" not in rec.getMessage() and "token=REDACTED&x=1" in rec.getMessage()
    assert api.ACCESS_LOG_FILTER in logging.getLogger("uvicorn.access").filters


def test_legacy_pending_row_unsubscribed_before_confirming(client, nlenv):
    confirm, unsub = legacy_pending(nlenv)
    act(client, "unsubscribe", unsub)
    resp = act(client, "confirm", confirm)
    assert resp.headers["location"].endswith("result=invalid")  # final until they subscribe again
    assert nlenv.store.by_email("reader@example.com")["status"] == "unsubscribed"


def test_unsubscribe_is_final_until_a_new_subscription(client, nlenv):
    old = confirmed_reader(client, nlenv)
    act(client, "unsubscribe", token_from(old['text'], 'unsubscribe'))
    assert nlenv.store.by_email("reader@example.com")["status"] == "unsubscribed"
    # Subscribing again subscribes at once, with a new generation; the old links are retired.
    subscribe(client, "reader@example.com", ip="198.51.100.8")
    row = nlenv.store.by_email("reader@example.com")
    assert row["status"] == "confirmed" and row["token_generation"] == 2
    resp = act(client, "unsubscribe", token_from(old['text'], 'unsubscribe'))
    assert resp.headers["location"].endswith("result=invalid")
    assert row["status"] == "confirmed"


def test_unsubscribe_token_for_another_subscriber_is_refused(client, nlenv):
    a = confirmed_reader(client, nlenv, "a@example.com")
    confirmed_reader(client, nlenv, "b@example.com")
    b_id = nlenv.store.by_email("b@example.com")["id"]
    a_secret = token_from(a["text"], "unsubscribe").split(".")[1]
    forged = f"{uuid.UUID(b_id).hex}.{a_secret}"
    resp = act(client, "unsubscribe", forged)
    assert resp.headers["location"].endswith("result=invalid")
    assert nlenv.store.by_email("b@example.com")["status"] == "confirmed"


# ---------------------------------------------------------------------------
# GrokBot drafts: schema, banned wording, key
# ---------------------------------------------------------------------------
def test_grokbot_creates_a_draft(client, nlenv):
    resp = post_draft(client)
    assert resp.status_code == 201
    issue = nlenv.store.issues[resp.json()["id"]]
    assert issue["status"] == "draft" and issue["created_by"] == "grokbot"
    assert nlenv.store.audit[-1]["action"] == "newsletter.draft_created"


def _section(**over):
    return {**good_draft()["sections"][0], **over}


REJECTED_DRAFTS = {
    "extra top-level field": good_draft(author="me"),
    "extra section field": good_draft(sections=[_section(image="x.png")]),
    "extra link field": good_draft(sections=[_section(links=[{"label": "A", "url": "https://a.example.com", "rel": "x"}])]),
    "subject too long": good_draft(subject="a" * 121),
    "preview too long": good_draft(preview="a" * 161),
    "no sections": good_draft(sections=[]),
    "six sections": good_draft(sections=[_section()] * 6),
    "unknown type": good_draft(sections=[_section(type="opinion")]),
    "heading too long": good_draft(sections=[_section(heading="a" * 101)]),
    "body too long": good_draft(sections=[_section(body="a" * 1501)]),
    "html in body": good_draft(sections=[_section(body="Read <b>this</b> now.")]),
    "html in subject": good_draft(subject="<script>x</script>"),
    "markdown link in body": good_draft(sections=[_section(body="Read [the note](https://ndpc.gov.ng).")]),
    "url in body": good_draft(sections=[_section(body="See https://ndpc.gov.ng for details.")]),
    "bare domain in body": good_draft(sections=[_section(body="See ndpc.gov.ng for details.")]),
    "www in body": good_draft(sections=[_section(body="See www.example for details.")]),
    "http link": good_draft(sections=[_section(links=[{"label": "A", "url": "http://cyphward.com/a"}])]),
    "javascript link": good_draft(sections=[_section(links=[{"label": "A", "url": "javascript:alert(1)//aaaa"}])]),
    "credentials in link": good_draft(sections=[_section(links=[{"label": "A", "url": "https://u:p@cyphward.com/a"}])]),
    "four links": good_draft(sections=[_section(links=[{"label": "A", "url": "https://cyphward.com/a"}] * 4)]),
    "label too long": good_draft(sections=[_section(links=[{"label": "a" * 61, "url": "https://cyphward.com/a"}])]),
    "url too long": good_draft(sections=[_section(links=[{"label": "A", "url": "https://cyphward.com/" + "a" * 300}])]),
    "regulation without sources": good_draft(sections=[_section(type="regulation", links=[])]),
    "http source": good_draft(sections=[_section(type="regulation", sources=[{"title": "T", "url": "http://ndpc.gov.ng/x"}])]),
    "control character": good_draft(subject="Hello\x07there"),
    "newline in subject": good_draft(subject="Hello\nthere"),
    "zero-width character": good_draft(sections=[_section(body="com​pliant")]),
    "bidi override": good_draft(subject="Hello ‮ there"),
    "template marker": good_draft(sections=[_section(body="Hi {{ contact.EMAIL }}")]),
    "number as subject": good_draft(subject=12),
    "string as sections": good_draft(sections="none"),
}


@pytest.mark.parametrize("case", sorted(REJECTED_DRAFTS))
def test_draft_schema_rejections(client, nlenv, case):
    resp = post_draft(client, REJECTED_DRAFTS[case])
    assert resp.status_code == 422, case
    assert nlenv.store.issues == {}


BANNED = ["compliant", "certified", "certification", "satisfies", "adequate", "guarantee", "passes audit",
          "compliance score", "meets the requirement", "is met", "fully compliant", "is compliant"]


@pytest.mark.parametrize("phrase", BANNED)
@pytest.mark.parametrize("field", ["subject", "preview", "heading", "body", "label", "source"])
def test_banned_claim_wording_is_rejected_in_every_field(client, nlenv, phrase, field):
    cased = phrase.title() if field in ("heading", "label") else phrase.upper() if field == "preview" else phrase
    text = f"Your setup {cased} now"
    sec = _section(type="regulation", sources=[{"title": "Source", "url": "https://ndpc.gov.ng/a"}])
    if field in ("subject", "preview"):
        draft = good_draft(**{field: text})
    elif field == "label":
        draft = good_draft(sections=[{**sec, "links": [{"label": text[:60], "url": "https://cyphward.com/a"}]}])
    elif field == "source":
        draft = good_draft(sections=[{**sec, "sources": [{"title": text, "url": "https://ndpc.gov.ng/a"}]}])
    else:
        draft = good_draft(sections=[{**sec, field: text}])
    resp = post_draft(client, draft)
    assert resp.status_code == 422, (field, phrase)
    assert "claim wording" in resp.text


@pytest.mark.parametrize("text", ["Guaranteed results", "fully COMPLIANT", "compliance scores", "it is  met",
                                  # the shared C6 filter: other verdict words and disguises
                                  "Your setup complies", "it conforms to the act", "Approved by Cyphward",
                                  "c\u043empliant", "c0mpliant", "c o m p l i a n t", "NDPA-ready", "noncompliant"])
def test_banned_wording_inflections_and_spacing(text):
    assert nl.banned_claim(text)


@pytest.mark.parametrize("text", ["this method works", "the meeting is metered", "a certificate expired", "board approval minutes",
                                  "Cyphward checks TLS certificates"])
def test_ordinary_words_are_not_flagged(text):
    assert nl.banned_claim(text) is None


@pytest.mark.parametrize("key", [None, "", "wrong-key", DRAFT_KEY + "x", DRAFT_KEY[:-1]])
def test_draft_key_is_required(client, nlenv, key):
    resp = post_draft(client, key=key)
    assert resp.status_code == 401 and nlenv.store.issues == {}


def test_empty_configured_key_never_matches(client, nlenv, monkeypatch):
    monkeypatch.setattr(config, "NEWSLETTER_DRAFT_API_KEY", "")
    assert client.post("/api/v1/newsletter/drafts", json=good_draft(), headers={"Authorization": "Bearer "}).status_code == 401
    assert post_draft(client, key="").status_code == 401


def test_unauthenticated_draft_gets_401_before_any_schema_detail(client, nlenv):
    resp = post_draft(client, {"nonsense": True}, key="wrong")
    assert resp.status_code == 401


def test_draft_key_cannot_read_send_or_touch_subscribers(client, nlenv):
    iid = post_draft(client).json()["id"]
    confirmed_reader(client, nlenv)
    calls_before = list(nlenv.brevo.calls)
    h = {"Authorization": f"Bearer {DRAFT_KEY}"}
    assert client.get("/api/v1/newsletter/drafts", headers=h).status_code == 401
    assert client.get("/api/v1/newsletter/stats", headers=h).status_code in (401, 403)
    assert send(client, h, iid).status_code == 401
    assert client.post(f"/api/v1/newsletter/drafts/{iid}/send", json={"approve": True, "subject": "x"},
                       headers={"X-Newsletter-Key": DRAFT_KEY}).status_code == 401
    assert nlenv.store.issues[iid]["send_claimed_at"] is None
    assert nlenv.brevo.calls == calls_before


def test_draft_key_is_never_logged(client, nlenv, caplog):
    caplog.set_level(logging.DEBUG)
    post_draft(client)
    post_draft(client, key="wrong-" + DRAFT_KEY)
    assert all(DRAFT_KEY not in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Admin preview and send
# ---------------------------------------------------------------------------
def test_admin_previews_drafts(client, nlenv, auth_headers):
    post_draft(client)
    confirmed_reader(client, nlenv)
    body = client.get("/api/v1/newsletter/drafts", headers=staff(nlenv.fake_db, auth_headers)).json()
    assert body["confirmed_subscribers"] == 1
    (issue,) = body["issues"]
    assert issue["sendable"] is True and issue["status"] == "draft"
    assert POSTAL in issue["preview_html"] and "unsubscribe?token=" in issue["preview_html"]
    assert "Reports show the scan date" in issue["preview_text"]
    assert "reader@example.com" not in json.dumps(body)  # previews never list subscribers


@pytest.mark.parametrize("who", ["anonymous", "org_owner_without_grant", "staff_with_read_only", "unverified_staff"])
def test_admin_endpoints_refuse_others(client, nlenv, auth_headers, who):
    iid = post_draft(client).json()["id"]
    if who == "anonymous":
        h = {}
    elif who == "org_owner_without_grant":
        nlenv.fake_db.profiles[ALICE]["email_verified_at"] = datetime.now(timezone.utc)
        h = auth_headers(ALICE, email=f"{ALICE[:8]}@acme.test")
    elif who == "staff_with_read_only":
        h = staff(nlenv.fake_db, auth_headers, scopes=("platform:read",))
    else:
        h = staff(nlenv.fake_db, auth_headers)
        nlenv.fake_db.profiles[BOB]["email_verified_at"] = None
    assert client.get("/api/v1/newsletter/drafts", headers=h).status_code in (401, 403)
    assert send(client, h, iid).status_code in (401, 403)
    assert nlenv.store.issues[iid]["send_claimed_at"] is None


def test_send_needs_explicit_approval_and_the_exact_subject(client, nlenv, auth_headers):
    iid = post_draft(client).json()["id"]
    h = staff(nlenv.fake_db, auth_headers)
    assert send(client, h, iid, approve=False).status_code == 422
    assert client.post(f"/api/v1/newsletter/drafts/{iid}/send", json={"subject": "Cyphward notes for October"}, headers=h).status_code == 422
    assert send(client, h, iid, subject="cyphward notes for october").status_code == 422
    assert nlenv.store.issues[iid]["send_claimed_at"] is None and nlenv.brevo.calls == []


@pytest.mark.parametrize("bad", ["not-a-uuid", "1", "drafts", "%27%20OR%201=1"])
def test_malformed_issue_id_is_404(client, nlenv, auth_headers, bad):
    assert send(client, staff(nlenv.fake_db, auth_headers), bad).status_code == 404


def test_unknown_issue_is_404(client, nlenv, auth_headers):
    assert send(client, staff(nlenv.fake_db, auth_headers), str(uuid.uuid4())).status_code == 404


def test_send_once_only_and_audited(client, nlenv, auth_headers):
    confirmed_reader(client, nlenv)
    iid = post_draft(client).json()["id"]
    h = staff(nlenv.fake_db, auth_headers)
    resp = send(client, h, iid)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "sent" and resp.json()["recipients"] == 1
    campaign = nlenv.brevo.campaigns[resp.json()["brevo_campaign_id"]]
    assert campaign["sender"] == ("Cyphward News", "news@cyphward.com")
    assert campaign["recipients"] == ["reader@example.com"]
    assert "{{ contact.CW_UNSUB_TOKEN }}" in campaign["html"] and POSTAL in campaign["html"]
    assert "<img" not in campaign["html"].lower()
    assert nlenv.brevo.sent == [resp.json()["brevo_campaign_id"]]
    # A second attempt is refused and creates nothing.
    again = send(client, h, iid)
    assert again.status_code == 409 and len(nlenv.brevo.campaigns) == 1 and len(nlenv.brevo.sent) == 1
    actions = [a["action"] for a in nlenv.store.audit if a["resource_id"] == iid]
    assert actions == ["newsletter.draft_created", "newsletter.send_approved", "newsletter.campaign_created", "newsletter.sent"]
    assert all(a["user_id"] == BOB for a in nlenv.store.audit if a["action"] != "newsletter.draft_created")
    assert nlenv.store.issues[iid]["approved_by"] == BOB


def test_concurrent_sends_claim_once(client, nlenv, auth_headers):
    iid = post_draft(client).json()["id"]
    actor = {"kind": "owner", "user_id": ALICE}
    assert nlenv.store.claim_issue(iid, actor) is not None
    assert nlenv.store.claim_issue(iid, actor) is None
    assert send(client, staff(nlenv.fake_db, auth_headers), iid).status_code == 409


def test_unconfirmed_and_unsubscribed_never_receive_an_issue(client, nlenv, auth_headers):
    confirmed_reader(client, nlenv, "confirmed@example.com")
    confirmed_reader(client, nlenv, "missing@example.com")
    legacy_pending(nlenv, "pending@example.com")
    gone = confirmed_reader(client, nlenv, "gone@example.com")
    nlenv.brevo.fail.add("remove")  # the unsubscribe-time removal fails ...
    act(client, "unsubscribe", token_from(gone['text'], 'unsubscribe'))
    nlenv.brevo.fail.clear()
    assert "gone@example.com" in nlenv.brevo.contacts
    # ... a pending address and a stranger appear on the list, a confirmed one went missing, one was blocked in Brevo.
    nlenv.brevo.contacts["pending@example.com"] = {"blocked": False, "attributes": {}}
    nlenv.brevo.contacts["stranger@example.com"] = {"blocked": False, "attributes": {}}
    nlenv.brevo.contacts.pop("missing@example.com")
    confirmed_reader(client, nlenv, "blocked@example.com")
    nlenv.brevo.contacts["blocked@example.com"]["blocked"] = True
    nlenv.brevo.calls.clear()

    iid = post_draft(client).json()["id"]
    resp = send(client, staff(nlenv.fake_db, auth_headers), iid)
    assert resp.status_code == 200, resp.text
    campaign = nlenv.brevo.campaigns[resp.json()["brevo_campaign_id"]]
    assert campaign["recipients"] == ["confirmed@example.com", "missing@example.com"]
    ops = nlenv.brevo.ops()
    assert ops.index("remove") < ops.index("create_campaign") and ops.index("upsert") < ops.index("create_campaign")
    removed = [c[1] for c in nlenv.brevo.calls if c[0] == "remove"][0]
    assert set(removed) == {"gone@example.com", "pending@example.com", "stranger@example.com", "blocked@example.com"}
    assert ("upsert", "pending@example.com") not in nlenv.brevo.calls
    assert nlenv.store.by_email("blocked@example.com")["status"] == "unsubscribed"  # Brevo unsubscribes come back here


def test_failure_before_the_campaign_sends_nothing_and_burns_the_attempt(client, nlenv, auth_headers):
    confirmed_reader(client, nlenv)
    iid = post_draft(client).json()["id"]
    h = staff(nlenv.fake_db, auth_headers)
    nlenv.brevo.fail.add("create_campaign")
    resp = send(client, h, iid)
    assert resp.status_code == 502 and "Nothing was sent" in resp.json()["detail"]
    assert nlenv.brevo.sent == [] and nlenv.store.issues[iid]["send_error"]
    nlenv.brevo.fail.clear()
    assert send(client, h, iid).status_code == 409  # never retried: a new draft is needed
    assert [a["action"] for a in nlenv.store.audit if a["resource_id"] == iid][-1] == "newsletter.send_failed"


def test_uncertain_send_is_never_retried(client, nlenv, auth_headers):
    confirmed_reader(client, nlenv)
    iid = post_draft(client).json()["id"]
    h = staff(nlenv.fake_db, auth_headers)
    nlenv.brevo.fail.add("send_now")
    resp = send(client, h, iid)
    assert resp.status_code == 502 and nlenv.store.issues[iid]["brevo_campaign_id"]
    nlenv.brevo.fail.clear()
    assert send(client, h, iid).status_code == 409 and len(nlenv.brevo.campaigns) == 1


def test_stale_unsubscribe_attribute_is_refreshed_before_sending(client, nlenv, auth_headers):
    old = confirmed_reader(client, nlenv)
    # Unsubscribe; the Brevo removal fails, so the contact stays on the list with the generation-1 token.
    nlenv.brevo.fail.add("remove")
    act(client, "unsubscribe", token_from(old['text'], 'unsubscribe'))
    # Subscribe again (confirmed at once); the subscribe-time upsert also fails.
    nlenv.brevo.fail = {"upsert"}
    subscribe(client, "reader@example.com", ip="198.51.100.21")
    nlenv.brevo.fail.clear()
    row = nlenv.store.by_email("reader@example.com")
    assert row["status"] == "confirmed" and row["token_generation"] == 2
    stale = nlenv.brevo.contacts["reader@example.com"]["attributes"]["CW_UNSUB_TOKEN"]
    fresh = nl.unsubscribe_token(SECRET, row["id"], 2)
    assert stale == token_from(old["text"], "unsubscribe") and stale != fresh

    resp = send(client, staff(nlenv.fake_db, auth_headers), post_draft(client).json()["id"])
    assert resp.status_code == 200, resp.text
    assert nlenv.brevo.contacts["reader@example.com"]["attributes"]["CW_UNSUB_TOKEN"] == fresh
    ops = nlenv.brevo.ops()
    assert ops.index("upsert") < ops.index("create_campaign")


def test_missing_unsubscribe_attribute_refuses_the_send(client, nlenv, auth_headers):
    nlenv.brevo.drop_attributes = True  # e.g. the attribute was never created in Brevo
    confirmed_reader(client, nlenv)
    iid = post_draft(client).json()["id"]
    resp = send(client, staff(nlenv.fake_db, auth_headers), iid)
    assert resp.status_code == 502 and "Nothing was sent" in resp.json()["detail"]
    assert nlenv.brevo.campaigns == {} and nlenv.brevo.sent == []
    assert "CW_UNSUB_TOKEN" in nlenv.store.issues[iid]["send_error"]


def test_owner_console_can_send_from_the_console_origin_only(client, nlenv, monkeypatch):
    confirmed_reader(client, nlenv)
    iid = post_draft(client).json()["id"]
    monkeypatch.setattr(owner_mod, "require_owner", lambda request: {"user_id": ALICE, "email": "owner@acme.test",
                                                                     "session_id": "s", "expires_at": None})
    monkeypatch.setattr(owner_mod, "OWNER_CONSOLE_ORIGINS", ["https://admin.cyphward.test"])
    assert client.get("/api/v1/newsletter/drafts").status_code == 200
    assert send(client, {"Origin": "https://evil.example"}, iid).status_code == 403
    assert nlenv.store.issues[iid]["send_claimed_at"] is None
    resp = send(client, {"Origin": "https://admin.cyphward.test"}, iid)
    assert resp.status_code == 200
    assert [a for a in nlenv.store.audit if a["action"] == "newsletter.send_approved"][0]["metadata"]["actor"] == "owner"


# ---------------------------------------------------------------------------
# Owner console: subscriber counts (read-only, owner cookie only, numbers only)
# ---------------------------------------------------------------------------
def _as_owner(monkeypatch):
    seen = []

    def fake_owner(request):
        seen.append(request.url.path)
        return {"user_id": ALICE, "email": "owner@acme.test", "session_id": "s", "expires_at": None}

    monkeypatch.setattr(owner_mod, "require_owner", fake_owner)
    return seen


def _three_states(client, env):
    confirmed_reader(client, env, "kept@example.com")
    confirmed_reader(client, env, "also-kept@example.com")
    gone = confirmed_reader(client, env, "gone@example.com")
    assert act(client, "unsubscribe", token_from(gone["text"], "unsubscribe")).status_code == 303
    legacy_pending(env, "waiting@example.com")


def test_owner_reads_subscriber_counts_without_any_address(client, nlenv, monkeypatch):
    _three_states(client, nlenv)
    seen = _as_owner(monkeypatch)
    resp = client.get("/api/v1/newsletter/stats")
    assert resp.status_code == 200
    assert resp.json() == {"confirmed": 2, "unsubscribed": 1, "pending": 1}
    assert seen == ["/api/v1/newsletter/stats"]
    assert "@" not in resp.text and "example.com" not in resp.text
    assert not any(k in resp.text for k in ("id", "email", "token"))


def test_reading_the_counts_is_in_the_owner_log_first(client, nlenv, monkeypatch):
    _as_owner(monkeypatch)
    resp = client.get("/api/v1/newsletter/stats")
    assert resp.status_code == 200
    row = nlenv.fake_db.owner_audit[-1]
    assert row["action"] == "owner.view.newsletter_stats" and row["outcome"] == "success"
    nlenv.fake_db.owner_audit_fails = True
    refused = client.get("/api/v1/newsletter/stats")
    assert refused.status_code == 503 and "confirmed" not in refused.text  # no audit row, no data


def test_subscriber_counts_are_zero_filled(client, nlenv, monkeypatch):
    _as_owner(monkeypatch)
    assert client.get("/api/v1/newsletter/stats").json() == {"confirmed": 0, "unsubscribed": 0, "pending": 0}


def test_subscriber_counts_change_nothing(client, nlenv, monkeypatch):
    _three_states(client, nlenv)
    _as_owner(monkeypatch)
    before = {k: dict(v) for k, v in nlenv.store.subscribers.items()}
    calls, audit = list(nlenv.brevo.calls), list(nlenv.store.audit)
    client.get("/api/v1/newsletter/stats")
    assert {k: dict(v) for k, v in nlenv.store.subscribers.items()} == before
    assert nlenv.brevo.calls == calls and nlenv.store.audit == audit


@pytest.mark.parametrize("who", ["anonymous", "staff_without_scope", "staff_with_newsletter_scope",
                                 "org_owner_without_grant", "unverified_staff"])
def test_subscriber_counts_are_for_the_owner_console_only(client, nlenv, auth_headers, who):
    _three_states(client, nlenv)
    if who == "anonymous":
        h = {}
    elif who == "staff_without_scope":
        h = staff(nlenv.fake_db, auth_headers, scopes=("platform:read",))
    elif who == "staff_with_newsletter_scope":
        h = staff(nlenv.fake_db, auth_headers)
    elif who == "org_owner_without_grant":
        nlenv.fake_db.profiles[ALICE]["email_verified_at"] = datetime.now(timezone.utc)
        h = auth_headers(ALICE, email=f"{ALICE[:8]}@acme.test")
    else:
        h = staff(nlenv.fake_db, auth_headers)
        nlenv.fake_db.profiles[BOB]["email_verified_at"] = None
    resp = client.get("/api/v1/newsletter/stats", headers=h)
    assert resp.status_code in (401, 403)
    assert "@" not in resp.text and "confirmed" not in resp.text


def test_a_bearer_token_never_reaches_the_owner_check(client, nlenv, auth_headers, monkeypatch):
    seen = _as_owner(monkeypatch)
    h = staff(nlenv.fake_db, auth_headers)
    assert client.get("/api/v1/newsletter/stats", headers=h).status_code == 403
    assert seen == []  # even a valid owner cookie alongside a bearer token is refused


def test_subscriber_counts_are_404_while_the_feature_is_off(client, nlenv, monkeypatch):
    _as_owner(monkeypatch)
    monkeypatch.setattr(config, "NEWSLETTER_ENABLED", False)
    assert client.get("/api/v1/newsletter/stats").status_code == 404


def test_a_stored_draft_that_fails_the_rules_cannot_be_sent(client, nlenv, auth_headers):
    iid = post_draft(client).json()["id"]
    nlenv.store.issues[iid]["body_json"] = good_draft(subject="We guarantee it")
    nlenv.store.issues[iid]["subject"] = "We guarantee it"
    resp = send(client, staff(nlenv.fake_db, auth_headers), iid, subject="We guarantee it")
    assert resp.status_code == 422 and nlenv.store.issues[iid]["send_claimed_at"] is None


# ---------------------------------------------------------------------------
# Mailer: the newsletter path can never fall back to the list-2 campaign
# ---------------------------------------------------------------------------
def test_mailer_without_campaign_fallback_makes_no_list_or_campaign_call(monkeypatch):
    import backend.app.services.mailer as mailer
    urls = []

    class FailingClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            urls.append(url)
            raise RuntimeError("down")

    def failing_smtp(*a, **k):
        raise OSError("smtp down")

    monkeypatch.setattr(mailer, "BREVO_API_KEY", "k")
    monkeypatch.setattr(mailer.httpx, "AsyncClient", FailingClient)
    monkeypatch.setattr(mailer.smtplib, "SMTP", failing_smtp)
    with pytest.raises(RuntimeError):
        asyncio.run(mailer.send_email_async("a@example.com", "s", "<p>h</p>", "t", sender=config.NEWSLETTER_SENDER,
                                            allow_campaign_fallback=False))
    assert urls == ["https://api.brevo.com/v3/smtp/email"]
    urls.clear()
    with pytest.raises(RuntimeError):
        asyncio.run(mailer.send_email_async("a@example.com", "s", "<p>h</p>", "t"))
    assert "https://api.brevo.com/v3/contacts" in urls  # the transactional default is unchanged


# ---------------------------------------------------------------------------
# Copy: no claim wording anywhere a reader sees it
# ---------------------------------------------------------------------------
def _settings():
    return nl.Settings(list_id=7, postal_line=POSTAL, base_url=BASE, token_secret=SECRET,
                       unsub_attribute="CW_UNSUB_TOKEN", sender=config.NEWSLETTER_SENDER)


def _subscribed(version=nl.CONSENT_WORDING_VERSION):
    sid = str(uuid.uuid4())
    return nl.Subscribed(sid, "a@example.com", nl.unsubscribe_token(SECRET, sid, 1), 1, version)


def test_rendered_newsletter_copy_has_no_claim_wording():
    s = _settings()
    mail = nl.render_confirmation(s, _subscribed())
    texts = [mail["subject"], mail["html"], mail["text"]] + list(nl.render_issue(s, good_draft()).values())
    texts += [api.SUBSCRIBE_ACCEPTED["message"], nl.CONSENT_WORDING, nl.NOT_A_LAW_FIRM]
    for text in texts:
        assert nl.banned_claim(re.sub(r"<[^>]+>", " ", text)) is None, text[:80]
        lowered = text.lower()
        for phrase in BANNED + ["passes audit", "meets the requirement"]:
            assert phrase not in lowered, (phrase, text[:80])


def test_subscribe_answer_is_the_single_opt_in_sentence():
    assert api.SUBSCRIBE_ACCEPTED == {
        "message": "You are subscribed. We have sent a confirmation email with an unsubscribe link."}


# ---------------------------------------------------------------------------
# Branded email
# ---------------------------------------------------------------------------
def test_confirmation_email_is_branded_and_self_contained():
    s = _settings()
    mail = nl.render_confirmation(s, _subscribed())
    html, text = mail["html"], mail["text"]
    assert mail["subject"] == "You are subscribed to Cyphward updates"
    assert "CYPHWARD" in html and "#E5532B" in html and "#0A0907" in html and "#14130F" in html
    lowered = html.lower()
    for forbidden in ("<img", "<svg", "<script", "<style", "<link", "url(", "@import", "class=", "fonts.g",
                      "javascript:", "src=", "/api/v1/newsletter/confirm"):
        assert forbidden not in lowered, forbidden
    # Inline styles only: every tag that is styled carries style="..."; nothing else references CSS.
    assert re.findall(r"https?://[^\s\"'<>]+", html) == [nl.unsubscribe_url(s, _token_in(html))]
    unsub_url = nl.unsubscribe_url(s, _token_in(html))
    assert html.count(unsub_url) == 1 and html.count("/api/v1/newsletter/unsubscribe") == 1  # exactly once
    assert POSTAL in html and html.index(POSTAL) > html.index(unsub_url)  # the postal line is in the footer
    assert "about once a month" in text.lower() and nl.CONSENT_WORDING_VERSION in text and unsub_url in text
    assert len(text) < 1200  # a short plain-text part


def _token_in(html):
    m = re.search(r"/api/v1/newsletter/unsubscribe\?token=([A-Za-z0-9._-]+)", html)
    return m.group(1)


def test_issue_wrapper_is_branded_with_the_unsubscribe_link_once():
    rendered = nl.render_issue(_settings(), good_draft())
    html = rendered["html"]
    assert "CYPHWARD" in html and "#E5532B" in html and nl.NOT_A_LAW_FIRM in html and POSTAL in html
    assert html.count("/api/v1/newsletter/unsubscribe") == 1 and "{{ contact.CW_UNSUB_TOKEN }}" in html
    for forbidden in ("<img", "<svg", "<script", "<style", "<link", "url(", "@import", "class="):
        assert forbidden not in html.lower(), forbidden


HOSTILE = "<b>\"Acme\" & 'Co'</b><script>alert(1)</script>"


def test_email_html_escapes_every_interpolated_value():
    s = nl.Settings(list_id=7, postal_line=HOSTILE, base_url='https://cyphward.test/"><i>x</i>', token_secret=SECRET,
                    unsub_attribute="CW_UNSUB_TOKEN", sender=("News", 'news@cyphward.com"><u>y</u>'))
    mail = nl.render_confirmation(s, _subscribed(version='v1"><em>z</em>'))
    issue = nl.render_issue(s, good_draft(), unsub_href='https://cyphward.test/u?token="><s>q</s>')
    for html in (mail["html"], issue["html"]):
        for raw in ("<b>", "<script", "<i>", "<u>", "<em>", "<s>", '"><i>', '"><u>', '"><em>', '"><s>'):
            assert raw not in html, raw
    assert "&lt;b&gt;&quot;Acme&quot; &amp; &#x27;Co&#x27;&lt;/b&gt;&lt;script&gt;" in mail["html"]
    assert "&quot;&gt;&lt;i&gt;x&lt;/i&gt;" in mail["html"]  # the base URL inside the href
    assert "&lt;u&gt;y&lt;/u&gt;" in mail["html"] and "&lt;em&gt;z&lt;/em&gt;" in mail["html"]
    assert "&quot;&gt;&lt;s&gt;q&lt;/s&gt;" in issue["html"]


def test_frontend_consent_wording_matches_the_server():
    source = (FRONTEND / "lib" / "newsletter.ts").read_text(encoding="utf-8")
    assert nl.CONSENT_WORDING in source and nl.CONSENT_WORDING_VERSION in source


@pytest.mark.parametrize("name", ["components/NewsletterSubscribe.tsx", "pages/Newsletter.tsx",
                                  "pages/NewsletterResult.tsx", "lib/newsletter.ts", "PRIVACY_NEWSLETTER",
                                  "owner/newsletterView.tsx", "owner/ownerApi.ts", "owner/shell.tsx"])
def test_frontend_newsletter_copy_has_no_claim_wording(name):
    text = _privacy_newsletter_section() if name == "PRIVACY_NEWSLETTER" else (FRONTEND / name).read_text(encoding="utf-8")
    strings = re.findall(r"'([^'\n]*)'|\"([^\"\n]*)\"|>([^<>{}\n]+)<", text)
    for groups in strings:
        for s in groups:
            assert nl.banned_claim(s) is None, (name, s)


def test_owner_console_names_the_configured_sender():
    """The send dialog states who the email comes from; it must be the sender the server uses."""
    source = (FRONTEND / "owner" / "newsletterView.tsx").read_text(encoding="utf-8")
    name, address = config.NEWSLETTER_SENDER
    assert f"NEWSLETTER_SENDER_NAME = '{name}'" in source
    assert f"NEWSLETTER_SENDER_ADDRESS = '{address}'" in source


def _privacy_newsletter_section():
    source = (FRONTEND / "pages" / "Privacy.tsx").read_text(encoding="utf-8")
    m = re.search(r'<Section n="\d+" heading="Newsletter">(.*?)</Section>', source, re.S)
    assert m, "the privacy policy has a Newsletter section"
    return m.group(1)


def test_privacy_policy_newsletter_section_says_what_the_brief_requires():
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>|\{' '\}", " ", _privacy_newsletter_section()))
    for needed in ("email address", "wording version", "source page", "monthly", "Brevo", "unsubscribe link",
                   "contact form", "until you unsubscribe", "honour the unsubscribe", "not a law firm",
                   # what the unsubscribe record really holds (core/newsletter.py unsubscribe(); the CHECKs keep the
                   # consent columns), what stays in Brevo, and the rate-limit buckets
                   "that it is unsubscribed", "when you gave consent and were subscribed", "how many times",
                   "one-way hash of your last unsubscribe link", "contact that is off the mailing list",
                   "code from your last unsubscribe link", "privacy@cyphward.com",
                   "one-way hashes of your email address and of your network (IP) address", "24 hours"):
        assert needed in text, needed
    assert nl.banned_claim(text) is None
    for phrase in BANNED + ["passes audit", "meets the requirement"]:
        assert phrase not in text.lower(), phrase


def test_newsletter_page_is_not_published_while_the_flag_can_be_off():
    """/newsletter is never prerendered or listed: crawlers get the noindex SPA shell (the build checks that too)."""
    scripts, public = FRONTEND.parent / "scripts", FRONTEND.parent / "public"
    assert "/newsletter" not in (public / "sitemap.xml").read_text(encoding="utf-8")
    prerender = (scripts / "prerender.mjs").read_text(encoding="utf-8")
    pages = prerender[prerender.index("const PAGES = ["):prerender.index("];", prerender.index("const PAGES = ["))]
    assert "/newsletter" not in pages
    assert "assertNewsletterUnpublished(appShell);" in prerender  # the build fails if it is ever published
    entry = (FRONTEND / "prerender-entry.tsx").read_text(encoding="utf-8")
    assert "Newsletter" not in entry and "/newsletter" not in entry


# ---------------------------------------------------------------------------
# Send once: the route's pre-check and the claim's condition each hold on their own
# ---------------------------------------------------------------------------
def test_route_precheck_alone_refuses_a_claimed_or_sent_issue(client, nlenv, auth_headers, monkeypatch):
    claims = []
    monkeypatch.setattr(nlenv.store, "claim_issue", lambda iid, actor: claims.append(iid) or {"id": iid})  # would allow
    h = staff(nlenv.fake_db, auth_headers)
    for state in ({"send_claimed_at": datetime.now(timezone.utc)}, {"status": "sent", "send_claimed_at": datetime.now(timezone.utc)}):
        iid = post_draft(client).json()["id"]
        nlenv.store.issues[iid].update(state)
        assert send(client, h, iid).status_code == 409
    assert claims == [] and nlenv.brevo.calls == []


def test_claim_condition_alone_refuses_when_the_precheck_saw_a_stale_row(client, nlenv, auth_headers, monkeypatch):
    iid = post_draft(client).json()["id"]
    stale = nlenv.store.get_issue(iid)  # read before another admin's claim
    assert nlenv.store.claim_issue(iid, {"kind": "owner", "user_id": ALICE}) is not None
    monkeypatch.setattr(nlenv.store, "get_issue", lambda _id: dict(stale))  # pre-check sees "draft, unclaimed"
    resp = send(client, staff(nlenv.fake_db, auth_headers), iid)
    assert resp.status_code == 409 and nlenv.brevo.calls == []


def test_mailer_passes_list_unsubscribe_headers_to_brevo(monkeypatch):
    import backend.app.services.mailer as mailer
    payloads = []

    class Resp:
        status_code = 201

        def json(self):
            return {"messageId": "m1"}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            payloads.append(json)
            return Resp()

    monkeypatch.setattr(mailer, "BREVO_API_KEY", "k")
    monkeypatch.setattr(mailer.httpx, "AsyncClient", Client)
    h = nl.list_unsubscribe_headers("https://cyphward.test/api/v1/newsletter/unsubscribe?token=t")
    asyncio.run(mailer.send_email_async("a@example.com", "s", "<p>h</p>", "t", sender=config.NEWSLETTER_SENDER,
                                        allow_campaign_fallback=False, mail_headers=h))
    asyncio.run(mailer.send_email_async("a@example.com", "s", "<p>h</p>", "t"))
    assert payloads[0]["headers"] == h and payloads[0]["sender"]["email"] == "news@cyphward.com"
    assert "api-key" not in payloads[0]["headers"]  # mail headers, never the HTTP ones carrying the API key
    assert "headers" not in payloads[1] and payloads[1]["sender"]["email"] == "no-reply@cyphward.com"



# ---------------------------------------------------------------------------
# Re-review fixes
# ---------------------------------------------------------------------------
def test_one_click_from_one_provider_ip_is_never_capped(client, nlenv):
    mails = [confirmed_reader(client, nlenv, f"r{i}@example.com") for i in range(5)]
    codes = []
    for i in range(100):  # one provider's shared sending server
        token = token_from(mails[i % 5]["text"], "unsubscribe")
        resp = client.post(f"/api/v1/newsletter/unsubscribe?token={token}", content=b"List-Unsubscribe=One-Click",
                           headers={"Content-Type": "application/x-www-form-urlencoded", "X-Forwarded-For": "209.85.220.41"})
        codes.append(resp.status_code)
    assert codes == [200] * 100
    assert all(nlenv.store.by_email(f"r{i}@example.com")["status"] == "unsubscribed" for i in range(5))
    # The browser button keeps its per-IP limit.
    browser = [act(client, "unsubscribe", "x", ip="198.51.100.200").status_code for _ in range(61)]
    assert browser[:60] == [303] * 60 and browser[60] == 429


def test_one_click_has_a_global_ceiling(client, nlenv, monkeypatch):
    monkeypatch.setattr(api, "ONE_CLICK_HOURLY_CEILING", 3)
    url = "/api/v1/newsletter/unsubscribe?token=" + "0" * 32 + "." + "a" * 43
    codes = [client.post(url, content=b"List-Unsubscribe=One-Click", headers={
        "Content-Type": "application/x-www-form-urlencoded", "X-Forwarded-For": f"203.0.113.{i}"}).status_code
        for i in range(4)]
    assert codes == [400, 400, 400, 429]


def test_confirm_reads_the_token_from_the_form_body_only(client, nlenv):
    token, _ = legacy_pending(nlenv)
    resp = client.post(f"/api/v1/newsletter/confirm?token={token}", follow_redirects=False)  # token only in the URL
    assert resp.status_code == 303 and resp.headers["location"].endswith("result=invalid")
    resp = client.post(f"/api/v1/newsletter/confirm?token={token}", data={"token": ""}, follow_redirects=False)
    assert resp.headers["location"].endswith("result=invalid")
    assert nlenv.store.by_email("reader@example.com")["status"] == "pending" and nlenv.brevo.calls == []
    assert act(client, "confirm", token).headers["location"].endswith("result=ok")  # the body is what counts


@pytest.mark.parametrize("text", ["The NDPC approved new guidance on breach reporting.",
                                  "How to meet the NDPA filing date", "The regulator has approved the new forms.",
                                  "Teams must meet the annual audit deadline."])
def test_ordinary_regulation_news_is_allowed(client, nlenv, text):
    assert nl.banned_claim(text) is None
    sec = {**_section(type="regulation", sources=[{"title": "NDPC notice", "url": "https://ndpc.gov.ng/a"}]), "heading": "NDPC update",
           "body": text}
    assert post_draft(client, good_draft(sections=[sec])).status_code == 201


ALLOW_LIST_CLAIMS = [
    "Approved by Cyphward", "Cyphward approved your setup", "Your setup meets the NDPA",
    "This meets the requirement deadline", "The NDPC approved; you are compliant",
    "The NDPC approved your setup", "The NDPC approved Cyphward", "Regulators approved this product",
    "The commission has approved your organisation", "The regulator approved your security programme",
    "Your organisation meets the NDPA compliance deadline", "Cyphward customers meet the NDPC filing deadline",
    "meet the conforming sufficient deadline", "The NDPC approved the new platform", "You meet the NDPA filing date",
    "The regulator approved new guidance and your setup is compliant",
]


@pytest.mark.parametrize("text", ALLOW_LIST_CLAIMS + [t.replace(" ", "\u00a0") for t in ALLOW_LIST_CLAIMS]
                         + [t.replace(" ", "  ") for t in ALLOW_LIST_CLAIMS])
def test_allow_list_does_not_open_claims(text):
    assert nl.banned_claim(text)


@pytest.mark.parametrize("text", ["The NDPC approved new guidance", "How to meet the NDPA filing date",
                                  "The\u00a0NDPC  approved new\u00a0guidance", "The regulator has approved the new forms",
                                  "The commission approved revised regulations"])
def test_allow_list_keeps_ordinary_news(text):
    assert nl.banned_claim(text) is None
