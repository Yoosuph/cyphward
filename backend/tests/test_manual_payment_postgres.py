"""Manual reconciliation against the owned, restricted-role PostgreSQL fixture."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest

from backend.scripts.record_manual_payment import record_payment, validate_destination
from test_owner_views_postgres import urls, world  # noqa: F401


def _payment(world, **changes):
    return {"org_id": world["org"], "actor_id": world["owner"], "plan": "growth",
            "reference": f"BANK-{world['tag']}", "amount_kobo": 2_500_000,
            "reason": "Bank statement independently reconciled, pilot receipt", **changes}


def _call(urls, world, **changes):
    with psycopg.connect(urls[0], row_factory=dict_row) as conn:
        return record_payment(conn, **_payment(world, **changes))


def _state(urls, world):
    with psycopg.connect(urls[0], row_factory=dict_row) as conn:
        sub = conn.execute("SELECT status, plan, current_period_end FROM subscriptions WHERE org_id=%s", (world["org"],)).fetchone()
        count = conn.execute("SELECT count(*) AS n FROM invoices WHERE org_id=%s", (world["org"],)).fetchone()["n"]
        audit = conn.execute("SELECT count(*) AS n FROM owner_audit WHERE actor_user_id=%s AND action='owner.payment_confirmed'", (world["owner"],)).fetchone()["n"]
    return sub, count, audit


def test_dry_run_has_no_invoice_entitlement_or_audit_write(world, urls):
    preview = _call(urls, world)
    assert preview["state"] == "dry_run"
    assert preview["amount_kobo"] == 2_500_000
    assert _state(urls, world) == (None, 0, 0)


def test_confirmed_receipt_activates_once_and_replay_cannot_extend(world, urls):
    first = _call(urls, world, apply=True)
    assert first["state"] == "recorded"
    sub, count, audit = _state(urls, world)
    assert sub["status"] == "active" and count == audit == 1
    assert datetime.now(timezone.utc) + timedelta(days=29) < sub["current_period_end"] < datetime.now(timezone.utc) + timedelta(days=31)
    second = _call(urls, world, apply=True, reference=f"bank-{world['tag']}")
    assert second["state"] == "already_recorded" and second["invoice_id"] == first["invoice_id"]
    assert _state(urls, world) == (sub, 1, 1)


def test_confirmed_renewal_preserves_remaining_paid_time(world, urls):
    _call(urls, world, apply=True)
    before = _state(urls, world)[0]["current_period_end"]
    _call(urls, world, apply=True, reference=f"NEW-{world['tag']}")
    sub, count, audit = _state(urls, world)
    assert sub["current_period_end"] == before + timedelta(days=30)
    assert count == audit == 2


@pytest.mark.parametrize("changes", [{"amount_kobo": 1}, {"plan": "platinum"}, {"reference": "bad"}, {"reason": ""}])
def test_invalid_receipt_never_grants_access(world, urls, changes):
    with pytest.raises(ValueError):
        _call(urls, world, apply=True, **changes)
    assert _state(urls, world) == (None, 0, 0)


def test_customer_identity_cannot_be_recorded_as_operator(world, urls):
    with pytest.raises(ValueError, match="platform owner"):
        _call(urls, world, apply=True, actor_id=world["customer"])
    assert _state(urls, world) == (None, 0, 0)


def test_reference_cannot_be_reused_for_another_plan(world, urls):
    _call(urls, world, apply=True)
    before = _state(urls, world)
    with pytest.raises(ValueError, match="different payment details"):
        _call(urls, world, apply=True, plan="starter", amount_kobo=1_500_000)
    assert _state(urls, world) == before


def test_reference_cannot_be_reused_for_another_organization(world, urls):
    _call(urls, world, apply=True)
    other = str(uuid4())
    with psycopg.connect(urls[0]) as conn:
        conn.execute("INSERT INTO organizations (id,name,slug,plan) VALUES (%s,'Other pilot',%s,'growth')", (other, f"other-{other}"))
    try:
        with pytest.raises(ValueError, match="different payment details"):
            _call(urls, world, apply=True, org_id=other)
    finally:
        with psycopg.connect(urls[0]) as conn:
            assert conn.execute("SELECT id FROM subscriptions WHERE org_id=%s", (other,)).fetchone() is None
            conn.execute("DELETE FROM organizations WHERE id=%s", (other,))


def test_different_live_paid_plan_requires_a_separate_agreement(world, urls):
    _call(urls, world, apply=True)
    with pytest.raises(ValueError, match="still active"):
        _call(urls, world, apply=True, plan="starter", amount_kobo=1_500_000, reference=f"OTHER-{world['tag']}")
    assert _state(urls, world)[1:] == (1, 1)


def test_duplicate_concurrent_receipts_do_not_double_extend(world, urls):
    barrier = Barrier(2)
    def run():
        barrier.wait(timeout=10)
        return _call(urls, world, apply=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda _: run(), range(2)))
    assert {a["state"], b["state"]} == {"recorded", "already_recorded"}
    assert a["invoice_id"] == b["invoice_id"]
    assert _state(urls, world)[1:] == (1, 1)


def test_distinct_concurrent_transfers_preserve_both_paid_periods(world, urls):
    barrier = Barrier(2)
    def run(suffix):
        barrier.wait(timeout=10)
        return _call(urls, world, apply=True, reference=f"{suffix}-{world['tag']}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ["FIRST", "SECOND"]))
    assert all(r["state"] == "recorded" for r in results)
    sub, count, audit = _state(urls, world)
    assert count == audit == 2
    assert datetime.now(timezone.utc) + timedelta(days=59) < sub["current_period_end"] < datetime.now(timezone.utc) + timedelta(days=61)


def test_audit_failure_rolls_back_receipt_and_subscription(world, urls):
    with psycopg.connect(urls[0], row_factory=dict_row) as conn:
        class Cursor:
            def __enter__(self):
                self.cur = conn.cursor()
                return self
            def __exit__(self, *args): self.cur.close()
            def execute(self, statement, params=None):
                if statement.startswith("INSERT INTO owner_audit"):
                    raise RuntimeError("synthetic audit failure")
                return self.cur.execute(statement, params)
            def fetchone(self): return self.cur.fetchone()
        class Connection:
            def transaction(self): return conn.transaction()
            def cursor(self): return Cursor()
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            record_payment(Connection(), **_payment(world), apply=True)
    assert _state(urls, world) == (None, 0, 0)


def test_reference_uniqueness_is_enforced_by_postgres(world, urls):
    _call(urls, world, apply=True)
    with psycopg.connect(urls[0], row_factory=dict_row) as conn:
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO invoices (org_id,plan,amount_kobo,status,provider_ref) VALUES (%s,'growth',2500000,'paid',%s)",
                         (world["org"], f"manual-confirmed:BANK-{world['tag'].upper()}"))


def test_recorded_payment_does_not_repurpose_an_old_open_invoice(world, urls):
    with psycopg.connect(urls[0]) as conn:
        conn.execute("INSERT INTO invoices (org_id,plan,amount_kobo,status) VALUES (%s,'growth',2500000,'open')", (world["org"],))
    _call(urls, world, apply=True)
    with psycopg.connect(urls[0]) as conn:
        assert conn.execute("SELECT status FROM invoices WHERE org_id=%s ORDER BY created_at", (world["org"],)).fetchall() == [("open",), ("paid",)]


def test_manual_destination_requires_explicit_operator_target():
    with pytest.raises(ValueError): validate_destination("", "local")
    with pytest.raises(ValueError): validate_destination("postgresql://user@remote.example/prod", "local")
    with pytest.raises(ValueError): validate_destination("postgresql://user@remote.example/prod", "production")
    validate_destination("postgresql://cyphward_app@127.0.0.1/cyphward_test", "local")


def test_cli_apply_refuses_before_connection_without_payment_confirmation(monkeypatch):
    from backend.scripts import record_manual_payment as script
    monkeypatch.setattr(script.psycopg, "connect", lambda *a, **k: pytest.fail("Must refuse before connecting"))
    with pytest.raises(SystemExit) as refused:
        script.main(["--database-url", "postgresql://cyphward_app@127.0.0.1/cyphward_test", "--org-id", str(uuid4()),
                     "--actor-id", str(uuid4()), "--plan", "growth", "--amount-kobo", "2500000", "--reference", "BANK-123456", "--reason", "Confirmed transfer", "--apply"])
    assert refused.value.code == 2
