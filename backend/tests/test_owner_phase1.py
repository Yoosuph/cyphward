"""Owner console phase 1 (docs/admin-2026-10-29): checks that need no database.

The PostgreSQL behaviour (access, audit rows, suspension, member removal, exports) is in
test_owner_phase1_postgres.py. This file covers the pieces that must hold whatever the data: every new route sits
behind the owner session, sort and filter values map to fixed SQL, CSV cells are spreadsheet-safe, analytics
responses are built from counts only, the migration is additive, and no new copy uses claim wording.
"""
import json
import re
from pathlib import Path
from typing import get_args

import pytest

from backend.app.api import owner_actions, owner_analytics, owner_exports, owner_views
from backend.app.core import owner as owner_mod
from backend.app.core import owner_lists, owner_reads

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase" / "migrations" / "20261030100000_organization_suspension.sql"
BANNED = (
    "compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit",
    "compliance score", "fully meets", "meets the requirement", "is met", "adequate", "adequacy", "guarantee",
)


def _dependency_calls(route):
    seen, stack = set(), list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        seen.add(dep.call)
        stack.extend(dep.dependencies)
    return seen


def _routes(router, prefix=""):
    return [r for r in router.routes if getattr(r, "path", "").startswith(prefix)]


def test_every_new_route_needs_an_owner_session():
    routes = _routes(owner_analytics.router) + _routes(owner_exports.router)
    assert {r.path for r in routes} == {
        "/api/v1/owner/analytics/summary", "/api/v1/owner/analytics/timeseries",
        "/api/v1/owner/exports/organizations.csv", "/api/v1/owner/exports/users.csv",
        "/api/v1/owner/exports/subscriptions.csv",
    }
    for route in routes:
        assert route.methods == {"GET"}, route.path
        assert owner_mod.require_owner in _dependency_calls(route), route.path
    for route in owner_actions.router.routes:
        assert route.methods == {"POST"}, route.path
        assert owner_mod.require_owner_mutation in _dependency_calls(route), route.path
    actions = {r.path for r in owner_actions.router.routes}
    assert {"/api/v1/owner/organizations/{org_id}/suspend", "/api/v1/owner/organizations/{org_id}/unsuspend",
            "/api/v1/owner/organizations/{org_id}/members/{user_id}/remove"} <= actions
    for route in owner_views.router.routes:
        assert owner_mod.require_owner in _dependency_calls(route), route.path


def test_organization_actions_need_the_typed_name():
    for model in (owner_actions.PlanBody, owner_actions.TrialBody, owner_actions.OrgActionBody):
        assert model.model_fields["confirm_name"].is_required()
        assert model.model_fields["reason"].is_required()


def test_every_sort_value_maps_to_fixed_sql():
    assert set(get_args(owner_lists.OrgSort)) == set(owner_lists._ORG_SORT)
    assert set(get_args(owner_lists.UserSort)) == set(owner_lists._USER_SORT)
    assert set(get_args(owner_lists.SubSort)) == set(owner_lists._SUB_SORT)
    for mapping in (owner_lists._ORG_SORT, owner_lists._USER_SORT, owner_lists._SUB_SORT):
        for expr in mapping.values():
            assert re.fullmatch(r"(lower\()?x\.[a-z_]+\)?", expr), expr
    rows, total = owner_lists.organizations("acme", "paid", "", "yes", "members", "asc", 50, 0)
    assert "ORDER BY x.members ASC NULLS LAST, x.id ASC" in rows[0]
    assert rows[1]["like"] == "%acme%" and "acme" not in rows[0]


def test_search_text_is_escaped_for_like():
    assert owner_lists.like("50%_off\\") == "%50\\%\\_off\\\\%"
    assert len(owner_lists.like("x" * 500)) == 102


def test_page_size_is_capped_not_refused():
    assert owner_reads.page_size(500) == 100
    assert owner_reads.page_size(100) == 100
    assert owner_reads.page_size(1) == 1
    assert owner_reads.EXPORT_MAX == 10_000


@pytest.mark.parametrize("value, expected", [
    ("=SUM(A1)", "'=SUM(A1)"), ("+1", "'+1"), ("-2", "'-2"), ("@cmd", "'@cmd"), ("\tx", "'\tx"), ("\rx", "'\rx"),
    ("Acme Ltd", "Acme Ltd"), (None, ""), (True, "yes"), (False, "no"), (3, "3"),
])
def test_csv_cells_are_spreadsheet_safe(value, expected):
    assert owner_reads.csv_cell(value) == expected


def test_csv_writes_headers_and_rows():
    out = owner_reads.to_csv((("a", "first"), ("b", "second")), [{"a": "=1", "b": "x,y"}])
    assert out == "first,second\r\n'=1,\"x,y\"\r\n"


def _fake_owner():
    return {"user_id": "u", "email": "owner@example.test", "session_id": "s"}


def test_analytics_responses_are_built_from_counts_only(monkeypatch):
    """Even if a query returned extra columns, nothing but counts reaches the response."""
    leaky = {"title": "SECRET finding title", "email": "someone@example.test", "domain": "secret.example",
             "hostname": "host.secret.example"}
    audits = []
    monkeypatch.setattr(owner_mod, "audit", lambda *a, **k: audits.append(a[1]))

    def fake_summary_read(statements):
        assert all("statement_timeout" not in sql for sql, _ in statements)
        return [[{"total": 5, "new_in_range": 1, "suspended": 1, **leaky}],
                [{"billing": "paid", "n": 2, **leaky}, {"billing": "free", "n": 3, **leaky}],
                [{"status": "active", "n": 2, **leaky}],
                [{"status": "completed", "n": 3, **leaky}, {"status": "failed", "n": 1, **leaky}],
                [{"total": 9, "new_in_range": 2, **leaky}]]

    monkeypatch.setattr(owner_reads, "bounded_read", fake_summary_read)
    s = owner_analytics.summary(None, "30", _fake_owner())
    assert s["scans"]["success_rate"] == 0.75 and s["billing"] == {"paid": 2, "trialing": 0, "free": 3}

    def fake_series_read(statements):
        return [[{"day": "2000-01-01", "status": "completed", "n": 1, **leaky}],
                [{"day": "2000-01-01", "severity": "high", "n": 1, **leaky}]]

    monkeypatch.setattr(owner_reads, "bounded_read", fake_series_read)
    t = owner_analytics.timeseries(None, "7", _fake_owner())
    assert len(t["scans_per_day"]) == 7 and len(t["findings_per_day"]) == 7
    text = json.dumps(s, default=str) + json.dumps(t, default=str)
    assert "SECRET" not in text and "secret.example" not in text and "@" not in text
    assert audits == ["owner.view.analytics_summary", "owner.view.analytics_timeseries"]


def test_analytics_sql_never_selects_customer_content():
    source = Path(owner_analytics.__file__).read_text()
    sql = " ".join(re.findall(r'"""(.*?)"""', source, flags=re.S)[1:])  # every SQL block, not the module docstring
    for column in ("title", "description", "email", "domain", "hostname", "evidence", "remediation", "full_name"):
        assert not re.search(rf"\b{column}\b", sql), column


def test_migration_is_additive_with_timeouts():
    text = MIGRATION.read_text()
    body = "\n".join(line for line in text.splitlines() if not line.startswith("--"))
    statements = [s.strip() for s in body.split(";") if s.strip()]
    assert statements[:3] == ["BEGIN", "SET LOCAL lock_timeout = '5s'", "SET LOCAL statement_timeout = '60s'"]
    assert statements[-1] == "COMMIT"
    assert "CREATE TABLE IF NOT EXISTS organization_suspensions" in body
    assert "CREATE INDEX IF NOT EXISTS" in body
    for forbidden in ("DROP TABLE", "DROP COLUMN", "ALTER TABLE organizations", "DISABLE ROW LEVEL SECURITY",
                      "GRANT DELETE", "TRUNCATE", "DELETE FROM"):
        assert forbidden not in body.upper().replace("  ", " "), forbidden


def test_new_backend_copy_has_no_claim_wording():
    files = [Path(m.__file__) for m in (owner_actions, owner_analytics, owner_exports, owner_views, owner_reads,
                                        owner_lists)] + [MIGRATION]
    hits = [f"{f.name}: {p}" for f in files for p in BANNED if p in f.read_text(encoding="utf-8").lower()]
    assert not hits, hits
