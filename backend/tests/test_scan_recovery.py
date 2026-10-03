"""Startup recovery for scans orphaned by a process restart (review P1 —
durable jobs: FastAPI background tasks need explicit recovery when the API
process stops)."""
import backend.app.core.scan_recovery as scan_recovery


def test_local_mode_fails_orphaned_queued_and_running_scans(monkeypatch):
    calls = []

    def fake_execute_query(sql, params=()):
        calls.append((" ".join(sql.split()), params))
        return [{"id": "s1"}, {"id": "s2"}]

    monkeypatch.setattr(scan_recovery, "SCANNER_MODE", "local")
    monkeypatch.setattr(scan_recovery, "execute_query", fake_execute_query)

    count = scan_recovery.recover_interrupted_scans()

    assert count == 2
    assert len(calls) == 1
    sql, params = calls[0]
    assert sql.startswith("UPDATE scans")
    assert "status = 'failed'" in sql
    assert "claimed_by IS NULL" in sql  # never leased by this process
    assert "status IN ('queued', 'running')" in sql
    assert "RETURNING id" in sql
    assert params == (scan_recovery.INTERRUPTED_MESSAGE,)


def test_remote_mode_is_a_no_op(monkeypatch):
    """remote: queued rows await the worker (claimed_by NULL is the waiting
    state) and running rows carry a lease — recovery must not touch them."""
    def boom(sql, params=()):
        raise AssertionError("must not touch the database in remote mode")

    monkeypatch.setattr(scan_recovery, "SCANNER_MODE", "remote")
    monkeypatch.setattr(scan_recovery, "execute_query", boom)

    assert scan_recovery.recover_interrupted_scans() == 0


def test_recovery_failure_propagates_to_startup_wrapper():
    """The function itself does not swallow DB errors; main.py wraps the
    startup hook so a recovery failure cannot block boot."""
    import inspect

    import backend.app.main as main_mod

    source = inspect.getsource(main_mod.recover_interrupted_scans_on_startup)
    assert "except Exception" in source
    assert "recover_interrupted_scans()" in source
