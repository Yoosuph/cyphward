"""
Cyphward test fixtures.

Strategy:
    - Set SUPABASE_JWT_SECRET before the app imports so HS256 verification works offline.
    - Patch database.get_db (and overview's by-value import) with an in-memory fake that
      routes the exact SQL used by the routers to seeded tenant data. This exercises the
      REAL auth chain (JWT -> profile upsert -> membership resolution -> RBAC) with no
      network and no Postgres.
"""
import os
import re
import time
import uuid
from contextlib import contextmanager

os.environ.setdefault("SUPABASE_JWT_SECRET", "cyphward-test-secret-not-for-prod")

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.app.core.database as database
from backend.app.core import config
from backend.app.main import app
from backend.app.core.auth import get_current_user, get_current_org

# ---------------------------------------------------------------------------
# Tenant fixtures
# ---------------------------------------------------------------------------
ORG_A = "11111111-aaaa-4aaa-8aaa-111111111111"
ORG_B = "22222222-bbbb-4bbb-8bbb-222222222222"

ALICE = "aaaaaaaa-0000-4000-8000-000000000001"  # owner of A
BOB = "bbbbbbbb-0000-4000-8000-000000000002"    # member of A
ADMI = "cccccccc-0000-4000-8000-000000000003"    # admin of A
CAROL = "dddddddd-0000-4000-8000-000000000004"   # owner of B
DAVE = "eeeeeeee-0000-4000-8000-000000000005"    # member of A AND owner of B

FINDING_A1 = "f1111111-0000-4000-8000-000000000001"
FINDING_A2 = "f2222222-0000-4000-8000-000000000002"
FINDING_A3 = "f3333333-0000-4000-8000-000000000003"  # resolved
FINDING_B1 = "f4444444-0000-4000-8000-000000000004"  # org B

SCAN_A1 = "51111111-0000-4000-8000-000000000001"
DOM_A1 = "d1111111-0000-4000-8000-000000000001"


def sign_token(user_id: str, email: str = "user@acme.test") -> str:
    secret = config.SUPABASE_JWT_SECRET
    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": user_id,
            "email": email,
            "aud": "authenticated",
            "iat": now,
            "exp": now + 3600,
            "user_metadata": {"full_name": email.split("@")[0].title()},
        },
        secret,
        algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# Fake SQL layer
# ---------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, store: "FakeStore"):
        self._store = store
        self._rows = []

    def execute(self, sql: str, params=()):
        if isinstance(params, list):
            params = tuple(params)
        self._rows = self._store.route(sql, params)
        return self

    def executemany(self, sql: str, seq):
        for params in seq:
            self.execute(sql, params)

    @property
    def description(self):
        return [("col",)]

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, store: "FakeStore"):
        self._store = store

    def cursor(self):
        return FakeCursor(self._store)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeStore:
    """In-memory tenant data + SQL router for the exact queries the app issues."""

    def __init__(self):
        self.organizations: dict = {}
        self.memberships: list = []
        self.profiles: dict = {}
        self.findings: list = []
        self.domains: list = []
        self.assets: list = []
        self.scans: list = []
        self.snapshots: list = []
        self.evidence: list = []
        self.audit: list = []

    # -- routing ----------------------------------------------------------
    def route(self, sql: str, params: tuple):
        s = " ".join(sql.split())

        if "SELECT 1 as ok" in s:
            return [{"ok": 1}]

        if s.startswith("INSERT INTO profiles"):
            return [self._upsert_profile(params)]

        if "INSERT INTO audit_log" in s:
            self.audit.append({"id": len(self.audit) + 1, "params": params})
            return [{"id": len(self.audit)}]

        if "SELECT id FROM organizations WHERE slug" in s:
            return [{"id": o["id"]} for o in self.organizations.values() if o["slug"] == params[0]]

        if s.startswith("INSERT INTO organization_members"):
            role_match = re.search(r"'(owner|admin|member)'", s)
            self.memberships.append({
                "user_id": params[0],
                "org_id": params[1],
                "role": role_match.group(1) if role_match else "member",
            })
            return [{"id": len(self.memberships)}]

        if s.startswith("INSERT INTO organizations"):
            org = {
                "id": str(uuid.uuid4()),
                "name": params[0],
                "slug": params[1],
                "cac_rc": params[2],
                "sector": params[3],
                "plan": "scale",
                "created_at": "2026-01-01T00:00:00",
            }
            self.organizations[org["id"]] = org
            return [org]

        if s.startswith("UPDATE findings"):
            st, _st2, finding_id, org_id = params
            for f in self.findings:
                if f["id"] == finding_id and f["org_id"] == org_id:
                    f["status"] = st
                    f["resolved_at"] = "2026-09-23T12:00:00" if st == "resolved" else None
                    f["updated_at"] = "2026-09-23T12:00:00"
                    return [f]
            return []

        if s.startswith("UPDATE organizations"):
            set_part = s.split("WHERE")[0]
            cols = re.findall(r"(\w+) = %s", set_part)
            org_id = params[-1]
            org = self.organizations.get(org_id)
            if not org:
                return []
            for col, val in zip(cols, params[:-1]):
                org[col] = val
            return [org]

        # organization list for current user (organizations router)
        if "SELECT o.id, o.name, o.slug, o.sector, o.plan, m.role" in s:
            user_id = params[0]
            rows = []
            for m in self.memberships:
                if m["user_id"] != user_id:
                    continue
                org = self.organizations.get(m["org_id"])
                if org:
                    rows.append({**org, "role": m["role"]})
            rows.sort(key=lambda r: r["created_at"])
            return rows

        # targeted membership resolution (X-Organization-Id / org_id)
        if "o.id::text" in s:
            current_user_id, user_id, target, _t2 = params
            for m in self.memberships:
                if m["user_id"] != user_id:
                    continue
                org = self.organizations.get(m["org_id"])
                if org and (str(org["id"]) == target or org["slug"] == target):
                    return [{**org, "membership_role": m["role"], "current_user_id": current_user_id}]
            return []

        # all memberships for user
        if "membership_role" in s:
            current_user_id, user_id = params
            rows = [
                {**self.organizations[m["org_id"]], "membership_role": m["role"], "current_user_id": current_user_id}
                for m in self.memberships
                if m["user_id"] == user_id and m["org_id"] in self.organizations
            ]
            rows.sort(key=lambda r: r["created_at"])
            return rows

        # findings category counts
        if "SELECT category, count(*)" in s:
            org_id = params[0]
            counts: dict = {}
            for f in self.findings:
                if f["org_id"] == org_id and f["status"] != "resolved":
                    counts[f["category"]] = counts.get(f["category"], 0) + 1
            return [{"category": c, "count": n} for c, n in counts.items()]

        if "FROM finding_evidence" in s:
            finding_id, org_id = params
            return [e for e in self.evidence if e["finding_id"] == finding_id and e["org_id"] == org_id]

        # finding existence check before status update (unaliased columns)
        if "SELECT id, status FROM findings WHERE id = %s AND org_id = %s" in s:
            finding_id, org_id = params
            return [f for f in self.findings if f["id"] == finding_id and f["org_id"] == org_id]

        if "WHERE f.id = %s AND f.org_id = %s" in s:
            finding_id, org_id = params
            return [f for f in self.findings if f["id"] == finding_id and f["org_id"] == org_id]

        if "FROM findings f" in s:
            org_id = params[0]
            return [f for f in self.findings if f["org_id"] == org_id]

        # overview open findings
        if "FROM findings" in s and "status != 'resolved'" in s and "remediation" in s:
            org_id = params[0]
            return [f for f in self.findings if f["org_id"] == org_id and f["status"] != "resolved"]

        if "SELECT * FROM domains WHERE org_id" in s:
            org_id = params[0]
            return [d for d in self.domains if d["org_id"] == org_id]

        if "SELECT count(*) as cnt FROM assets" in s:
            org_id = params[0]
            return [{"cnt": len([a for a in self.assets if a["org_id"] == org_id])}]

        if "FROM score_snapshots" in s:
            org_id = params[0]
            rows = sorted(
                [s_ for s_ in self.snapshots if s_["org_id"] == org_id],
                key=lambda r: r["created_at"],
                reverse=True,
            )
            return rows[:2]

        # overview recent scans (LIMIT 5, no COUNT)
        if "FROM scans" in s and "LIMIT 5" in s:
            org_id = params[0]
            rows = sorted(
                [s_ for s_ in self.scans if s_["org_id"] == org_id],
                key=lambda r: r["created_at"],
                reverse=True,
            )
            return rows[:5]

        if "COUNT(f.id)" in s and "WHERE s.id = %s" in s:
            scan_id, org_id = params
            rows = [s_ for s_ in self.scans if s_["id"] == scan_id and s_["org_id"] == org_id]
            for r in rows:
                r["findings_discovered"] = len([f for f in self.findings if f["scan_id"] == scan_id])
            return rows

        if "COUNT(f.id)" in s:
            org_id = params[0]
            rows = []
            for s_ in [x for x in self.scans if x["org_id"] == org_id]:
                r = {**s_, "findings_discovered": len([f for f in self.findings if f["scan_id"] == s_["id"]])}
                rows.append(r)
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return rows

        # Unknown statement: behave like an empty result set.
        return []

    def _upsert_profile(self, params):
        user_id, email, full_name, role = params
        prof = self.profiles.get(user_id, {"id": user_id, "role": role})
        if email:
            prof["email"] = email
        if full_name:
            prof["full_name"] = full_name
        prof.setdefault("role", role)
        self.profiles[user_id] = prof
        return prof

    # -- seeding ----------------------------------------------------------
    def seed(self):
        self.organizations = {
            ORG_A: {
                "id": ORG_A, "name": "Acme Traders", "slug": "acme-traders",
                "cac_rc": "RC-123", "sector": "fintech", "plan": "scale",
                "created_at": "2026-01-01T00:00:00",
            },
            ORG_B: {
                "id": ORG_B, "name": "Other Holdings", "slug": "other-holdings",
                "cac_rc": None, "sector": "banking", "plan": "enterprise",
                "created_at": "2026-01-02T00:00:00",
            },
        }
        self.memberships = [
            {"user_id": ALICE, "org_id": ORG_A, "role": "owner"},
            {"user_id": BOB, "org_id": ORG_A, "role": "member"},
            {"user_id": ADMI, "org_id": ORG_A, "role": "admin"},
            {"user_id": CAROL, "org_id": ORG_B, "role": "owner"},
            {"user_id": DAVE, "org_id": ORG_A, "role": "member"},
            {"user_id": DAVE, "org_id": ORG_B, "role": "owner"},
        ]
        self.domains = [
            {
                "id": DOM_A1, "org_id": ORG_A, "domain": "acme.test",
                "verification_status": "verified",
                "verification_token": "tok-acme", "verified_at": "2026-02-01T00:00:00",
                "created_at": "2026-01-15T00:00:00",
            },
        ]
        self.assets = [
            {"id": "a1", "org_id": ORG_A, "hostname": "www.acme.test"},
            {"id": "a2", "org_id": ORG_A, "hostname": "api.acme.test"},
            {"id": "b1", "org_id": ORG_B, "hostname": "www.other.test"},
        ]
        self.findings = [
            {
                "id": FINDING_A1, "org_id": ORG_A, "scan_id": SCAN_A1, "asset_id": "a1",
                "title": "HSTS Missing", "description": "No Strict-Transport-Security header.",
                "severity": "high", "category": "HTTP Headers", "status": "open",
                "evidence": {"header": "missing"}, "remediation": "Enable HSTS.",
                "hostname": "www.acme.test", "ip_address": "198.51.100.10", "asset_type": "web",
                "first_seen_at": "2026-03-01T00:00:00", "last_seen_at": "2026-03-01T00:00:00",
                "resolved_at": None, "updated_at": "2026-03-01T00:00:00",
                "created_at": "2026-03-01T00:00:00",
            },
            {
                "id": FINDING_A2, "org_id": ORG_A, "scan_id": SCAN_A1, "asset_id": "a2",
                "title": "DMARC Missing", "description": "No DMARC policy on _dmarc.acme.test.",
                "severity": "critical", "category": "DNS & Email Security", "status": "open",
                "evidence": {"txt": None}, "remediation": "Publish a DMARC record.",
                "hostname": "api.acme.test", "ip_address": "198.51.100.11", "asset_type": "api",
                "first_seen_at": "2026-03-01T00:00:00", "last_seen_at": "2026-03-01T00:00:00",
                "resolved_at": None, "updated_at": "2026-03-01T00:00:00",
                "created_at": "2026-03-01T00:00:00",
            },
            {
                "id": FINDING_A3, "org_id": ORG_A, "scan_id": SCAN_A1, "asset_id": "a1",
                "title": "Server Version Disclosed", "description": "Server header leaks version.",
                "severity": "low", "category": "HTTP Headers", "status": "resolved",
                "evidence": {}, "remediation": "Hide version tokens.",
                "hostname": "www.acme.test", "ip_address": "198.51.100.10", "asset_type": "web",
                "first_seen_at": "2026-03-01T00:00:00", "last_seen_at": "2026-03-02T00:00:00",
                "resolved_at": "2026-03-02T00:00:00", "updated_at": "2026-03-02T00:00:00",
                "created_at": "2026-03-01T00:00:00",
            },
            {
                "id": FINDING_B1, "org_id": ORG_B, "scan_id": None, "asset_id": "b1",
                "title": "Org B Critical Finding", "description": "Only visible to org B.",
                "severity": "critical", "category": "HTTP Headers", "status": "open",
                "evidence": {}, "remediation": "Fix it.",
                "hostname": "www.other.test", "ip_address": "203.0.113.5", "asset_type": "web",
                "first_seen_at": "2026-03-01T00:00:00", "last_seen_at": "2026-03-01T00:00:00",
                "resolved_at": None, "updated_at": "2026-03-01T00:00:00",
                "created_at": "2026-03-01T00:00:00",
            },
        ]
        self.evidence = [
            {
                "id": "e1", "finding_id": FINDING_A1, "org_id": ORG_A,
                "type": "http_response", "data": {"status": 200},
                "created_at": "2026-03-01T00:00:00",
            },
        ]
        self.scans = [
            {
                "id": SCAN_A1, "org_id": ORG_A, "domain_id": DOM_A1, "domain": "acme.test",
                "status": "completed", "score": 72, "current_stage": 6, "stage_progress": 100,
                "scan_type": "full", "started_at": "2026-03-01T00:00:00",
                "completed_at": "2026-03-01T00:10:00", "created_at": "2026-03-01T00:00:00",
            },
        ]
        self.snapshots = [
            {"org_id": ORG_A, "score": 70, "created_at": "2026-03-01T00:10:00"},
            {"org_id": ORG_A, "score": 75, "created_at": "2026-03-08T00:10:00"},
        ]
        self.profiles = {}
        self.audit = []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def store(monkeypatch):
    st = FakeStore()
    st.seed()

    @contextmanager
    def fake_get_db():
        yield FakeConn(st)

    monkeypatch.setattr(database, "get_db", fake_get_db)
    import backend.app.api.overview as overview_mod
    monkeypatch.setattr(overview_mod, "get_db", fake_get_db)
    return st


@pytest.fixture
def client(store):
    return TestClient(app)


@pytest.fixture
def auth_headers():
    def _make(user_id: str, email: str | None = None, org: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {sign_token(user_id, email or f'{user_id[:8]}@acme.test')}"}
        if org:
            headers["X-Organization-Id"] = org
        return headers

    return _make


@pytest.fixture
def override_deps():
    """Yield a registry that auto-clears app.dependency_overrides after the test."""
    app.dependency_overrides.clear()
    yield app.dependency_overrides
    app.dependency_overrides.clear()


__all__ = [
    "HTTPException", "TestClient", "app", "sign_token",
    "ORG_A", "ORG_B", "ALICE", "BOB", "ADMI", "CAROL", "DAVE",
    "FINDING_A1", "FINDING_A2", "FINDING_A3", "FINDING_B1",
    "SCAN_A1", "DOM_A1",
    "get_current_user", "get_current_org",
]
