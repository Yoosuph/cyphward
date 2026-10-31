"""Suspension enforcement for customers (admin phase 2, core/suspension.py), without a database.

1. Every POST/PUT/PATCH/DELETE route under /api/v1 either takes a suspension gate dependency or sits on the short
   allow-list below, each entry with its reason. A new write route that forgets the gate fails here.
2. With the in-memory store: a suspended organisation's writes are refused with 403 and the stable code on every
   gated route, its reads still work, and lifting the suspension restores writes.

The same rule against the real migrated database (scheduler, scan claims, owner actions) is in
test_admin_phase2_postgres.py.
"""
import re
from uuid import uuid4

from fastapi.routing import APIRoute

from backend.app.core import suspension
from backend.app.core.auth import READ_ONLY_POSTS
from backend.app.main import app
from conftest import ADMI, ALICE, BOB, ORG_A, ORG_B, CAROL, FINDING_A1, SCAN_A1, DOM_A1

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_ACCOUNT = "personal account and sign-in: acts on the person, not on an organisation"
_WORKER = "scanner or browser worker protocol: machine credentials and a claimed job, no organisation session"
_OWNER = "owner console: separate owner session; owner actions are never blocked by a suspension"
_PUBLIC = "public form or newsletter flow: no organisation"

# (method, path) -> reason. Reviewed; keep it short. Prefixes are deliberately not used.
ALLOWED = {
    **{("POST", f"/api/v1/auth/{p}"): _ACCOUNT for p in (
        "register", "login", "logout", "refresh", "forgot-password", "reset-password", "demo-login",
        "mfa/start", "mfa/send", "mfa/verify", "mfa/enroll", "mfa/disable/request", "mfa/disable/confirm",
        "totp/enroll/start", "totp/enroll/confirm", "totp/disable", "otp/send", "otp/verify", "welcome",
        "trusted-browsers/forget", "account/delete", "google/one-tap", "exchange")},
    # Protective changes stay open while suspended (founder decision, 2026-10-31).
    ("POST", "/api/v1/billing/subscription/cancel"): "cancelling only stops future cost; a customer can always stop paying",
    ("POST", "/api/v1/compliance/reviewer-grants/{grant_id}/revoke"): "revoking outside access only reduces it",
    ("DELETE", "/api/v1/members/invites/{invite_id}"): "withdrawing a pending invitation only removes access",
    ("PATCH", "/api/v1/members/{user_id}"):
        "the same route lowers and raises roles: the handler allows lowering and refuses a promotion with "
        "organization_suspended (test_member_role_changes_while_suspended)",
    ("POST", "/api/v1/members/invites/accept"):
        "the organisation comes from the invitation token, so the handler calls suspension.ensure_active on it "
        "(test_invite_accept_is_refused_for_a_suspended_organisation)",
    ("PATCH", "/api/v1/notifications/{notification_id}/read"): "the person's own read marker; no organisation record",
    ("POST", "/api/v1/notifications/read-all"): "the person's own read markers; no organisation record",
    ("PUT", "/api/v1/notifications/preferences/{category}"): "the person's own notification settings; no organisation record",
    **{("POST", path): "read-only AI answer (core.auth.READ_ONLY_POSTS): writes no customer record"
       for path in READ_ONLY_POSTS},
    **{("POST", f"/api/v1/scanner/{p}"): _WORKER for p in (
        "claim", "jobs/{scan_id}/progress", "jobs/{scan_id}/observations", "jobs/{scan_id}/complete",
        "jobs/{scan_id}/fail")},
    **{("POST", f"/api/v1/browser-worker/{p}"): _WORKER for p in (
        "claim", "jobs/{job_id}/heartbeat", "jobs/{job_id}/result", "jobs/{job_id}/fail")},
    **{("POST", f"/api/v1/owner/{p}"): _OWNER for p in (
        "session", "logout", "setup/authenticator", "setup/complete",
        "organizations/{org_id}/plan", "organizations/{org_id}/trial", "organizations/{org_id}/suspend",
        "organizations/{org_id}/unsuspend", "organizations/{org_id}/members/{user_id}/remove",
        "organizations/{org_id}/members/restore", "scans/{scan_id}/cancel", "users/{user_id}/sign-out",
        "notifications/read-all", "notifications/{notification_id}/read")},
    **{("POST", f"/api/v1/newsletter/{p}"): _PUBLIC for p in ("subscribe", "confirm", "unsubscribe")},
    ("POST", "/api/v1/newsletter/drafts"): "newsletter draft upload with the drafts key; no organisation",
    ("POST", "/api/v1/newsletter/drafts/{issue_id}/send"): "owner or newsletter staff send; no organisation",
    ("POST", "/api/v1/contact"): _PUBLIC,
}


def _walk(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):  # this FastAPI wraps every included router
            yield from _walk(route.original_router.routes)


def _gated(dependant) -> bool:
    return any(suspension.is_gate(d.call) or _gated(d) for d in dependant.dependencies)


def write_routes():
    out = {}
    for route in _walk(app.routes):
        if not route.path.startswith("/api/v1/"):
            continue
        for method in route.methods & WRITE_METHODS:
            out[(method, route.path)] = route
    return out


def gated_routes():
    return sorted(key for key, route in write_routes().items() if _gated(route.dependant))


# ── 1. Every write route is gated or reviewed ──────────────────────────────
def test_every_write_route_is_gated_or_on_the_reviewed_allow_list():
    routes = write_routes()
    assert len(routes) > 80, "the route walk found too few routes to mean anything"
    ungated = [key for key, route in routes.items() if not _gated(route.dependant) and key not in ALLOWED]
    assert not ungated, f"write routes with no suspension gate and no reviewed reason: {sorted(ungated)}"
    both = [key for key, route in routes.items() if _gated(route.dependant) and key in ALLOWED]
    assert not both, f"gated routes still on the allow-list (remove them): {sorted(both)}"
    stale = [key for key in ALLOWED if key not in routes]
    assert not stale, f"allow-list entries that match no route (remove them): {sorted(stale)}"


def test_the_named_write_paths_are_gated():
    gated = set(gated_routes())
    for key in [
        ("POST", "/api/v1/scans/launch"), ("POST", "/api/v1/scans/{scan_id}/cancel"),
        ("POST", "/api/v1/domains"), ("POST", "/api/v1/domains/{domain_id}/verify"),
        ("DELETE", "/api/v1/domains/{domain_id}"), ("POST", "/api/v1/domains/{domain_id}/hosts"),
        ("PATCH", "/api/v1/organizations/current"), ("POST", "/api/v1/settings/company"),
        ("POST", "/api/v1/organizations/close"),
        ("POST", "/api/v1/members/invite"), ("POST", "/api/v1/organizations"),
        ("POST", "/api/v1/billing/subscription"), ("POST", "/api/v1/billing/subscription/renew"),
        ("POST", "/api/v1/compliance/reviewer-grants"),
        ("POST", "/api/v1/compliance/attestations"), ("POST", "/api/v1/compliance/incidents"),
        ("PATCH", "/api/v1/compliance/incidents/{incident_id}"),
        ("POST", "/api/v1/compliance/documents/{kind}/generate"),
        ("POST", "/api/v1/compliance/documents/{document_id}/approve"),
        ("POST", "/api/v1/compliance/evidence-files"), ("DELETE", "/api/v1/compliance/evidence-files/{file_id}"),
        ("POST", "/api/v1/compliance/reviewer/requirements/{key}/review"),
        ("POST", "/api/v1/compliance/reviewer/requirements/{key}/clause-reference"),
        ("POST", "/api/v1/packs"), ("POST", "/api/v1/snapshots"), ("PUT", "/api/v1/snapshots/retention"),
        ("POST", "/api/v1/reports"), ("POST", "/api/v1/remediation/{task_id}/verify"),
    ]:
        assert key in gated, key


def test_every_gate_is_built_on_the_shared_dependency():
    """A role gate must check suspension through require_active_org, never on its own."""
    calls = set()

    def collect(dependant):
        for d in dependant.dependencies:
            calls.add(d.call)
            collect(d)

    for route in write_routes().values():
        collect(route.dependant)
    gates = {c for c in calls if suspension.is_gate(c)}
    assert suspension.require_active_org in gates
    from backend.app.api.compliance_reviewer import require_active_reviewer
    for gate in gates - {suspension.require_active_org, require_active_reviewer, suspension.refuse_suspended_owner}:
        assert gate.__name__ == "dependency" and gate.__qualname__.startswith("require_active_role"), gate


# ── 2. Behaviour (in-memory store) ─────────────────────────────────────────
def _fill(path: str) -> str:
    known = {"{scan_id}": SCAN_A1, "{domain_id}": DOM_A1, "{finding_id}": FINDING_A1, "{user_id}": BOB,
             "{kind}": "privacy_notice", "{key}": "ndpa.s24"}
    for placeholder, value in known.items():
        path = path.replace(placeholder, value)
    return re.sub(r"\{[^}]+\}", str(uuid4()), path)


def _refused(resp):
    body = resp.json()
    return (resp.status_code == 403 and isinstance(body.get("detail"), dict)
            and body["detail"].get("code") == suspension.SUSPENDED_CODE
            and body["detail"].get("message") in (suspension.SUSPENDED_MESSAGE, suspension.SUSPENDED_OWNER_MESSAGE))


def test_a_suspended_organisation_is_refused_on_every_gated_route(client, store, auth_headers, override_deps):
    store.suspensions[ORG_A] = "suspended"
    # The reviewer routes need a live grant; stand one in so the suspension gate is what answers.
    from backend.app.compliance import reviewer
    override_deps[reviewer.require_reviewer] = lambda: {"org": {"id": ORG_A}, "user": {"id": CAROL}}
    headers = auth_headers(ALICE, org=ORG_A)
    leaks = []
    for method, path in gated_routes():
        resp = client.request(method, _fill(path), headers=headers, json={})
        if not _refused(resp):
            leaks.append((method, path, resp.status_code, resp.text[:120]))
    assert not leaks, leaks
    assert len(gated_routes()) == 34


def test_the_refusal_names_no_internal_detail(client, store, auth_headers):
    store.suspensions[ORG_A] = "suspended"
    resp = client.post("/api/v1/scans/launch", headers=auth_headers(ALICE, org=ORG_A), json={})
    assert _refused(resp)
    assert "organization_suspensions" not in resp.text and "Traceback" not in resp.text


def test_reads_still_work_while_suspended(client, store, auth_headers):
    headers = auth_headers(ALICE, org=ORG_A)
    reads = ["/api/v1/organizations/current", "/api/v1/scans", f"/api/v1/scans/{SCAN_A1}", "/api/v1/findings",
             "/api/v1/domains", "/api/v1/members", "/api/v1/settings", "/api/v1/overview", "/api/v1/reports",
             "/api/v1/billing/subscription", "/api/v1/auth/bootstrap"]
    before = {path: client.get(path, headers=headers) for path in reads}
    assert all(r.status_code == 200 for r in before.values()), {p: r.status_code for p, r in before.items()}
    store.suspensions[ORG_A] = "suspended"
    during = {path: client.get(path, headers=headers) for path in reads}
    assert all(r.status_code == 200 for r in during.values()), {p: r.status_code for p, r in during.items()}
    assert during["/api/v1/organizations/current"].json()["suspended"] is True
    assert before["/api/v1/organizations/current"].json()["suspended"] is False
    boot = during["/api/v1/auth/bootstrap"].json()
    assert [m["org"]["suspended"] for m in boot["memberships"]] == [True]


def test_unsuspending_restores_writes(client, store, auth_headers):
    headers = auth_headers(ALICE, org=ORG_A)
    store.suspensions[ORG_A] = "suspended"
    assert _refused(client.patch("/api/v1/organizations/current", headers=headers, json={"sector": "Retail"}))
    store.suspensions[ORG_A] = "active"  # the owner's unsuspend keeps the row with status 'active'
    resp = client.patch("/api/v1/organizations/current", headers=headers, json={"sector": "Retail"})
    assert resp.status_code == 200, resp.text


def test_only_the_suspended_organisation_is_affected(client, store, auth_headers):
    store.suspensions[ORG_A] = "suspended"
    resp = client.patch("/api/v1/organizations/current", headers=auth_headers(CAROL, org=ORG_B),
                        json={"sector": "Retail"})
    assert resp.status_code == 200, resp.text


def test_a_plain_member_still_gets_the_role_refusal(client, store, auth_headers):
    """Role checks are unchanged for an active organisation."""
    resp = client.post("/api/v1/scans/launch", headers=auth_headers(BOB, org=ORG_A), json={})
    assert resp.status_code == 403 and resp.json()["detail"] == "Insufficient role permissions"


def test_invite_accept_is_refused_for_a_suspended_organisation(client, store, auth_headers):
    from datetime import datetime, timedelta, timezone
    from backend.app.core.security import hash_opaque_token

    store.suspensions[ORG_A] = "suspended"
    token = "invite-token-" + uuid4().hex
    store.organization_invites.append({
        "id": str(uuid4()), "org_id": ORG_A, "email": "carol@acme.test", "role": "member",
        "token_hash": hash_opaque_token(token), "revoked_at": None, "accepted_at": None,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1), "full_name": "Carol",
    })
    store.profiles[CAROL]["email"] = "carol@acme.test"
    store.profiles[CAROL]["email_verified_at"] = "2026-01-01T00:00:00"
    resp = client.post("/api/v1/members/invites/accept", headers=auth_headers(CAROL, email="carol@acme.test"),
                       json={"token": token})
    assert _refused(resp), resp.text
    assert not any(m["user_id"] == CAROL and m["org_id"] == ORG_A for m in store.memberships)


def test_scan_admission_refuses_a_suspended_organisation(store):
    """The scheduled sweep and the launch route share admit_scan, which re-checks under the org row lock."""
    from backend.app.core.scan_admission import admit_scan
    store.suspensions[ORG_A] = "suspended"
    admission = admit_scan(ORG_A, DOM_A1, request_scope="scheduled:2026-10-31", request_key=f"domain:{DOM_A1}")
    assert admission.outcome == "suspended" and admission.scan is None


def test_the_scheduled_sweep_counts_suspended_admissions(monkeypatch):
    import asyncio
    from backend.app.core.scan_admission import Admission
    from backend.app.workflows import inngest_workflow as wf

    sent = []
    monkeypatch.setattr(wf, "execute_query", lambda sql, params=(): [
        {"domain_id": DOM_A1, "org_id": ORG_A, "domain": "acme.test"}] if "FROM domains" in sql else None)
    monkeypatch.setattr(wf, "admit_scan", lambda *a, **k: Admission("suspended"))
    monkeypatch.setattr(wf, "log_audit", lambda *a, **k: None)

    async def fake_send(event):
        sent.append(event)

    monkeypatch.setattr(wf.inngest_client, "send", fake_send)
    result = asyncio.run(wf._daily_scan_sweep())
    assert result["skipped_suspended"] == 1 and result["scheduled"] == 0 and sent == []


def test_the_sweep_and_the_claim_leave_suspended_organisations_out_in_sql():
    import inspect
    from backend.app.core import scan_execution
    from backend.app.workflows import inngest_workflow as wf
    from backend.app.core import browser_jobs, scan_recovery
    for source in (inspect.getsource(wf._daily_scan_sweep), inspect.getsource(scan_execution.claim_recon),
                   scan_recovery.LOCAL_QUEUE_SQL, inspect.getsource(browser_jobs.claim)):
        flat = " ".join(source.split())
        assert "NOT EXISTS (SELECT 1 FROM organization_suspensions os" in flat
        assert "status='suspended'" in flat.replace(" = ", "=")


# ── Copy ───────────────────────────────────────────────────────────────────
BANNED = (
    "compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit",
    "compliance score", "fully meets", "meets the requirement", "is met", "adequate", "adequacy", "guarantee",
)


def test_new_backend_wording_has_no_claim_language():
    import inspect
    from backend.app.api import owner_actions
    from backend.app.core import scan_failures
    texts = [suspension.SUSPENDED_MESSAGE, suspension.SUSPENDED_OWNER_MESSAGE, *scan_failures.CATEGORIES.values(),
             scan_failures.STAGE_NOTE_FALLBACK,
             inspect.getsource(owner_actions.restore_member)]
    hits = [(p, t[:60]) for t in texts for p in BANNED if p in t.lower()]
    assert not hits, hits
    # The refusal names the existing contact address only.
    for message in (suspension.SUSPENDED_MESSAGE, suspension.SUSPENDED_OWNER_MESSAGE):
        assert re.findall(r"[\w.]+@[\w.]+\w", message) == ["info@cyphward.com"]


# ── Founder decisions (2026-10-31): protective changes allowed, cost and access additions refused ──
def _not_suspension_refusal(resp):
    try:
        detail = resp.json().get("detail")
    except ValueError:
        return True
    return not (isinstance(detail, dict) and detail.get("code") == suspension.SUSPENDED_CODE)


def test_billing_cancel_is_allowed_while_suspended_and_cost_changes_are_refused(client, store, auth_headers):
    from datetime import datetime, timedelta, timezone
    end = datetime.now(timezone.utc) + timedelta(days=9)
    store.subscriptions.append({"id": "sub", "org_id": ORG_A, "plan": "growth", "status": "active",
                                "current_period_end": end, "trial_ends_at": None, "cancel_at_period_end": False})
    store.suspensions[ORG_A] = "suspended"
    headers = auth_headers(ALICE, org=ORG_A)
    cancel = client.post("/api/v1/billing/subscription/cancel", headers=headers)
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["subscription"]["cancel_at_period_end"] is True
    assert _refused(client.post("/api/v1/billing/subscription", headers=headers, json={"plan": "growth"}))
    assert _refused(client.post("/api/v1/billing/subscription/renew", headers=headers))


def test_reviewer_revoke_is_allowed_while_suspended_and_grant_is_refused(client, store, auth_headers):
    store.suspensions[ORG_A] = "suspended"
    headers = auth_headers(ALICE, org=ORG_A)
    revoke = client.post(f"/api/v1/compliance/reviewer-grants/{uuid4()}/revoke", headers=headers)
    assert revoke.status_code != 403 and _not_suspension_refusal(revoke), revoke.text
    grant = client.post("/api/v1/compliance/reviewer-grants", headers=headers,
                        json={"email": "rev@outside.test", "days": 7, "purpose": "Review our readiness answers"})
    assert _refused(grant)


def test_member_role_changes_while_suspended(client, store, auth_headers):
    """Lowering a role and withdrawing an invitation stay open; promotions and invitations are refused."""
    store.suspensions[ORG_A] = "suspended"
    headers = auth_headers(ALICE, org=ORG_A)
    down = client.patch(f"/api/v1/members/{ADMI}", headers=headers, json={"role": "member"})
    assert down.status_code == 200, down.text
    assert next(m for m in store.memberships if m["user_id"] == ADMI and m["org_id"] == ORG_A)["role"] == "member"
    assert _refused(client.patch(f"/api/v1/members/{BOB}", headers=headers, json={"role": "admin"}))
    assert next(m for m in store.memberships if m["user_id"] == BOB and m["org_id"] == ORG_A)["role"] == "member"
    assert _refused(client.patch(f"/api/v1/members/{BOB}", headers=headers, json={"role": "owner"}))
    # admin -> owner is a promotion too (ADMI was lowered above, so use another admin).
    store.memberships.append({"user_id": CAROL, "org_id": ORG_A, "role": "admin"})
    assert _refused(client.patch(f"/api/v1/members/{CAROL}", headers=headers, json={"role": "owner"}))
    assert next(m for m in store.memberships if m["user_id"] == CAROL and m["org_id"] == ORG_A)["role"] == "admin"
    assert client.patch(f"/api/v1/members/{BOB}", headers=headers, json={"role": "member"}).status_code == 200
    withdraw = client.delete(f"/api/v1/members/invites/{uuid4()}", headers=headers)
    assert withdraw.status_code == 404 and _not_suspension_refusal(withdraw)  # past the gate; no such invitation
    assert _refused(client.post("/api/v1/members/invite", headers=headers,
                                json={"email": "new@acme.test", "full_name": "New", "role": "member"}))
    store.suspensions[ORG_A] = "active"  # promotions work again once the suspension is lifted
    assert client.patch(f"/api/v1/members/{BOB}", headers=headers, json={"role": "admin"}).status_code == 200


def test_owner_of_a_suspended_organisation_cannot_create_a_new_one(client, store, auth_headers):
    for uid in (ALICE, BOB, CAROL):
        store.profiles[uid]["email_verified_at"] = "2026-01-01T00:00:00"
    store.suspensions[ORG_A] = "suspended"
    refused = client.post("/api/v1/organizations", headers=auth_headers(ALICE), json={"name": "Fresh Start Ltd"})
    assert _refused(refused)
    assert refused.json()["detail"]["message"] == suspension.SUSPENDED_OWNER_MESSAGE
    assert not any(o["name"] == "Fresh Start Ltd" for o in store.organizations.values())
    # A member (not an owner) of the suspended organisation, and the owner of an active one, are unaffected.
    for uid, name in ((BOB, "Bob Side Project"), (CAROL, "Carol Second Org")):
        resp = client.post("/api/v1/organizations", headers=auth_headers(uid), json={"name": name})
        assert resp.status_code == 201, (uid, resp.text)
    store.suspensions[ORG_A] = "active"
    resp = client.post("/api/v1/organizations", headers=auth_headers(ALICE), json={"name": "Fresh Start Ltd"})
    assert resp.status_code == 201, resp.text
