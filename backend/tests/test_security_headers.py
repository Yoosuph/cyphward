"""API security headers and third-party hosts' response checks."""
import asyncio

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.core.security_headers import API_CSP, DOCS_CSP, SecurityHeadersMiddleware
from backend.app.main import app
from backend.app.scanner import ip_guard
from backend.app.scanner.security_checks import run_security_checks
from backend.app.workflows.inngest_workflow import checker_view_for_third_party


def test_api_responses_carry_security_headers():
    r = TestClient(app).get("/health")
    assert r.headers["strict-transport-security"] == "max-age=63072000; includeSubDomains"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"] == API_CSP


def test_docs_pages_get_a_csp_that_lets_them_load():
    client = TestClient(app)
    for path in ("/docs", "/api/v1/docs", "/redoc"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-security-policy"] == DOCS_CSP, path


def test_cors_preflight_still_works_with_headers():
    r = TestClient(app).options("/api/v1/compliance/overview", headers={
        "Origin": "https://app.cyphward.com", "Access-Control-Request-Method": "GET"})
    assert r.status_code == 200 and r.headers.get("access-control-allow-origin") == "https://app.cyphward.com"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_a_header_set_by_the_route_is_not_overwritten():
    mini = FastAPI()
    mini.add_middleware(SecurityHeadersMiddleware)

    @mini.get("/x")
    def x():
        return JSONResponse({}, headers={"X-Frame-Options": "SAMEORIGIN"})

    r = TestClient(mini).get("/x")
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers.get_list("x-frame-options") == ["SAMEORIGIN"]


# ── Third-party hosts (e.g. a mail provider's click-tracking host) ─────────
BREVO_PROBE = {  # what the HTTP stage stored for r.info.cyphward.com on 16 Oct
    "hostname": "r.info.example.test", "http_status": 301, "error": "redirect blocked: img.mailin.fr out of scope",
    "third_party_redirect": "img.mailin.fr", "security_headers": {"x-content-type-options": "nosniff"},
    "raw_headers": {"location": "https://img.mailin.fr/", "server": "envoy/1.2", "x-content-type-options": "nosniff"},
    "server_header": "envoy/1.2", "powered_by_header": None,
    "tls_info": {"issuer": "Provider CA", "valid_to": "2026-10-20T00:00:00Z", "days_remaining": 4, "valid": True},
}


def _titles(findings):
    return sorted(f["title"] for f in findings)


def test_the_providers_response_raises_header_findings_without_the_fix(monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda host: None)  # no network
    found = _titles(asyncio.run(run_security_checks("r.info.example.test", {}, BREVO_PROBE, is_apex=False)))
    assert "Strict-Transport-Security (HSTS) Header Missing" in found  # the false finding seen in production


def test_third_party_view_keeps_only_the_certificate(monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda host: None)
    view = checker_view_for_third_party(BREVO_PROBE)
    found = _titles(asyncio.run(run_security_checks("r.info.example.test", {}, view, is_apex=False)))
    # Header, banner and robots checks see no response; the certificate on the customer's hostname still counts.
    assert found == ["SSL/TLS Certificate Expiring Soon"]
    assert checker_view_for_third_party(None)["http_status"] is None
