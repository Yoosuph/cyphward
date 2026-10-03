"""
Mailer / report email unit tests (no network, no Brevo dispatch).
"""
import asyncio

from backend.app.core.config import DEFAULT_EMAIL_SENDER_KIND, EMAIL_SENDERS
from backend.app.services import mailer
from backend.app.services.mailer import email_sender, generate_executive_report_html, send_email_async
from backend.app.risk.engine import compute_risk_score


def test_executive_report_html_score_scale_100():
    html = generate_executive_report_html(
        org_name="Acme Africa",
        domain="acmetraders.ng",
        score=74,
        grade="B",
        posture_label="Good",
        assets_count=6,
        critical_count=1,
        high_count=2,
        medium_count=2,
    )
    assert len(html) > 1000
    assert "/100" in html
    assert "/1000" not in html
    assert "74" in html
    assert "HOW TO IMPROVE YOUR SCORE" in html
    assert "SECURITY SCORE" in html


def test_report_defaults_use_100_scale():
    html = generate_executive_report_html()
    assert "/100" in html
    assert "/1000" not in html
    assert "76" in html  # default score


def test_report_uses_live_engine_scores():
    scoring = compute_risk_score(
        [
            {"title": "DMARC Missing", "severity": "critical", "category": "DNS & Email Security", "status": "open"},
            {"title": "HSTS Missing", "severity": "high", "category": "HTTP Headers", "status": "open"},
        ],
        assessment={
            "scan_id": "scan-1", "status": "completed",
            "completed_at": "2026-10-01T00:00:00", "model": "cyphward-risk-v1",
        },
    )
    assert 0 <= scoring["score"] <= 100
    html = generate_executive_report_html(
        score=scoring["score"],
        grade=scoring["grade"],
        posture_label=scoring["posture_label"],
    )
    assert f"{scoring['score']}" in html
    assert "/1000" not in html


def test_report_html_not_assessed_without_score():
    """A report with no completed scan must say so — never render None or a fake score."""
    scoring = compute_risk_score([])
    html = generate_executive_report_html(
        org_name="Acme Africa",
        domain="acmetraders.ng",
        score=scoring["score"],
        grade=scoring["grade"] or "",
        posture_label=scoring["posture_label"],
    )
    assert scoring["score"] is None
    assert "Not assessed" in html
    assert "not assessed" in html
    assert "None" not in html


# --- Central sender map (EMAIL_SENDERS) -------------------------------------

def test_sender_map_covers_all_verified_identities():
    assert set(EMAIL_SENDERS) == {
        "system", "alerts", "reports", "support", "security", "general",
    }
    assert EMAIL_SENDERS["system"] == ("Cyphward", "no-reply@cyphward.com")
    assert EMAIL_SENDERS["alerts"] == ("Cyphward Alerts", "alerts@cyphward.com")
    assert EMAIL_SENDERS["reports"] == ("Cyphward Reports", "reports@cyphward.com")
    assert EMAIL_SENDERS["support"] == ("Cyphward Support", "support@cyphward.com")
    assert EMAIL_SENDERS["security"] == ("Cyphward Security", "security@cyphward.com")
    assert EMAIL_SENDERS["general"] == ("Cyphward", "info@cyphward.com")
    assert all("@" in addr for _, addr in EMAIL_SENDERS.values())


def test_default_sender_kind_is_system():
    assert DEFAULT_EMAIL_SENDER_KIND == "system"
    assert email_sender(DEFAULT_EMAIL_SENDER_KIND) == EMAIL_SENDERS["system"]


def test_email_sender_unknown_kind_falls_back_to_system(caplog):
    with caplog.at_level("WARNING", logger="cyphward.mailer"):
        assert email_sender("typo-kind") == EMAIL_SENDERS["system"]
    assert any("typo-kind" in r.message for r in caplog.records)


class _FakeBrevoResponse:
    status_code = 201
    text = "ok"

    def json(self):
        return {"messageId": "test-message-id"}


class _FakeAsyncClient:
    captured: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.captured = json or {}
        return _FakeBrevoResponse()


def test_send_email_async_uses_kind_sender(monkeypatch):
    monkeypatch.setattr(mailer, "BREVO_API_KEY", "test-key")
    monkeypatch.setattr(mailer.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.captured = {}

    result = asyncio.run(
        send_email_async(
            "dest@example.com",
            "Your Cyphward security report is ready",
            "<p>report</p>",
            kind="reports",
        )
    )

    assert result["success"] is True
    assert result["method"] == "brevo_api"
    assert _FakeAsyncClient.captured["sender"] == {
        "name": "Cyphward Reports",
        "email": "reports@cyphward.com",
    }


def test_send_email_async_defaults_to_system_sender(monkeypatch):
    monkeypatch.setattr(mailer, "BREVO_API_KEY", "test-key")
    monkeypatch.setattr(mailer.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.captured = {}

    result = asyncio.run(send_email_async("dest@example.com", "Verify", "<p>x</p>"))

    assert result["success"] is True
    assert _FakeAsyncClient.captured["sender"] == {
        "name": "Cyphward",
        "email": "no-reply@cyphward.com",
    }
