"""Compliance evidence against the real, migrated test database (packet C1).

Uses the execution-race fixtures (restricted `cyphward_app`, independent
connections, synthetic tenants). Covers: evidence written inside the fenced
completion; a stale finaliser writes nothing; replay can't duplicate; a
compliance failure never fails a scan; the table is append-only; and the API
is member-readable, tenant-isolated and plan-gated, with live gaps.
"""
import asyncio
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from backend.app.compliance import mapping
from backend.app.compliance.register import DISCLAIMER, REGISTER, tool_requirements
from backend.app.core import scan_execution as ex
from backend.app.core.execution_fence import ClaimLost
from backend.app.core.security import hash_password
from backend.app.core.sessions import issue_session
from backend.app.main import app
from backend.app.workflows import inngest_workflow as wf
from backend.tests.test_scan_execution_postgres import (  # noqa: F401 (fixtures)
    _clean_declared_scope_scan, admission_db, disposable_postgres_url, execution_db, expire, held, no_external,
)

ENC, EMAIL = "ndpa.s39.encryption_in_transit", "ndpa.s39.email_anti_spoofing"
PORTS, CVE = "ndpa.s39.exposed_services_inventoried", "ndpa.s39.known_vulnerability_testing"
PERIODIC = "ndpa.s39.periodic_risk_assessment"


@pytest.fixture
def world(execution_db, monkeypatch):
    conn, org, domains = execution_db
    no_external(monkeypatch)
    people, extra_orgs = [], []

    def member(org_id, role="member"):
        uid = str(uuid4())
        conn.execute("INSERT INTO profiles (id, email, full_name, role, password_hash, provider, email_verified_at) "
                     "VALUES (%s, %s, 'Compliance Tester', 'Member', %s, 'email', now())",
                     (uid, f"c1-{uid[:8]}@compliance.test", hash_password("compliance-pass-1")))
        conn.execute("INSERT INTO organization_members (user_id, org_id, role) VALUES (%s, %s, %s)", (uid, org_id, role))
        conn.commit()
        people.append(uid)
        token = issue_session({"id": uid, "email": f"c1-{uid[:8]}@compliance.test", "full_name": "Compliance Tester",
                               "role": "Member"})["access_token"]
        return {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}

    def other_org():
        oid = str(uuid4())
        conn.execute("INSERT INTO organizations (id, name, slug, sector, plan) VALUES (%s, 'Other Org', %s, 'Retail', 'growth')",
                     (oid, f"other-{oid}"))
        conn.execute("INSERT INTO domains (id, org_id, domain, verification_status, verification_token) "
                     "VALUES (%s, %s, %s, 'verified', %s)", (str(uuid4()), oid, f"other-{oid[:8]}.example.test", f"t-{oid}"))
        conn.commit()
        extra_orgs.append(oid)
        return oid

    yield {"conn": conn, "org": org, "domains": domains, "member": member, "other_org": other_org}
    conn.rollback()
    for oid in extra_orgs:
        conn.execute("DELETE FROM organizations WHERE id = %s", (oid,))
    for uid in people:
        conn.execute("DELETE FROM profiles WHERE id = %s", (uid,))
    conn.commit()


def _checker(findings_for_host):
    async def checks(hostname, dns_item, http_item, is_apex=True):
        return list(findings_for_host(hostname, is_apex))
    return checks


def _finalize(world, monkeypatch, domain_index=0, findings=lambda host, apex: []):
    monkeypatch.setattr(wf, "run_security_checks", _checker(findings))
    core = _clean_declared_scope_scan((world["conn"], world["org"], world["domains"]), domain_index)
    result = asyncio.run(wf.finalize_scan(core.scan_id, core))
    assert result["status"] == "completed"
    return core.scan_id


def _rows(conn, scan_id):
    return {r["requirement_key"]: r for r in conn.execute(
        "SELECT * FROM compliance_evidence WHERE scan_id = %s", (scan_id,)).fetchall()}


def _audit(conn, scan_id):
    return conn.execute("SELECT metadata FROM audit_log WHERE resource_id = %s AND action = 'scan.completed'",
                        (scan_id,)).fetchone()["metadata"]


HSTS = {"title": "Strict-Transport-Security (HSTS) Header Missing", "severity": "high", "category": "HTTP Headers",
        "description": "synthetic", "evidence": {"missing_header": "Strict-Transport-Security"}, "remediation": "x"}
DMARC = {"title": "Missing Email DMARC Authentication Policy", "severity": "critical",
         "category": "DNS & Email Security", "description": "synthetic", "evidence": {"record_type": "TXT"},
         "remediation": "x"}


# ── Write side ─────────────────────────────────────────────────────────────
def test_clean_complete_scan_writes_tool_evidence_inside_the_completion(world, monkeypatch):
    conn = world["conn"]
    scan_id = _finalize(world, monkeypatch)
    rows = _rows(conn, scan_id)
    assert set(rows) == {r["key"] for r in tool_requirements()}
    assert {k: r["status"] for k, r in rows.items()} == {
        ENC: "present", "ndpa.s39.web_security_headers": "present", PORTS: "present", EMAIL: "present",
        CVE: "not_assessed"}
    assert all(r["source"] == "tool_observed" and str(r["domain_id"]) == world["domains"][0] for r in rows.values())
    assert all(r["register_version"] == REGISTER["version"] for r in rows.values())
    assert rows[CVE]["details"]["reason"] == "clean_result_not_provable"
    host = next(iter(rows[PORTS]["details"]["open_ports"]))
    assert rows[PORTS]["details"]["open_ports"][host] == [80, 443]
    assert _audit(conn, scan_id)["compliance_evidence"] == 5
    # Only the scanned domain gets rows.
    assert conn.execute("SELECT count(*) AS n FROM compliance_evidence WHERE domain_id = %s",
                        (world["domains"][1],)).fetchone()["n"] == 0


def test_open_hsts_and_apex_dmarc_findings_are_gaps_linked_to_the_findings(world, monkeypatch):
    conn = world["conn"]
    scan_id = _finalize(world, monkeypatch, findings=lambda host, apex: [HSTS] + ([DMARC] if apex else []))
    rows = _rows(conn, scan_id)
    assert rows[ENC]["status"] == "gap" and rows[EMAIL]["status"] == "gap"
    for key, title in ((ENC, HSTS["title"]), (EMAIL, DMARC["title"])):
        linked = conn.execute("SELECT title, status FROM findings WHERE id = ANY(%s)", (rows[key]["finding_ids"],)).fetchall()
        assert [r["title"] for r in linked] == [title] and linked[0]["status"] == "open"


def test_a_stale_finaliser_writes_no_evidence_and_no_snapshot(world):
    conn, org = world["conn"], world["org"]
    core = ex.handoff_to_core(held((conn, org, world["domains"])))
    rows = mapping.domain_rows(tool_requirements(), None, [], org_id=org, domain_id=world["domains"][0],
                               scan_id=core.scan_id, observed_at=None, register_version=REGISTER["version"])
    expire(conn, core)
    with pytest.raises(ClaimLost):
        ex.finish_assessment(core, org, {"score": None, "subscores": [], "factors": []}, {}, {},
                             {"model": "m", "scope": "s", "title": "t", "body": "b", "severity": "info"},
                             compliance_evidence=rows)
    assert _rows(conn, core.scan_id) == {}
    assert conn.execute("SELECT count(*) AS n FROM score_snapshots WHERE scan_id = %s", (core.scan_id,)).fetchone()["n"] == 0


def test_replayed_rows_cannot_duplicate(world):
    conn, org = world["conn"], world["org"]
    core = ex.handoff_to_core(held((conn, org, world["domains"])))
    rows = mapping.domain_rows(tool_requirements(), None, [], org_id=org, domain_id=world["domains"][0],
                               scan_id=core.scan_id, observed_at=None, register_version=REGISTER["version"])
    with ex.owned_transaction(core) as (cur, _):
        assert ex._insert_compliance_evidence(cur, core, org, rows) == 5
        assert ex._insert_compliance_evidence(cur, core, org, rows) == 5
    assert len(_rows(conn, core.scan_id)) == 5
    assert conn.execute("SELECT count(*) AS n FROM compliance_evidence WHERE scan_id = %s",
                        (core.scan_id,)).fetchone()["n"] == 5


def test_a_mapping_failure_never_fails_the_scan(world, monkeypatch):
    conn = world["conn"]

    def broken(**_):
        raise RuntimeError("mapping bug")

    monkeypatch.setattr(wf, "evidence_for_scan", broken)
    scan_id = _finalize(world, monkeypatch)
    assert _rows(conn, scan_id) == {}
    assert conn.execute("SELECT count(*) AS n FROM score_snapshots WHERE scan_id = %s", (scan_id,)).fetchone()["n"] == 1
    assert _audit(conn, scan_id)["compliance_evidence"] == "error"


def test_a_failed_evidence_insert_rolls_back_alone(world, monkeypatch):
    conn = world["conn"]
    real = wf.evidence_for_scan

    def invalid(**kwargs):
        rows = real(**kwargs)
        rows[-1]["status"] = "compliant"  # violates the status check constraint
        return rows

    monkeypatch.setattr(wf, "evidence_for_scan", invalid)
    scan_id = _finalize(world, monkeypatch)
    assert _rows(conn, scan_id) == {}, "the savepoint rolled back every evidence row"
    assert conn.execute("SELECT status FROM scans WHERE id = %s", (scan_id,)).fetchone()["status"] == "completed"
    assert _audit(conn, scan_id)["compliance_evidence"] == "error"


def test_evidence_is_append_only_for_the_app_role(world, monkeypatch):
    conn = world["conn"]
    scan_id = _finalize(world, monkeypatch)
    for statement in ("UPDATE compliance_evidence SET status = 'present' WHERE scan_id = %s",
                      "DELETE FROM compliance_evidence WHERE scan_id = %s"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement, (scan_id,))
        conn.rollback()


# ── Read side / API ────────────────────────────────────────────────────────
def _req(payload, key):
    return next(r for g in payload["groups"] for r in g["requirements"] if r["key"] == key)


def test_member_reads_evidence_and_scan_history_needs_every_domain(world, monkeypatch):
    conn, org = world["conn"], world["org"]
    conn.execute("UPDATE organizations SET plan = 'growth' WHERE id = %s", (org,))
    conn.commit()
    client, headers = TestClient(app), world["member"](org)
    _finalize(world, monkeypatch, domain_index=0)

    body = client.get("/api/v1/compliance/overview", headers=headers).json()
    assert body["disclaimer"] == DISCLAIMER and body["plan"] == "growth"
    enc = _req(body, ENC)
    # The second verified domain was never scanned: not assessed overall, never present.
    assert enc["status"] == "not_assessed"
    assert [d["status"] for d in enc["domains"]] == ["present", "not_assessed"]
    assert enc["domains"][1]["source"] is None and enc["clause_label"].endswith("reference pending review")
    assert _req(body, PERIODIC)["status"] == "not_assessed"
    assert body["readiness"]["present"] == 0 and body["readiness"]["applicable"] == 29

    _finalize(world, monkeypatch, domain_index=1)
    body = client.get("/api/v1/compliance/overview", headers=headers).json()
    assert _req(body, ENC)["status"] == "present" and _req(body, ENC)["source"] == "tool_observed"
    assert _req(body, PERIODIC)["status"] == "present"
    assert _req(body, CVE)["status"] == "not_assessed"
    assert body["readiness"] == {"percent": 20, "present": 6, "gap": 0, "not_assessed": 23, "applicable": 29}

    detail = client.get(f"/api/v1/compliance/requirements/{ENC}", headers=headers).json()
    assert len(detail["history"]) == 2 and detail["disclaimer"] == DISCLAIMER


def test_a_reopened_finding_turns_stored_present_into_a_live_gap(world, monkeypatch):
    conn, org = world["conn"], world["org"]
    client, headers = TestClient(app), world["member"](org)
    _finalize(world, monkeypatch, domain_index=0)
    asset = conn.execute("SELECT id FROM assets WHERE org_id = %s AND domain_id = %s LIMIT 1",
                         (org, world["domains"][0])).fetchone()["id"]
    fid = conn.execute("INSERT INTO findings (org_id, asset_id, title, description, severity, category, evidence, "
                       "remediation, status) VALUES (%s, %s, %s, 'x', 'high', 'HTTP Headers', '{}'::jsonb, 'x', "
                       "'acknowledged') RETURNING id", (org, asset, HSTS["title"])).fetchone()["id"]
    conn.commit()
    enc = _req(client.get("/api/v1/compliance/overview", headers=headers).json(), ENC)
    assert enc["status"] == "gap" and enc["findings"][0]["id"] == str(fid)
    assert enc["domains"][0]["finding_ids"] == [str(fid)]


def test_tenants_are_isolated(world, monkeypatch):
    conn, org = world["conn"], world["org"]
    _finalize(world, monkeypatch, domain_index=0)
    other = world["other_org"]()
    client, outsider = TestClient(app), world["member"](other)

    body = client.get("/api/v1/compliance/overview", headers=outsider).json()
    assert [d["domain"] for d in body["domains"]] == [f"other-{other[:8]}.example.test"]
    assert all(d["status"] != "present" for g in body["groups"] for r in g["requirements"] for d in r["domains"])
    assert client.get(f"/api/v1/compliance/requirements/{ENC}", headers=outsider).json()["history"] == []
    # An outsider naming the first organization is refused.
    assert client.get("/api/v1/compliance/overview", headers={**outsider, "X-Organization-Id": org}).status_code == 403
    assert client.get("/api/v1/compliance/overview").status_code == 401


def test_starter_sees_readiness_and_security_only(world, monkeypatch):
    client, headers = TestClient(app), world["member"](world["org"])  # fixture organizations are starter
    body = client.get("/api/v1/compliance/overview", headers=headers).json()
    assert body["plan"] == "starter" and body["readiness"]["applicable"] == 29
    locked = {g["key"]: g["locked"] for g in body["groups"]}
    assert locked["security"] is False and all(v for k, v in locked.items() if k != "security")
    assert all(g["requirements"] == [] for g in body["groups"] if g["locked"])
    assert client.get("/api/v1/compliance/requirements/gaid.dpo.designated", headers=headers).status_code == 403
    assert client.get(f"/api/v1/compliance/requirements/{ENC}", headers=headers).status_code == 200
    assert client.get("/api/v1/compliance/requirements/no.such.key", headers=headers).status_code == 404
