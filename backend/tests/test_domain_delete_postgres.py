"""Deleting a domain succeeds when the domain has assets, on the real migrated database.

Regression: the composite foreign keys used ON DELETE SET NULL on (org_id, domain_id),
which tried to null the NOT NULL org_id and failed the delete. The migration limits the
SET NULL to domain_id.
"""
from backend.tests.test_scan_admission_postgres import (  # noqa: F401 (fixtures)
    admission_db, disposable_postgres_url,
)


def test_deleting_a_domain_with_assets_succeeds_and_keeps_the_org_link(admission_db):
    conn, org, domains = admission_db
    conn.execute(
        "INSERT INTO assets (org_id, domain_id, hostname, status, last_seen) "
        "VALUES (%s, %s, 'mail.delete-test.example', 'active', now())",
        (org, domains[0]),
    )
    conn.commit()

    deleted = conn.execute("DELETE FROM domains WHERE id = %s AND org_id = %s RETURNING id", (domains[0], org)).fetchone()
    conn.commit()
    assert deleted is not None

    asset = conn.execute("SELECT org_id, domain_id FROM assets WHERE hostname = 'mail.delete-test.example'").fetchone()
    assert str(asset["org_id"]) == org
    assert asset["domain_id"] is None
