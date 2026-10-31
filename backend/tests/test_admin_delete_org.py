"""Delete organisation (docs/admin-delete-org/README.md), without a database.

* The three new owner write routes need the owner session and the console Origin, and their bodies need the typed
  name (and, for purge, the word DELETE).
* With the in-memory store: a deleted organisation answers 404 to its customers on every read and every gated write,
  is gone from sign-in and from their organisation list, its owners cannot create a new organisation, and other
  organisations are unaffected.
* The guardrail helpers (core/org_guard.py): paid subscription, protected organisations and the override flag.
* Wording: every new server sentence is on the console's reviewed list, verbatim, and has no claim language.

The same rules against the real migrated database are in test_admin_delete_org_postgres.py.
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api import owner_actions
from backend.app.core import org_guard, suspension
from backend.app.core import owner as owner_mod
from backend.app.core.demo_org import DEMO_ORG_ID
from conftest import ALICE, BOB, ORG_A, ORG_B
from test_suspension_gate import BANNED, _fill, gated_routes

ROUTES = {"/api/v1/owner/organizations/{org_id}/delete", "/api/v1/owner/organizations/{org_id}/restore",
          "/api/v1/owner/organizations/{org_id}/purge"}


def _calls(route):
    seen, stack = set(), list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        seen.add(dep.call)
        stack.extend(dep.dependencies)
    return seen


# ── Routes and bodies ──────────────────────────────────────────────────────
def test_the_new_write_routes_need_the_owner_session_and_console_origin():
    routes = {r.path: r for r in owner_actions.router.routes if r.path in ROUTES}
    assert set(routes) == ROUTES
    for path, route in routes.items():
        assert route.methods == {"POST"}, path
        calls = _calls(route)
        assert owner_mod.require_owner_mutation in calls and owner_mod.require_owner in calls, path
        assert not any(suspension.is_gate(c) for c in calls), "owner actions never take a customer gate"


def test_every_step_needs_the_typed_name_and_purge_needs_the_word():
    for model in (owner_actions.OrgActionBody, owner_actions.PurgeBody):
        assert model.model_fields["confirm_name"].is_required()
        assert model.model_fields["reason"].is_required()
    assert owner_actions.PurgeBody.model_fields["confirm_word"].is_required()
    assert org_guard.PURGE_WORD == "DELETE"


def test_purge_runs_in_one_transaction_with_timeouts_and_queues_files():
    import inspect
    src = inspect.getsource(owner_actions.purge_organization)
    assert "SET LOCAL lock_timeout" in src and "SET LOCAL statement_timeout" in src
    assert "QUEUE_PURGE_SQL" in src and "_purge_evidence_files" not in src and "purge_organization(" not in \
        src.split("def work", 1)[1], "stored files are queued, never deleted inline"
    assert "_run(request, owner, \"owner.action.purge_org\"" in src


# ── Customers of a deleted organisation (in-memory store) ─────────────────
READS = ["/api/v1/organizations/current", "/api/v1/scans", "/api/v1/findings", "/api/v1/domains", "/api/v1/members",
         "/api/v1/settings", "/api/v1/overview", "/api/v1/reports", "/api/v1/billing/subscription"]


def test_a_deleted_organisation_answers_404_to_its_customers(client, store, auth_headers):
    headers = auth_headers(ALICE, org=ORG_A)
    assert all(client.get(p, headers=headers).status_code == 200 for p in READS)
    store.suspensions[ORG_A] = "deleted"
    for path in READS:
        resp = client.get(path, headers=headers)
        assert resp.status_code == 404, (path, resp.status_code, resp.text[:120])
        assert resp.json() == {"detail": "Organization not found."}
        slug = client.get(path, headers=auth_headers(ALICE, org=store.organizations[ORG_A]["slug"]))
        assert slug.status_code == 404, path
    boot = client.get("/api/v1/auth/bootstrap", headers=auth_headers(ALICE)).json()
    assert ORG_A not in [m["org"]["id"] for m in boot["memberships"]]
    assert ORG_A not in [o["id"] for o in client.get("/api/v1/organizations", headers=auth_headers(ALICE)).json()]


def test_every_gated_write_answers_404_and_never_the_suspension_text(client, store, auth_headers, override_deps):
    store.suspensions[ORG_A] = "deleted"
    headers = auth_headers(ALICE, org=ORG_A)
    leaks = []
    for method, path in gated_routes():
        if "/compliance/reviewer/" in path:
            continue  # reviewer routes resolve the organisation from the grant (core/compliance/reviewer.ACTIVE_SQL)
        resp = client.request(method, _fill(path), headers=headers, json={})
        if path == "/api/v1/organizations" and method == "POST":
            ok = resp.status_code in (403, 422) and suspension.SUSPENDED_MESSAGE not in resp.text
        else:
            ok = resp.status_code == 404 and suspension.SUSPENDED_MESSAGE not in resp.text
        if not ok:
            leaks.append((method, path, resp.status_code, resp.text[:120]))
    assert not leaks, leaks


def test_an_owner_of_a_deleted_organisation_cannot_create_another(client, store, auth_headers):
    store.suspensions[ORG_A] = "deleted"
    store.profiles[ALICE]["email_verified_at"] = datetime.now(timezone.utc)
    resp = client.post("/api/v1/organizations", headers=auth_headers(ALICE), json={"name": "Fresh Start Ltd"})
    assert resp.status_code == 403 and resp.json()["detail"] == suspension.DELETED_OWNER_MESSAGE


def test_other_organisations_are_unaffected(client, store, auth_headers):
    store.suspensions[ORG_A] = "deleted"
    member_of_b = [m["user_id"] for m in store.memberships if m["org_id"] == ORG_B]
    assert member_of_b
    headers = auth_headers(member_of_b[0], org=ORG_B)
    assert client.get("/api/v1/organizations/current", headers=headers).status_code == 200


def test_ensure_active_answers_404_for_deleted_and_403_for_suspended(store):
    store.suspensions[ORG_A] = "deleted"
    with pytest.raises(HTTPException) as deleted:
        suspension.ensure_active(ORG_A)
    assert deleted.value.status_code == 404
    store.suspensions[ORG_A] = "suspended"
    with pytest.raises(HTTPException) as suspended:
        suspension.ensure_active(ORG_A)
    assert suspended.value.status_code == 403
    store.suspensions[ORG_A] = "active"
    suspension.ensure_active(ORG_A)


def test_the_worker_claim_skips_a_deleted_organisation(store):
    from backend.app.core import scan_execution
    scan = next(s for s in store.scans if s["org_id"] == ORG_A)
    scan.update(status="queued", current_stage=None, execution_phase=None)
    for d in store.domains:
        if d["id"] == scan["domain_id"]:
            d["verification_status"] = "verified"
    store.suspensions[ORG_A] = "deleted"
    assert scan_execution.claim_recon("unit-worker", "worker", 60, scan_id=scan["id"]) is None


# ── Guardrails ─────────────────────────────────────────────────────────────
def test_paid_subscription_rule():
    now = datetime.now(timezone.utc)
    later, earlier = now + timedelta(days=5), now - timedelta(days=1)
    paid = org_guard.paid_subscription_active
    assert paid({"status": "active", "current_period_end": later, "cancel_at_period_end": False}) is True
    assert paid({"status": "active", "current_period_end": later.replace(tzinfo=None)}) is True
    assert paid({"status": "active", "current_period_end": later, "cancel_at_period_end": True}) is False
    assert paid({"status": "active", "current_period_end": earlier}) is False  # lapsed
    assert paid({"status": "trialing", "current_period_end": later}) is False
    assert paid({"status": "canceled", "current_period_end": later}) is False
    assert paid({"status": "past_due", "current_period_end": later}) is False
    assert paid(None) is False


def test_protected_organisations_and_the_override(monkeypatch):
    for key in (org_guard.OVERRIDE_ENV, org_guard.INNOVATECH_ENV, "DEMO_LOGIN_ORG_ID"):
        monkeypatch.delenv(key, raising=False)
    plain = {"id": str(uuid4()), "name": "Acme Traders Ltd"}
    assert org_guard.is_protected({"id": DEMO_ORG_ID, "name": "Fintech Org (SAMPLE DATA)"})
    assert not org_guard.is_protected(plain)
    for name in ("INNOVATECH Nigeria Limited", "InnovaTech", "Innova-Tech Ltd", "innova tech"):
        assert org_guard.is_protected({"id": str(uuid4()), "name": name}), name
    monkeypatch.setenv(org_guard.INNOVATECH_ENV, plain["id"].upper())
    assert org_guard.is_protected(plain)
    monkeypatch.setenv(org_guard.INNOVATECH_ENV, "not-a-uuid")
    assert not org_guard.is_protected(plain)
    monkeypatch.setenv("DEMO_LOGIN_ORG_ID", plain["id"])
    assert org_guard.is_protected(plain)
    assert org_guard.override_enabled() is False
    for value, on in (("true", True), ("TRUE", True), (" true ", True), ("1", False), ("yes", False), ("", False)):
        monkeypatch.setenv(org_guard.OVERRIDE_ENV, value)
        assert org_guard.override_enabled() is on, value


def test_the_guard_refuses_protected_without_the_override(monkeypatch):
    monkeypatch.delenv(org_guard.OVERRIDE_ENV, raising=False)
    with pytest.raises(HTTPException) as refused:
        owner_actions._guard_protected({"id": DEMO_ORG_ID, "name": "Demo"})
    assert refused.value.status_code == 409 and refused.value.detail == owner_actions.PROTECTED_REFUSED
    monkeypatch.setenv(org_guard.OVERRIDE_ENV, "true")
    assert owner_actions._guard_protected({"id": DEMO_ORG_ID, "name": "Demo"}) is True
    assert owner_actions._guard_protected({"id": str(uuid4()), "name": "Acme"}) is False


def test_retention_covers_every_record_type_named_in_the_rule():
    sql = " ".join(org_guard.RETENTION_SQL.split())
    for table in ("compliance_reviewer_grants", "evidence_packs", "assessment_snapshots", "compliance_documents",
                  "compliance_evidence_files", "compliance_practitioner_reviews", "compliance_clause_verifications",
                  "compliance_document_approvals", "compliance_incidents"):
        assert f"FROM {table}" in sql, table
    assert "make_interval(months => evidence_retention_months)" in sql
    assert org_guard.RETAINED_KINDS == ("reviewer_grants", "packs", "snapshots", "documents", "evidence_files",
                                        "incidents")
    # Breach incidents: a fixed six years from when the incident was opened (founder decision, 2026-10-31).
    assert org_guard.INCIDENT_RETENTION_YEARS == 6
    assert "GREATEST(i.detected_at, i.became_aware_at, i.created_at) + make_interval(years => %(incident_years)s)" in sql
    # Attestations are removed with the organisation, not held back.
    assert "compliance_attestations" not in sql


# ── Wording ────────────────────────────────────────────────────────────────
OWNER_API = Path(__file__).resolve().parents[2] / "frontend" / "src" / "owner" / "ownerApi.ts"


def test_every_new_server_sentence_is_reviewed_in_the_console_verbatim():
    reviewed = OWNER_API.read_text()
    for message in (*owner_actions.DELETE_ORG_MESSAGES, owner_actions.NAME_MISMATCH):
        literal = message.replace("'", "\\'")
        assert f"'{literal}'" in reviewed or f'"{message}"' in reviewed, message


def test_new_wording_has_no_claim_language_and_names_only_the_existing_contact():
    texts = [*owner_actions.DELETE_ORG_MESSAGES, suspension.DELETED_OWNER_MESSAGE]
    hits = [(p, t[:60]) for t in texts for p in BANNED if p in t.lower()]
    assert not hits, hits
    assert re.findall(r"[\w.]+@[\w.]+\w", suspension.DELETED_OWNER_MESSAGE) == ["info@cyphward.com"]
    for t in texts:
        assert "organization_suspensions" not in t and "deleted_at" not in t and "%" not in t
