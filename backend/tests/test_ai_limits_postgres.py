"""AI usage limits against the owned, restricted-role PostgreSQL fixture: the stream
lease SQL and the per-user / per-organisation buckets."""
from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.rows import dict_row

import backend.app.core.ai_limits as limits
import backend.app.core.database as database
from test_owner_views_postgres import urls  # noqa: F401


@pytest.fixture
def db(urls, monkeypatch):
    app_url, admin_url = urls

    @contextmanager
    def get_db():
        conn = psycopg.connect(app_url, row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(database, "get_db", get_db)
    tag = uuid4().hex
    yield admin_url, tag
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("DELETE FROM rate_limits WHERE bucket_key LIKE %s", (f"%{tag}%",))


def _age(admin_url, key, seconds):
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("UPDATE rate_limits SET window_start = now() - make_interval(secs => %s) WHERE bucket_key = %s",
                     (float(seconds), key))


def test_two_stream_leases_per_user_then_429(db):
    _admin, user = db
    first, second = limits.acquire_stream_slot(user), limits.acquire_stream_slot(user)
    assert first[0] != second[0]
    with pytest.raises(HTTPException) as refused:
        limits.acquire_stream_slot(user)
    assert refused.value.status_code == 429 and refused.value.headers["Retry-After"]
    assert limits.acquire_stream_slot(f"other-{user}")  # another user is unaffected
    limits.release_stream_slot(first)
    assert limits.acquire_stream_slot(user)[0] == first[0]


def test_abandoned_lease_expires_and_stale_release_keeps_the_new_holder(db):
    admin_url, user = db
    first = limits.acquire_stream_slot(user)
    limits.acquire_stream_slot(user)
    _age(admin_url, first[0], limits.STREAM_LEASE_SECONDS + 5)
    reclaimed = limits.acquire_stream_slot(user)
    assert reclaimed[0] == first[0] and reclaimed[1] != first[1]
    limits.release_stream_slot(first)  # the old holder finishing late must not free the new lease
    with pytest.raises(HTTPException):
        limits.acquire_stream_slot(user)
    limits.release_stream_slot(reclaimed)
    assert limits.acquire_stream_slot(user)


def test_upstream_charges_share_the_org_bucket(db, monkeypatch):
    _admin, org = db
    monkeypatch.setenv("CYPHWARD_AI_ORG_MAX_PER_HOUR", "3")
    budget = limits._Budget(org)
    token = limits._budget.set(budget)
    try:
        limits.check_rate_limit(limits.org_bucket(org), limits.org_limit(), limits.AI_WINDOW_SECONDS)  # admission
        assert limits.charge_upstream_attempt()  # prepaid by admission
        assert limits.charge_upstream_attempt()  # 2
        assert limits.charge_upstream_attempt()  # 3
        assert not limits.charge_upstream_attempt()  # over the limit: skipped, never raised
        assert budget.attempts == 4
    finally:
        limits._budget.reset(token)
