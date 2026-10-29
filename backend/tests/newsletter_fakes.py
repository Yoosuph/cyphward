"""In-memory newsletter store and Brevo stub for the unit tests (no network, no PostgreSQL).

The store makes its choices with the same decision functions as the PostgreSQL store
(backend.app.core.newsletter); backend/tests/test_newsletter_postgres.py runs the real SQL.
"""
import uuid
from datetime import datetime, timedelta, timezone

from backend.app.core import newsletter as nl
from backend.app.services.newsletter_brevo import BrevoError


def _now():
    return datetime.now(timezone.utc)


class FakeNewsletterStore:
    def __init__(self):
        self.subscribers = {}
        self.issues = {}
        self.audit = []

    def by_email(self, email):
        return next((r for r in self.subscribers.values() if r["email_normalised"] == email), None)

    def subscribe(self, email, consent_version, source, secret):
        """Single opt-in, as PostgresNewsletterStore.subscribe: confirmed at once, consent recorded."""
        row = self.by_email(email)
        generation = nl.subscribe_generation(row)
        if generation is None:
            return None
        previous = row["status"] if row else "new"
        sid = row["id"] if row else str(uuid.uuid4())
        unsub = nl.unsubscribe_token(secret, sid, generation)
        if row is None:
            row = {"id": sid, "email_normalised": email, "created_at": _now()}
            self.subscribers[sid] = row
        row.update(status="confirmed", consent_at=_now(), consent_wording_version=consent_version, source=source,
                   token_generation=generation, confirm_token_hash=None, confirm_expires_at=None,
                   unsubscribe_token_hash=nl.hash_token(unsub), confirmed_at=_now(), unsubscribed_at=None)
        return nl.Subscribed(sid, email, unsub, generation, consent_version, previous)

    def seed_legacy_pending(self, email, secret, source="newsletter_page"):
        """A row as the earlier double opt-in left it: pending, with a 72-hour confirm token.
        Returns (confirm token, unsubscribe token), as its email carried them."""
        sid = str(uuid.uuid4())
        confirm = nl.new_confirm_token(sid)
        unsub = nl.unsubscribe_token(secret, sid, 1)
        self.subscribers[sid] = {
            "id": sid, "email_normalised": email, "created_at": _now(), "status": "pending", "consent_at": _now(),
            "consent_wording_version": nl.CONSENT_WORDING_VERSION, "source": source, "token_generation": 1,
            "confirm_token_hash": nl.hash_token(confirm), "confirm_expires_at": _now() + nl.CONFIRM_TTL,
            "unsubscribe_token_hash": nl.hash_token(unsub), "confirmed_at": None, "unsubscribed_at": None,
        }
        return confirm, unsub

    def confirm(self, token):
        sid = nl.token_subscriber_id(token)
        if sid is None:
            return nl.ConfirmResult("invalid")
        row = self.subscribers.get(sid)
        outcome = nl.confirm_decision(row, token, _now())
        if outcome == "confirmed":
            row.update(status="confirmed", confirmed_at=_now())
        if outcome in ("confirmed", "already"):
            return nl.ConfirmResult(outcome, sid, row["email_normalised"], row["token_generation"])
        return nl.ConfirmResult(outcome)

    def unsubscribe(self, token):
        sid = nl.token_subscriber_id(token)
        if sid is None:
            return nl.UnsubscribeResult("invalid")
        row = self.subscribers.get(sid)
        outcome = nl.unsubscribe_decision(row, token)
        if outcome == "unsubscribed":
            row.update(status="unsubscribed", unsubscribed_at=_now(), confirm_token_hash=None, confirm_expires_at=None)
        return nl.UnsubscribeResult(outcome, row["email_normalised"] if outcome != "invalid" else None)

    def confirmed_subscribers(self):
        return [{"id": r["id"], "email_normalised": r["email_normalised"], "token_generation": r["token_generation"]}
                for r in self.subscribers.values() if r["status"] == "confirmed"]

    def count_confirmed(self):
        return len(self.confirmed_subscribers())

    def subscriber_counts(self):
        counts = {"confirmed": 0, "unsubscribed": 0, "pending": 0}
        for r in self.subscribers.values():
            if r["status"] in counts:
                counts[r["status"]] += 1
        return counts

    def mark_unsubscribed(self, emails):
        n = 0
        for r in self.subscribers.values():
            if r["email_normalised"] in emails and r["status"] != "unsubscribed":
                r.update(status="unsubscribed", unsubscribed_at=_now(), confirm_token_hash=None)
                n += 1
        return n

    def _audit(self, user_id, action, issue_id, metadata):
        self.audit.append({"user_id": user_id, "action": action, "resource_type": "newsletter_issue",
                           "resource_id": issue_id, "metadata": metadata})

    def create_issue(self, draft, created_by, metadata):
        iid = str(uuid.uuid4())
        row = {"id": iid, "status": "draft", "subject": draft["subject"], "preview": draft["preview"],
               "body_json": draft, "created_by": created_by, "created_at": _now(), "sent_at": None,
               "brevo_campaign_id": None, "approved_by": None, "approved_at": None, "send_claimed_at": None,
               "send_error": None}
        self.issues[iid] = row
        self._audit(None, "newsletter.draft_created", iid, {"author": created_by, **metadata})
        return dict(row)

    def list_issues(self, limit=50):
        return [dict(r) for r in sorted(self.issues.values(), key=lambda r: r["created_at"], reverse=True)][:limit]

    def get_issue(self, issue_id):
        row = self.issues.get(issue_id)
        return dict(row) if row else None

    def claim_issue(self, issue_id, actor):
        row = self.issues.get(issue_id)
        if row is None or row["status"] != "draft" or row["send_claimed_at"] is not None:
            return None
        row.update(send_claimed_at=_now(), approved_at=_now(), approved_by=actor["user_id"])
        self._audit(actor["user_id"], "newsletter.send_approved", issue_id, {"actor": actor["kind"], "subject": row["subject"]})
        return dict(row)

    def record_campaign(self, issue_id, campaign_id, actor, metadata):
        row = self.issues[issue_id]
        assert row["brevo_campaign_id"] is None and row["send_claimed_at"] is not None
        row["brevo_campaign_id"] = campaign_id
        self._audit(actor["user_id"], "newsletter.campaign_created", issue_id,
                    {"actor": actor["kind"], "brevo_campaign_id": campaign_id, **metadata})

    def mark_sent(self, issue_id, actor):
        row = self.issues[issue_id]
        row.update(status="sent", sent_at=_now())
        self._audit(actor["user_id"], "newsletter.sent", issue_id, {"actor": actor["kind"], "brevo_campaign_id": row["brevo_campaign_id"]})
        return dict(row)

    def record_failure(self, issue_id, actor, error):
        self.issues[issue_id]["send_error"] = error[:600]
        self._audit(actor["user_id"], "newsletter.send_failed", issue_id, {"actor": actor["kind"], "error": error[:600]})


class StubBrevo:
    """Records every call in order; `fail` names operations that raise; `contacts` is the Brevo list.
    `on_upsert(email)` runs before each upsert (tests use it to see the database at that moment)."""

    def __init__(self):
        self.calls = []
        self.contacts = {}  # email -> {"blocked": bool, "attributes": {...}}
        self.fail = set()
        self.campaigns = {}
        self.sent = []
        self.list_ids = []
        self.drop_attributes = False  # behave like an account without the CW_UNSUB_TOKEN attribute
        self.on_upsert = None

    def _maybe_fail(self, op):
        if op in self.fail:
            raise BrevoError(op, 503)

    async def upsert_list_contact(self, email, unsub_token):
        self.calls.append(("upsert", email))
        if self.on_upsert:
            self.on_upsert(email)
        self._maybe_fail("upsert")
        blocked = self.contacts.get(email, {}).get("blocked", False)
        self.contacts[email] = {"blocked": blocked,
                                "attributes": {} if self.drop_attributes else {"CW_UNSUB_TOKEN": unsub_token}}

    async def remove_from_list(self, emails):
        self.calls.append(("remove", tuple(emails)))
        self._maybe_fail("remove")
        for e in emails:
            self.contacts.pop(e, None)

    async def list_contacts(self):
        self.calls.append(("list", None))
        self._maybe_fail("list")
        return [{"email": e, "blocked": c["blocked"], "unsub": c["attributes"].get("CW_UNSUB_TOKEN", "")}
                for e, c in self.contacts.items()]

    async def create_campaign(self, *, name, subject, preview, html, sender):
        self.calls.append(("create_campaign", subject))
        self._maybe_fail("create_campaign")
        cid = str(1000 + len(self.campaigns))
        self.campaigns[cid] = {"name": name, "subject": subject, "preview": preview, "html": html, "sender": sender,
                               "recipients": sorted(e for e, c in self.contacts.items() if not c["blocked"])}
        return cid

    async def send_campaign_now(self, campaign_id):
        self.calls.append(("send_now", campaign_id))
        self._maybe_fail("send_now")
        self.sent.append(campaign_id)

    def ops(self):
        return [c[0] for c in self.calls]


def past(hours=1):
    return _now() - timedelta(hours=hours)
