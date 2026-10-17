"""Deleting a domain succeeds on the real migrated database, and removes what belongs to it.

Regression: the composite foreign keys used ON DELETE SET NULL on (org_id, domain_id), which tried to
null the NOT NULL org_id and failed the delete. Now:
  - assets are deleted with the domain;
  - reports and score snapshots keep their row and lose only domain_id.
"""
from uuid import uuid4

import psycopg.types.json

from backend.app.core import scan_admission as admission
from backend.tests.test_scan_admission_postgres import (  # noqa: F401 (fixtures)
    admission_db, disposable_postgres_url,
)


def _seed(conn, org, domain):
    asset = conn.execute(
        "INSERT INTO assets (org_id, domain_id, hostname, status, last_seen) "
        "VALUES (%s, %s, %s, 'active', now()) RETURNING id",
        (org, domain, f"mail-{domain[:8]}.delete-test.example")).fetchone()["id"]
    conn.commit()  # admission takes its own locks on the domain: do not hold ours open
    scan = str(admission.admit_scan(org, domain, request_scope="delete-test", request_key=str(uuid4())).scan["id"])
    conn.execute(
        "INSERT INTO findings (org_id, asset_id, scan_id, title, description, severity, category, evidence, remediation, status) "
        "VALUES (%s, %s, %s, 'Delete test', 'x', 'high', 'HTTP Headers', %s, 'x', 'open')",
        (org, asset, scan, psycopg.types.json.Jsonb({})))
    report = conn.execute("INSERT INTO reports (org_id, domain_id, title) VALUES (%s, %s, 'Delete test report') RETURNING id",
                          (org, domain)).fetchone()["id"]
    snapshot = conn.execute("INSERT INTO score_snapshots (org_id, domain_id, score) VALUES (%s, %s, 80) RETURNING id",
                            (org, domain)).fetchone()["id"]
    conn.commit()
    return asset, report, snapshot


def test_deleting_a_domain_removes_its_assets_and_keeps_reports_and_snapshots(admission_db):
    conn, org, domains = admission_db
    asset, report, snapshot = _seed(conn, org, domains[0])

    deleted = conn.execute("DELETE FROM domains WHERE id = %s AND org_id = %s RETURNING id", (domains[0], org)).fetchone()
    conn.commit()
    assert deleted is not None

    assert conn.execute("SELECT count(*) AS n FROM assets WHERE id = %s", (asset,)).fetchone()["n"] == 0, \
        "an asset belongs to the domain and goes with it"
    assert conn.execute("SELECT count(*) AS n FROM findings WHERE asset_id = %s OR org_id = %s AND title = 'Delete test'",
                        (asset, org)).fetchone()["n"] == 0, "no finding of the domain is left behind"
    kept_report = conn.execute("SELECT org_id, domain_id FROM reports WHERE id = %s", (report,)).fetchone()
    kept_snapshot = conn.execute("SELECT org_id, domain_id FROM score_snapshots WHERE id = %s", (snapshot,)).fetchone()
    assert str(kept_report["org_id"]) == org and kept_report["domain_id"] is None
    assert str(kept_snapshot["org_id"]) == org and kept_snapshot["domain_id"] is None


def test_another_domains_rows_are_untouched(admission_db):
    conn, org, domains = admission_db
    _seed(conn, org, domains[0])
    other_asset, other_report, other_snapshot = _seed(conn, org, domains[1])

    conn.execute("DELETE FROM domains WHERE id = %s AND org_id = %s", (domains[0], org))
    conn.commit()

    assert conn.execute("SELECT domain_id FROM assets WHERE id = %s", (other_asset,)).fetchone()["domain_id"] is not None
    assert str(conn.execute("SELECT domain_id FROM reports WHERE id = %s", (other_report,)).fetchone()["domain_id"]) == domains[1]
    assert str(conn.execute("SELECT domain_id FROM score_snapshots WHERE id = %s", (other_snapshot,)).fetchone()["domain_id"]) == domains[1]


def test_the_migration_is_one_transaction_with_timeouts():
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"
           / "20261017170000_domain_delete_set_null_column.sql").read_text()
    body = [line.strip() for line in sql.splitlines() if line.strip() and not line.strip().startswith("--")]
    assert body[0] == "BEGIN;" and body[-1] == "COMMIT;"
    assert "SET LOCAL lock_timeout" in sql and "SET LOCAL statement_timeout" in sql
