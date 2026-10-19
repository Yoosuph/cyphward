"""Evidence file uploads against the real, migrated test database (packet C6), with the in-memory storage fake.

Runs only against the owned loopback `cyphward_test` database through the restricted `cyphward_app` role. No test
can reach Supabase Storage. Covers: grants and the guard trigger; the migration (one transaction, timeouts,
idempotent, private bucket where a storage schema exists); upload/list/download/remove through the API with roles,
the Starter gate and cross-tenant ids; attachment-only signed links; the file, byte and rate caps, also under
concurrency; a failed insert deleting the object; no database connection while bytes move; lock waits as 503;
audit rows without names; removal and its reconcile; organisation closing and its failure paths; snapshots and
packs carrying no file data; no service key anywhere.
"""
import asyncio
import json
import logging
import os
import pathlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from urllib.parse import quote
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from backend.app import storage as file_storage
from backend.app.api import compliance as api
from backend.app.compliance import attestation_store
from backend.app.compliance import evidence_file_store as store
from backend.app.compliance import evidence_files as ef
from backend.app.core import database
from backend.app.main import app
from backend.app.storage import StorageError, SupabaseStorage
from backend.app.storage.base import StoredObject  # noqa: F401
from backend.app.storage.memory import MemoryStorage
from backend.tests.evidence_samples import DOCX, JPEG, PDF, PNG
from backend.tests.test_compliance_attestations_postgres import _record, world  # noqa: F401 (fixture)
from backend.tests.test_scan_admission_postgres import disposable_postgres_url  # noqa: F401 (fixture)
from backend.tests.test_snapshots_postgres import _assessed_org, _create, world as snapshot_world  # noqa: F401

BASE = "/api/v1/compliance/evidence-files"
KEY = "breach.response_plan"
MIGRATION = pathlib.Path(__file__).resolve().parents[2] / "supabase/migrations/20261019100000_compliance_evidence_files.sql"


@pytest.fixture
def team(world):  # noqa: F811
    org_id = world.make_org()
    return org_id, world.make_person(org_id, "owner"), world.make_person(org_id, "admin"), world.make_person(org_id, "member")


def _upload(world, org_id, uid, name="policy.pdf", data=PDF, key=KEY, ctype="application/octet-stream", **kw):
    headers = {**world.headers(uid, org_id), "X-File-Name": quote(name), "Content-Type": ctype}
    return world.client.post(f"{BASE}?question_key={key}", content=data, headers=headers, **kw)


def _download(world, org_id, uid, file_id):
    return world.client.get(f"{BASE}/{file_id}/download", headers=world.headers(uid, org_id))


def _remove(world, org_id, uid, file_id):
    return world.client.delete(f"{BASE}/{file_id}", headers=world.headers(uid, org_id))


def _rows(world, org_id):
    return world.rows("SELECT * FROM compliance_evidence_files WHERE org_id = %s ORDER BY uploaded_at", (org_id,))


def _audit(world, org_id, action=None):
    sql, params = "SELECT action, user_id, resource_id, metadata FROM audit_log WHERE org_id = %s", [org_id]
    if action:
        sql, params = sql + " AND action = %s", params + [action]
    return world.rows(sql + " ORDER BY created_at", tuple(params))


@pytest.fixture
def fake(fake_file_storage):
    return fake_file_storage


# ── Grants, guard and migration ───────────────────────────────────────────────


def test_the_app_role_can_select_insert_and_update_only_the_removal_columns(world):
    rows = world.rows(
        "SELECT privilege_type FROM information_schema.role_table_grants WHERE grantee = 'cyphward_app' "
        "AND table_name = 'compliance_evidence_files' ORDER BY 1")
    assert [r["privilege_type"] for r in rows] == ["INSERT", "SELECT"]
    columns = world.rows(
        "SELECT column_name FROM information_schema.column_privileges WHERE grantee = 'cyphward_app' "
        "AND table_name = 'compliance_evidence_files' AND privilege_type = 'UPDATE' ORDER BY 1")
    assert [c["column_name"] for c in columns] == ["removed_at", "removed_by"]


def test_rls_is_on_and_there_is_no_delete_or_truncate(world, team):
    org_id, owner, *_ = team
    assert world.rows("SELECT relrowsecurity FROM pg_class WHERE relname = 'compliance_evidence_files'")[0]["relrowsecurity"]
    file_id = _upload(world, org_id, owner).json()["id"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(world.url) as conn:
            conn.execute("DELETE FROM compliance_evidence_files WHERE id = %s", (file_id,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(world.url) as conn:
            conn.execute("UPDATE compliance_evidence_files SET display_name = 'x' WHERE id = %s", (file_id,))


def test_the_guard_lets_a_row_be_marked_removed_once_and_nothing_else(world, team):
    org_id, owner, *_ = team
    file_id = _upload(world, org_id, owner).json()["id"]
    with psycopg.connect(world.url) as conn:
        conn.execute("UPDATE compliance_evidence_files SET removed_at = now(), removed_by = %s WHERE id = %s", (owner, file_id))
    for sql in ("UPDATE compliance_evidence_files SET removed_at = NULL WHERE id = %s",
                "UPDATE compliance_evidence_files SET removed_at = now() + interval '1 day' WHERE id = %s"):
        with pytest.raises(psycopg.errors.RaiseException):
            with psycopg.connect(world.url) as conn:
                conn.execute(sql, (file_id,))


def test_the_database_refuses_a_path_that_is_not_derived_from_the_ids_and_other_types_and_sizes(world, team):
    org_id, owner, *_ = team
    base = ("INSERT INTO compliance_evidence_files (id, org_id, question_key, display_name, content_type, size_bytes, "
            "sha256, storage_path) VALUES (%s, %s, 'k', 'a.pdf', %s, %s, %s, %s)")
    sha = "a" * 64
    fid = str(uuid4())
    good = (fid, org_id, "application/pdf", 10, sha, f"org/{org_id}/{fid}")
    for bad in ((fid, org_id, "application/pdf", 10, sha, "org/x/y.pdf"),
                (fid, org_id, "text/html", 10, sha, f"org/{org_id}/{fid}"),
                (fid, org_id, "application/pdf", ef.MAX_BYTES + 1, sha, f"org/{org_id}/{fid}"),
                (fid, org_id, "application/pdf", 0, sha, f"org/{org_id}/{fid}"),
                (fid, org_id, "application/pdf", 10, "nothex", f"org/{org_id}/{fid}")):
        with pytest.raises(psycopg.errors.CheckViolation):
            with psycopg.connect(world.url) as conn:
                conn.execute(base, bad)
    with psycopg.connect(world.url) as conn:
        conn.execute(base, good)


def test_a_file_cannot_point_at_another_organisations_answer(world, team):
    org_id, owner, *_ = team
    other = world.make_org()
    other_owner = world.make_person(other, "owner")
    theirs = _record(world, other, other_owner)["id"]
    fid = str(uuid4())
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(world.url) as conn:
            conn.execute(
                "INSERT INTO compliance_evidence_files (id, org_id, question_key, attestation_id, display_name, "
                "content_type, size_bytes, sha256, storage_path) VALUES (%s, %s, 'k', %s, 'a.pdf', 'application/pdf', 1, %s, %s)",
                (fid, org_id, theirs, "a" * 64, f"org/{org_id}/{fid}"))


def test_deleting_an_uploaders_profile_keeps_the_file_and_clears_the_name(world, team):
    org_id, owner, admin, member = team
    file_id = _upload(world, org_id, admin).json()["id"]
    world.setup.execute("DELETE FROM organization_members WHERE user_id = %s", (admin,))
    world.setup.execute("DELETE FROM profiles WHERE id = %s", (admin,))
    world.setup.commit()
    row = _rows(world, org_id)[0]
    assert str(row["id"]) == file_id and row["uploaded_by"] is None
    listing = world.client.get(BASE, headers=world.headers(owner, org_id)).json()
    assert listing["files"][0]["uploaded_by"] is None


def test_the_migration_is_one_transaction_with_timeouts_and_is_additive():
    text = MIGRATION.read_text()
    assert len(re.findall(r"^BEGIN;", text, re.M)) == 1 and len(re.findall(r"^COMMIT;", text, re.M)) == 1
    body = text.split("BEGIN;", 1)[1].lstrip()
    assert body.startswith("SET LOCAL lock_timeout = '5s';\nSET LOCAL statement_timeout = '60s';")
    assert not re.search(r"\b(DROP TABLE|DROP COLUMN|TRUNCATE|DELETE FROM|ALTER COLUMN)\b", text)
    assert "CREATE TABLE IF NOT EXISTS" in text and "to_regclass('storage.buckets') IS NOT NULL" in text
    assert "CREATE POLICY" in text and "ON storage.objects" not in text  # no policy on storage objects


def test_the_migration_is_idempotent_and_the_bucket_is_created_private_where_storage_exists():
    admin = os.environ.get("CYPHWARD_TEST_DATABASE_ADMIN_URL")
    if not admin:
        pytest.skip("needs the admin URL of the local test database")
    sql = MIGRATION.read_text()
    inner = sql.replace("\nBEGIN;", "\n", 1).replace("\nCOMMIT;", "\n")
    with psycopg.connect(admin) as conn:
        conn.execute(sql)  # whole file, twice: plain re-run
        conn.execute(sql)
        conn.execute("CREATE SCHEMA storage")  # then pretend to be Supabase, inside a transaction we roll back
        conn.execute("CREATE TABLE storage.buckets (id text PRIMARY KEY, name text NOT NULL, public boolean DEFAULT false, "
                     "file_size_limit bigint, allowed_mime_types text[])")
        conn.execute(inner)
        conn.execute("UPDATE storage.buckets SET public = true, file_size_limit = 1")  # drift
        conn.execute(inner)  # a re-run puts it right again
        bucket = conn.execute("SELECT id, name, public, file_size_limit, allowed_mime_types FROM storage.buckets").fetchall()
        conn.rollback()
    assert len(bucket) == 1
    bid, name, public, limit, mimes = bucket[0]
    assert (bid, name, public, limit) == ("evidence-files", "evidence-files", False, 10485760)
    assert sorted(mimes) == sorted(ef.ALLOWED_TYPES.values())
    with psycopg.connect(admin) as conn:
        assert conn.execute("SELECT to_regclass('storage.buckets')").fetchone()[0] is None  # rolled back


# ── Upload ────────────────────────────────────────────────────────────────────


def test_owner_and_admin_upload_and_the_object_lands_under_the_org_path(world, team, fake):
    org_id, owner, admin, member = team
    for uid in (owner, admin):
        resp = _upload(world, org_id, uid, name="board policy.pdf")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["display_name"] == "board policy.pdf" and body["size_bytes"] == len(PDF)
        assert f"org/{org_id}/{body['id']}" in fake.objects
    assert len(_rows(world, org_id)) == 2
    assert all(p.startswith(f"org/{org_id}/") and "policy" not in p for p in fake.objects)


def test_the_stored_type_comes_from_the_bytes_not_the_client_header(world, team, fake):
    org_id, owner, *_ = team
    resp = _upload(world, org_id, owner, name="scan.png", data=PNG, ctype="text/html")
    assert resp.status_code == 201
    assert resp.json()["content_type"] == "image/png"
    (data, stored_type, _) = fake.objects[f"org/{org_id}/{resp.json()['id']}"]
    assert stored_type == "image/png" and _rows(world, org_id)[0]["content_type"] == "image/png"


@pytest.mark.parametrize("name,data", [("a.jpg", JPEG), ("a.jpeg", JPEG), ("a.docx", DOCX), ("a.png", PNG)])
def test_every_allowed_type_uploads(world, team, name, data):
    org_id, owner, *_ = team
    assert _upload(world, org_id, owner, name=name, data=data).status_code == 201


@pytest.mark.parametrize("name,data,status", [
    ("tool.exe", PDF, 422), ("page.html", b"<html>", 422), ("a.pdf", PNG, 422), ("a.png", PDF, 422),
    ("a.pdf", b"", 422), ("a.docx", PDF, 422), ("evil.php.png", PNG, 422), ("a.pdf", b"x" * 20, 422),
    ("a.pdf", PDF + b"0" * ef.MAX_BYTES, 413)])
def test_rejections_store_nothing(world, team, fake, name, data, status):
    org_id, owner, *_ = team
    resp = _upload(world, org_id, owner, name=name, data=data)
    assert resp.status_code == status, resp.text
    assert fake.objects == {} and _rows(world, org_id) == []


def test_a_zip_bomb_is_refused_at_the_api(world, team, fake):
    from backend.tests.evidence_samples import docx
    org_id, owner, *_ = team
    resp = _upload(world, org_id, owner, name="a.docx", data=docx({"word/media/big.bin": b"\0" * (30 * 1024 * 1024)}))
    assert resp.status_code == 422 and fake.objects == {}


def test_path_and_control_characters_in_names_are_cleaned(world, team, fake):
    org_id, owner, *_ = team
    resp = _upload(world, org_id, owner, name="..\\..\\etc/pass\x00wd‮​.pdf")
    assert resp.status_code == 201
    assert resp.json()["display_name"] == "passwd.pdf"
    assert all(".." not in p for p in fake.objects)


def test_the_header_name_may_not_be_missing_or_an_unknown_question(world, team, fake):
    org_id, owner, *_ = team
    headers = {**world.headers(owner, org_id), "Content-Type": "application/octet-stream"}
    assert world.client.post(f"{BASE}?question_key={KEY}", content=PDF, headers=headers).status_code == 422
    assert _upload(world, org_id, owner, key="no.such.question").status_code == 404
    assert fake.objects == {}


def test_members_cannot_upload_or_remove_but_can_list(world, team, fake):
    org_id, owner, admin, member = team
    file_id = _upload(world, org_id, owner).json()["id"]
    assert _upload(world, org_id, member).status_code == 403
    assert _remove(world, org_id, member, file_id).status_code == 403
    listing = world.client.get(BASE, headers=world.headers(member, org_id))
    assert listing.status_code == 200 and [f["id"] for f in listing.json()["files"]] == [file_id]
    assert len(fake.objects) == 1 and _rows(world, org_id)[0]["removed_at"] is None


def test_starter_gets_the_growth_plan_403_on_everything(world, fake):
    org_id = world.make_org("starter")
    owner = world.make_person(org_id, "owner")
    fid = str(uuid4())
    assert _upload(world, org_id, owner).status_code == 403
    assert world.client.get(BASE, headers=world.headers(owner, org_id)).status_code == 403
    assert _download(world, org_id, owner, fid).status_code == 403
    assert _remove(world, org_id, owner, fid).status_code == 403
    assert fake.objects == {} and fake.calls == []


def test_a_file_is_linked_to_the_answer_current_at_upload_time(world, team):
    org_id, owner, *_ = team
    before = _upload(world, org_id, owner).json()
    answer = _record(world, org_id, owner)
    after = _upload(world, org_id, owner).json()
    assert before["attestation_id"] is None and after["attestation_id"] == answer["id"]
    listing = world.client.get(f"{BASE}?question_key={KEY}", headers=world.headers(owner, org_id)).json()
    assert len(listing["files"]) == 2 and listing["usage"]["files"] == 2


def test_listing_is_scoped_to_the_callers_organisation(world, team):
    org_id, owner, *_ = team
    other = world.make_org()
    other_owner = world.make_person(other, "owner")
    _upload(world, other, other_owner)
    mine = _upload(world, org_id, owner).json()["id"]
    ids = [f["id"] for f in world.client.get(BASE, headers=world.headers(owner, org_id)).json()["files"]]
    assert ids == [mine]


# ── Download ──────────────────────────────────────────────────────────────────


def test_download_returns_a_short_lived_attachment_link_and_audits_it(world, team, fake):
    org_id, owner, admin, member = team
    file_id = _upload(world, org_id, owner, name="Board minutes.docx", data=DOCX).json()["id"]
    resp = _download(world, org_id, member, file_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["expires_in"] == 60 and body["display_name"] == "Board minutes.docx"
    assert "download=Board%20minutes.docx" in body["url"] and "token=" in body["url"]
    assert fake.signed[-1]["expires_in"] == 60
    assert resp.headers["cache-control"] == "no-store"
    assert "inline" not in body["url"] and "public" not in body["url"]
    events = _audit(world, org_id, "compliance.evidence_file.download_link_issued")
    assert len(events) == 1 and str(events[0]["user_id"]) == member
    assert events[0]["metadata"]["file_id"] == file_id


def test_another_organisations_file_and_malformed_ids_are_404(world, team, fake):
    org_id, owner, *_ = team
    other = world.make_org()
    other_owner = world.make_person(other, "owner")
    theirs = _upload(world, other, other_owner).json()["id"]
    assert _download(world, org_id, owner, theirs).status_code == 404
    assert _remove(world, org_id, owner, theirs).status_code == 404
    assert fake.signed == []
    assert _rows(world, other)[0]["removed_at"] is None and len(fake.objects) == 1
    for bad in ("not-a-uuid", "1", "../etc", "%00"):
        assert _download(world, org_id, owner, bad).status_code == 404
        assert _remove(world, org_id, owner, bad).status_code == 404
    assert _download(world, org_id, owner, str(uuid4())).status_code == 404


def test_a_removed_file_no_longer_downloads(world, team, fake):
    org_id, owner, *_ = team
    file_id = _upload(world, org_id, owner).json()["id"]
    assert _remove(world, org_id, owner, file_id).status_code == 200
    assert _download(world, org_id, owner, file_id).status_code == 404
    assert world.client.get(BASE, headers=world.headers(owner, org_id)).json()["files"] == []


def test_a_storage_error_while_signing_is_a_clean_502_and_a_missing_object_a_404(world, team, fake):
    org_id, owner, *_ = team
    file_id = _upload(world, org_id, owner).json()["id"]
    fake.fail_sign = True
    assert _download(world, org_id, owner, file_id).status_code == 502
    fake.fail_sign = False
    fake.objects.clear()
    assert _download(world, org_id, owner, file_id).status_code == 404


# ── Removal and reconcile ─────────────────────────────────────────────────────


def test_removal_soft_deletes_the_row_removes_the_object_and_audits_without_the_name(world, team, fake):
    org_id, owner, admin, member = team
    file_id = _upload(world, org_id, owner, name="secret-name.pdf").json()["id"]
    resp = _remove(world, org_id, admin, file_id)
    assert resp.status_code == 200 and resp.json() == {"id": file_id, "removed": True, "object_deleted": True}
    row = _rows(world, org_id)[0]
    assert row["removed_at"] is not None and str(row["removed_by"]) == admin and fake.objects == {}
    assert _remove(world, org_id, admin, file_id).status_code == 404  # already removed
    events = _audit(world, org_id)
    assert [e["action"] for e in events if e["action"].startswith("compliance.evidence_file")] == [
        "compliance.evidence_file.uploaded", "compliance.evidence_file.removed"]


def test_audit_rows_carry_ids_size_type_and_question_but_never_the_name(world, team, fake):
    org_id, owner, *_ = team
    file_id = _upload(world, org_id, owner, name="very-identifying-name.pdf").json()["id"]
    _download(world, org_id, owner, file_id)
    _remove(world, org_id, owner, file_id)
    events = [e for e in _audit(world, org_id) if e["action"].startswith("compliance.evidence_file")]
    assert len(events) == 3
    for event in events:
        meta = event["metadata"]
        assert meta["file_id"] == file_id and meta["size_bytes"] == len(PDF)
        assert meta["content_type"] == "application/pdf" and meta["question_key"] == KEY
        assert "identifying" not in json.dumps(event, default=str) and "display_name" not in meta
    assert {str(e["resource_id"]) for e in events} == {file_id}


def test_a_failed_storage_delete_leaves_a_marked_row_that_reconcile_cleans(world, team, fake):
    org_id, owner, *_ = team
    file_id = _upload(world, org_id, owner).json()["id"]
    fake.fail_delete = True
    resp = _remove(world, org_id, owner, file_id)
    assert resp.status_code == 200 and resp.json()["object_deleted"] is False
    assert _rows(world, org_id)[0]["removed_at"] is not None and len(fake.objects) == 1
    assert _download(world, org_id, owner, file_id).status_code == 404  # marked rows do not download
    report = store.reconcile(fake)  # report mode: touches nothing
    assert report["removed_but_present"] == [f"org/{org_id}/{file_id}"] and len(fake.objects) == 1
    assert store.reconcile(fake, delete=True)["failed"] == 1 and len(fake.objects) == 1  # still failing
    fake.fail_delete = False
    done = store.reconcile(fake, delete=True)
    assert done["deleted"] == 1 and fake.objects == {}
    assert store.reconcile(fake)["removed_but_present"] == []


def test_reconcile_finds_objects_without_rows_but_leaves_new_uploads_and_live_files_alone(world, team, fake):
    org_id, owner, *_ = team
    live = _upload(world, org_id, owner).json()["id"]
    fake.put(f"org/{uuid4()}/{uuid4()}", b"gone org", "application/pdf")       # an organisation that is gone
    old = f"org/{org_id}/{uuid4()}"
    fake.put(old, b"orphan", "application/pdf")
    fake.age(old, 7200)
    fresh = f"org/{org_id}/{uuid4()}"
    fake.put(fresh, b"between put and insert", "application/pdf")
    report = store.reconcile(fake, now=time.time())
    assert old in report["orphans"] and fresh not in report["orphans"] and report["too_new_to_judge"] == 2
    assert f"org/{org_id}/{live}" not in report["orphans"] and report["deleted"] == 0 and len(fake.objects) == 4
    store.reconcile(fake, delete=True, min_age_seconds=0)
    assert list(fake.objects) == [f"org/{org_id}/{live}"]


def test_reconcile_reports_rows_whose_object_is_missing(world, team, fake):
    org_id, owner, *_ = team
    file_id = _upload(world, org_id, owner).json()["id"]
    fake.objects.clear()
    assert store.reconcile(fake)["rows_missing_object"] == [f"org/{org_id}/{file_id}"]


# ── Caps and rate ─────────────────────────────────────────────────────────────


def test_the_file_cap_counts_only_active_files(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(ef, "MAX_FILES", 2)
    first = _upload(world, org_id, owner).json()["id"]
    assert _upload(world, org_id, owner).status_code == 201
    over = _upload(world, org_id, owner)
    assert over.status_code == 409 and "2 evidence files" in over.json()["detail"]
    assert len(fake.objects) == 2  # the refused file left nothing behind
    _remove(world, org_id, owner, first)
    assert _upload(world, org_id, owner).status_code == 201


def test_the_total_size_cap_counts_only_active_bytes(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(ef, "MAX_TOTAL_BYTES", len(PDF) * 2 + 5)
    a = _upload(world, org_id, owner).json()["id"]
    assert _upload(world, org_id, owner).status_code == 201
    refused = _upload(world, org_id, owner)
    assert refused.status_code == 409 and "in total" in refused.json()["detail"]
    _remove(world, org_id, owner, a)
    assert _upload(world, org_id, owner).status_code == 201


def test_the_rate_limit_counts_uploads_even_when_they_were_removed(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(ef, "UPLOADS_PER_HOUR", 3)
    for _i in range(3):
        file_id = _upload(world, org_id, owner).json()["id"]
        _remove(world, org_id, owner, file_id)
    limited = _upload(world, org_id, owner)
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1
    assert fake.objects == {}
    other = world.make_org()
    other_owner = world.make_person(other, "owner")
    assert _upload(world, other, other_owner).status_code == 201  # per organisation


def test_the_rate_window_opens_again_after_it_passes(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(ef, "UPLOADS_PER_HOUR", 1)
    monkeypatch.setattr(ef, "RATE_WINDOW_SECONDS", 1)
    assert _upload(world, org_id, owner).status_code == 201
    assert _upload(world, org_id, owner).status_code == 429
    time.sleep(1.3)
    assert _upload(world, org_id, owner).status_code == 201


def _register_one(org_id, actor, data=PDF):
    file_id = str(uuid4())
    checked = ef.check("a.pdf", data)
    import hashlib
    return store.register(org_id, actor, question_key=KEY, file_id=file_id, checked=checked, size=len(data),
                          sha256=hashlib.sha256(data).hexdigest())


def _race(fn, n):
    barrier = threading.Barrier(n)
    results = []

    def run():
        barrier.wait()
        try:
            results.append(("ok", fn()))
        except Exception as exc:  # noqa: BLE001
            results.append(("err", exc))

    threads = [threading.Thread(target=run) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results


def test_two_concurrent_uploads_for_the_last_slot_make_one_file(world, team, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(ef, "MAX_FILES", 3)
    _register_one(org_id, owner)
    _register_one(org_id, owner)
    results = _race(lambda: _register_one(org_id, owner), 2)
    assert sorted(r[0] for r in results) == ["err", "ok"]
    assert isinstance([r for r in results if r[0] == "err"][0][1], store.QuotaExceeded)
    assert len(_rows(world, org_id)) == 3


def test_the_byte_cap_holds_under_concurrency(world, team, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(ef, "MAX_TOTAL_BYTES", len(PDF) * 3)
    results = _race(lambda: _register_one(org_id, owner), 8)
    assert [r[0] for r in results].count("ok") == 3
    assert sum(r["size_bytes"] for r in _rows(world, org_id)) <= len(PDF) * 3


def test_the_rate_limit_holds_under_concurrency_and_a_refused_insert_charges_nothing(world, team, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(ef, "UPLOADS_PER_HOUR", 4)
    results = _race(lambda: _register_one(org_id, owner), 10)
    assert [r[0] for r in results].count("ok") == 4
    assert all(isinstance(r[1], store.QuotaExceeded) and r[1].reason == "rate" for r in results if r[0] == "err")
    assert len(_rows(world, org_id)) == 4
    assert world.rows("SELECT count(*) AS n FROM audit_log WHERE org_id = %s AND action = 'compliance.evidence_file.uploaded'",
                      (org_id,))[0]["n"] == 4


def test_a_quota_refusal_after_the_put_deletes_the_object(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(ef, "MAX_FILES", 1)
    monkeypatch.setattr(store, "precheck", lambda *a, **k: None)  # as if the other upload committed after the check
    assert _upload(world, org_id, owner).status_code == 201
    refused = _upload(world, org_id, owner)
    assert refused.status_code == 409
    assert len(fake.objects) == 1 and len(_rows(world, org_id)) == 1
    assert fake.call_names("delete")  # the compensating delete ran


def test_a_failed_insert_or_audit_deletes_the_object_and_leaves_no_row(world, team, fake, monkeypatch):
    org_id, owner, *_ = team

    def broken(*a, **k):
        raise psycopg.errors.InternalError_("audit write failed")

    monkeypatch.setattr(store, "_audit", broken)
    with pytest.raises(Exception):
        _upload(world, org_id, owner)
    assert fake.objects == {} and _rows(world, org_id) == []
    assert len(fake.call_names("put")) == 1 and len(fake.call_names("delete")) == 1


def test_an_insert_that_fails_on_the_organisation_having_gone_deletes_the_object(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    real = store.register

    def vanish(org, actor, **kw):
        world.setup.execute("DELETE FROM organizations WHERE id = %s", (org,))
        world.setup.commit()
        return real(org, actor, **kw)

    monkeypatch.setattr(api.evidence_file_store, "register", vanish)
    with pytest.raises(Exception):
        _upload(world, org_id, owner)
    assert fake.objects == {}


def test_storage_failure_on_put_is_a_clean_502_and_nothing_is_recorded(world, team, fake):
    org_id, owner, *_ = team
    fake.fail_put = True
    resp = _upload(world, org_id, owner)
    assert resp.status_code == 502 and _rows(world, org_id) == []


# ── Pool safety and bounded work ──────────────────────────────────────────────


def test_no_database_connection_is_open_while_bytes_move(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    open_now = {"n": 0}
    real_get_db = database.get_db

    @contextmanager
    def counting():
        with real_get_db() as conn:
            open_now["n"] += 1
            try:
                yield conn
            finally:
                open_now["n"] -= 1

    monkeypatch.setattr(database, "get_db", counting)
    seen = []
    for name in ("put", "create_signed_url", "delete"):
        original = getattr(fake, name)

        def spy(*a, _orig=original, _name=name, **k):
            seen.append((_name, open_now["n"]))
            return _orig(*a, **k)

        monkeypatch.setattr(fake, name, spy)
    file_id = _upload(world, org_id, owner).json()["id"]
    _download(world, org_id, owner, file_id)
    _remove(world, org_id, owner, file_id)
    assert {n for n, _c in seen} == {"put", "create_signed_url", "delete"}
    assert all(c == 0 for _n, c in seen), seen


def test_an_oversize_body_is_refused_while_streaming_without_reading_it_all():
    import asyncio
    from fastapi import HTTPException

    pulled = {"n": 0}
    chunk = b"0" * (1024 * 1024)

    class Request:
        headers = {}

        async def stream(self):
            for _i in range(200):  # 200 MB on offer
                pulled["n"] += 1
                yield chunk

    with pytest.raises(HTTPException) as err:
        asyncio.run(api._read_body(Request()))
    assert err.value.status_code == 413 and pulled["n"] == 11  # stopped one chunk past the 10 MB limit


def test_a_body_at_the_limit_is_read_whole():
    import asyncio

    class Request:
        headers = {"content-length": str(ef.MAX_BYTES)}

        async def stream(self):
            for _i in range(10):
                yield b"0" * (1024 * 1024)

    assert len(asyncio.run(api._read_body(Request()))) == ef.MAX_BYTES


def test_a_declared_oversize_length_is_refused_before_any_body_is_read(world, team, fake):
    org_id, owner, *_ = team
    headers = {**world.headers(owner, org_id), "X-File-Name": "big.pdf", "Content-Length": str(ef.MAX_BYTES + 1)}
    resp = world.client.post(f"{BASE}?question_key={KEY}", content=b"%PDF-1", headers=headers)
    assert resp.status_code in (400, 413)
    assert fake.objects == {}


def test_concurrent_uploads_per_process_are_bounded_and_waiters_get_503_with_retry_after(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(api, "MAX_CONCURRENT_UPLOADS", 1)
    monkeypatch.setattr(api, "UPLOAD_SLOT_WAIT_SECONDS", 0.2)
    api._slots.clear()
    monkeypatch.setattr("backend.app.main.SCHEDULER_ENABLED", False)
    started = threading.Event()
    real_put = fake.put

    def slow_put(*a, **k):
        started.set()
        time.sleep(1.5)
        return real_put(*a, **k)

    monkeypatch.setattr(fake, "put", slow_put)
    headers = lambda: {**world.headers(owner, org_id), "X-File-Name": "a.pdf"}  # noqa: E731
    # One client as a context manager keeps one event loop across requests, as the server has.
    with TestClient(app) as client, ThreadPoolExecutor(2) as pool:
        post = lambda: client.post(f"{BASE}?question_key={KEY}", content=PDF, headers=headers())  # noqa: E731
        first = pool.submit(post)
        assert started.wait(20)  # the first request holds the only slot now
        second = post()
        assert second.status_code == 503 and second.headers["retry-after"]
        assert first.result().status_code == 201
        monkeypatch.setattr(fake, "put", real_put)
        assert post().status_code == 201  # the slot came back


def test_a_slow_sender_cannot_hold_an_upload_slot_forever(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(api, "UPLOAD_READ_SECONDS", 0.2)

    async def slow(request):
        await asyncio.sleep(5)

    real = api._read_body
    monkeypatch.setattr(api, "_read_body", slow)
    resp = _upload(world, org_id, owner)
    assert resp.status_code == 408 and fake.objects == {}
    monkeypatch.setattr(api, "_read_body", real)
    assert _upload(world, org_id, owner).status_code == 201  # the slot was released


def test_a_lock_wait_is_a_503_with_retry_after_and_the_object_is_deleted(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(store, "LOCK_WAIT_MS", 200)
    holder = psycopg.connect(world.url)
    try:
        holder.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"evidence-files:{org_id}",))
        resp = _upload(world, org_id, owner)
    finally:
        holder.rollback()
        holder.close()
    assert resp.status_code == 503 and resp.headers["retry-after"]
    assert fake.objects == {} and _rows(world, org_id) == []
    assert _upload(world, org_id, owner).status_code == 201


# ── Storage configuration and secrets ─────────────────────────────────────────


def test_without_storage_configuration_uploads_fail_closed_with_503(world, team, monkeypatch):
    org_id, owner, *_ = team
    file_storage.set_storage(None)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    resp = _upload(world, org_id, owner)
    assert resp.status_code == 503 and resp.headers["retry-after"] and _rows(world, org_id) == []
    assert world.client.get(BASE, headers=world.headers(owner, org_id)).json()["uploads_available"] is False


def test_the_service_key_is_in_no_response_or_log_line(world, team, caplog, monkeypatch):
    org_id, owner, *_ = team
    key = "sk-service-role-never-show-this"
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.startswith("/storage/v1/object/evidence-files/"):
            return httpx.Response(200, json={})
        if "/object/sign/" in request.url.path:
            return httpx.Response(200, json={"signedURL": "/object/sign/evidence-files/x?token=tok"})
        return httpx.Response(500, text=f"upstream said {key}")

    file_storage.set_storage(SupabaseStorage("https://proj.example.test", key, transport=httpx.MockTransport(handler)))
    caplog.set_level(logging.DEBUG)
    created = _upload(world, org_id, owner)
    got = _download(world, org_id, owner, created.json()["id"])
    failing = _remove(world, org_id, owner, created.json()["id"])  # the mock answers the delete with a 500
    for resp in (created, got, failing):
        assert key not in resp.text and key not in json.dumps(dict(resp.headers))
    assert key not in caplog.text
    assert all(key not in str(r.url) for r in seen) and all(r.headers["authorization"] == f"Bearer {key}" for r in seen)
    assert failing.status_code == 200 and failing.json()["object_deleted"] is False


# ── Closing an organisation ───────────────────────────────────────────────────


def _close(world, org_id, uid):
    slug = world.rows("SELECT slug FROM organizations WHERE id = %s", (org_id,))[0]["slug"]
    return world.client.post("/api/v1/organizations/close", json={"slug": slug}, headers=world.headers(uid, org_id))


def _clear_queue(world):
    """Other tests leave entries behind; the queue is global, so tests that count it start from empty."""
    world.setup.execute("DELETE FROM compliance_evidence_purge_queue")
    world.setup.commit()


def _queue(world, org_id):
    return world.rows("SELECT org_id FROM compliance_evidence_purge_queue WHERE org_id = %s", (org_id,))


def test_closing_queues_the_purge_then_deletes_the_objects_and_only_its_own(world, team, fake):
    org_id, owner, *_ = team
    other = world.make_org()
    other_owner = world.make_person(other, "owner")
    for _i in range(3):
        _upload(world, org_id, owner)
    removed = _upload(world, org_id, owner).json()["id"]
    _remove(world, org_id, owner, removed)
    _upload(world, other, other_owner)
    seen = []
    original = fake.delete_prefix
    fake.delete_prefix = lambda p: (seen.append((p, len(_queue(world, org_id)),
                                                 len(world.rows("SELECT 1 FROM organizations WHERE id = %s", (org_id,))))),
                                    original(p))[1]
    resp = _close(world, org_id, owner)
    assert resp.status_code == 200, resp.text
    assert seen == [(f"org/{org_id}/", 1, 0)]  # queued, and the rows were already gone when the objects went
    assert _queue(world, org_id) == []  # done: the entry is cleared
    assert [p for p in fake.objects if p.startswith(f"org/{org_id}/")] == []
    assert len([p for p in fake.objects if p.startswith(f"org/{other}/")]) == 1
    assert world.rows("SELECT 1 FROM compliance_evidence_files WHERE org_id = %s", (org_id,)) == []


def test_a_storage_failure_does_not_block_closing_and_the_queue_finishes_the_job(world, team, fake):
    org_id, owner, *_ = team
    _clear_queue(world)
    _upload(world, org_id, owner)
    fake.fail_delete_prefix = True
    assert _close(world, org_id, owner).status_code == 200
    assert world.rows("SELECT 1 FROM organizations WHERE id = %s", (org_id,)) == []
    assert len(_queue(world, org_id)) == 1 and len(fake.objects) == 1  # recorded, not silently orphaned
    report = store.process_purge_queue(fake, delete=True)
    assert report["failed"] == 1 and len(_queue(world, org_id)) == 1
    fake.fail_delete_prefix = False
    assert store.process_purge_queue(fake, delete=True)["purged"] == 1
    assert fake.objects == {} and _queue(world, org_id) == []


def test_a_failed_database_delete_leaves_the_files_and_the_stale_queue_entry_is_dropped(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    _clear_queue(world)
    _upload(world, org_id, owner)
    from backend.app.api import organizations as orgs

    def broken(sql, params=()):
        raise RuntimeError("database went away")

    monkeypatch.setattr(orgs, "execute_one", broken)
    with pytest.raises(RuntimeError):
        _close(world, org_id, owner)
    assert len(fake.objects) == 1 and len(_rows(world, org_id)) == 1  # nothing was deleted before the rows
    assert len(_queue(world, org_id)) == 1
    assert store.process_purge_queue(fake, delete=True)["dropped"] == 1  # the organisation still exists
    assert len(fake.objects) == 1 and _queue(world, org_id) == []


def test_closing_works_with_storage_unset_and_leaves_a_queue_entry(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    _clear_queue(world)
    _upload(world, org_id, owner)
    file_storage.set_storage(None)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert _close(world, org_id, owner).status_code == 200
    assert len(_queue(world, org_id)) == 1 and len(fake.objects) == 1
    file_storage.set_storage(fake)
    assert store.process_purge_queue(fake, delete=True)["purged"] == 1 and fake.objects == {}


def test_a_storage_outage_does_not_block_closing_an_organisation_with_no_files(world, team, fake):
    org_id, owner, *_ = team
    fake.fail_delete_prefix = True
    assert _close(world, org_id, owner).status_code == 200
    assert world.rows("SELECT 1 FROM organizations WHERE id = %s", (org_id,)) == [] and _queue(world, org_id) == []


# ── Review round 1: bounded work, attempts, switch, reconcile safety, download audit ──


def test_uploads_are_off_unless_the_operator_turns_them_on_but_downloads_still_work(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    file_id = _upload(world, org_id, owner).json()["id"]
    monkeypatch.delenv("EVIDENCE_UPLOADS_ENABLED")
    assert _upload(world, org_id, owner).status_code == 503
    listing = world.client.get(BASE, headers=world.headers(owner, org_id)).json()
    assert listing["uploads_available"] is False and len(listing["files"]) == 1
    assert _download(world, org_id, owner, file_id).status_code == 200
    assert _remove(world, org_id, owner, file_id).status_code == 200


def test_a_many_entry_docx_is_refused_from_the_directory_record_without_parsing_it(world, team, fake, monkeypatch):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for i in range(30000):
            z.writestr(f"word/{i}", b"")
    data = buf.getvalue()

    def boom(*a, **k):
        raise AssertionError("the zip directory must not be parsed")

    monkeypatch.setattr(ef.zipfile, "ZipFile", boom)
    started = time.perf_counter()
    with pytest.raises(ef.FileRejected, match="too many parts"):
        ef.check_content("docx", data)
    assert time.perf_counter() - started < 0.05  # constant work, not proportional to the entry count
    org_id, owner, *_ = team
    assert _upload(world, org_id, owner, name="a.docx", data=data).status_code == 422 and fake.objects == {}


def test_refused_attempts_count_toward_the_hourly_attempt_limit(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(api, "ATTEMPTS_PER_HOUR", 3)
    for _i in range(3):
        assert _upload(world, org_id, owner, name="a.pdf", data=PNG).status_code == 422
    limited = _upload(world, org_id, owner)
    assert limited.status_code == 429 and limited.headers["retry-after"]
    assert fake.objects == {}
    other = world.make_org()
    assert _upload(world, other, world.make_person(other, "owner")).status_code == 201


def test_one_organisation_cannot_take_more_than_its_share_of_upload_slots(world, team, fake, monkeypatch):
    org_id, owner, *_ = team
    monkeypatch.setattr(api, "MAX_UPLOADS_PER_ORG", 1)
    monkeypatch.setattr("backend.app.main.SCHEDULER_ENABLED", False)
    started = threading.Event()
    real_put = fake.put

    def slow_put(*a, **k):
        started.set()
        time.sleep(1.2)
        return real_put(*a, **k)

    monkeypatch.setattr(fake, "put", slow_put)
    headers = lambda: {**world.headers(owner, org_id), "X-File-Name": "a.pdf"}  # noqa: E731
    with TestClient(app) as client, ThreadPoolExecutor(2) as pool:
        post = lambda: client.post(f"{BASE}?question_key={KEY}", content=PDF, headers=headers())  # noqa: E731
        first = pool.submit(post)
        assert started.wait(20)
        second = post()
        assert second.status_code == 503 and second.headers["retry-after"]
        assert first.result().status_code == 201
        other = world.make_org()
        other_owner = world.make_person(other, "owner")
        monkeypatch.setattr(fake, "put", real_put)
        third = client.post(f"{BASE}?question_key={KEY}", content=PDF,
                            headers={**world.headers(other_owner, other), "X-File-Name": "a.pdf"})
        assert third.status_code == 201  # another organisation is not held up


def test_a_database_outage_is_a_503_with_retry_after_and_the_object_is_cleaned_up(world, team, fake, monkeypatch):
    from psycopg_pool import PoolTimeout
    org_id, owner, *_ = team

    def timeout(*a, **k):
        raise PoolTimeout("pool busy")

    monkeypatch.setattr(api.evidence_file_store, "register", timeout)
    resp = _upload(world, org_id, owner)
    assert resp.status_code == 503 and resp.headers["retry-after"] and fake.objects == {}
    monkeypatch.setattr(api.evidence_file_store, "precheck", timeout)
    assert _upload(world, org_id, owner).status_code == 503


def test_the_download_audit_row_is_written_only_after_a_link_exists(world, team, fake):
    org_id, owner, *_ = team
    file_id = _upload(world, org_id, owner).json()["id"]
    fake.fail_sign = True
    assert _download(world, org_id, owner, file_id).status_code == 502
    assert _audit(world, org_id, "compliance.evidence_file.download_link_issued") == []
    fake.fail_sign = False
    assert _download(world, org_id, owner, file_id).status_code == 200
    assert len(_audit(world, org_id, "compliance.evidence_file.download_link_issued")) == 1


def test_download_links_are_rate_limited_per_user(world, team, fake, monkeypatch):
    org_id, owner, admin, member = team
    file_id = _upload(world, org_id, owner).json()["id"]
    monkeypatch.setattr(api, "DOWNLOADS_PER_MINUTE", 2)
    assert [_download(world, org_id, member, file_id).status_code for _i in range(3)] == [200, 200, 429]
    assert _download(world, org_id, admin, file_id).status_code == 200  # another user has their own allowance
    assert len(fake.signed) == 3


def test_reconcile_delete_refuses_when_the_table_is_empty_but_storage_is_not(world, team, fake):
    org_id, *_ = team
    for i in range(3):
        path = f"org/{org_id}/{uuid4()}"
        fake.put(path, b"x", "application/pdf")
        fake.age(path, 7200)
    assert len(store.reconcile(fake)["orphans"]) == 3  # report mode still reports
    with pytest.raises(store.ReconcileRefused):
        store.reconcile(fake, delete=True)
    assert len(fake.objects) == 3


def test_reconcile_deletes_at_most_the_cap_per_run_and_unknown_age_is_too_new(world, team, fake):
    org_id, owner, *_ = team
    _upload(world, org_id, owner)  # one real row, so the table is not empty
    for i in range(5):
        path = f"org/{org_id}/{uuid4()}"
        fake.put(path, b"x", "application/pdf")
        fake.age(path, 7200)
    unknown = f"org/{org_id}/{uuid4()}"
    fake.put(unknown, b"x", "application/pdf")
    real_list = fake.list_objects
    fake.list_objects = lambda prefix: [StoredObject(o.path, None if o.path == unknown else o.created_at)
                                         for o in real_list(prefix)]
    run = store.reconcile(fake, delete=True, max_delete=2)
    assert run["deleted"] == 2 and run["left_for_next_run"] == 3 and unknown in fake.objects
    assert unknown not in run["orphans"] and run["too_new_to_judge"] >= 1


def test_the_reconcile_script_needs_yes_delete_as_well(world, team, fake, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("reconcile_script", pathlib.Path(__file__).resolve().parents[1] / "scripts/reconcile_evidence_files.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--delete"]) == 2
    assert "--yes-delete" in capsys.readouterr().err
    assert mod.main([]) in (0, 1)


def test_the_api_roles_hold_no_privileges_on_the_new_tables(world):
    rows = world.rows("SELECT grantee, table_name FROM information_schema.role_table_grants WHERE grantee IN ('anon', 'authenticated') "
                      "AND table_name IN ('compliance_evidence_files', 'compliance_evidence_purge_queue')")
    assert rows == []
    grants = world.rows("SELECT privilege_type FROM information_schema.role_table_grants WHERE grantee = 'cyphward_app' "
                        "AND table_name = 'compliance_evidence_purge_queue' ORDER BY 1")
    assert [g["privilege_type"] for g in grants] == ["DELETE", "INSERT", "SELECT"]


# ── Snapshots and packs ───────────────────────────────────────────────────────


def test_snapshots_and_packs_carry_no_file_data(snapshot_world, fake):  # noqa: F811
    w = snapshot_world
    org, owner, domain, scan, finding = _assessed_org(w)
    resp = w.client.post(f"{BASE}?question_key={KEY}", content=PDF,
                         headers={**w.headers(owner, org), "X-File-Name": "marker-name-xyz.pdf"})
    assert resp.status_code == 201, resp.text
    snap = _create(w, org, owner)
    assert snap.status_code == 201, snap.text
    stored = w.rows("SELECT content FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["content"]
    dumped = json.dumps(stored)
    assert "marker-name-xyz" not in dumped and "evidence_file" not in dumped and resp.json()["sha256"] not in dumped
    pack = w.client.post("/api/v1/packs", json={}, headers=w.headers(owner, org))
    assert pack.status_code == 201, pack.text
    html = w.client.get(f"/api/v1/packs/{pack.json()['pack']['id']}/html", headers=w.headers(owner, org)).content.decode()
    assert "marker-name-xyz" not in html and resp.json()["sha256"] not in html


def test_snapshot_and_pack_code_does_not_read_evidence_files():
    root = pathlib.Path(__file__).resolve().parents[2] / "backend/app"
    for folder in ("snapshots", "packs"):
        for path in (root / folder).glob("*.py"):
            assert "evidence_file" not in path.read_text(), path
