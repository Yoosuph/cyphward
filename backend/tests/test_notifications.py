"""Notifications phase 1 without a database: the reviewed wording, the kind table and the helper's failure rules.

The rules that need SQL (tenancy, dedupe, grouping, the cap, preferences, email, triggers, grants) run against the
migrated PostgreSQL database in test_notifications_postgres.py.
"""
import asyncio
from contextlib import contextmanager

import pytest

from backend.app.core import database
from backend.app.core.execution_fence import ClaimLost
from backend.app.core.scan_failures import CATEGORIES as FAILURE_SENTENCES
from backend.app.services import mailer
from backend.app.services import notification_messages as msg
from backend.app.services import notifications
from test_ux_copy_claims import BANNED as UX_BANNED

ORIGINAL_SEND = notifications._send  # captured before the conftest stub replaces it

# The extended list: the UX list plus every phrase the notifications brief names, and the stricter stem.
BANNED = tuple(sorted(set(UX_BANNED) | {
    "compliant", "certified", "certification", "certif", "satisfies", "adequate", "guarantee", "passes audit",
    "compliance score", "meets the requirement"}))
RAW = "Traceback ConnectError [Errno 111] 10.9.8.7 RAW-WORKER-TEXT"
SAMPLE = {"domain": "acme.ng", "hostname": "shop.acme.ng", "score": 72, "grade": "B", "new": 2, "resolved": 1,
          "not_evaluated": 1, "code": "timeout", "email": "ada@acme.ng", "name": "Ada Bello", "date": "3 November 2026",
          "org_name": "Acme Traders", "item": "Breach response plan", "reopened": True, "recheck": True}


def _all_copy():
    for kind in msg.KINDS:
        for count in (1, 3):
            for audience in ("customer", "owner"):
                for params in (SAMPLE, {}):
                    yield kind, msg.render(kind, params, count, audience)


def test_no_template_uses_claim_wording():
    texts = [t for _, pair in _all_copy() for t in pair]
    texts += list(msg.CATEGORIES.values()) + list(msg.CATEGORY_HINTS.values()) + list(msg.LEGACY_REVIEWED_BODY.values())
    texts += [msg.EMAIL_FOOTER.format(label=label.lower()) for label in msg.CATEGORIES.values()]
    texts += [mailer.generate_notification_email_html("Ada", "T", "B", "https://a/x", "https://a/p", "F"),
              mailer.generate_notification_email_text("Ada", "T", "B", "https://a/x", "https://a/p", "F")]
    hits = [(phrase, text) for text in texts for phrase in BANNED if phrase in text.lower()]
    assert hits == []


def test_every_template_renders_plain_text_within_limits_for_every_count():
    for kind, (title, body) in _all_copy():
        assert title and body, kind
        assert len(title) <= 200 and len(body) <= 600, kind
        assert "None" not in title + body and "{" not in title + body, (kind, title, body)


def test_the_kind_table_is_consistent():
    for name, kind in msg.KINDS.items():
        assert kind.severity in msg.SEVERITIES, name
        assert kind.category in msg.CATEGORIES, name
        assert kind.recipients in ("all", "admins", "owners"), name
        assert kind.link.startswith("/") and not kind.link.startswith("//"), name
    assert set(msg.CATEGORIES) == set(msg.CATEGORY_HINTS)


def test_every_critical_kind_reaches_the_owner_console():
    """So a customer's mute can never hide a critical event from the owner console."""
    critical = [name for name, kind in msg.KINDS.items() if kind.severity == "critical"]
    assert critical and all(msg.KINDS[name].owner for name in critical)


def test_a_failed_scan_is_described_only_by_the_reviewed_failure_sentences():
    for code, sentence in FAILURE_SENTENCES.items():
        assert msg.render("scan_failed", {"code": code})[1] == sentence
    assert msg.render("scan_failed", {"code": RAW})[1] == FAILURE_SENTENCES["internal"]
    assert msg.render("scan_failed", {})[1] == FAILURE_SENTENCES["internal"]


def test_templates_ignore_values_they_do_not_name():
    for kind in msg.KINDS:
        title, body = msg.render(kind, {**SAMPLE, "description": RAW, "error": RAW, "remediation": RAW})
        assert RAW not in title + body, kind


def test_the_owner_console_title_names_the_organisation():
    assert msg.render("scan_failed", SAMPLE, 1, "owner")[0] == "Acme Traders: Scan did not finish for acme.ng"
    assert msg.render("scan_failed", SAMPLE, 1, "customer")[0] == "Scan did not finish for acme.ng"


def test_legacy_rows_get_a_category_a_phase_1_severity_and_a_reviewed_body():
    row = {"id": "x", "type": "critical_finding", "title": "Critical finding: X", "body": RAW, "severity": "high",
           "link": "https://evil.example", "shared": True, "group_count": 1, "read_at": None, "created_at": None}
    out = notifications.public_row(row)
    assert out["body"] == msg.LEGACY_REVIEWED_BODY["critical_finding"] and out["severity"] == "warning"
    assert out["category"] == "findings" and out["link"] is None and RAW not in str(out)
    assert set(out) == {"id", "kind", "type", "category", "severity", "title", "body", "link", "count", "read_at",
                        "created_at"}


def test_the_email_escapes_its_values_and_links_to_the_preferences_page():
    html = mailer.generate_notification_email_html("<b>Ada</b>", "<script>x</script>", "a & b", "https://a/o?x=1&y=2",
                                                   notifications.preferences_url("findings"), "Footer")
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;Ada" in html
    assert "settings?tab=notifications&amp;category=findings" in html


def test_the_email_goes_from_the_info_sender_with_a_list_unsubscribe_header(monkeypatch):
    seen = {}

    async def capture(to, subject, html, text=None, name=None, kind="system", **kwargs):
        seen.update(to=to, kind=kind, headers=kwargs.get("mail_headers"))
        return {"success": True}

    monkeypatch.setattr(mailer, "send_email_async", capture)
    url = notifications.preferences_url("organisation")
    asyncio.run(ORIGINAL_SEND("ada@acme.ng", "s", "<p>h</p>", "t", "Ada", url))
    assert seen["kind"] == "general" and mailer.email_sender("general")[1] == "info@cyphward.com"
    assert seen["headers"] == {"List-Unsubscribe": f"<{url}>"}


def test_emit_never_fails_its_caller_except_for_a_lost_claim(monkeypatch):
    @contextmanager
    def broken():
        raise RuntimeError("database down")
        yield  # pragma: no cover

    monkeypatch.setattr(database, "get_db", broken)
    assert notifications.emit("scan_completed", "org", key="k", params={}) == 0

    @contextmanager
    def lost():
        raise ClaimLost("claim gone")
        yield  # pragma: no cover

    monkeypatch.setattr(database, "get_db", lost)
    with pytest.raises(ClaimLost):
        notifications.emit("scan_completed", "org", key="k")
    assert notifications.emit("no_such_kind", "org", key="k") == 0
    assert notifications.emit("scan_completed", "org", key="") == 0


def test_only_critical_and_high_findings_are_notified():
    assert set(msg.FINDING_KIND_BY_SEVERITY) == {"critical", "high"}
    assert notifications.emit_finding("org", "f", "medium", "a") == 0
    assert notifications.emit_finding("org", "f", None, "a") == 0


def test_delivery_never_raises_when_the_outbox_cannot_be_read(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(database, "execute_query", boom)
    assert asyncio.run(notifications.deliver_pending_emails()) == {"sent": 0, "failed": 0, "skipped": 0,
                                                                   "scan_not_completed": 0}


def test_scan_completion_in_the_pipeline_notifies_every_member_with_the_not_evaluated_count(store, monkeypatch):
    """The in-memory store runs the real finalize code path (test_baseline_coverage builds the same scan)."""
    from test_baseline_coverage import _finalize, _obs
    from conftest import ORG_A

    _finalize(store, monkeypatch, _obs(), sec_ok=False)
    done = [n for n in store.notifications if n.get("type") == "scan_completed"]
    members = {str(m["user_id"]) for m in store.memberships if str(m["org_id"]) == ORG_A}
    assert {str(n["user_id"]) for n in done} == members and len(done) == len(members)
    assert all("not evaluated" in n["body"] and n["severity"] == "info" for n in done)


def _recheck(client, auth_headers, store, monkeypatch, still_there):
    from test_remediation_verify import _mock_probes, _seed_task
    from conftest import ALICE, FINDING_A1

    _seed_task(store, FINDING_A1)
    _mock_probes(monkeypatch)

    async def checks(hostname, dns_data, http_data, is_apex=True):
        return [{"title": "HSTS Missing"}] if still_there else []

    monkeypatch.setattr("backend.app.api.remediation.run_security_checks", checks)
    first = client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE))
    assert first.status_code == 200
    if not still_there:  # a verified task cannot be rechecked again, so its notice cannot repeat
        assert client.post("/api/v1/remediation/task-1/verify", headers=auth_headers(ALICE)).status_code >= 400
    return first.json()["result"]


def _org_a_members_but(store, who):
    from conftest import ORG_A
    return {str(m["user_id"]) for m in store.memberships if str(m["org_id"]) == ORG_A} - {who}


def test_trigger_recheck_still_present(client, auth_headers, store, monkeypatch):
    from conftest import ALICE
    assert _recheck(client, auth_headers, store, monkeypatch, still_there=True) == "reopened"
    rows = [n for n in store.notifications if n.get("type") == "finding_still_open"]
    assert {str(n["user_id"]) for n in rows} == _org_a_members_but(store, ALICE) and len(rows) == len({n["user_id"] for n in rows})
    assert all(n["dedupe_key"].startswith("finding_still_open:task-1:") for n in rows)
    assert not [n for n in store.notifications if n.get("type") == "finding_resolved"]


def test_trigger_recheck_resolved(client, auth_headers, store, monkeypatch):
    from conftest import ALICE
    assert _recheck(client, auth_headers, store, monkeypatch, still_there=False) == "verified"
    rows = [n for n in store.notifications if n.get("type") == "finding_resolved"]
    assert {str(n["user_id"]) for n in rows} == _org_a_members_but(store, ALICE) and len(rows) == len({n["user_id"] for n in rows})
    assert all(n["dedupe_key"].startswith("finding_resolved:recheck:task-1:") for n in rows)
    assert all("A recheck no longer sees the issue" in n["body"] for n in rows)
