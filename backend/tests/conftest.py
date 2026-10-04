"""
Cyphward test fixtures.

Strategy:
    - Set AUTH_JWT_SECRET before the app imports so HS256 verification works offline.
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
from datetime import datetime, timedelta, timezone

os.environ.setdefault("AUTH_JWT_SECRET", "cyphward-test-secret-not-for-prod")

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


def sign_token(user_id: str, email: str = "user@acme.test", sid: str | None = None) -> str:
    """Mint a Cyphward access token exactly as the backend does in production."""
    secret = config.AUTH_JWT_SECRET
    now = int(time.time())
    claims = {
        "sub": user_id,
        "email": email,
        "full_name": email.split("@")[0].title(),
        "iat": now,
        "exp": now + 3600,
    }
    if sid:
        claims["sid"] = sid
    return pyjwt.encode(claims, secret, algorithm="HS256")


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
        self.email_otps: list = []
        self.sessions: list = []
        self.password_reset_tokens: list = []
        self.organization_invites: list = []
        self.remediation_tasks: list = []
        self.notifications: list = []
        self.staff_grants: list = []
        self.cron_runs: list = []
        self.rate_limits: list = []
        self.subscriptions: list = []
        self.invoices: list = []
        self.monitored_hosts: list = []

    # -- routing ----------------------------------------------------------
    def route(self, sql: str, params: tuple):
        s = " ".join(sql.split())

        if "SELECT 1 as ok" in s:
            return [{"ok": 1}]

        # --- own auth: credentials ---------------------------------------
        if s.startswith("SELECT * FROM profiles WHERE email = %s"):
            email = (params[0] or "").lower()
            for p in self.profiles.values():
                if (p.get("email") or "").lower() == email:
                    return [p]
            return []

        if s.startswith("SELECT * FROM profiles WHERE id = %s"):
            p = self.profiles.get(str(params[0]))
            return [p] if p else []

        if s.startswith("INSERT INTO profiles (id, email, full_name, role, password_hash, provider)"):
            email, full_name, password_hash = params
            prof = {
                "id": str(uuid.uuid4()), "email": email, "full_name": full_name,
                "role": "Member", "password_hash": password_hash, "provider": "email",
                "email_verified_at": None, "created_at": datetime.now(timezone.utc),
            }
            self.profiles[prof["id"]] = prof
            return [prof]

        if s.startswith("INSERT INTO profiles (id, email, full_name, role, provider, email_verified_at)"):
            email, full_name = params
            prof = {
                "id": str(uuid.uuid4()), "email": email, "full_name": full_name,
                "role": "Member", "password_hash": None, "provider": "google",
                "email_verified_at": datetime.now(timezone.utc),
                "created_at": datetime.now(timezone.utc),
            }
            self.profiles[prof["id"]] = prof
            return [prof]

        if s.startswith("UPDATE profiles SET password_hash = %s, updated_at = now() WHERE id = %s"):
            password_hash, user_id = params
            prof = self.profiles.get(str(user_id))
            if prof is not None:
                prof["password_hash"] = password_hash
            return [{"id": user_id}] if prof else []

        if s.startswith("UPDATE profiles SET full_name = CASE WHEN full_name IS NULL"):
            name, user_id = params
            prof = self.profiles.get(str(user_id))
            if not prof:
                return []
            if not prof.get("full_name"):
                prof["full_name"] = name
            if not prof.get("email_verified_at"):
                prof["email_verified_at"] = datetime.now(timezone.utc)
            if prof.get("provider") == "email":
                prof["provider"] = "both"
            return [prof]

        # --- own auth: sessions ------------------------------------------
        # get_current_user: profile + session-revocation join (single query).
        # Never creates rows — a deleted profile must stay deleted (P1).
        if s.startswith("SELECT p.*, s.revoked_at AS session_revoked_at FROM profiles p"):
            sid, uid = params
            prof = self.profiles.get(str(uid))
            if prof is None:
                return []
            revoked = None
            if sid:
                sess = next((x for x in self.sessions if x["id"] == sid), None)
                if sess is not None:
                    revoked = sess.get("revoked_at")
            return [{**prof, "session_revoked_at": revoked}]

        if s.startswith("INSERT INTO auth_sessions"):
            if "otc_hash" in s:
                uid, refresh_hash, otc_hash, ttl = params
                otc_hash_val, otc_exp = otc_hash, datetime.now(timezone.utc) + timedelta(minutes=5)
            else:
                uid, refresh_hash, ttl = params
                otc_hash_val, otc_exp = None, None
            row = {
                "id": str(uuid.uuid4()), "user_id": uid, "refresh_token_hash": refresh_hash,
                "otc_hash": otc_hash_val, "otc_expires_at": otc_exp,
                "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=int(ttl)),
                "revoked_at": None, "last_used_at": None,
            }
            self.sessions.append(row)
            return [{"id": row["id"]}]

        if s.startswith("SELECT id, user_id FROM auth_sessions WHERE refresh_token_hash"):
            return [
                {"id": x["id"], "user_id": x["user_id"]}
                for x in self.sessions
                if x["refresh_token_hash"] == params[0]
            ][:1]

        if s.startswith("SELECT id, user_id FROM auth_sessions WHERE otc_hash"):
            return [
                {"id": x["id"], "user_id": x["user_id"]}
                for x in self.sessions
                if x["otc_hash"] == params[0] and x["revoked_at"] is None
            ][:1]

        if s.startswith("UPDATE auth_sessions SET refresh_token_hash = %s, last_used_at = now() WHERE id = %s AND refresh_token_hash"):
            # Conditional compare-and-set: old hash + not revoked + not expired
            # must all hold, mirroring the single UPDATE in Postgres.
            new_hash, sid, old_hash = params
            now = datetime.now(timezone.utc)
            for x in self.sessions:
                if (x["id"] == sid and x["refresh_token_hash"] == old_hash
                        and x["revoked_at"] is None and x["expires_at"] > now):
                    x["refresh_token_hash"] = new_hash
                    x["last_used_at"] = now
                    return [{"id": x["id"]}]
            return []

        if s.startswith("UPDATE auth_sessions SET otc_hash = NULL"):
            new_hash, sid, otc_hash = params
            now = datetime.now(timezone.utc)
            for x in self.sessions:
                if (x["id"] == sid and x["otc_hash"] == otc_hash
                        and x["revoked_at"] is None
                        and x["otc_expires_at"] is not None and x["otc_expires_at"] > now):
                    x["otc_hash"] = None
                    x["otc_expires_at"] = None
                    x["refresh_token_hash"] = new_hash
                    x["last_used_at"] = now
                    return [{"id": x["id"]}]
            return []

        if s.startswith("UPDATE auth_sessions SET revoked_at = now() WHERE refresh_token_hash"):
            now = datetime.now(timezone.utc)
            for x in self.sessions:
                if x["refresh_token_hash"] == params[0] and x["revoked_at"] is None:
                    x["revoked_at"] = now
            return []

        if s.startswith("UPDATE auth_sessions SET revoked_at = now() WHERE user_id"):
            now = datetime.now(timezone.utc)
            for x in self.sessions:
                if str(x["user_id"]) == str(params[0]) and x["revoked_at"] is None:
                    x["revoked_at"] = now
            return []

        # --- own auth: password reset tokens ------------------------------
        if s.startswith("INSERT INTO password_reset_tokens"):
            uid, token_hash, minutes = params
            row = {
                "id": str(uuid.uuid4()), "user_id": uid, "token_hash": token_hash,
                "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=int(minutes)),
                "used_at": None,
            }
            self.password_reset_tokens.append(row)
            return [{"id": row["id"]}]

        if s.startswith("SELECT id, user_id, expires_at FROM password_reset_tokens"):
            rows = [
                r for r in self.password_reset_tokens
                if r["token_hash"] == params[0] and r["used_at"] is None
            ]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return rows[:1]

        if s.startswith("UPDATE password_reset_tokens SET used_at"):
            # Conditional consume: only an unused, unexpired row flips to used.
            rid = params[0]
            now = datetime.now(timezone.utc)
            for r in self.password_reset_tokens:
                if r["id"] == rid and r["used_at"] is None and r["expires_at"] > now:
                    r["used_at"] = now
                    return [{"id": r["id"]}]
            return []

        if s.startswith("DELETE FROM password_reset_tokens"):
            self.password_reset_tokens = [
                r for r in self.password_reset_tokens if str(r["user_id"]) != str(params[0])
            ]
            return []

        if "FROM audit_log" in s and "welcome.sent" in s:
            uid = params[0]
            return [
                r for r in self.audit
                if r["params"][1] == uid and r["params"][2] == "welcome.sent"
            ]

        if "INSERT INTO audit_log" in s:
            self.audit.append({"id": len(self.audit) + 1, "params": params})
            return [{"id": len(self.audit)}]

        # --- platform staff (P1 workspace authorization) -------------------
        if s == "SELECT 1":
            return [{"ok": 1}]

        if s.startswith("SELECT id, scopes FROM platform_staff WHERE user_id = %s"):
            uid = params[0]
            now = datetime.now(timezone.utc)
            live = [
                g for g in self.staff_grants
                if g["user_id"] == uid and g.get("revoked_at") is None
                and (g.get("expires_at") is None or g["expires_at"] > now)
            ]
            live.sort(key=lambda g: g.get("created_at") or now, reverse=True)
            return (
                [{"id": live[0]["id"], "scopes": live[0]["scopes"]}]
                if live else []
            )

        if s.startswith("SELECT run_day, status FROM cron_runs"):
            done = sorted(
                (r for r in self.cron_runs
                 if r.get("cron_name") == "daily-scans" and r.get("status") == "completed"),
                key=lambda r: r.get("run_day", ""), reverse=True,
            )
            return [{"run_day": done[0]["run_day"], "status": "completed"}] if done else []

        if s.startswith("SELECT count(*) AS n FROM scans WHERE status IN"):
            return [{"n": sum(1 for x in self.scans if x.get("status") in ("queued", "running"))}]

        if s.startswith("SELECT id, name, slug, plan, created_at FROM organizations WHERE id = %s"):
            o = self.organizations.get(str(params[0]))
            if not o:
                return []
            return [{k: o.get(k) for k in ("id", "name", "slug", "plan", "created_at")}]

        if s.startswith("SELECT count(*) AS n FROM organization_members WHERE org_id = %s"):
            org_id = params[0]
            return [{"n": sum(1 for m in self.memberships if m["org_id"] == org_id)}]

        if s.startswith("SELECT count(*) AS n FROM domains WHERE org_id = %s"):
            org_id = params[0]
            return [{"n": sum(1 for d in self.domains if d["org_id"] == org_id)}]

        # Active-scan count (tenant lookup). The monthly-quota variant
        # (AND created_at >= ...) is routed to its own handler below.
        if s.startswith("SELECT count(*) AS n FROM scans WHERE org_id = %s") and "created_at >=" not in s:
            org_id = params[0]
            return [{"n": sum(
                1 for x in self.scans
                if x["org_id"] == org_id and x.get("status") in ("queued", "running")
            )}]

        if s.startswith("SELECT s.id, s.org_id, o.name AS org_name"):
            limit = params[0] if params else 50
            now = datetime.now(timezone.utc)
            rows = []
            for x in self.scans:
                if x.get("status") not in ("queued", "running"):
                    continue
                lease = x.get("lease_expires_at")
                if lease is not None and lease >= now:
                    continue
                o = self.organizations.get(x["org_id"], {})
                rows.append({
                    "id": x["id"], "org_id": x["org_id"],
                    "org_name": o.get("name"), "status": x["status"],
                    "created_at": str(x.get("created_at")),
                    "lease_expires_at": (
                        str(lease) if lease is not None else None
                    ),
                })
            return rows[:limit]

        # --- email OTP (Brevo verification + admin login step-up) --------
        if s.startswith("DELETE FROM email_otps"):
            uid = params[0]
            purpose = "mfa" if "purpose = 'mfa'" in s else (
                "verify" if "purpose = 'verify'" in s else None)
            self.email_otps = [
                r for r in self.email_otps
                if not (r["user_id"] == uid and (purpose is None or r.get("purpose", "verify") == purpose))
            ]
            return []

        if s.startswith("INSERT INTO email_otps"):
            uid, code_hash, _ttl = params
            now = datetime.now(timezone.utc)
            self.email_otps.append({
                "id": str(uuid.uuid4()),
                "user_id": uid,
                "code_hash": code_hash,
                "attempts": 0,
                "created_at": now,
                "purpose": "mfa" if "'mfa'" in s else "verify",
                # the real SQL computes now() + ttl; mirror it in the fake
                "expires_at": now + timedelta(seconds=600),
            })
            return []

        # --- shared rate limits (P2 throttling) ---------------------------
        if s.startswith("INSERT INTO rate_limits"):
            bucket, window = params[0], float(params[1])
            now = datetime.now(timezone.utc)
            row = next((r for r in self.rate_limits if r["bucket_key"] == bucket), None)
            if row is None:
                row = {"bucket_key": bucket, "window_start": now, "count": 0}
                self.rate_limits.append(row)
            if (now - row["window_start"]).total_seconds() >= window:
                row["window_start"] = now
                row["count"] = 1
            else:
                row["count"] += 1
            return [{"count": row["count"], "window_start": row["window_start"]}]

        if s.startswith("DELETE FROM rate_limits"):
            if "bucket_key = %s" in s:
                self.rate_limits = [r for r in self.rate_limits if r["bucket_key"] != params[0]]
            else:
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=float(params[0]))
                self.rate_limits = [r for r in self.rate_limits if r["window_start"] >= cutoff]
            return []

        if s.startswith("SELECT 1 FROM organization_members WHERE user_id = %s AND role IN"):
            uid = params[0]
            return [{"ok": 1}] if any(
                m["user_id"] == uid and m["role"] in ("owner", "admin")
                for m in self.memberships
            ) else []

        if s.startswith("SELECT created_at FROM email_otps"):
            uid = params[0]
            purpose = "mfa" if "purpose = 'mfa'" in s else (
                "verify" if "purpose = 'verify'" in s else None)
            rows = [r for r in self.email_otps
                    if r["user_id"] == uid and (purpose is None or r.get("purpose", "verify") == purpose)]
            if not rows:
                return []
            return [{"created_at": max(r["created_at"] for r in rows)}]

        if s.startswith("SELECT id FROM email_otps WHERE user_id = %s AND purpose = 'mfa'"):
            uid = params[0]
            now = datetime.now(timezone.utc)
            rows = sorted(
                [r for r in self.email_otps
                 if r["user_id"] == uid and r.get("purpose") == "mfa"
                 and r.get("expires_at") is not None and r["expires_at"] > now],
                key=lambda r: r["created_at"],
                reverse=True,
            )
            return [{"id": rows[0]["id"]}] if rows else []

        if s.startswith("SELECT id, code_hash, attempts, expires_at") and "email_otps" in s:
            uid = params[0]
            purpose = "mfa" if "purpose = 'mfa'" in s else (
                "verify" if "purpose = 'verify'" in s else None)
            rows = sorted(
                [r for r in self.email_otps
                 if r["user_id"] == uid and (purpose is None or r.get("purpose", "verify") == purpose)],
                key=lambda r: r["created_at"],
                reverse=True,
            )
            return [rows[0]] if rows else []

        if s.startswith("UPDATE email_otps SET attempts"):
            # Conditional bump: budget check + increment in one statement.
            row_id, max_attempts = params
            for r in self.email_otps:
                if r["id"] == row_id:
                    if r["attempts"] < max_attempts:
                        r["attempts"] += 1
                        return [{"attempts": r["attempts"]}]
                    return []
            return []

        if s.startswith("UPDATE profiles SET email_verified_at"):
            uid = params[0]
            prof = self.profiles.get(uid)
            if prof is not None:
                prof["email_verified_at"] = datetime.now(timezone.utc)
            return []

        if s.startswith("UPDATE profiles SET mfa_enrolled_at = now()"):
            uid = params[0]
            prof = self.profiles.get(uid)
            if prof is not None:
                prof["mfa_enrolled_at"] = datetime.now(timezone.utc)
            return [{"id": uid}] if prof else []

        if s.startswith("UPDATE profiles SET mfa_enrolled_at = NULL"):
            uid = params[0]
            prof = self.profiles.get(uid)
            if prof is not None:
                prof["mfa_enrolled_at"] = None
            return [{"id": uid}] if prof else []

        if s.startswith("SELECT totp_secret_enc, totp_enrolled_at FROM profiles WHERE id = %s"):
            p = self.profiles.get(str(params[0]))
            if not p:
                return []
            return [{"totp_secret_enc": p.get("totp_secret_enc"),
                     "totp_enrolled_at": p.get("totp_enrolled_at")}]

        if s.startswith("UPDATE profiles SET totp_secret_enc = %s, totp_enrolled_at = NULL"):
            enc, uid = params
            prof = self.profiles.get(str(uid))
            if prof is not None:
                prof["totp_secret_enc"] = enc
                prof["totp_enrolled_at"] = None
            return [{"id": uid}] if prof else []

        if s.startswith("UPDATE profiles SET totp_enrolled_at = now()"):
            uid = params[0]
            prof = self.profiles.get(str(uid))
            if prof is not None:
                prof["totp_enrolled_at"] = datetime.now(timezone.utc)
            return [{"id": uid}] if prof else []

        if s.startswith("UPDATE profiles SET totp_secret_enc = NULL, totp_enrolled_at = NULL"):
            uid = params[0]
            prof = self.profiles.get(str(uid))
            if prof is not None:
                prof["totp_secret_enc"] = None
                prof["totp_enrolled_at"] = None
            return [{"id": uid}] if prof else []

        if "SELECT id FROM organizations WHERE slug" in s:
            return [{"id": o["id"]} for o in self.organizations.values() if o["slug"] == params[0]]

        if s.startswith("INSERT INTO organization_members"):
            user_id, org_id = params[0], params[1]
            if len(params) >= 3 and params[2] in ("owner", "admin", "member"):
                role = params[2]
            else:
                role_match = re.search(r"'(owner|admin|member)'", s)
                role = role_match.group(1) if role_match else "member"
            if "DO NOTHING" in s and any(
                m["user_id"] == user_id and m["org_id"] == org_id for m in self.memberships
            ):
                return []
            self.memberships.append({
                "user_id": user_id,
                "org_id": org_id,
                "role": role,
            })
            return [{"id": len(self.memberships)}]

        if s.startswith("SELECT m.role FROM organization_members m JOIN profiles p"):
            email, org_id = (params[0] or "").lower(), params[1]
            for p in self.profiles.values():
                if (p.get("email") or "").lower() == email:
                    for m in self.memberships:
                        if m["user_id"] == p["id"] and m["org_id"] == org_id:
                            return [{"role": m["role"]}]
            return []

        if s.startswith("SELECT role FROM organization_members WHERE user_id = %s AND org_id = %s"):
            user_id, org_id = params
            for m in self.memberships:
                if m["user_id"] == user_id and m["org_id"] == org_id:
                    return [{"role": m["role"]}]
            return []

        if s.startswith("SELECT COUNT(*) AS n FROM organization_members WHERE org_id = %s AND role = 'owner'"):
            org_id = params[0]
            return [{"n": sum(1 for m in self.memberships
                              if m["org_id"] == org_id and m["role"] == "owner")}]

        if "UPDATE organization_members m SET role = %s" in s and "WITH locked AS" in s:
            org_id_lock, role, user_id, org_id, _pred_role = params
            target = next((m for m in self.memberships
                           if m["user_id"] == user_id and m["org_id"] == org_id), None)
            if target is None:
                return []
            # Mirror the SQL guard: demoting an owner requires >1 owner in
            # the org at update time (the atomic last-owner protection).
            if target["role"] == "owner" and role != "owner":
                owners = [m for m in self.memberships
                          if m["org_id"] == org_id and m["role"] == "owner"]
                if len(owners) <= 1:
                    return []
            target["role"] = role
            return [{"id": 1}]

        # --- tokenized invitations (members router) ------------------------
        if s.startswith("DELETE FROM organization_invites WHERE org_id = %s"):
            org_id, email = params[0], (params[1] or "").lower()
            self.organization_invites = [
                i for i in self.organization_invites
                if not (i["org_id"] == org_id and i["email"].lower() == email
                        and i["accepted_at"] is None and i["revoked_at"] is None)
            ]
            return []

        if s.startswith("INSERT INTO organization_invites"):
            org_id, email, full_name, role, token_hash, invited_by = params
            now = datetime.now(timezone.utc)
            invite = {
                "id": str(uuid.uuid4()), "org_id": org_id, "email": email,
                "full_name": full_name, "role": role, "token_hash": token_hash,
                "invited_by": invited_by, "created_at": now,
                # real SQL: now() + interval '7 days'
                "expires_at": now + timedelta(days=7),
                "accepted_at": None, "accepted_user_id": None, "revoked_at": None,
            }
            self.organization_invites.append(invite)
            return [{"id": invite["id"]}]

        if s.startswith("SELECT * FROM organization_invites WHERE token_hash = %s"):
            return [i for i in self.organization_invites if i["token_hash"] == params[0]]

        if s.startswith("SELECT i.id, i.email"):
            org_id = params[0]
            return [
                {k: i[k] for k in ("id", "email", "full_name", "role",
                                   "created_at", "expires_at", "invited_by")}
                for i in self.organization_invites
                if i["org_id"] == org_id and i["accepted_at"] is None and i["revoked_at"] is None
            ]

        if s.startswith("UPDATE organization_invites SET accepted_at = now()"):
            user_id, invite_id = params
            for i in self.organization_invites:
                if (i["id"] == str(invite_id) and i["accepted_at"] is None
                        and i["revoked_at"] is None):
                    i["accepted_at"] = datetime.now(timezone.utc)
                    i["accepted_user_id"] = user_id
                    return [{"id": i["id"]}]
            return []

        if s.startswith("UPDATE organization_invites SET revoked_at"):
            invite_id, org_id = params
            for i in self.organization_invites:
                if (i["id"] == str(invite_id) and i["org_id"] == org_id
                        and i["accepted_at"] is None and i["revoked_at"] is None):
                    i["revoked_at"] = datetime.now(timezone.utc)
                    return [{"id": i["id"]}]
            return []

        if s.startswith("UPDATE organization_invites SET accepted_at = NULL"):
            invite_id, user_id = params
            for i in self.organization_invites:
                if i["id"] == str(invite_id) and i["accepted_user_id"] == user_id:
                    i["accepted_at"] = None
                    i["accepted_user_id"] = None
                    return [{"id": i["id"]}]
            return []

        if s.startswith("INSERT INTO organizations"):
            org = {
                "id": str(uuid.uuid4()),
                "name": params[0],
                "slug": params[1],
                "cac_rc": params[2],
                "sector": params[3],
                "plan": params[4] if len(params) > 4 else "scale",
                "created_at": "2026-01-01T00:00:00",
            }
            self.organizations[org["id"]] = org
            return [org]

        if s.startswith("UPDATE organizations SET ") and "WHERE id = %s RETURNING *" in s:
            set_part = s.split("UPDATE organizations SET ", 1)[1].rsplit(" WHERE id = %s", 1)[0]
            cols = [m.group(1) for m in re.finditer(r"(\w+) = %s", set_part)]
            org_id = params[-1]
            o = self.organizations.get(str(org_id))
            if not o:
                return []
            for col, val in zip(cols, params[:-1]):
                if col == "updated_at":
                    continue
                o[col] = val
            return [o]

        if s.startswith("SELECT id, plan FROM organizations"):
            return [{"id": o["id"], "plan": o.get("plan")} for o in self.organizations.values()]

        # --- account self-service deletion ----------------------------------
        if s.startswith("SELECT o.id, o.name, o.slug FROM organization_members m"):
            uid = params[0]
            rows = []
            for m in self.memberships:
                if m["user_id"] != uid or m["role"] != "owner":
                    continue
                owners = [x for x in self.memberships
                          if x["org_id"] == m["org_id"] and x["role"] == "owner"]
                if len(owners) == 1:
                    o = self.organizations.get(m["org_id"], {})
                    rows.append({"id": m["org_id"], "name": o.get("name"),
                                 "slug": o.get("slug")})
            return rows

        if s.startswith("DELETE FROM profiles WHERE id = %s"):
            uid = str(params[0])
            if uid not in self.profiles:
                return []
            del self.profiles[uid]
            # mirror ON DELETE CASCADE / SET NULL
            self.sessions = [x for x in self.sessions if x["user_id"] != uid]
            self.email_otps = [x for x in self.email_otps if x["user_id"] != uid]
            self.password_reset_tokens = [
                x for x in self.password_reset_tokens if str(x["user_id"]) != uid]
            self.memberships = [x for x in self.memberships if x["user_id"] != uid]
            self.staff_grants = [g for g in self.staff_grants if g["user_id"] != uid]
            return [{"id": uid}]

        # --- billing model (subscriptions + invoices, manual provider) ---
        if s.startswith("SELECT * FROM subscriptions WHERE org_id = %s"):
            sub = next((x for x in self.subscriptions if x["org_id"] == params[0]), None)
            return [sub] if sub else []

        if s.startswith("INSERT INTO subscriptions"):
            org_id, plan = params[0], params[1]
            now = datetime.now(timezone.utc)
            sub = next((x for x in self.subscriptions if x["org_id"] == org_id), None)
            if sub is None:
                sub = {"id": str(uuid.uuid4()), "org_id": org_id, "created_at": now}
                self.subscriptions.append(sub)
            sub.update({"plan": plan, "status": "active" if sub.get("status") != "canceled" else "active",
                        "provider": "manual", "cancel_at_period_end": False,
                        "current_period_start": now,
                        "current_period_end": now + timedelta(days=30),
                        "updated_at": now})
            # mirror the SQL: canceled flips back to active on plan set
            if sub.get("_was_canceled"):
                sub["status"] = "active"
            return [sub]

        if s.startswith("UPDATE subscriptions"):
            org_id = params[-1]
            sub = next((x for x in self.subscriptions if x["org_id"] == org_id), None)
            if sub is None:
                return []
            now = datetime.now(timezone.utc)
            if "cancel_at_period_end = true" in s:
                sub["cancel_at_period_end"] = True
            else:
                sub.update({"status": "active", "cancel_at_period_end": False,
                            "current_period_start": now,
                            "current_period_end": now + timedelta(days=30),
                            "updated_at": now})
            return [sub]

        if s.startswith("INSERT INTO invoices"):
            org_id, plan, amount = params[0], params[1], params[2]
            now = datetime.now(timezone.utc)
            inv = {"id": str(uuid.uuid4()), "number": f"INV-{len(self.invoices) + 1}",
                   "org_id": org_id, "plan": plan, "amount_kobo": amount,
                   "currency": "NGN", "status": "open", "provider_ref": None,
                   "period_start": now, "period_end": now + timedelta(days=30),
                   "created_at": now}
            self.invoices.append(inv)
            return [{"id": inv["id"], "number": inv["number"], "plan": plan,
                     "amount_kobo": amount, "currency": "NGN", "status": "open",
                     "created_at": now}]

        if s.startswith("SELECT id, number, plan, amount_kobo, currency, status, provider_ref"):
            return sorted(
                [i for i in self.invoices if i["org_id"] == params[0]],
                key=lambda r: r["created_at"], reverse=True)[:20]

        # --- monitored hosts (scan-scope registration) --------------------
        if s.startswith("SELECT hostname FROM monitored_hosts WHERE org_id = %s AND domain_id = %s"):
            org_id, domain_id = params
            return [{"hostname": h["hostname"]} for h in self.monitored_hosts
                    if h["org_id"] == org_id and h["domain_id"] == domain_id]

        if s.startswith("SELECT id, hostname, created_at FROM monitored_hosts"):
            org_id, domain_id = params
            return [{"id": h["id"], "hostname": h["hostname"], "created_at": h["created_at"]}
                    for h in self.monitored_hosts
                    if h["org_id"] == org_id and h["domain_id"] == domain_id]

        if s.startswith("SELECT id FROM monitored_hosts WHERE org_id = %s AND hostname = %s"):
            org_id, hostname = params
            return [{"id": h["id"]} for h in self.monitored_hosts
                    if h["org_id"] == org_id and h["hostname"] == hostname][:1]

        if s.startswith("SELECT id FROM monitored_hosts WHERE org_id = %s"):
            return [{"id": h["id"]} for h in self.monitored_hosts if h["org_id"] == params[0]]

        if s.startswith("INSERT INTO monitored_hosts"):
            org_id, domain_id, hostname, added_by = params
            row = {"id": str(uuid.uuid4()), "org_id": org_id, "domain_id": domain_id,
                   "hostname": hostname, "added_by": added_by,
                   "created_at": datetime.now(timezone.utc)}
            self.monitored_hosts.append(row)
            return [{"id": row["id"], "hostname": hostname, "created_at": row["created_at"]}]

        if s.startswith("DELETE FROM monitored_hosts WHERE id = %s"):
            hid, org_id, domain_id = params
            before = len(self.monitored_hosts)
            self.monitored_hosts = [
                h for h in self.monitored_hosts
                if not (h["id"] == hid and h["org_id"] == org_id and h["domain_id"] == domain_id)
            ]
            return [{"id": hid}] if len(self.monitored_hosts) < before else []

        # --- workspace export + closure (P2 data lifecycle) -----------------
        if s.startswith("SELECT m.role, m.created_at, p.email, p.full_name FROM organization_members m"):
            org_id = params[0]
            rows = []
            for m in self.memberships:
                if m["org_id"] != org_id:
                    continue
                p = self.profiles.get(m["user_id"], {})
                rows.append({"role": m["role"], "created_at": m.get("created_at"),
                             "email": p.get("email"), "full_name": p.get("full_name")})
            return rows

        if s.startswith("SELECT id, domain, verification_status, verified_at, created_at FROM domains"):
            return [d for d in self.domains if d["org_id"] == params[0]]

        if s.startswith("SELECT id, hostname, ip_address, asset_type, status, last_seen FROM assets"):
            return [a for a in self.assets if a["org_id"] == params[0]]

        if s.startswith("SELECT id, asset_id, title, description, severity, category, status,"):
            return [f for f in self.findings if f["org_id"] == params[0]]

        if s.startswith("SELECT id, domain_id, status, score, started_at, completed_at, created_at FROM scans"):
            return [x for x in self.scans if x["org_id"] == params[0]]

        if s.startswith("SELECT id, score, created_at FROM score_snapshots"):
            return [r for r in self.snapshots if r["org_id"] == params[0]]

        if s.startswith("SELECT id, domain_id, title, status, summary, created_at FROM reports"):
            return [r for r in self.reports if r["org_id"] == params[0]]

        if s.startswith("SELECT email, full_name, role, accepted_at, revoked_at, created_at FROM organization_invites"):
            return [i for i in self.organization_invites if i["org_id"] == params[0]]

        if s.startswith("DELETE FROM organizations WHERE id = %s"):
            org_id = str(params[0])
            org = self.organizations.pop(org_id, None)
            if org is None:
                return []
            # mirror ON DELETE CASCADE across every tenant-owned collection
            self.memberships = [m for m in self.memberships if m["org_id"] != org_id]
            self.domains = [d for d in self.domains if d["org_id"] != org_id]
            self.assets = [a for a in self.assets if a["org_id"] != org_id]
            self.findings = [f for f in self.findings if f["org_id"] != org_id]
            self.scans = [x for x in self.scans if x["org_id"] != org_id]
            self.snapshots = [r for r in self.snapshots if r["org_id"] != org_id]
            self.reports = [r for r in self.reports if r["org_id"] != org_id]
            self.organization_invites = [
                i for i in self.organization_invites if i["org_id"] != org_id]
            self.audit = [a for a in self.audit
                          if not (a["params"][0] == org_id)]
            return [{"id": org_id}]

        def _in_current_month(value) -> bool:
            now = datetime.now(timezone.utc)
            dt = value
            if isinstance(value, str):
                try:
                    dt = datetime.fromisoformat(value)
                except ValueError:
                    return False
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (dt.year, dt.month) == (now.year, now.month)

        if s.startswith("SELECT count(*) AS n FROM scans WHERE org_id = %s AND created_at >="):
            org_id = params[0]
            return [{"n": sum(
                1 for x in self.scans
                if x["org_id"] == org_id and _in_current_month(x.get("created_at"))
            )}]

        if s.startswith("SELECT count(*) AS n FROM reports WHERE org_id = %s AND created_at >="):
            org_id = params[0]
            return [{"n": sum(
                1 for r in self.reports
                if r["org_id"] == org_id and _in_current_month(r.get("created_at"))
            )}]

        # --- findings status transitions used by remediation verification ---
        if s.startswith("UPDATE findings SET status = 'open', resolved_at = NULL"):
            finding_id, org_id = params
            for f in self.findings:
                if f["id"] == finding_id and f["org_id"] == org_id:
                    f["status"] = "open"
                    f["resolved_at"] = None
                    f["last_seen_at"] = "2026-09-23T12:00:00"
                    f["updated_at"] = "2026-09-23T12:00:00"
                    return [f]
            return []

        if s.startswith("UPDATE findings SET status = 'resolved', resolved_at = now()"):
            finding_id, org_id = params
            for f in self.findings:
                if f["id"] == finding_id and f["org_id"] == org_id:
                    f["status"] = "resolved"
                    f["resolved_at"] = "2026-09-23T12:00:00"
                    f["last_seen_at"] = "2026-09-23T12:00:00"
                    f["updated_at"] = "2026-09-23T12:00:00"
                    return [f]
            return []

        # --- remediation tasks ------------------------------------------
        if s.startswith("INSERT INTO remediation_tasks"):
            cols_match = re.search(r"INSERT INTO remediation_tasks \(([^)]+)\)", s)
            cols = [c.strip() for c in cols_match.group(1).split(",")] if cols_match else []
            task = {col: val for col, val in zip(cols, params)}
            task.update({
                "id": str(uuid.uuid4()),
                "status": "open",
                "verified_at": None,
                "created_at": "2026-09-23T12:00:00",
                "updated_at": "2026-09-23T12:00:00",
            })
            self.remediation_tasks.append(task)
            return [task]

        if s.startswith("UPDATE remediation_tasks"):
            task_id, org_id = params[-2], params[-1]
            task = next(
                (t for t in self.remediation_tasks if t["id"] == task_id and t["org_id"] == org_id),
                None,
            )
            if not task:
                return []
            if "SET status = 'reopened'" in s:
                task["status"] = "reopened"
                task["updated_at"] = "2026-09-23T12:00:00"
            elif "SET status = 'verified'" in s:
                task["status"] = "verified"
                task["verified_at"] = "2026-09-23T12:00:00"
                task["updated_at"] = "2026-09-23T12:00:00"
            else:
                set_part = s.split("WHERE")[0]
                for col, val in zip(re.findall(r"(\w+) = %s", set_part), params[:-2]):
                    task[col] = val
                task["updated_at"] = "2026-09-23T12:00:00"
            return [task]

        if s.startswith("SELECT id, status, assignee_id FROM remediation_tasks"):
            task_id, org_id = params
            return [t for t in self.remediation_tasks
                    if t["id"] == task_id and t["org_id"] == org_id]

        if "FROM remediation_tasks t JOIN findings f" in s:
            task_id, org_id = params
            task = next((t for t in self.remediation_tasks
                         if t["id"] == task_id and t["org_id"] == org_id), None)
            if not task:
                return []
            f = next((x for x in self.findings if x["id"] == task.get("finding_id")), None)
            if not f:
                return []
            return [{**task, "f_id": f["id"], "f_title": f["title"],
                     "asset_id": f.get("asset_id"), "f_status": f["status"],
                     "f_category": f.get("category"), "f_evidence": f.get("evidence")}]

        if "FROM remediation_tasks t LEFT JOIN findings f" in s:
            if "WHERE t.id = %s AND t.org_id = %s" in s:
                task_id, org_id = params
                task = next((t for t in self.remediation_tasks
                             if t["id"] == task_id and t["org_id"] == org_id), None)
                if not task:
                    return []
                f = next((x for x in self.findings if x["id"] == task.get("finding_id")), None)
                row = {**task}
                if f:
                    row.update({"finding_title": f["title"],
                                "finding_description": f.get("description"),
                                "severity": f.get("severity"),
                                "finding_status": f["status"],
                                "finding_instructions": f.get("remediation")})
                return [row]
            org_id = params[0]
            status_filter = params[1] if len(params) > 1 else None
            finding_filter = params[2] if len(params) > 2 else None
            rows = []
            for t in self.remediation_tasks:
                if t["org_id"] != org_id:
                    continue
                if status_filter and t.get("status") != status_filter:
                    continue
                if finding_filter and t.get("finding_id") != finding_filter:
                    continue
                f = next((x for x in self.findings if x["id"] == t.get("finding_id")), None)
                row = {**t}
                if f:
                    row.update({"finding_title": f["title"],
                                "severity": f.get("severity"),
                                "finding_status": f["status"]})
                rows.append(row)
            return rows

        # --- notifications (remediation verify notices) -------------------
        if s.startswith("INSERT INTO notifications"):
            cols_match = re.search(r"INSERT INTO notifications \(([^)]+)\)", s)
            cols = [c.strip() for c in cols_match.group(1).split(",")] if cols_match else []
            row = {col: val for col, val in zip(cols, params)}
            row.update({"id": str(uuid.uuid4()), "read_at": None,
                        "created_at": "2026-09-23T12:00:00"})
            self.notifications.append(row)
            return [row]

        # --- asset lookup for remediation rechecks ------------------------
        if s.startswith("SELECT hostname, domain_id FROM assets WHERE id = %s AND org_id = %s"):
            asset_id, org_id = params
            return [a for a in self.assets if a["id"] == asset_id and a["org_id"] == org_id]

        if s.startswith("SELECT id FROM assets WHERE org_id = %s AND hostname = %s"):
            org_id, hostname = params
            return [a for a in self.assets if a["org_id"] == org_id and a["hostname"] == hostname]

        # finalize asset inventory upsert: (org_id, domain_id, hostname, ip, type,
        # status, http_status, techs, tls, records)
        if s.startswith("INSERT INTO assets"):
            org_id, domain_id, hostname, ip, atype, status, http_status, techs, tls, records = params
            for a in self.assets:
                if a["org_id"] == org_id and a["hostname"] == hostname:
                    a.update(ip_address=ip, asset_type=atype, status=status,
                             http_status=http_status)
                    return [{"id": a["id"]}]
            new_id = f"agen-{len(self.assets)}"
            self.assets.append({
                "id": new_id, "org_id": org_id, "domain_id": domain_id,
                "hostname": hostname, "ip_address": ip, "asset_type": atype,
                "status": status, "http_status": http_status,
            })
            return [{"id": new_id}]

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

        # scan launch (scans router + daily sweep share this shape)
        if s.startswith("INSERT INTO scans (org_id, domain_id, scan_type, status, current_stage, stage_progress)"):
            org_id, domain_id, _progress = params
            now = datetime.now(timezone.utc)
            row = {
                "id": str(uuid.uuid4()), "org_id": org_id, "domain_id": domain_id,
                "domain": None, "status": "queued", "score": None,
                "current_stage": "queued", "stage_progress": {},
                "scan_type": "EXTERNAL_ASSESSMENT",
                "started_at": None, "completed_at": None,
                "created_at": now, "claimed_by": None, "lease_expires_at": None,
                "error_message": None,
            }
            self.scans.append(row)
            return [row]

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

        # finding existence check before status update / task creation
        if "FROM findings WHERE id = %s AND org_id = %s" in s:
            finding_id, org_id = params
            return [f for f in self.findings if f["id"] == finding_id and f["org_id"] == org_id]

        if "WHERE f.id = %s AND f.org_id = %s" in s:
            finding_id, org_id = params
            return [f for f in self.findings if f["id"] == finding_id and f["org_id"] == org_id]

        if "FROM findings f" in s:
            org_id = params[0]
            return [f for f in self.findings if f["org_id"] == org_id]

        # baseline diff: existing findings on the scanned assets
        if s.startswith(
            "SELECT id, asset_id, title, status, severity, description, category, "
            "evidence, remediation FROM findings WHERE org_id = %s AND asset_id = ANY(%s)"
        ):
            org_id, asset_ids = params
            wanted = set(asset_ids)
            return [dict(f) for f in self.findings
                    if f["org_id"] == org_id and f.get("asset_id") in wanted]

        # overview open findings
        # plain SELECT * open findings (dashboard / reports / exec summary)
        if s.startswith("SELECT * FROM findings WHERE org_id = %s AND status != 'resolved'"):
            org_id = params[0]
            return [f for f in self.findings
                    if f["org_id"] == org_id and f["status"] != "resolved"]

        if s.startswith("SELECT * FROM findings WHERE org_id = %s AND status = 'open'"):
            org_id = params[0]
            return [f for f in self.findings
                    if f["org_id"] == org_id and f["status"] == "open"]

        if "FROM findings" in s and "status != 'resolved'" in s and "remediation" in s:
            org_id = params[0]
            return [f for f in self.findings if f["org_id"] == org_id and f["status"] != "resolved"]

        # --- reports: org-scoped domain lookups + tenant-scoped join (P1) ---
        if s.startswith("SELECT * FROM domains WHERE id = %s AND org_id = %s"):
            did, org_id = params
            d = next((x for x in self.domains
                      if x["id"] == did and x["org_id"] == org_id), None)
            return [d] if d else []

        if s.startswith("SELECT id FROM domains WHERE id = %s AND org_id = %s"):
            did, org_id = params
            return [d for d in self.domains if d["id"] == did and d["org_id"] == org_id][:1]

        if s.startswith("SELECT domain FROM domains WHERE id = %s AND org_id = %s"):
            did, org_id = params
            return [{"domain": d["domain"]} for d in self.domains
                    if d["id"] == did and d["org_id"] == org_id]

        if "FROM reports r LEFT JOIN domains d ON d.id = r.domain_id AND d.org_id = r.org_id" in s:
            org_id = params[0]
            rows = []
            for r in self.reports:
                if r["org_id"] != org_id:
                    continue
                dom = next((d for d in self.domains
                            if d["id"] == r.get("domain_id") and d["org_id"] == org_id), None)
                rows.append({**r, "domain": dom["domain"] if dom else None})
            return rows

        if s.startswith("INSERT INTO reports"):
            org_id, domain_id, title, html, summary, created_by = params
            row = {
                "id": f"rep-{len(self.reports) + 1}", "org_id": org_id,
                "domain_id": domain_id, "title": title, "status": "ready",
                "summary": summary, "created_at": "2026-10-04T00:00:00",
                "updated_at": "2026-10-04T00:00:00",
            }
            self.reports.append(row)
            return [{k: row[k] for k in ("id", "org_id", "domain_id", "title",
                                         "status", "summary", "created_at", "updated_at")}]

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

        # completed-scan assessment lookup (risk engine "not assessed" gate)
        if s.startswith("SELECT id, status, completed_at, stage_progress FROM scans WHERE org_id = %s AND status = 'completed'"):
            org_id = params[0]
            rows = sorted(
                [sc for sc in self.scans
                 if sc["org_id"] == org_id and sc.get("status") == "completed"],
                key=lambda r: r.get("completed_at") or "",
                reverse=True,
            )
            return rows[:1]

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

        # --- scanner worker endpoints (spec §14) -------------------------
        # claim: atomic UPDATE ... FOR UPDATE SKIP LOCKED ... RETURNING id
        if "FOR UPDATE OF s SKIP LOCKED" in s:
            scanner_id = params[1]
            for sc in self.scans:
                if sc.get("status") == "queued":
                    sc["status"] = "running"
                    sc["claimed_by"] = scanner_id
                    sc["current_stage"] = "discovery"
                    sc["lease_expires_at"] = "2026-09-30T12:00:00"
                    return [{"id": sc["id"]}]
            return []

        # claim follow-up: ScanJob payload select
        if "s.lease_expires_at, d.domain" in s:
            scan_id = params[0]
            sc = next((x for x in self.scans if x["id"] == scan_id), None)
            if not sc:
                return []
            dom = next((d for d in self.domains if d["id"] == sc.get("domain_id")), None)
            return [{
                **sc,
                "domain": (dom or {}).get("domain", "example.test"),
                "lease_expires_at": "2026-09-30T12:00:00",
            }]

        # _held_job lease ownership check
        if s.startswith("SELECT id, status, claimed_by, lease_expires_at FROM scans"):
            scan_id = params[0]
            return [x for x in self.scans if x["id"] == scan_id]

        # --- scan cancel-fencing / lifecycle CAS transitions ---------------
        # cancel endpoint: initial row read
        if s.startswith("SELECT * FROM scans WHERE id = %s AND org_id = %s"):
            scan_id, org_id = params
            return [x for x in self.scans if x["id"] == scan_id and x["org_id"] == org_id]

        # cancel endpoint: status re-read after a lost CAS
        if s.startswith("SELECT status FROM scans WHERE id = %s AND org_id = %s"):
            scan_id, org_id = params
            sc = next((x for x in self.scans if x["id"] == scan_id and x["org_id"] == org_id), None)
            return [{"status": sc["status"]}] if sc else []

        # pipeline boundary checks: status by scan id
        if s.startswith("SELECT status FROM scans WHERE id = %s"):
            scan_id = params[0]
            sc = next((x for x in self.scans if x["id"] == scan_id), None)
            return [{"status": sc["status"]}] if sc else []

        # recon + finalize initial join select
        if "FROM scans s JOIN domains d ON s.domain_id = d.id WHERE s.id = %s" in s:
            scan_id = params[0]
            sc = next((x for x in self.scans if x["id"] == scan_id), None)
            if not sc:
                return []
            dom = next((d for d in self.domains if d["id"] == sc.get("domain_id")), None)
            return [{**sc, "domain": (dom or {}).get("domain") or sc.get("domain") or "example.test"}]

        # recon entry CAS: queued/running -> running (fences cancel-before-dispatch)
        if "SET status = 'running', current_stage = 'discovery', started_at = now()" in s:
            progress, scan_id = params
            sc = next((x for x in self.scans if x["id"] == scan_id), None)
            if not sc or sc.get("status") not in ("queued", "running"):
                return []
            sc["status"] = "running"
            sc["current_stage"] = "discovery"
            sc["stage_progress"] = progress
            sc["started_at"] = sc.get("started_at") or "2026-10-03T00:00:00"
            return [{"id": sc["id"]}]

        # finalize entry CAS: queued/running -> running at security_checks
        if "SET status = 'running', current_stage = %s, stage_progress = %s::jsonb WHERE id = %s AND status IN ('queued', 'running')" in s:
            stage, progress, scan_id = params
            sc = next((x for x in self.scans if x["id"] == scan_id), None)
            if not sc or sc.get("status") not in ("queued", "running"):
                return []
            sc["status"] = "running"
            sc["current_stage"] = stage
            sc["stage_progress"] = progress
            return [{"id": sc["id"]}]

        # completion CAS: running -> completed (score snapshot evidence)
        if "SET status = 'completed', current_stage = 'completed', score = %s" in s:
            score, progress, scan_id = params
            sc = next((x for x in self.scans if x["id"] == scan_id), None)
            if not sc or sc.get("status") != "running":
                return []
            sc.update(
                status="completed", current_stage="completed", score=score,
                stage_progress=progress, completed_at="2026-10-03T00:10:00",
                claimed_by=None, lease_expires_at=None,
            )
            return [{"id": sc["id"]}]

        # terminal-cancel CAS (cancel endpoint)
        if "SET status = 'cancelled', completed_at = now()" in s:
            scan_id, org_id = params
            sc = next((x for x in self.scans if x["id"] == scan_id and x["org_id"] == org_id), None)
            if not sc or sc.get("status") not in ("queued", "running"):
                return []
            sc.update(
                status="cancelled", completed_at="2026-10-03T00:05:00",
                claimed_by=None, lease_expires_at=None,
            )
            return [{"id": sc["id"]}]

        # guarded failure writes: never clobber cancelled/terminal statuses
        if "SET status = 'failed', error_message = %s" in s and "status IN ('queued', 'running')" in s:
            if "stage_progress = %s::jsonb" in s:
                error, progress, scan_id = params
            else:
                error, scan_id = params
                progress = None
            sc = next((x for x in self.scans if x["id"] == scan_id), None)
            if sc and sc.get("status") in ("queued", "running"):
                sc["status"] = "failed"
                sc["error_message"] = error
                sc["completed_at"] = "2026-10-03T00:05:00"
                if progress is not None:
                    sc["stage_progress"] = progress
            return []

        # worker -> core finalize hand-off (worker must still hold the job)
        if "SET claimed_by = 'core-recovery'" in s and "WHERE id = %s AND claimed_by = %s" in s:
            scan_id, scanner_id = params
            sc = next((x for x in self.scans if x["id"] == scan_id), None)
            if not sc or sc.get("claimed_by") != scanner_id or sc.get("status") != "running":
                return []
            sc["claimed_by"] = "core-recovery"
            return [{"id": sc["id"]}]

        # worker terminal failure (must still hold a running job)
        if "SET status = 'failed', error_message = %s" in s and "WHERE id = %s AND claimed_by = %s" in s:
            error, scan_id, scanner_id = params
            sc = next((x for x in self.scans if x["id"] == scan_id), None)
            if sc and sc.get("claimed_by") == scanner_id and sc.get("status") == "running":
                sc.update(
                    status="failed", error_message=error,
                    completed_at="2026-10-03T00:05:00",
                    claimed_by=None, lease_expires_at=None,
                )
            return []

        # score snapshot insert (completion evidence)
        if s.startswith("INSERT INTO score_snapshots"):
            org_id, domain_id, score, subscores, factors = params
            self.snapshots.append({
                "org_id": str(org_id), "score": score,
                "created_at": "2026-10-03T00:10:00",
            })
            return []

        # Unknown statement: behave like an empty result set.
        return []

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
            {"org_id": ORG_A, "score": 70, "created_at": "2026-09-01T00:10:00"},
            {"org_id": ORG_A, "score": 75, "created_at": "2026-09-08T00:10:00"},
        ]
        # Fixture accounts: get_current_user only SELECTs profiles now (a
        # missing profile is a 401, rows are never created from token claims),
        # so every auth_headers() identity needs a row up front. email follows
        # the sign_token default claim ({uid[:8]}@acme.test); deliberately no
        # email_verified_at — OTP/org-gate tests rely on starting unverified.
        now = datetime.now(timezone.utc)
        self.profiles = {
            uid: {
                "id": uid, "email": f"{uid[:8]}@acme.test", "full_name": name,
                "role": "Member", "password_hash": None, "provider": "email",
                "created_at": now,
            }
            for uid, name in (
                (ALICE, "Alice"),
                (BOB, "Bob"),
                (ADMI, "Admin"),
                (CAROL, "Carol"),
                (DAVE, "Dave"),
            )
        }
        self.audit = []
        self.email_otps = []
        self.sessions = []
        self.password_reset_tokens = []
        self.organization_invites = []
        self.reports = []


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
    def _make(user_id: str, email: str | None = None, org: str | None = None,
              sid: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {sign_token(user_id, email or f'{user_id[:8]}@acme.test', sid=sid)}"}
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
