"""
Mailer / report email unit tests (no network, no Brevo dispatch).
"""
from backend.app.services.mailer import generate_executive_report_html
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
        ]
    )
    assert 0 <= scoring["score"] <= 100
    html = generate_executive_report_html(
        score=scoring["score"],
        grade=scoring["grade"],
        posture_label=scoring["posture_label"],
    )
    assert f"{scoring['score']}" in html
    assert "/1000" not in html
