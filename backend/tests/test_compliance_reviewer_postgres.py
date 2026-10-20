"""DPCO reviewer access against the real, migrated test database (packet C6).

Runs only against the owned loopback `cyphward_test` database through the restricted `cyphward_app` role (some
checks also use the admin URL, to age a grant or to attack a table the way a superuser could). Covers: who can
grant (owners only, Growth only); expiry and revocation enforced on every request; a grant that waits for a
verified email; cross-tenant isolation and identical refusals; a reviewer is not a member and platform staff are
not reviewers (both ways); the review and the clause overlay never touch a status; newest-wins overlay visible
in /comply and in new snapshots and packs but not in old ones; append-only tables and the grant guard triggers;
audit rows without free text; one live grant per person under concurrency; cascades; the banned phrases.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from backend.app.compliance import attestation_store
from backend.app.compliance import practitioner, reviewer
from backend.app.compliance.register import REGISTER
from backend.app.core.rate_limit import reset_bucket
from backend.app.core.security import hash_password
from backend.app.api import auth as auth_mod
from backend.app.api import auth_google as google_mod
from backend.tests.test_scan_admission_postgres import disposable_postgres_url  # noqa: F401 (fixture)
from backend.tests.test_snapshots_postgres import _assessed_org, world  # noqa: F401 (fixtures)

BASE = "/api/v1/compliance/reviewer-grants"
RB = "/api/v1/compliance/reviewer"
BANNED = ("compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit",
          "compliance score", "fully meets", "meets the requirement", "is met", "partial compliance", "fully compliant",
          "is compliant", "satisfy ndpa", "adequate", "adequacy", "guarantee")
KEY = "ndpa.s25.lawful_basis_documented"
SECRET_NOTE = "NOTE-MARKER-do-not-leak"
SECRET_TEXT = "FREE-TEXT-MARKER-do-not-leak"
SECRET_LINK = "https://evidence.example/LINK-MARKER"


def _admin():
    url = os.environ.get("CYPHWARD_TEST_DATABASE_ADMIN_URL", "")
    if not url:
        pytest.skip("Set CYPHWARD_TEST_DATABASE_ADMIN_URL")
    return psycopg.connect(url, row_factory=dict_row, autocommit=True)


@pytest.fixture
def rw(world):  # noqa: F811
    extra = []

    def make_user(email=None, verified=True, name="Dr Ada Reviewer"):
        uid = str(uuid4())
        mail = email or f"rev-{uid[:8]}@dpco.test"
        world.setup.execute(
            "INSERT INTO profiles (id, email, full_name, role, password_hash, provider, email_verified_at) "
            "VALUES (%s, %s, %s, 'Member', %s, 'email', %s)",
            (uid, mail, name, hash_password("reviewer-pass-1"), None))
        if verified:
            world.setup.execute("UPDATE profiles SET email_verified_at = now() WHERE id = %s", (uid,))
        world.setup.commit()
        extra.append(uid)
        return uid, mail

    def grant(org, owner, email, days=30, purpose="DPCO readiness review", **kw):
        return world.client.post(BASE, json={"email": email, "days": days, "purpose": purpose, **kw},
                                 headers=world.headers(owner, org))

    def listing(org, owner):
        return world.client.get(BASE, headers=world.headers(owner, org))

    def age(grant_id, granted_days_ago=40, expired_days_ago=10):
        with _admin() as conn:
            conn.execute("ALTER TABLE compliance_reviewer_grants DISABLE TRIGGER trg_compliance_reviewer_grants_guard")
            try:
                conn.execute("UPDATE compliance_reviewer_grants SET granted_at = now() - make_interval(days => %s), "
                             "expires_at = now() - make_interval(days => %s) WHERE id = %s",
                             (granted_days_ago, expired_days_ago, grant_id))
            finally:
                conn.execute("ALTER TABLE compliance_reviewer_grants ENABLE TRIGGER trg_compliance_reviewer_grants_guard")

    def setup_org(plan="growth", name="Reviewed Org"):
        org = world.make_org(plan, name=name)
        owner = world.make_person(org, "owner")
        return org, owner

    def extra_profile(email):
        row = world.setup.execute("SELECT id FROM profiles WHERE email = %s", (email,)).fetchone()
        world.setup.commit()
        extra.append(str(row["id"]))

    def reset_limits(org, owner):
        reset_bucket(f"reviewer-grant:{org}")
        reset_bucket(f"reviewer-grant-user:{owner}")

    yield SimpleNamespace(w=world, make_user=make_user, grant=grant, listing=listing, age=age, setup_org=setup_org, extra_profile=extra_profile,
                          reset_limits=reset_limits)
    world.setup.rollback()
    for uid in extra:
        world.setup.execute("DELETE FROM profiles WHERE id = %s", (uid,))
    world.setup.commit()


def _h(rw, uid, org):
    return rw.w.headers(uid, org)


def _active(rw, owner_org=None):
    """An organisation with an owner, a Growth plan, and one active grant for a verified reviewer."""
    org, owner = rw.setup_org()
    uid, email = rw.make_user()
    resp = rw.grant(org, owner, email)
    assert resp.status_code == 201, resp.text
    return SimpleNamespace(org=org, owner=owner, uid=uid, email=email, grant_id=resp.json()["grant"]["id"])


def _review(rw, a, key=KEY, **body):
    return rw.w.client.post(f"{RB}/requirements/{key}/review", json={"outcome": "reviewed", **body},
                            headers=_h(rw, a.uid, a.org))


def _clause(rw, a, key=KEY, verified=True, **body):
    return rw.w.client.post(f"{RB}/requirements/{key}/clause-reference", json={"verified": verified, **body},
                            headers=_h(rw, a.uid, a.org))


def _audit(rw, org, action):
    return rw.w.rows("SELECT user_id, resource_id, metadata FROM audit_log WHERE org_id = %s AND action = %s "
                     "ORDER BY created_at", (org, action))


def _strip(value, keys=("practitioner_review", "clause_review", "clause_label")):
    if isinstance(value, dict):
        return {k: _strip(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_strip(v, keys) for v in value]
    return value


def _strings(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, str):
        yield value


# ── Granting: owners only, Growth only, validated ─────────────────────────


def test_only_an_owner_can_grant_and_the_grant_reads_pending(rw):
    org, owner = rw.setup_org()
    admin, member = rw.w.make_person(org, "admin"), rw.w.make_person(org, "member")
    uid, email = rw.make_user()
    for who in (admin, member):
        assert rw.grant(org, who, email).status_code == 403
        assert rw.listing(org, who).status_code == 403
    assert rw.w.rows("SELECT 1 FROM compliance_reviewer_grants WHERE org_id = %s", (org,)) == []
    resp = rw.grant(org, owner, email, days=7, purpose="Annual readiness review")
    assert resp.status_code == 201
    grant = resp.json()["grant"]
    assert grant["status"] == "pending" and grant["reviewer_email"] == email and grant["purpose"] == "Annual readiness review"
    listed = rw.listing(org, owner).json()
    assert [g["id"] for g in listed["grants"]] == [grant["id"]] and listed["can_grant"] is True


def test_starter_cannot_grant_but_can_still_list_and_revoke(rw):
    org, owner = rw.setup_org()
    uid, email = rw.make_user()
    grant = rw.grant(org, owner, email).json()["grant"]
    rw.w.setup.execute("UPDATE organizations SET plan = 'starter' WHERE id = %s", (org,))
    rw.w.setup.commit()
    assert rw.grant(org, owner, "other@dpco.test").status_code == 403
    listed = rw.listing(org, owner)
    assert listed.status_code == 200 and listed.json()["can_grant"] is False
    # A downgraded organisation's grant stops working (Growth only) and can still be revoked.
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, uid, org)).status_code == 403
    assert rw.w.client.post(f"{BASE}/{grant['id']}/revoke", headers=_h(rw, owner, org)).status_code == 200


@pytest.mark.parametrize("body", [
    {"email": "not-an-email", "days": 30, "purpose": "x"},
    {"email": "a@b", "days": 30, "purpose": "x"},
    {"email": "a b@dpco.test", "days": 30, "purpose": "x"},
    {"email": "ok@dpco.test", "days": 0, "purpose": "x"},
    {"email": "ok@dpco.test", "days": 91, "purpose": "x"},
    {"email": "ok@dpco.test", "days": 30, "purpose": ""},
    {"email": "ok@dpco.test", "days": 30, "purpose": "   "},
    {"email": "ok@dpco.test", "days": 30, "purpose": "x" * 201},
    {"email": "ok@dpco.test", "days": 30, "purpose": "Confirm we are compliant"},
    {"email": "ok@dpco.test", "days": 30, "purpose": "x", "reviewer_id": str(uuid4())},
])
def test_invalid_grants_are_refused_and_store_nothing(rw, body):
    org, owner = rw.setup_org()
    resp = rw.w.client.post(BASE, json=body, headers=_h(rw, owner, org))
    assert resp.status_code == 422, resp.text
    assert rw.w.rows("SELECT 1 FROM compliance_reviewer_grants WHERE org_id = %s", (org,)) == []


def test_expiry_bounds_are_one_to_ninety_days_on_the_database_clock(rw):
    org, owner = rw.setup_org()
    one = rw.grant(org, owner, "one@dpco.test", days=1)
    ninety = rw.grant(org, owner, "ninety@dpco.test", days=90)
    assert one.status_code == ninety.status_code == 201
    default = rw.w.client.post(BASE, json={"email": "d@dpco.test", "purpose": "p"}, headers=_h(rw, owner, org))
    assert default.status_code == 201
    rows = rw.w.rows("SELECT reviewer_email, expires_at - granted_at AS span FROM compliance_reviewer_grants "
                     "WHERE org_id = %s", (org,))
    spans = {r["reviewer_email"]: r["span"].days for r in rows}
    assert spans == {"one@dpco.test": 1, "ninety@dpco.test": 90, "d@dpco.test": 30}
    # The database refuses a longer or shorter window even from SQL.
    for days in (0, 91):
        with pytest.raises(psycopg.errors.CheckViolation):
            rw.w.as_app("INSERT INTO compliance_reviewer_grants (org_id, reviewer_email, purpose, granted_by, expires_at) "
                        "VALUES (%s, 'sql@dpco.test', 'p', %s, now() + make_interval(days => %s))", (org, owner, days))


def test_a_member_of_the_organisation_cannot_be_its_reviewer(rw):
    org, owner = rw.setup_org()
    member = rw.w.make_person(org, "member")
    email = rw.w.rows("SELECT email FROM profiles WHERE id = %s", (member,))[0]["email"]
    resp = rw.grant(org, owner, email.upper())
    assert resp.status_code == 422
    # Even a grant made before the person joined stops working once they are a member.
    uid, mail = rw.make_user()
    rw.grant(org, owner, mail)
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, uid, org)).status_code == 200
    rw.w.setup.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s, %s, 'member')", (uid, org))
    rw.w.setup.commit()
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, uid, org)).status_code == 403


def test_the_grant_endpoint_is_rate_limited(rw):
    org, owner = rw.setup_org()
    rw.reset_limits(org, owner)
    codes = [rw.grant(org, owner, f"r{i}@dpco.test").status_code for i in range(21)]
    rw.reset_limits(org, owner)
    assert codes[:20] == [201] * 20 and codes[20] == 429


def test_the_owner_never_learns_whether_an_account_exists(rw):
    org, owner = rw.setup_org()
    _, existing = rw.make_user()
    known = rw.grant(org, owner, existing).json()["grant"]
    unknown = rw.grant(org, owner, "nobody-yet@dpco.test").json()["grant"]
    assert known["status"] == unknown["status"] == "pending"
    assert set(known) == set(unknown)
    # Still pending in the list until the reviewer actually opens the grant.
    assert {g["status"] for g in rw.listing(org, owner).json()["grants"]} == {"pending"}


# ── Pending until a verified sign-in ──────────────────────────────────────


def test_a_grant_waits_for_the_email_to_have_an_account_and_be_verified(rw):
    org, owner = rw.setup_org()
    email = f"later-{uuid4().hex[:6]}@dpco.test"
    assert rw.grant(org, owner, email).status_code == 201
    uid, _ = rw.make_user(email=email, verified=False)  # signed up but has not verified the email
    for path in ("/overview", f"/requirements/{KEY}", "/grants"):
        resp = rw.w.client.get(f"{RB}{path}", headers=_h(rw, uid, org))
        assert resp.status_code == 403 if path != "/grants" else resp.json()["grants"] == []
    assert _review(rw, SimpleNamespace(uid=uid, org=org)).status_code == 403
    assert rw.w.rows("SELECT 1 FROM compliance_practitioner_reviews WHERE org_id = %s", (org,)) == []
    rw.w.setup.execute("UPDATE profiles SET email_verified_at = now() WHERE id = %s", (uid,))
    rw.w.setup.commit()
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, uid, org)).status_code == 200
    assert [g["status"] for g in rw.listing(org, owner).json()["grants"]] == ["active"]


def test_the_reviewer_is_matched_on_the_profile_email_not_a_token_claim(rw):
    a = _active(rw)
    other, _ = rw.make_user(email="someone-else@dpco.test")
    # A token whose email claim names the reviewer, for a different account: the database decides.
    from backend.app.core.sessions import issue_session
    token = issue_session({"id": other, "email": a.email, "full_name": "Impostor", "role": "Member"})["access_token"]
    resp = rw.w.client.get(f"{RB}/overview", headers={"Authorization": f"Bearer {token}", "X-Organization-Id": a.org})
    assert resp.status_code == 403


# ── Expiry and revocation on every request ────────────────────────────────


def test_a_grant_that_expires_mid_session_stops_working_at_once(rw):
    a = _active(rw)
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)).status_code == 200
    assert _review(rw, a).status_code == 201
    rw.age(a.grant_id)
    for resp in (rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)),
                 rw.w.client.get(f"{RB}/requirements/{KEY}", headers=_h(rw, a.uid, a.org)),
                 _review(rw, a), _clause(rw, a)):
        assert resp.status_code == 403
    assert rw.w.client.get(f"{RB}/grants", headers=_h(rw, a.uid, a.org)).json()["grants"] == []
    assert len(rw.w.rows("SELECT 1 FROM compliance_practitioner_reviews WHERE org_id = %s", (a.org,))) == 1
    assert [g["status"] for g in rw.listing(a.org, a.owner).json()["grants"]] == ["expired"]
    # Revoking something that already expired is a clear no, not a silent success.
    assert rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, a.owner, a.org)).status_code == 409


def test_revocation_takes_effect_on_the_next_request_and_is_audited(rw):
    a = _active(rw)
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)).status_code == 200
    assert rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, a.owner, a.org)).status_code == 200
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)).status_code == 403
    assert _review(rw, a).status_code == 403 and _clause(rw, a).status_code == 403
    assert [g["status"] for g in rw.listing(a.org, a.owner).json()["grants"]] == ["revoked"]
    assert rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, a.owner, a.org)).status_code == 409
    assert len(_audit(rw, a.org, "compliance.reviewer.revoked")) == 1


def test_only_an_owner_can_revoke_and_only_their_own_grants(rw):
    a = _active(rw)
    admin = rw.w.make_person(a.org, "admin")
    assert rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, admin, a.org)).status_code == 403
    assert rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, a.uid, a.org)).status_code == 403  # the reviewer
    other_org, other_owner = rw.setup_org()
    assert rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, other_owner, other_org)).status_code == 404
    assert rw.w.client.post(f"{BASE}/not-a-uuid/revoke", headers=_h(rw, other_owner, other_org)).status_code == 404
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)).status_code == 200


def test_a_new_grant_replaces_the_old_one_and_grants_are_never_extended_in_place(rw):
    a = _active(rw)
    resp = rw.grant(a.org, a.owner, a.email.upper(), days=60, purpose="Second engagement")
    assert resp.status_code == 201
    rows = rw.w.rows("SELECT id, revoked_at, revoked_by FROM compliance_reviewer_grants WHERE org_id = %s "
                     "ORDER BY granted_at", (a.org,))
    assert len(rows) == 2 and rows[0]["revoked_at"] is not None and rows[0]["revoked_by"] is not None and rows[1]["revoked_at"] is None
    statuses = {g["id"]: g["status"] for g in rw.listing(a.org, a.owner).json()["grants"]}
    assert statuses[a.grant_id] == "revoked" and sorted(statuses.values()) == ["pending", "revoked"]
    assert len(_audit(rw, a.org, "compliance.reviewer.replaced")) == 1
    assert rw.w.client.patch(f"{BASE}/{a.grant_id}", json={"days": 90}, headers=_h(rw, a.owner, a.org)).status_code in (404, 405)
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)).status_code == 200  # the new grant works


def test_replacing_an_expired_grant_reads_as_expired_not_revoked(rw):
    a = _active(rw)
    rw.age(a.grant_id)
    assert rw.grant(a.org, a.owner, a.email).status_code == 201
    statuses = {g["id"]: g["status"] for g in rw.listing(a.org, a.owner).json()["grants"]}
    assert statuses[a.grant_id] == "expired"


# ── Isolation: tenants, identical refusals, non-compliance data ───────────


def test_every_refusal_is_the_same_403(rw):
    a = _active(rw)
    other_org, other_owner = rw.setup_org()
    stranger, _ = rw.make_user(email="stranger@dpco.test")
    cases = [
        _h(rw, a.uid, other_org),                                                  # an organisation with no grant
        _h(rw, a.uid, str(uuid4())),                                               # one that does not exist
        {**_h(rw, a.uid, a.org), "X-Organization-Id": "not-a-uuid"},               # malformed
        {k: v for k, v in _h(rw, a.uid, a.org).items() if k != "X-Organization-Id"},  # missing
        _h(rw, stranger, a.org),                                                   # an account the grant does not name
        _h(rw, other_owner, a.org),                                                # a member of ANOTHER organisation
        _h(rw, a.owner, a.org),                                                    # an owner of the organisation itself
    ]
    bodies = set()
    for headers in cases:
        resp = rw.w.client.get(f"{RB}/overview", headers=headers)
        assert resp.status_code == 403, (headers, resp.text)
        bodies.add(resp.content)
    rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, a.owner, a.org))
    bodies.add(rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)).content)  # revoked
    assert len(bodies) == 1, "refusals must not distinguish the reasons"
    assert b"grant" not in bodies.copy().pop().lower().replace(b"reviewer access is not available", b"")


def test_a_reviewer_with_two_grants_sees_only_the_organisation_they_name(rw):
    a = _active(rw)
    org_b, owner_b = rw.setup_org(name="Second Org")
    assert rw.grant(org_b, owner_b, a.email).status_code == 201
    names = {g["org_name"] for g in rw.w.client.get(f"{RB}/grants", headers=_h(rw, a.uid, a.org)).json()["grants"]}
    assert names == {"Reviewed Org", "Second Org"}
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, org_b)).json()["organisation"]["name"] == "Second Org"
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)).json()["organisation"]["name"] == "Reviewed Org"
    assert _review(rw, SimpleNamespace(uid=a.uid, org=org_b)).status_code == 201
    assert rw.w.rows("SELECT org_id FROM compliance_practitioner_reviews") and \
        {str(r["org_id"]) for r in rw.w.rows("SELECT org_id FROM compliance_practitioner_reviews")} == {org_b}


def _org_scoped_routes():
    """Every route that needs an organisation membership, found by walking the dependency trees."""
    from fastapi.routing import APIRoute
    from backend.app.core.auth import get_current_org
    from backend.app.main import app

    def uses(dependant):
        return any(d.call is get_current_org or uses(d) for d in dependant.dependencies)

    def walk(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, "original_router"):  # this FastAPI wraps every included router
                yield from walk(route.original_router.routes)

    out = []
    for route in walk(app.routes):
        if uses(route.dependant):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                out.append((method, route.path))
    return sorted(out)


def test_a_reviewer_reaches_no_organisation_route_of_the_organisation(rw):
    a = _active(rw)
    routes = _org_scoped_routes()
    assert len(routes) > 40, "the route walk found too few routes to mean anything"
    assert ("GET", "/api/v1/members") in routes and ("GET", "/api/v1/compliance/overview") in routes
    assert ("GET", "/api/v1/packs/{pack_id}/pdf") in routes
    # A reviewer who ALSO owns an organisation of their own: naming the granting organisation still finds nothing.
    own_org, own_owner = rw.setup_org(name="DPCO Practice")
    rw.w.setup.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s, %s, 'owner')", (a.uid, own_org))
    rw.w.setup.commit()
    leaks = []
    for method, path in routes:
        url = re.sub(r"\{[^}]+\}", str(uuid4()), path)
        for headers, params in ((_h(rw, a.uid, a.org), {}), ({"Authorization": _h(rw, a.uid, a.org)["Authorization"]}, {"org_id": a.org})):
            resp = rw.w.client.request(method, url, headers=headers, params=params, json={} if method != "GET" else None)
            if resp.status_code != 403:
                leaks.append((method, path, resp.status_code))
    assert leaks == []
    # Without naming the organisation they act in their own, and only their own.
    domain = rw.w.make_domain(a.org, "granting-org-only.test")
    own = rw.w.client.get("/api/v1/compliance/overview", headers={"Authorization": _h(rw, a.uid, a.org)["Authorization"]})
    assert own.status_code == 200 and domain not in {d["id"] for d in own.json()["domains"]}


def test_the_reviewer_is_not_a_member_and_cannot_read_members(rw):
    a = _active(rw)
    members = rw.w.client.get("/api/v1/members", headers=_h(rw, a.owner, a.org))
    assert members.status_code == 200
    assert a.email not in json.dumps(members.json()) and a.uid not in json.dumps(members.json())
    assert rw.w.rows("SELECT 1 FROM organization_members WHERE user_id = %s", (a.uid,)) == []
    assert rw.w.client.get("/api/v1/members", headers=_h(rw, a.uid, a.org)).status_code == 403


# ── Staff and reviewers are separate authorities ──────────────────────────


def test_platform_staff_gain_no_reviewer_powers_and_reviewers_no_staff_powers(rw):
    a = _active(rw)
    staff, _ = rw.make_user(email="staff@cyphward.test")
    with _admin() as conn:
        for uid in (staff, a.uid):
            conn.execute("INSERT INTO platform_staff (user_id, scopes, reason) VALUES (%s, ARRAY['platform:read'], 'test')", (uid,))
    # Staff (no grant) cannot use a reviewer endpoint, for the organisation or any other.
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, staff, a.org)).status_code == 403
    assert _review(rw, SimpleNamespace(uid=staff, org=a.org)).status_code == 403
    assert rw.w.client.get(f"{RB}/grants", headers=_h(rw, staff, a.org)).json()["grants"] == []
    # And a staff member is not an owner: they cannot grant or list grants.
    assert rw.grant(a.org, staff, "x@dpco.test").status_code == 403
    assert rw.listing(a.org, staff).status_code == 403
    # The reviewer, with an active grant, is not staff.
    assert rw.w.client.get("/api/v1/platform/health", headers=_h(rw, a.uid, a.org)).status_code in (200, 403) and \
        rw.w.client.get("/api/v1/platform/health", headers=_h(rw, staff, a.org)).status_code == 200
    # Revoke the staff row: the reviewer (who never had staff rights beyond what the row says) is judged on the grant alone.
    with _admin() as conn:
        conn.execute("UPDATE platform_staff SET revoked_at = now() WHERE user_id = %s", (a.uid,))
    assert rw.w.client.get("/api/v1/platform/health", headers=_h(rw, a.uid, a.org)).status_code == 403
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)).status_code == 200
    # Revoking the grant does not touch staff rights, and does not give any.
    rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, a.owner, a.org))
    assert rw.w.client.get("/api/v1/platform/health", headers=_h(rw, staff, a.org)).status_code == 200
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, staff, a.org)).status_code == 403


def test_the_reviewer_code_reads_no_staff_or_membership_role_tables():
    import inspect
    src = inspect.getsource(reviewer)
    for forbidden in ("platform_staff", "platform_owners", "owner_sessions", "membership_role", "require_platform"):
        assert forbidden not in src
    assert "organization_members" in src  # only to refuse members, never to grant


# ── What the reviewer sees ────────────────────────────────────────────────


def test_the_reviewer_sees_values_dates_owner_and_expiry_but_never_free_text_notes_or_links(rw):
    a = _active(rw)
    attestation_store.record({"id": a.org}, a.owner, question_key="dpo.designated", answer={"value": "yes", "text": SECRET_TEXT},
                             owner_user_id=a.owner, evidence_link=SECRET_LINK, notes=SECRET_NOTE)
    overview = rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org))
    detail = rw.w.client.get(f"{RB}/requirements/gaid.dpo.designated", headers=_h(rw, a.uid, a.org))
    assert overview.status_code == detail.status_code == 200
    for marker in (SECRET_NOTE, SECRET_TEXT, SECRET_LINK):
        assert marker not in overview.text and marker not in detail.text
    answers = [x for x in detail.json()["answers"] if x["question_key"] == "dpo.designated"]
    assert answers and answers[0]["value"] == "yes" and answers[0]["owner_name"] and answers[0]["expires_at"]
    assert overview.json()["organisation"]["name"] == "Reviewed Org" and overview.json()["grant"]["purpose"]
    assert rw.w.client.get(f"{RB}/requirements/no.such.key", headers=_h(rw, a.uid, a.org)).status_code == 404
    # Same register and statuses the organisation sees.
    own = rw.w.client.get("/api/v1/compliance/overview", headers=_h(rw, a.owner, a.org)).json()
    mine = overview.json()
    assert [(r["key"], r["status"]) for g in mine["groups"] for r in g["requirements"]] == \
        [(r["key"], r["status"]) for g in own["groups"] for r in g["requirements"]]


def test_the_reviewer_cannot_reach_packs_snapshots_questionnaire_or_documents(rw):
    a = _active(rw)
    for path in ("/api/v1/packs", "/api/v1/snapshots", "/api/v1/compliance/questionnaire", "/api/v1/compliance/documents",
                 "/api/v1/compliance/incidents", "/api/v1/compliance/overview", f"/api/v1/compliance/requirements/{KEY}",
                 "/api/v1/findings", "/api/v1/domains", "/api/v1/settings"):
        assert rw.w.client.get(path, headers=_h(rw, a.uid, a.org)).status_code == 403, path


# ── Writes never change a status ──────────────────────────────────────────


def test_a_review_and_a_clause_verification_never_change_any_status_for_any_requirement(rw):
    org, owner, domain, scan, finding = _assessed_org(rw.w)
    uid, email = rw.make_user()
    rw.grant(org, owner, email)
    a = SimpleNamespace(uid=uid, org=org)
    attestation_store.record({"id": org}, owner, question_key="lawful_basis.documented", answer={"value": "yes"}, owner_user_id=owner)
    evidence_before = rw.w.rows("SELECT count(*) AS n FROM compliance_evidence WHERE org_id = %s", (org,))[0]["n"]
    before = rw.w.client.get("/api/v1/compliance/overview", headers=_h(rw, owner, org)).json()
    before_detail = {r["key"]: rw.w.client.get(f"/api/v1/compliance/requirements/{r['key']}", headers=_h(rw, owner, org)).json()
                     for r in REGISTER["requirements"]}
    for i, req in enumerate(REGISTER["requirements"]):
        body = {"outcome": "reviewed_with_comments" if i % 2 else "reviewed", "comment": f"Read the clause for {i}" if i % 2 else None}
        r = rw.w.client.post(f"{RB}/requirements/{req['key']}/review", json=body, headers=_h(rw, uid, org))
        assert r.status_code == 201, r.text
        c = _clause(rw, a, req["key"], verified=bool(i % 3), note=None)
        assert c.status_code == 201, c.text
    after = rw.w.client.get("/api/v1/compliance/overview", headers=_h(rw, owner, org)).json()
    assert _strip(after) != after, "the notes must be visible"
    stripped_before, stripped_after = _strip(before), _strip(after)
    stripped_before.pop("register"), stripped_after.pop("register")  # the pending-reference count is allowed to move
    assert stripped_before == stripped_after
    for req in REGISTER["requirements"]:
        now = rw.w.client.get(f"/api/v1/compliance/requirements/{req['key']}", headers=_h(rw, owner, org)).json()
        assert _strip(now) == _strip(before_detail[req["key"]]), req["key"]
    # No evidence row or attestation was written by a reviewer.
    assert rw.w.rows("SELECT count(*) AS n FROM compliance_evidence WHERE org_id = %s", (org,))[0]["n"] == evidence_before
    assert rw.w.rows("SELECT count(*) AS n FROM compliance_attestations WHERE org_id = %s", (org,))[0]["n"] == 1


def test_a_review_note_appears_next_to_the_requirement_with_name_date_and_comment(rw):
    a = _active(rw)
    resp = _review(rw, a, outcome="reviewed_with_comments", comment="Checked against the published text of the Act.")
    assert resp.status_code == 201
    note = resp.json()["practitioner_review"]
    assert note["label"].startswith("Practitioner review recorded by Dr Ada Reviewer (dpco.test), a reviewer named by this organisation, on 20")
    seen = rw.w.client.get(f"/api/v1/compliance/requirements/{KEY}", headers=_h(rw, a.owner, a.org)).json()
    assert seen["practitioner_review"]["comment"] == "Checked against the published text of the Act."
    assert seen["practitioner_review"]["outcome_label"] == "Reviewed, with comments"
    assert seen["source"] != "practitioner_reviewed" and all(s["source"] != "practitioner_reviewed" for s in seen["sources"])
    newer = _review(rw, a, outcome="reviewed").json()["practitioner_review"]
    again = rw.w.client.get(f"/api/v1/compliance/requirements/{KEY}", headers=_h(rw, a.owner, a.org)).json()
    assert again["practitioner_review"]["reviewed_at"] == newer["reviewed_at"] and again["practitioner_review"]["comment"] is None


@pytest.mark.parametrize("body", [
    {"outcome": "approved"}, {"outcome": "reviewed", "comment": "x" * 501}, {"outcome": "reviewed", "comment": "Looks compliant"},
    {"outcome": "reviewed", "comment": "This is adequate"}, {"outcome": "reviewed", "extra": 1}, {},
])
def test_invalid_reviews_are_refused(rw, body):
    a = _active(rw)
    resp = rw.w.client.post(f"{RB}/requirements/{KEY}/review", json=body, headers=_h(rw, a.uid, a.org))
    assert resp.status_code == 422
    assert rw.w.rows("SELECT 1 FROM compliance_practitioner_reviews WHERE org_id = %s", (a.org,)) == []


def test_an_unknown_requirement_is_a_404_and_nothing_is_written(rw):
    a = _active(rw)
    assert _review(rw, a, key="not.a.requirement").status_code == 404
    assert _clause(rw, a, key="not.a.requirement").status_code == 404
    assert rw.w.rows("SELECT 1 FROM compliance_clause_verifications WHERE org_id = %s", (a.org,)) == []


# ── The clause overlay ────────────────────────────────────────────────────


def _unverified_key():
    return next(r["key"] for r in REGISTER["requirements"] if not r["clause_verified"])


def _verified_key():
    return next((r["key"] for r in REGISTER["requirements"] if r["clause_verified"]), None)


def _label(rw, who, org, key):
    return rw.w.client.get(f"/api/v1/compliance/requirements/{key}", headers=_h(rw, who, org)).json()["clause_label"]


def test_the_overlay_replaces_pending_for_this_organisation_only_and_newest_wins(rw):
    a = _active(rw)
    key = _unverified_key()
    other_org, other_owner = rw.setup_org(name="Other")
    assert "reference pending review" in _label(rw, a.owner, a.org, key)
    before = rw.w.client.get("/api/v1/compliance/overview", headers=_h(rw, a.owner, a.org)).json()["register"]
    assert _clause(rw, a, key, verified=True, note="Checked against the Act").status_code == 201
    label = _label(rw, a.owner, a.org, key)
    assert "reference reviewed by Dr Ada Reviewer (dpco.test), a reviewer named by this organisation, 20" in label and "pending" not in label
    assert "reference pending review" in _label(rw, other_owner, other_org, key)  # another organisation is untouched
    after = rw.w.client.get("/api/v1/compliance/overview", headers=_h(rw, a.owner, a.org)).json()["register"]
    assert after["references_pending_review"] == before["references_pending_review"] - 1
    assert _clause(rw, a, key, verified=False).status_code == 201  # the newest row wins, in both directions
    assert "reference pending review" in _label(rw, a.owner, a.org, key)
    assert _clause(rw, a, key, verified=True).status_code == 201
    assert "reference reviewed by" in _label(rw, a.owner, a.org, key)
    assert len(rw.w.rows("SELECT 1 FROM compliance_clause_verifications WHERE org_id = %s AND requirement_key = %s", (a.org, key))) == 3
    # The register file is code: nothing about it changed, and a requirement the register verified keeps its label.
    assert next(r for r in REGISTER["requirements"] if r["key"] == key)["clause_verified"] is False
    if _verified_key():
        _clause(rw, a, _verified_key(), verified=False)
        assert "pending" not in _label(rw, a.owner, a.org, _verified_key())


def test_the_overlay_is_in_new_snapshots_and_packs_but_old_ones_never_change(rw):
    org, owner, *_ = _assessed_org(rw.w)
    uid, email = rw.make_user()
    rw.grant(org, owner, email)
    a = SimpleNamespace(uid=uid, org=org)
    key = _unverified_key()
    old = rw.w.client.post("/api/v1/packs", json={}, headers=_h(rw, owner, org))
    assert old.status_code == 201, old.text
    old_pack = old.json()["pack"]
    old_snapshot = old_pack["snapshot_id"]
    old_content = rw.w.rows("SELECT content, content_sha256 FROM assessment_snapshots WHERE id = %s", (old_snapshot,))[0]
    assert "clause_review" not in json.dumps(old_content["content"]) and "practitioner_review" not in json.dumps(old_content["content"])
    old_html = rw.w.client.get(f"/api/v1/packs/{old_pack['id']}/html", headers=_h(rw, owner, org)).text
    assert _clause(rw, a, key, note="Citation checked").status_code == 201
    assert _review(rw, a, key, outcome="reviewed_with_comments", comment="Read with the explanatory notes").status_code == 201
    # The existing snapshot and pack are untouched.
    still = rw.w.rows("SELECT content, content_sha256 FROM assessment_snapshots WHERE id = %s", (old_snapshot,))[0]
    assert still == old_content
    assert rw.w.client.get(f"/api/v1/packs/{old_pack['id']}/html", headers=_h(rw, owner, org)).text == old_html
    # A pack issued from the OLD snapshot stays frozen: it shows what that snapshot froze, not the later overlay.
    from_old = rw.w.client.post("/api/v1/packs", json={"snapshot_id": old_snapshot}, headers=_h(rw, owner, org))
    assert from_old.status_code == 201
    text = rw.w.client.get(f"/api/v1/packs/{from_old.json()['pack']['id']}/html", headers=_h(rw, owner, org)).text
    assert "reference reviewed by" not in text and "Practitioner review notes" not in text
    # A newly issued pack carries both.
    new = rw.w.client.post("/api/v1/packs", json={}, headers=_h(rw, owner, org)).json()["pack"]
    snap = rw.w.rows("SELECT content FROM assessment_snapshots WHERE id = %s", (new["snapshot_id"],))[0]["content"]
    entry = next(r for r in snap["compliance"]["requirements"] if r["key"] == key)
    assert entry["clause_review"]["verified"] is True and entry["practitioner_review"]["outcome"] == "reviewed_with_comments"
    assert entry["clause_verified"] is False  # the register's own flag is what the snapshot froze; the overlay is additive
    assert snap["schema_version"] == 1
    html = rw.w.client.get(f"/api/v1/packs/{new['id']}/html", headers=_h(rw, owner, org)).text
    flat = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    assert "reference reviewed by Dr Ada Reviewer (dpco.test)" in flat and "Practitioner review recorded by Dr Ada Reviewer (dpco.test)" in flat
    assert "Read with the explanatory notes" in flat and "Practitioner review notes" in flat
    lowered = flat.lower()
    for phrase in BANNED:
        assert phrase not in lowered, phrase
    pdf = rw.w.client.get(f"/api/v1/packs/{new['id']}/pdf", headers=_h(rw, owner, org))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # A snapshot of an organisation without any notes is as it was before this feature.
    org2, owner2, *_ = _assessed_org(rw.w)
    plain = rw.w.client.post("/api/v1/snapshots", json={}, headers=_h(rw, owner2, org2)).json()["snapshot"]["id"]
    content = rw.w.rows("SELECT content FROM assessment_snapshots WHERE id = %s", (plain,))[0]["content"]
    assert all("clause_review" not in r and "practitioner_review" not in r for r in content["compliance"]["requirements"])


# ── Database: append-only, guard triggers, concurrency, cascades ──────────


@pytest.mark.parametrize("sql", [
    "UPDATE compliance_practitioner_reviews SET comment = 'x' WHERE id = %s",
    "DELETE FROM compliance_practitioner_reviews WHERE id = %s",
])
def test_reviews_are_append_only_for_the_app_role(rw, sql):
    a = _active(rw)
    rid = _review(rw, a, comment="A note").status_code == 201 and \
        str(rw.w.rows("SELECT id FROM compliance_practitioner_reviews WHERE org_id = %s", (a.org,))[0]["id"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        rw.w.as_app(sql, (rid,))


@pytest.mark.parametrize("sql", [
    "UPDATE compliance_clause_verifications SET verified = false WHERE id = %s",
    "DELETE FROM compliance_clause_verifications WHERE id = %s",
])
def test_clause_verifications_are_append_only_for_the_app_role(rw, sql):
    a = _active(rw)
    assert _clause(rw, a).status_code == 201
    rid = str(rw.w.rows("SELECT id FROM compliance_clause_verifications WHERE org_id = %s", (a.org,))[0]["id"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        rw.w.as_app(sql, (rid,))


@pytest.mark.parametrize("sql", [
    "DELETE FROM compliance_reviewer_grants WHERE id = %s",
    "UPDATE compliance_reviewer_grants SET expires_at = now() + interval '80 days' WHERE id = %s",
    "UPDATE compliance_reviewer_grants SET reviewer_email = 'other@dpco.test' WHERE id = %s",
    "UPDATE compliance_reviewer_grants SET purpose = 'new' WHERE id = %s",
    "UPDATE compliance_reviewer_grants SET org_id = gen_random_uuid() WHERE id = %s",
])
def test_grants_cannot_be_deleted_or_edited_by_the_app_role(rw, sql):
    a = _active(rw)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        rw.w.as_app(sql, (a.grant_id,))


def test_a_revocation_is_recorded_once_and_never_cleared_even_for_a_superuser(rw):
    a = _active(rw)
    rw.w.as_app("UPDATE compliance_reviewer_grants SET revoked_at = now(), revoked_by = %s WHERE id = %s", (a.owner, a.grant_id))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):  # not a column the app role may touch
        rw.w.as_app("UPDATE compliance_reviewer_grants SET granted_by = NULL WHERE id = %s", (a.grant_id,))
    with _admin() as conn:
        for sql in ("UPDATE compliance_reviewer_grants SET revoked_at = NULL WHERE id = %s",
                    "UPDATE compliance_reviewer_grants SET revoked_at = now() + interval '1 hour' WHERE id = %s",
                    "UPDATE compliance_reviewer_grants SET expires_at = expires_at + interval '1 day' WHERE id = %s",
                    "UPDATE compliance_reviewer_grants SET reviewer_email = 'x@y.test' WHERE id = %s"):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(sql, (a.grant_id,))


def test_the_database_refuses_a_grant_not_made_by_an_owner(rw):
    org, owner = rw.setup_org()
    admin = rw.w.make_person(org, "admin")
    outsider, _ = rw.make_user()
    for who in (admin, outsider, None):
        with pytest.raises(psycopg.errors.CheckViolation):
            rw.w.as_app("INSERT INTO compliance_reviewer_grants (org_id, reviewer_email, purpose, granted_by, expires_at) "
                        "VALUES (%s, 'x@dpco.test', 'p', %s, now() + interval '5 days')", (org, who))


def test_the_write_trigger_refuses_what_the_api_check_could_miss(rw):
    a = _active(rw)
    insert = ("INSERT INTO compliance_practitioner_reviews (org_id, requirement_key, grant_id, reviewer_user_id, "
              "reviewer_name, reviewer_domain, outcome) VALUES (%s, %s, %s, %s, 'N', 'dpco.test', 'reviewed')")
    other, _ = rw.make_user(email="intruder@dpco.test")
    unverified, _ = rw.make_user(email=a.email.replace("rev-", "rev-x"), verified=False)
    org2, owner2 = rw.setup_org()
    with pytest.raises(psycopg.errors.CheckViolation):  # not the person the grant names
        rw.w.as_app(insert, (a.org, KEY, a.grant_id, other))
    with pytest.raises(psycopg.errors.CheckViolation):  # no reviewer at all
        rw.w.as_app(insert, (a.org, KEY, a.grant_id, None))
    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation)):  # another organisation's grant
        rw.w.as_app(insert, (org2, KEY, a.grant_id, a.uid))
    rw.w.as_app(insert, (a.org, KEY, a.grant_id, a.uid))  # the real thing works
    rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, a.owner, a.org))
    with pytest.raises(psycopg.errors.CheckViolation):  # revoked
        rw.w.as_app(insert, (a.org, KEY, a.grant_id, a.uid))
    # Unverified email: the same grant but the profile loses its verification.
    b = _active(rw)
    rw.w.setup.execute("UPDATE profiles SET email_verified_at = NULL WHERE id = %s", (b.uid,))
    rw.w.setup.commit()
    with pytest.raises(psycopg.errors.CheckViolation):
        rw.w.as_app(insert, (b.org, KEY, b.grant_id, b.uid))
    # A member of the organisation.
    c = _active(rw)
    rw.w.setup.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s, %s, 'member')", (c.uid, c.org))
    rw.w.setup.commit()
    with pytest.raises(psycopg.errors.CheckViolation):
        rw.w.as_app(insert, (c.org, KEY, c.grant_id, c.uid))
    del unverified


def test_the_check_constraints_bound_the_texts_and_outcomes(rw):
    a = _active(rw)
    insert = ("INSERT INTO compliance_practitioner_reviews (org_id, requirement_key, grant_id, reviewer_user_id, "
              "reviewer_name, reviewer_domain, outcome, comment) VALUES (%s, %s, %s, %s, 'N', 'dpco.test', %s, %s)")
    for outcome, comment in (("approved", None), ("reviewed", "x" * 501), ("reviewed", "")):
        with pytest.raises(psycopg.errors.CheckViolation):
            rw.w.as_app(insert, (a.org, KEY, a.grant_id, a.uid, outcome, comment))
    with pytest.raises(psycopg.errors.CheckViolation):
        rw.w.as_app("INSERT INTO compliance_clause_verifications (org_id, requirement_key, verified, grant_id, reviewer_user_id, "
                    "reviewer_name, reviewer_domain, note) VALUES (%s, %s, true, %s, %s, 'N', 'dpco.test', %s)", (a.org, KEY, a.grant_id, a.uid, "y" * 501))
    with pytest.raises(psycopg.errors.CheckViolation):
        rw.w.as_app("INSERT INTO compliance_reviewer_grants (org_id, reviewer_email, purpose, granted_by, expires_at) "
                    "VALUES (%s, 'Upper@Case.test', 'p', %s, now() + interval '5 days')", (a.org, a.owner))


def test_one_live_grant_per_person_under_concurrency(rw):
    org, owner = rw.setup_org()
    org_dict = {"id": org}
    barrier = Barrier(6)

    def go(i):
        barrier.wait()
        return reviewer.grant_access(org_dict, owner, "Same.Person@dpco.test", 10 + i, f"Engagement {i}")

    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(go, range(6)))
    assert len(results) == 6
    rows = rw.w.rows("SELECT id, revoked_at FROM compliance_reviewer_grants WHERE org_id = %s", (org,))
    assert len(rows) == 6 and sum(1 for r in rows if r["revoked_at"] is None) == 1
    assert len(_audit(rw, org, "compliance.reviewer.granted")) == 6 and len(_audit(rw, org, "compliance.reviewer.replaced")) == 5
    # The unique index is the backstop even without the lock.
    with pytest.raises(psycopg.errors.UniqueViolation):
        rw.w.as_app("INSERT INTO compliance_reviewer_grants (org_id, reviewer_email, purpose, granted_by, expires_at) "
                    "VALUES (%s, 'same.person@dpco.test', 'p', %s, now() + interval '5 days')", (org, owner))


def test_a_busy_grant_is_a_503_with_retry_after_not_a_hang(rw, monkeypatch):
    org, owner = rw.setup_org()
    monkeypatch.setattr(reviewer, "LOCK_WAIT_MS", 150)
    blocker = psycopg.connect(rw.w.url, row_factory=dict_row)
    try:
        blocker.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"reviewer-grant:{org}:busy@dpco.test",))
        resp = rw.grant(org, owner, "busy@dpco.test")
        assert resp.status_code == 503 and resp.headers["Retry-After"]
    finally:
        blocker.rollback()
        blocker.close()
    assert rw.grant(org, owner, "busy@dpco.test").status_code == 201


def test_a_revoke_waits_for_a_write_in_flight_and_the_write_waits_for_a_revoke(rw, monkeypatch):
    a = _active(rw)
    monkeypatch.setattr(reviewer, "LOCK_WAIT_MS", 150)
    holder = psycopg.connect(rw.w.url, row_factory=dict_row)
    try:
        holder.execute("SELECT 1 FROM compliance_reviewer_grants WHERE id = %s FOR SHARE", (a.grant_id,))
        resp = rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, a.owner, a.org))
        assert resp.status_code == 503 and resp.headers["Retry-After"]
    finally:
        holder.rollback()
        holder.close()
    locker = psycopg.connect(rw.w.url, row_factory=dict_row)
    try:
        locker.execute("SELECT 1 FROM compliance_reviewer_grants WHERE id = %s FOR UPDATE", (a.grant_id,))
        assert _review(rw, a).status_code == 503
    finally:
        locker.rollback()
        locker.close()
    assert _review(rw, a).status_code == 201


def test_deleting_the_organisation_cascades_and_deleting_the_reviewer_keeps_the_record(rw):
    a = _active(rw)
    assert _review(rw, a, comment="Kept").status_code == 201 and _clause(rw, a).status_code == 201
    with _admin() as conn:
        conn.execute("DELETE FROM profiles WHERE id = %s", (a.uid,))
    kept = rw.w.rows("SELECT reviewer_user_id, reviewer_name FROM compliance_practitioner_reviews WHERE org_id = %s", (a.org,))
    assert kept == [{"reviewer_user_id": None, "reviewer_name": "Dr Ada Reviewer"}]
    with _admin() as conn:
        conn.execute("DELETE FROM profiles WHERE id = %s", (a.owner,))  # granted_by / revoked_by go to NULL, row stays
        assert conn.execute("SELECT granted_by FROM compliance_reviewer_grants WHERE id = %s", (a.grant_id,)).fetchone() == {"granted_by": None}
        conn.execute("DELETE FROM organizations WHERE id = %s", (a.org,))
        for table in ("compliance_reviewer_grants", "compliance_practitioner_reviews", "compliance_clause_verifications"):
            assert conn.execute(f"SELECT count(*) AS n FROM {table} WHERE org_id = %s", (a.org,)).fetchone()["n"] == 0


# ── Audit ─────────────────────────────────────────────────────────────────


def test_every_step_is_audited_without_comment_text_and_visible_to_the_owner(rw):
    a = _active(rw)
    marker = "COMMENT-MARKER-must-not-be-audited"
    purpose_marker = "Review of the retention schedule"
    rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org))
    rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org))  # a second request the same day adds no second row
    assert _review(rw, a, outcome="reviewed_with_comments", comment=marker).status_code == 201
    assert _clause(rw, a, note=marker).status_code == 201
    rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, a.owner, a.org))
    for action, expected in (("granted", 1), ("session", 1), ("review_recorded", 1), ("clause_recorded", 1), ("revoked", 1)):
        assert len(_audit(rw, a.org, f"compliance.reviewer.{action}")) == expected, action
    everything = json.dumps([dict(r, metadata=r["metadata"]) for r in rw.w.rows(
        "SELECT action, user_id, resource_id, metadata FROM audit_log WHERE org_id = %s", (a.org,))], default=str)
    assert marker not in everything and purpose_marker not in everything and a.email not in everything
    assert _audit(rw, a.org, "compliance.reviewer.session")[0]["user_id"] == __import__("uuid").UUID(a.uid)
    listing = rw.listing(a.org, a.owner).json()
    assert {e["action"] for e in listing["audit"]} >= {"compliance.reviewer.granted", "compliance.reviewer.session",
                                                       "compliance.reviewer.revoked", "compliance.reviewer.review_recorded"}
    assert {e["grant_id"] for e in listing["audit"]} == {a.grant_id}, "every audit event names the real grant"
    assert [e["kind"] for e in listing["activity"]] and {e["kind"] for e in listing["activity"]} == {"review", "clause"}
    assert listing["activity"] == sorted(listing["activity"], key=lambda e: e["at"], reverse=True)
    assert all(e["reviewer_name"] == "Dr Ada Reviewer" for e in listing["activity"])


def test_a_failed_audit_write_rolls_the_review_back(rw):
    a = _active(rw)
    with _admin() as conn:
        conn.execute("CREATE OR REPLACE FUNCTION c6_fail_audit() RETURNS trigger AS $$ BEGIN "
                     "IF NEW.action = 'compliance.reviewer.review_recorded' THEN RAISE EXCEPTION 'boom'; END IF; RETURN NEW; END $$ "
                     "LANGUAGE plpgsql")
        conn.execute("CREATE TRIGGER c6_fail_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION c6_fail_audit()")
    try:
        from fastapi.testclient import TestClient
        from backend.app.main import app
        resp = TestClient(app, raise_server_exceptions=False).post(
            f"{RB}/requirements/{KEY}/review", json={"outcome": "reviewed"}, headers=_h(rw, a.uid, a.org))
        assert resp.status_code >= 500
        assert rw.w.rows("SELECT 1 FROM compliance_practitioner_reviews WHERE org_id = %s", (a.org,)) == []
    finally:
        with _admin() as conn:
            conn.execute("DROP TRIGGER c6_fail_audit ON audit_log")
            conn.execute("DROP FUNCTION c6_fail_audit()")


# ── Words ─────────────────────────────────────────────────────────────────


def test_no_new_text_claims_compliance(rw):
    a = _active(rw)
    assert _clause(rw, a, note="Citation matches the published text").status_code == 201
    assert _review(rw, a, outcome="reviewed_with_comments", comment="Read the clause and the guidance").status_code == 201
    corpus = [json.dumps(rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)).json()),
              json.dumps(rw.w.client.get(f"{RB}/requirements/{KEY}", headers=_h(rw, a.uid, a.org)).json()),
              json.dumps(rw.w.client.get(f"{RB}/grants", headers=_h(rw, a.uid, a.org)).json()),
              json.dumps(rw.listing(a.org, a.owner).json()), json.dumps(practitioner.OUTCOMES), practitioner.GUIDANCE,
              reviewer.DENIED, reviewer.__doc__, practitioner.__doc__]
    from backend.app.api import compliance_reviewer as api
    corpus += [api.NOTE, api.GROWTH_DETAIL]
    for blob in corpus:
        lowered = blob.lower()
        # The register's own disclaimer legitimately contains the words as negations; only NEW text is scanned.
        for phrase in BANNED:
            assert phrase not in lowered or phrase in cstatus_register_text(rw, a), (phrase, blob[:80])


def cstatus_register_text(rw, a):
    """Text that already existed before C6 (the register, the disclaimer) and is allowed to use the words."""
    from backend.app.compliance.register import DISCLAIMER
    return (DISCLAIMER + json.dumps(REGISTER)).lower()


def test_the_review_text_validator_refuses_every_banned_phrase_and_control_characters():
    for phrase in BANNED:
        with pytest.raises(practitioner.TextError):
            practitioner.clean_text(f"We found it {phrase.upper()} today", "Comment")
    assert practitioner.clean_text("  line\x00 one\x07 ", "Comment") == "line one"
    assert practitioner.clean_text("   ", "Comment") is None
    for fine in ("Checked this method against the Act", "The analysis was thorough", "Read s.25 twice"):
        assert practitioner.clean_text(fine, "Comment") == fine
    for refused in ("Not compliant yet", "non-compliant", "It is met."):
        with pytest.raises(practitioner.TextError):
            practitioner.clean_text(refused, "Comment")
    with pytest.raises(practitioner.TextError):
        practitioner.clean_text("", "Purpose", required=True)


def test_a_reviewer_name_that_states_a_conclusion_is_never_copied_into_the_record(rw):
    org, owner = rw.setup_org()
    uid, email = rw.make_user(name="Certified Adequate Practitioner")
    assert rw.grant(org, owner, email).status_code == 201
    a = SimpleNamespace(uid=uid, org=org)
    assert _review(rw, a).status_code == 201
    assert _clause(rw, a).status_code == 201
    names = {r["reviewer_name"] for r in rw.w.rows(
        "SELECT reviewer_name FROM compliance_practitioner_reviews WHERE org_id = %s UNION ALL "
        "SELECT reviewer_name FROM compliance_clause_verifications WHERE org_id = %s", (org, org))}
    assert names == {"Reviewer (name withheld)"}
    shown = rw.w.client.get(f"/api/v1/compliance/requirements/{KEY}", headers=_h(rw, owner, org)).json()
    lowered = json.dumps(shown).lower()
    assert "certified" not in lowered and "adequate" not in lowered


# ── Review round 1 (independent security review): takeover, projection, wording, triggers ──


def _bearer(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_the_real_signup_and_email_code_flow_activates_a_pending_grant(rw, monkeypatch):
    org, owner = rw.setup_org()
    email = f"real-{uuid4().hex[:6]}@dpco.test"
    assert rw.grant(org, owner, email).status_code == 201
    monkeypatch.setattr(auth_mod, "send_email_async", lambda *a, **k: None)
    tokens = rw.w.client.post("/api/v1/auth/register", json={"email": email, "password": "a-long-password-1", "full_name": "Dr Real"}).json()
    rw.extra_profile(email)
    headers = {**_bearer(tokens), "X-Organization-Id": org}
    assert rw.w.client.get(f"{RB}/overview", headers=headers).status_code == 403  # signed up, email not verified
    rw.w.setup.execute("INSERT INTO email_otps (user_id, code_hash, expires_at, purpose) "
                       "SELECT id, %s, now() + interval '10 minutes', 'verify' FROM profiles WHERE email = %s",
                       (auth_mod._hash_code(email, "123456"), email))
    rw.w.setup.commit()
    assert rw.w.client.post("/api/v1/auth/otp/verify", json={"code": "123456"}, headers=_bearer(tokens)).status_code == 200
    # The same session that verified the address now holds the grant: the mailbox owner did both.
    assert rw.w.client.get(f"{RB}/overview", headers=headers).status_code == 200
    assert [g["status"] for g in rw.listing(org, owner).json()["grants"]] == ["active"]


def test_a_pre_registered_unverified_account_cannot_ride_a_later_google_verification(rw, monkeypatch):
    org, owner = rw.setup_org()
    victim = f"victim-{uuid4().hex[:6]}@dpco.test"
    monkeypatch.setattr(auth_mod, "send_email_async", lambda *a, **k: None)
    attacker = rw.w.client.post("/api/v1/auth/register", json={"email": victim, "password": "attacker-password-1", "full_name": "Mallory"}).json()
    rw.extra_profile(victim)
    uid = rw.w.rows("SELECT id FROM profiles WHERE email = %s", (victim,))[0]["id"]
    rw.w.setup.execute("INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (%s, 'x', now() + interval '1 hour')", (uid,))
    rw.w.setup.execute("INSERT INTO trusted_browsers (user_id, token_hash, expires_at) VALUES (%s, 'x', now() + interval '1 hour')", (uid,))
    rw.w.setup.commit()
    assert rw.grant(org, owner, victim).status_code == 201
    headers = {**_bearer(attacker), "X-Organization-Id": org}
    assert rw.w.client.get(f"{RB}/overview", headers=headers).status_code == 403  # unverified: nothing yet
    # The real practitioner signs in with Google (the mailbox is proven there).
    taken = google_mod._upsert_google_profile(victim, "Dr Real Practitioner")
    assert taken["email_verified_at"] is not None and taken["password_hash"] is None and taken["provider"] == "google"
    # Everything the pre-registration held is dead.
    assert rw.w.client.get(f"{RB}/overview", headers=headers).status_code == 401
    assert rw.w.client.get("/api/v1/auth/bootstrap", headers=_bearer(attacker)).status_code == 401
    assert rw.w.client.post("/api/v1/auth/login", json={"email": victim, "password": "attacker-password-1"}).status_code == 401
    assert rw.w.client.post("/api/v1/auth/refresh", json={"refresh_token": attacker["refresh_token"]}).status_code in (400, 401)
    for table in ("password_reset_tokens", "trusted_browsers", "email_otps"):
        assert rw.w.rows(f"SELECT 1 FROM {table} WHERE user_id = %s", (uid,)) == []
    # The grant works for the real person, with a session issued after the takeover.
    from backend.app.core.sessions import issue_session
    real = issue_session(taken)
    assert rw.w.client.get(f"{RB}/overview", headers={**_bearer(real), "X-Organization-Id": org}).status_code == 200
    resp = rw.w.client.post(f"{RB}/requirements/{KEY}/review", json={"outcome": "reviewed"}, headers={**_bearer(real), "X-Organization-Id": org})
    assert resp.status_code == 201 and "Dr Real Practitioner" in resp.json()["practitioner_review"]["label"]
    assert len(_audit(rw, org, "auth.unverified_account_taken_over_by_google")) == 0  # audited on the user, not the organisation
    assert rw.w.rows("SELECT 1 FROM audit_log WHERE action = 'auth.unverified_account_taken_over_by_google' AND user_id = %s", (uid,))


def test_a_verified_account_signing_in_with_google_keeps_its_password_and_sessions(rw, monkeypatch):
    monkeypatch.setattr(auth_mod, "send_email_async", lambda *a, **k: None)
    uid, email = rw.make_user()
    from backend.app.core.sessions import issue_session
    before = issue_session(rw.w.rows("SELECT * FROM profiles WHERE id = %s", (uid,))[0])
    rw.w.setup.execute("UPDATE profiles SET provider = 'email' WHERE id = %s", (uid,))
    rw.w.setup.commit()
    row = google_mod._upsert_google_profile(email, "Whoever")
    assert row["password_hash"] and row["provider"] == "both"
    assert rw.w.client.get("/api/v1/auth/verification", headers=_bearer(before)).status_code == 200


MARKERS = ("EVIDENCE-URL-MARKER", "COOKIE-MARKER", "SCAN-HOST-MARKER", "FINDING-TITLE-MARKER", "PLAN-MARKER")


def test_a_reviewer_gets_an_allow_listed_view_with_no_raw_evidence_hosts_titles_or_plan(rw):
    org, owner, domain, scan, finding = _assessed_org(rw.w)
    uid, email = rw.make_user()
    rw.grant(org, owner, email)
    a = SimpleNamespace(uid=uid, org=org)
    host = rw.w.rows("SELECT domain FROM domains WHERE id = %s", (domain,))[0]["domain"]
    rw.w.setup.execute("UPDATE findings SET title = 'FINDING-TITLE-MARKER' WHERE id = %s", (finding,))
    rw.w.setup.execute("INSERT INTO compliance_evidence (org_id, requirement_key, domain_id, status, source, observed_at, expires_at, "
                       "scan_id, finding_ids, details, register_version) VALUES (%s, 'gaid.notice.privacy_policy', %s, 'present', "
                       "'externally_observed', now(), now() + interval '30 days', %s, '{}', %s, 'ndpa-gaid-v1')",
                       (org, domain, scan, json.dumps({"url": "https://EVIDENCE-URL-MARKER.example/privacy",
                                                       "cookies": [{"name": "COOKIE-MARKER", "category": "tracker"}],
                                                       "missing": [{"hostname": "SCAN-HOST-MARKER.example", "check": "tls"}]})))
    rw.w.setup.commit()
    rw.w.setup.execute("UPDATE organizations SET plan = 'growth', name = 'Reviewed Org' WHERE id = %s", (org,))
    rw.w.setup.commit()
    texts = []
    for path in ("/overview", "/requirements/gaid.notice.privacy_policy", f"/requirements/{KEY}", "/requirements/ndpa.s39.encryption_in_transit"):
        resp = rw.w.client.get(f"{RB}{path}", headers=_h(rw, uid, org))
        assert resp.status_code == 200, path
        texts.append(resp.text)
    blob = " ".join(texts)
    for marker in MARKERS[:4] + (host, scan, finding, domain):
        assert marker not in blob, marker
    shown = rw.w.client.get(f"{RB}/requirements/gaid.notice.privacy_policy", headers=_h(rw, uid, org)).json()
    assert "history" not in shown and "plan" not in rw.w.client.get(f"{RB}/overview", headers=_h(rw, uid, org)).json()
    assert shown["domains"][0]["domain"] == "Domain 1" and shown["domains"][0]["status"] == "present"
    assert set(shown) <= set(reviewer.REQUIREMENT_KEYS) | {"sources", "answers", "domains", "open_finding_count", "findings",
                                                         "informational_findings", "locked", "disclaimer"}
    # The organisation's own view still shows its own detail.
    own = rw.w.client.get("/api/v1/compliance/requirements/gaid.notice.privacy_policy", headers=_h(rw, owner, org)).text
    assert "EVIDENCE-URL-MARKER" in own


ADVERSARIAL = [
    "The organisation complies with section 25", "Meets s.25 in full; conforms to the NDPA; approved",
    "\uff43\uff4f\uff4d\uff50\uff4c\uff49\uff41\uff4e\uff54", "\U0001d41c\U0001d428\U0001d426\U0001d429\U0001d425\U0001d422\U0001d41a\U0001d427\U0001d42d",
    "com\u200bpliant", "c\u043empliant", "com-pliant", "c.o.m.p.l.i.a.n.t", "Certif\u00ADied", "It satisfies the Act", "fully meets it",
    "This is adequate", "we guarantee it", "Fulfils s.25",
    "c0mpliant", "compIiant", "c\u00f6mpliant", "\u0441\u043e\u043c\u0440li\u0430nt", "c o m p l i a n t", "compl iant", "Requirement met.",
    "They meet s.25.", "In line with the NDPA; no gaps", "Lawful and sufficient.", "ndpa-compliant", "certification done",
    "Aligned with the NDPA", "In accordance with s.25", "Consistent with the NDPA", "NDPA-ready", "OK to go", "The policy passes",
    "Obligation met", "They meet the standard",
]
ORDINARY = ["TLS certificate on the site was reviewed", "Board approval minutes seen", "Checked this method against the Act",
            "Meeting minutes and approval records were seen", "Read the clause and the explanatory notes", "Looked at the DPO appointment letter",
            "Reviewed the lawful basis register for s.25", "We met the DPO on 3 October", "Useful file references provided",
            "Careful filing of records noted", "silicon form seen", "We will meet the DPO next week"]


@pytest.mark.parametrize("text", ADVERSARIAL)
def test_disguised_conclusions_are_refused_in_every_free_text_field(rw, text):
    org, owner = rw.setup_org()
    uid, email = rw.make_user()
    assert rw.grant(org, owner, email, purpose=text).status_code == 422
    assert rw.grant(org, owner, email).status_code == 201
    a = SimpleNamespace(uid=uid, org=org)
    assert _review(rw, a, outcome="reviewed_with_comments", comment=text).status_code == 422
    assert _clause(rw, a, note=text).status_code == 422
    assert rw.w.rows("SELECT 1 FROM compliance_practitioner_reviews WHERE org_id = %s", (org,)) == []
    assert practitioner.violation(text)
    assert practitioner.safe_text(text) == practitioner.WITHHELD


def test_a_disguised_display_name_is_withheld_and_stored_text_that_fails_today_is_withheld_in_the_pack(rw):
    org, owner, *_ = _assessed_org(rw.w)
    uid, email = rw.make_user(name="\uff43\uff4f\uff4d\uff50\uff4c\uff49\uff41\uff4e\uff54 Practitioner")
    rw.grant(org, owner, email)
    a = SimpleNamespace(uid=uid, org=org)
    assert _review(rw, a).status_code == 201
    assert rw.w.rows("SELECT reviewer_name FROM compliance_practitioner_reviews WHERE org_id = %s", (org,))[0]["reviewer_name"] == "Reviewer (name withheld)"
    # A comment stored before the rule existed (inserted as a superuser) is withheld when printed.
    with _admin() as conn:
        conn.execute("INSERT INTO compliance_practitioner_reviews (org_id, requirement_key, grant_id, reviewer_user_id, reviewer_name, "
                     "reviewer_domain, outcome, comment) VALUES (%s, %s, %s, %s, 'Dr Old', 'dpco.test', 'reviewed_with_comments', "
                     "'Fully compliant, approved')", (org, KEY, a.grant_id if hasattr(a, 'grant_id') else rw.w.rows(
                         "SELECT id FROM compliance_reviewer_grants WHERE org_id = %s", (org,))[0]["id"], uid))
    pack = rw.w.client.post("/api/v1/packs", json={}, headers=_h(rw, owner, org)).json()["pack"]
    html = rw.w.client.get(f"/api/v1/packs/{pack['id']}/html", headers=_h(rw, owner, org)).text.lower()
    assert "fully compliant" not in html and "approved" not in html and "comment withheld" in html
    shown = rw.w.client.get(f"/api/v1/compliance/requirements/{KEY}", headers=_h(rw, owner, org)).json()
    assert shown["practitioner_review"]["comment"] == practitioner.WITHHELD


def test_labels_name_the_email_domain_and_never_imply_a_licence_was_checked(rw):
    a = _active(rw)
    label = _review(rw, a).json()["practitioner_review"]["label"]
    assert "(dpco.test)" in label and "a reviewer named by this organisation" in label
    for word in ("licensed", "verified practitioner", "accredited", "registered"):
        assert word not in label.lower() and word not in _clause(rw, a).json()["clause_review"]["label"].lower()


def test_who_revoked_cannot_be_rewritten_and_only_an_owner_can_revoke(rw):
    a = _active(rw)
    other_owner = rw.w.make_person(a.org, "owner")
    member = rw.w.make_person(a.org, "member")
    with pytest.raises(psycopg.errors.CheckViolation):  # a member cannot be recorded as the revoker
        rw.w.as_app("UPDATE compliance_reviewer_grants SET revoked_at = now(), revoked_by = %s WHERE id = %s", (member, a.grant_id))
    with pytest.raises(psycopg.errors.CheckViolation):  # nor can revoked_at be set without a revoker
        rw.w.as_app("UPDATE compliance_reviewer_grants SET revoked_at = now() WHERE id = %s", (a.grant_id,))
    rw.w.as_app("UPDATE compliance_reviewer_grants SET revoked_at = now(), revoked_by = %s WHERE id = %s", (a.owner, a.grant_id))
    with pytest.raises(psycopg.errors.CheckViolation):
        rw.w.as_app("UPDATE compliance_reviewer_grants SET revoked_by = %s WHERE id = %s", (other_owner, a.grant_id))
    assert str(rw.w.rows("SELECT revoked_by FROM compliance_reviewer_grants WHERE id = %s", (a.grant_id,))[0]["revoked_by"]) == a.owner


@pytest.mark.parametrize("table,change", [
    ("compliance_practitioner_reviews", "UPDATE compliance_practitioner_reviews SET comment = 'x'"),
    ("compliance_practitioner_reviews", "DELETE FROM compliance_practitioner_reviews"),
    ("compliance_clause_verifications", "UPDATE compliance_clause_verifications SET verified = NOT verified"),
    ("compliance_clause_verifications", "DELETE FROM compliance_clause_verifications"),
])
def test_the_records_are_append_only_even_for_a_superuser(rw, table, change):
    a = _active(rw)
    assert _review(rw, a, comment="Kept").status_code == 201 and _clause(rw, a).status_code == 201
    with _admin() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(f"{change} WHERE org_id = %s", (a.org,))
        assert conn.execute(f"SELECT count(*) AS n FROM {table} WHERE org_id = %s", (a.org,)).fetchone()["n"] == 1


def test_a_retry_with_the_same_request_key_is_one_record_and_one_audit_row(rw):
    a = _active(rw)
    first = rw.w.client.post(f"{RB}/requirements/{KEY}/review", json={"outcome": "reviewed", "request_key": "retry-key-0001"}, headers=_h(rw, a.uid, a.org))
    again = rw.w.client.post(f"{RB}/requirements/{KEY}/review", json={"outcome": "reviewed", "request_key": "retry-key-0001"}, headers=_h(rw, a.uid, a.org))
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    assert len(rw.w.rows("SELECT 1 FROM compliance_practitioner_reviews WHERE org_id = %s", (a.org,))) == 1
    assert len(_audit(rw, a.org, "compliance.reviewer.review_recorded")) == 1
    other = rw.w.client.post(f"{RB}/requirements/ndpa.part6.rights_process/review", json={"outcome": "reviewed", "request_key": "retry-key-0001"}, headers=_h(rw, a.uid, a.org))
    assert other.status_code == 422
    assert rw.w.client.post(f"{RB}/requirements/{KEY}/review", json={"outcome": "reviewed", "request_key": "bad key!"}, headers=_h(rw, a.uid, a.org)).status_code == 422
    clause = [rw.w.client.post(f"{RB}/requirements/{KEY}/clause-reference", json={"verified": True, "request_key": "retry-key-0002"}, headers=_h(rw, a.uid, a.org)).status_code for _ in range(2)]
    assert clause == [201, 201] and len(rw.w.rows("SELECT 1 FROM compliance_clause_verifications WHERE org_id = %s", (a.org,))) == 1
    # After revocation even a retry is refused.
    rw.w.client.post(f"{BASE}/{a.grant_id}/revoke", headers=_h(rw, a.owner, a.org))
    assert rw.w.client.post(f"{RB}/requirements/{KEY}/review", json={"outcome": "reviewed", "request_key": "retry-key-0001"}, headers=_h(rw, a.uid, a.org)).status_code == 403


def test_a_failed_session_audit_is_tried_again_on_the_next_request(rw):
    a = _active(rw)
    reviewer._seen.clear()
    with _admin() as conn:
        conn.execute("CREATE OR REPLACE FUNCTION c6_fail_session() RETURNS trigger AS $$ BEGIN "
                     "IF NEW.action = 'compliance.reviewer.session' THEN RAISE EXCEPTION 'boom'; END IF; RETURN NEW; END $$ LANGUAGE plpgsql")
        conn.execute("CREATE TRIGGER c6_fail_session BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION c6_fail_session()")
    try:
        assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)).status_code == 200
        assert _audit(rw, a.org, "compliance.reviewer.session") == []
    finally:
        with _admin() as conn:
            conn.execute("DROP TRIGGER c6_fail_session ON audit_log")
            conn.execute("DROP FUNCTION c6_fail_session()")
    assert rw.w.client.get(f"{RB}/overview", headers=_h(rw, a.uid, a.org)).status_code == 200
    assert len(_audit(rw, a.org, "compliance.reviewer.session")) == 1


@pytest.mark.parametrize("text", ORDINARY)
def test_ordinary_review_wording_is_not_over_blocked(rw, text):
    a = _active(rw)
    assert practitioner.violation(text) is None
    assert _review(rw, a, outcome="reviewed_with_comments", comment=text).status_code == 201
    assert _clause(rw, a, note=text).status_code == 201


def test_a_reviewer_email_domain_that_states_a_conclusion_is_withheld_not_printed(rw):
    org, owner = rw.setup_org()
    uid, email = rw.make_user(email=f"ada-{uuid4().hex[:6]}@ndpa-compliant-certified.test")
    assert rw.grant(org, owner, email).status_code == 201
    a = SimpleNamespace(uid=uid, org=org)
    label = _review(rw, a).json()["practitioner_review"]["label"]
    assert "email domain withheld" in label and "compliant" not in label.lower() and "certified" not in label.lower()
    clause = _clause(rw, a).json()["clause_review"]["label"]
    assert "email domain withheld" in clause and "compliant" not in clause.lower()
    seen = json.dumps(rw.w.client.get(f"/api/v1/compliance/requirements/{KEY}", headers=_h(rw, owner, org)).json()["clause_review"]).lower()
    assert "compliant" not in seen


def test_a_request_authenticated_before_a_takeover_cannot_pass_or_write_after_it(rw, monkeypatch):
    from backend.app.core import auth as core_auth
    org, owner = rw.setup_org()
    victim = f"race-{uuid4().hex[:6]}@dpco.test"
    monkeypatch.setattr(auth_mod, "send_email_async", lambda *a, **k: None)
    attacker = rw.w.client.post("/api/v1/auth/register", json={"email": victim, "password": "attacker-password-1", "full_name": "Mallory"}).json()
    rw.extra_profile(victim)
    assert rw.grant(org, owner, victim).status_code == 201
    # The request is authenticated (get_current_user) while the account is still the attacker's.
    user = core_auth.get_current_user(authorization=f"Bearer {attacker['access_token']}")
    assert user["session_id"]
    google_mod._upsert_google_profile(victim, "Dr Real Practitioner")  # commits: verified, sessions revoked
    with pytest.raises(Exception) as refused:
        reviewer.require_reviewer(user=user, x_organization_id=org)
    assert getattr(refused.value, "status_code", None) == 403
    # And a context that already passed the access check cannot write once the session is gone.
    grant_id = rw.w.rows("SELECT id FROM compliance_reviewer_grants WHERE org_id = %s", (org,))[0]["id"]
    ctx = {"grant_id": grant_id, "org_id": org, "user_id": user["id"], "email": victim, "full_name": "Mallory",
           "session_id": user["session_id"]}
    with pytest.raises(reviewer.NoAccess):
        reviewer.record_review(ctx, KEY, "reviewed", None)
    assert rw.w.rows("SELECT 1 FROM compliance_practitioner_reviews WHERE org_id = %s", (org,)) == []


def test_concurrent_duplicate_request_keys_give_one_record_and_no_errors(rw):
    a = _active(rw)
    barrier = Barrier(6)

    def go(i):
        from fastapi.testclient import TestClient
        from backend.app.main import app
        barrier.wait()
        return TestClient(app).post(f"{RB}/requirements/{KEY}/review", json={"outcome": "reviewed", "request_key": "same-key-0001"},
                                    headers=_h(rw, a.uid, a.org)).status_code

    with ThreadPoolExecutor(6) as pool:
        codes = list(pool.map(go, range(6)))
    assert codes == [201] * 6
    assert len(rw.w.rows("SELECT 1 FROM compliance_practitioner_reviews WHERE org_id = %s", (a.org,))) == 1
    assert len(_audit(rw, a.org, "compliance.reviewer.review_recorded")) == 1
    differs = rw.w.client.post(f"{RB}/requirements/{KEY}/review", json={"outcome": "reviewed_with_comments", "comment": "Different", "request_key": "same-key-0001"},
                               headers=_h(rw, a.uid, a.org))
    assert differs.status_code == 422
