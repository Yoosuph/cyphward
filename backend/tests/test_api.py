"""
Cyphward API + unit test suite.

Covers:
    - Real auth chain: JWT -> profile upsert -> membership resolution (via fake DB)
    - Cross-tenant denial (X-Organization-Id verified server-side; org-scoped queries)
    - RBAC: member vs admin vs owner (require_admin / require_owner)
    - Endpoint shapes: overview, findings, scans, organizations, health
    - Pure units: risk engine, finding normalizer, AI privacy filter, role helpers

Run: npm test  (or: uv run --with pytest ... python -m pytest backend/tests -q)
"""
import pytest
from fastapi import HTTPException

from backend.app.core.auth import membership_role, require_role
from backend.app.risk.engine import compute_risk_score
from backend.app.scanner.normalizer import normalize_findings
from backend.app.ai.privacy import sanitize_for_ai
from backend.app.services.notifications import slugify

from conftest import (
    ORG_A, ORG_B, ALICE, BOB, ADMI, CAROL, DAVE,
    FINDING_A1, FINDING_A3, FINDING_B1, SCAN_A1,
    get_current_user, get_current_org,
)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def test_missing_token_returns_401(client):
    resp = client.get("/api/v1/organizations/current")
    assert resp.status_code == 401
    assert "token" in resp.json()["detail"].lower()


def test_invalid_token_returns_401(client):
    import jwt as pyjwt

    # Malformed token
    resp = client.get(
        "/api/v1/organizations/current",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401

    # Well-formed token signed with the wrong secret
    bogus = pyjwt.encode(
        {"sub": "someone", "exp": 9999999999},
        "wrong-secret-key-long-enough-for-hs256-1234",
        algorithm="HS256",
    )
    resp = client.get(
        "/api/v1/organizations/current",
        headers={"Authorization": f"Bearer {bogus}"},
    )
    assert resp.status_code == 401


def test_single_membership_resolves_without_header(client, auth_headers):
    resp = client.get("/api/v1/organizations/current", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == ORG_A
    assert data["role"] == "owner"


def test_multiple_memberships_require_header(client, auth_headers):
    resp = client.get("/api/v1/organizations/current", headers=auth_headers(DAVE))
    assert resp.status_code == 400
    assert "X-Organization-Id" in resp.json()["detail"]


def test_header_selects_membership(client, auth_headers):
    resp = client.get(
        "/api/v1/organizations/current",
        headers=auth_headers(DAVE, org=ORG_B),
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == ORG_B
    assert resp.json()["role"] == "owner"


def test_cross_org_header_denied(client, auth_headers):
    """Alice is only in ORG_A — requesting ORG_B must fail closed (403)."""
    resp = client.get(
        "/api/v1/organizations/current",
        headers=auth_headers(ALICE, org=ORG_B),
    )
    assert resp.status_code == 403
    assert "member" in resp.json()["detail"].lower()


def test_org_b_member_cannot_select_org_a(client, auth_headers):
    resp = client.get(
        "/api/v1/organizations/current",
        headers=auth_headers(CAROL, org=ORG_A),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_member_cannot_update_finding_status(client, auth_headers):
    resp = client.patch(
        f"/api/v1/findings/{FINDING_A1}/status",
        json={"status": "resolved"},
        headers=auth_headers(BOB),
    )
    assert resp.status_code == 403
    assert "role" in resp.json()["detail"].lower()


def test_member_cannot_update_org(client, auth_headers):
    resp = client.patch(
        "/api/v1/organizations/current",
        json={"name": "Hacked Inc"},
        headers=auth_headers(BOB),
    )
    assert resp.status_code == 403


def test_admin_can_update_finding_status(client, auth_headers, store):
    resp = client.patch(
        f"/api/v1/findings/{FINDING_A1}/status",
        json={"status": "in_progress"},
        headers=auth_headers(ADMI),
    )
    assert resp.status_code == 200
    assert resp.json()["finding"]["status"] == "in_progress"
    stored = next(f for f in store.findings if f["id"] == FINDING_A1)
    assert stored["status"] == "in_progress"


def test_owner_can_update_org(client, auth_headers, store):
    resp = client.patch(
        "/api/v1/organizations/current",
        json={"name": "Acme Traders Ltd"},
        headers=auth_headers(ALICE),
    )
    assert resp.status_code == 200
    assert store.organizations[ORG_A]["name"] == "Acme Traders Ltd"


def test_resolving_finding_sets_resolved_at(client, auth_headers, store):
    resp = client.patch(
        f"/api/v1/findings/{FINDING_A1}/status",
        json={"status": "resolved"},
        headers=auth_headers(ALICE),
    )
    assert resp.status_code == 200
    stored = next(f for f in store.findings if f["id"] == FINDING_A1)
    assert stored["status"] == "resolved"
    assert stored["resolved_at"] is not None


def test_invalid_finding_status_rejected(client, auth_headers):
    resp = client.patch(
        f"/api/v1/findings/{FINDING_A1}/status",
        json={"status": "suppressed"},
        headers=auth_headers(ADMI),
    )
    assert resp.status_code == 400
    assert "suppressed" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Cross-tenant data scoping
# ---------------------------------------------------------------------------
def test_findings_list_scoped_to_caller_org(client, auth_headers):
    resp = client.get("/api/v1/findings", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert all(f["org_id"] == ORG_A for f in data["findings"])
    assert FINDING_B1 not in [f["id"] for f in data["findings"]]

    resp_b = client.get("/api/v1/findings", headers=auth_headers(CAROL))
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert data_b["total"] == 1
    assert data_b["findings"][0]["id"] == FINDING_B1


def test_finding_detail_cross_tenant_404(client, auth_headers):
    resp = client.get(f"/api/v1/findings/{FINDING_B1}", headers=auth_headers(ALICE))
    assert resp.status_code == 404


def test_finding_detail_returns_evidence(client, auth_headers):
    resp = client.get(f"/api/v1/findings/{FINDING_A1}", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == FINDING_A1
    assert len(data["evidence_records"]) == 1


def test_scans_list_scoped_to_org(client, auth_headers):
    resp = client.get("/api/v1/scans", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    scans = resp.json()
    assert isinstance(scans, list)
    assert len(scans) == 1
    assert scans[0]["id"] == SCAN_A1
    assert scans[0]["org_id"] == ORG_A

    resp_b = client.get("/api/v1/scans", headers=auth_headers(CAROL))
    assert resp_b.status_code == 200
    assert resp_b.json() == []


def test_list_my_organizations_only_own_memberships(client, auth_headers):
    resp = client.get("/api/v1/organizations", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    orgs = resp.json()
    assert [o["id"] for o in orgs] == [ORG_A]

    resp_dave = client.get("/api/v1/organizations", headers=auth_headers(DAVE))
    assert resp_dave.status_code == 200
    assert sorted(o["id"] for o in resp_dave.json()) == sorted([ORG_A, ORG_B])


# ---------------------------------------------------------------------------
# Overview / health
# ---------------------------------------------------------------------------
def test_overview_shape(client, auth_headers):
    resp = client.get("/api/v1/overview", headers=auth_headers(ALICE))
    assert resp.status_code == 200
    data = resp.json()

    assert 0 <= data["score"] <= 100
    assert data["max_score"] == 100
    assert data["assessed"] is True
    assert data["assessment"]["scan_id"] == SCAN_A1
    assert data["assessment"]["status"] == "completed"
    assert data["organization"]["id"] == ORG_A
    assert data["organization"]["primary_domain"] == "acme.test"
    assert data["organization"]["verified_domains_count"] == 1
    assert len(data["subscores"]) == 4
    assert data["counts"]["total_findings"] == 2  # resolved finding excluded
    assert data["counts"]["critical"] == 1
    assert data["counts"]["high"] == 1
    assert data["counts"]["total_assets"] == 2
    assert data["trend"] is None  # legacy scores cannot be compared to v2
    assert len(data["recent_scans"]) == 1


def test_overview_not_assessed_without_completed_scan(client, auth_headers):
    """No completed scan -> 'Not assessed', never an empty-findings 100."""
    resp = client.get("/api/v1/overview", headers=auth_headers(DAVE, org=ORG_B))
    assert resp.status_code == 200
    data = resp.json()

    assert data["assessed"] is False
    assert data["score"] is None
    assert data["grade"] is None
    assert data["posture_label"] == "Not assessed"
    assert data["subscores"] == []
    assert data["factors"] == []
    assert data["assessment"] is None
    # Factual counts still report; only the score is withheld.
    assert data["counts"]["total_findings"] >= 1


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


# ---------------------------------------------------------------------------
# Dependency overrides
# ---------------------------------------------------------------------------
def test_dependency_override_get_current_org(client, override_deps):
    """FastAPI dependency_overrides can inject tenant context directly."""
    override_deps[get_current_org] = lambda: {
        "id": ORG_B,
        "name": "Other Holdings",
        "slug": "other-holdings",
        "cac_rc": None,
        "sector": "banking",
        "plan": "enterprise",
        "created_at": "2026-01-02T00:00:00",
        "membership_role": "owner",
        "current_user_id": ALICE,
    }
    resp = client.get("/api/v1/organizations/current")  # no token needed
    assert resp.status_code == 200
    assert resp.json()["id"] == ORG_B


def test_dependency_override_get_current_user(client, override_deps, store):
    override_deps[get_current_user] = lambda: {"id": ALICE, "email": "alice@acme.test"}
    resp = client.get("/api/v1/organizations")  # org resolution still runs via fake DB
    assert resp.status_code == 200
    assert [o["id"] for o in resp.json()] == [ORG_A]


# ---------------------------------------------------------------------------
# Unit: risk scoring engine
# ---------------------------------------------------------------------------
ASSESSMENT = {
    "scan_id": SCAN_A1,
    "status": "completed",
    "completed_at": "2026-03-01T00:10:00",
    "model": "cyphward-risk-v2",
}


def test_risk_engine_not_assessed_without_completed_scan():
    res = compute_risk_score([])
    assert res["assessed"] is False
    assert res["score"] is None
    assert res["grade"] is None
    assert res["posture_label"] == "Not assessed"
    assert res["subscores"] == []
    assert res["factors"] == []
    assert res["assessment"] is None
    assert res["model"] == "cyphward-risk-v2"


def test_risk_engine_counts_but_never_scores_without_assessment():
    findings = [
        {"title": "DMARC Missing", "severity": "critical", "category": "DNS & Email Security", "status": "open"},
    ]
    res = compute_risk_score(findings)
    # Factual finding counts survive; the score does not.
    assert res["counts"]["critical"] == 1
    assert res["score"] is None
    assert res["grade"] is None


def test_risk_engine_empty_findings_with_assessment_scores_100():
    res = compute_risk_score([], assessment=ASSESSMENT)
    assert res["assessed"] is True
    assert res["score"] == 100
    assert res["grade"] == "A"
    assert res["assessment"] == ASSESSMENT
    # Positive claims carry the assessment date and scan they derive from.
    positive = [f for f in res["factors"] if f["type"] == "positive"]
    assert positive
    for factor in positive:
        assert factor["assessed_at"] == ASSESSMENT["completed_at"]
        assert factor["scan_id"] == ASSESSMENT["scan_id"]


def test_risk_engine_reduces_for_open_findings():
    findings = [
        {"title": "DMARC Missing", "severity": "critical", "category": "DNS & Email Security", "status": "open"},
        {"title": "HSTS Missing", "severity": "high", "category": "HTTP Headers", "status": "open"},
    ]
    res = compute_risk_score(findings, assessment=ASSESSMENT)
    assert res["score"] < 100
    assert res["counts"]["critical"] == 1
    assert res["counts"]["high"] == 1
    negative = [f for f in res["factors"] if f["type"] == "negative"]
    assert negative
    # Findings without provenance must not inherit another scan's identity.
    assert all("scan_id" not in f for f in negative)


def test_risk_engine_skips_resolved_findings():
    resolved = [
        {"title": "Old Issue", "severity": "critical", "category": "HTTP Headers", "status": "resolved"},
    ]
    res = compute_risk_score(resolved, assessment=ASSESSMENT)
    assert res["score"] == 100
    assert res["counts"]["critical"] == 0


# ---------------------------------------------------------------------------
# Unit: normalizer / privacy / helpers
# ---------------------------------------------------------------------------
def test_normalizer_deduplicates_by_asset_and_title():
    raw = [
        {"title": "HSTS Missing", "severity": "high", "category": "HTTP Headers", "evidence": {"a": 1}},
        {"title": "HSTS Missing", "severity": "high", "category": "HTTP Headers", "evidence": {"a": 2}},
        {"title": "X-Frame-Options Missing", "severity": "medium", "category": "HTTP Headers", "evidence": {}},
    ]
    out = normalize_findings(raw, asset_id="asset-1", org_id="org-1", scan_id="scan-1")
    assert len(out) == 2
    titles = [f["title"] for f in out]
    assert titles.count("HSTS Missing") == 1
    assert all(f["status"] == "open" for f in out)


def test_normalizer_coerces_unknown_severity():
    out = normalize_findings(
        [{"title": "X", "severity": "bogus"}],
        asset_id="a", org_id="o", scan_id="s",
    )
    assert out[0]["severity"] == "medium"


def test_privacy_sanitizer_redacts_sensitive_fields():
    dirty = {
        "url": "https://102.134.88.12/admin",
        "header": "Authorization: Bearer secret_jwt_token_12345678901234",
        "api_key": "cyph_live_sensitive_internal_token_here",
        "password": "hunter2hunter2hunter2",
    }
    cleaned = sanitize_for_ai(dirty)
    assert cleaned["api_key"] == "[REDACTED_BY_CYPHWARD_PRIVACY_GUARD]"
    assert cleaned["password"] == "[REDACTED_BY_CYPHWARD_PRIVACY_GUARD]"
    assert "secret_jwt_token" not in cleaned["header"]
    assert "102.134.88.12" not in cleaned["url"]


def test_membership_role_defaults_to_member():
    assert membership_role({}) == "member"
    assert membership_role({"membership_role": "Owner"}) == "owner"


def test_require_role_gates():
    dep = require_role("owner", "admin")
    with pytest.raises(HTTPException) as exc:
        dep(org={"membership_role": "member"})
    assert exc.value.status_code == 403
    assert dep(org={"membership_role": "admin"})["membership_role"] == "admin"
    with pytest.raises(HTTPException):
        require_role("owner")(org={"membership_role": "admin"})


def test_slugify():
    assert slugify("Acme Traders Ltd!") == "acme-traders-ltd"
    assert slugify("") == "org"
