"""Evidence file rules, storage implementations and copy (packet C6). No database, no network.

Covers: every type, size and content rejection; name cleaning; the in-memory fake; the Supabase REST implementation
against a mock transport (key only in headers, signed URL forces a download, fail-closed without configuration,
no key in errors or logs); and the banned-phrase check over everything new.
"""
import io
import logging
import pathlib
import re
import zipfile

import httpx
import pytest

from backend.app.compliance import evidence_files as ef
from backend.app.storage import StorageError, StorageNotConfigured, StorageObjectNotFound, SupabaseStorage
from backend.app.storage.memory import MemoryStorage
from backend.tests.evidence_samples import DOCX, JPEG, PDF, PNG, SAMPLES, docx

ROOT = pathlib.Path(__file__).resolve().parents[2]
BANNED = ("compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit",
          "compliance score", "fully meets", "meets the requirement", "is met", "partial compliance",
          "fully compliant", "is compliant", "satisfy ndpa", "adequate", "adequacy", "guarantee")


# ── Accepted files ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", sorted(SAMPLES))
def test_each_allowed_type_is_accepted_with_a_server_derived_content_type(key):
    name, data = SAMPLES[key]
    checked = ef.check(name, data)
    assert checked.display_name == name
    assert checked.content_type == ef.ALLOWED_TYPES[checked.kind]


def test_jpeg_extension_spellings_and_upper_case_are_accepted():
    assert ef.check("A.JPEG", JPEG).kind == "jpeg"
    assert ef.check("a.JPG", JPEG).kind == "jpeg"
    assert ef.check("a.PDF", PDF).kind == "pdf"


def test_exactly_ten_megabytes_is_accepted_and_one_more_byte_is_not():
    ef.check_content("pdf", PDF + b"0" * (ef.MAX_BYTES - len(PDF)))
    with pytest.raises(ef.FileRejected) as err:
        ef.check_content("pdf", PDF + b"0" * (ef.MAX_BYTES - len(PDF) + 1))
    assert err.value.status == 413


# ── Rejections ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["tool.exe", "page.html", "notes.txt", "sheet.xlsx", "macro.docm", "archive.zip",
                                  "image.gif", "script.svg", "noextension", ".pdf", "report.pdf.exe", ""])
def test_other_types_are_refused_by_name(name):
    with pytest.raises(ef.FileRejected):
        ef.check_name(name)


@pytest.mark.parametrize("name", ["report.exe.pdf", "invoice.php.png", "a.b.c.pdf", "scan.js.jpg", "x.html.docx"])
def test_double_extensions_are_refused(name):
    with pytest.raises(ef.FileRejected, match="second extension"):
        ef.check_name(name)


def test_dotted_names_that_are_not_extensions_are_fine():
    assert ef.check_name("Policy v2.1.pdf")[0] == "Policy v2.1.pdf"
    assert ef.check_name("Acme Ltd. policy.pdf")[0] == "Acme Ltd. policy.pdf"


@pytest.mark.parametrize("name,data", [("a.pdf", PNG), ("a.png", PDF), ("a.jpg", PDF), ("a.docx", PDF),
                                       ("a.pdf", DOCX), ("a.png", JPEG), ("a.jpeg", PNG), ("a.pdf", b"hello world")])
def test_magic_byte_mismatches_are_refused(name, data):
    with pytest.raises(ef.FileRejected):
        ef.check(name, data)


def test_empty_file_is_refused():
    with pytest.raises(ef.FileRejected, match="empty"):
        ef.check("a.pdf", b"")


def test_a_pdf_header_must_be_at_the_very_start():
    with pytest.raises(ef.FileRejected):
        ef.check("a.pdf", b" \n" + PDF)


def test_docx_must_be_a_real_word_package():
    with pytest.raises(ef.FileRejected):
        ef.check("a.docx", b"PK\x03\x04 not really a zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", b"hi")
    with pytest.raises(ef.FileRejected):
        ef.check("a.docx", buf.getvalue())  # a zip without [Content_Types].xml and word/
    with pytest.raises(ef.FileRejected):
        ef.check("a.docx", docx(content_types=b"<Types/>"))  # right shape, not a Word main part
    with pytest.raises(ef.FileRejected, match="Macro"):
        ef.check("a.docx", docx(content_types=ef_types(b"macroEnabled")))


def ef_types(marker: bytes) -> bytes:
    from backend.tests.evidence_samples import CONTENT_TYPES
    return CONTENT_TYPES + marker


def test_zip_bomb_by_expansion_is_refused_without_decompressing():
    bomb = docx({"word/media/big.bin": b"\x00" * (30 * 1024 * 1024)})  # ~30 KB packed, 30 MB unpacked
    assert len(bomb) < ef.MAX_BYTES
    with pytest.raises(ef.FileRejected, match="unsafe size"):
        ef.check("a.docx", bomb)


def test_zip_with_too_many_entries_is_refused(monkeypatch):
    monkeypatch.setattr(ef, "DOCX_MAX_ENTRIES", 20)
    with pytest.raises(ef.FileRejected, match="too many parts"):
        ef.check("a.docx", docx({f"word/p{i}.xml": b"x" for i in range(30)}))


def test_a_zip64_record_is_refused_so_it_cannot_override_the_entry_count():
    import struct
    base = docx()
    eocd = base.rfind(b"PK\x05\x06")
    # A zip64 end-of-central-directory locator right before the classic record, as zipfile would follow it.
    locator = b"PK\x06\x07" + struct.pack("<IQI", 0, eocd, 1)
    forged = base[:eocd] + locator + base[eocd:]
    with pytest.raises(ef.FileRejected, match="too many parts"):
        ef.check("a.docx", forged)
    ef.check("a.docx", base)  # the same file without it is fine


def test_zip_with_path_traversal_entries_is_refused():
    with pytest.raises(ef.FileRejected):
        ef.check("a.docx", docx({"../evil.txt": b"x"}))


# ── Names ──────────────────────────────────────────────────────────────────────


def test_paths_are_cut_to_the_last_segment():
    assert ef.clean_name("../../etc/passwd.pdf") == "passwd.pdf"
    assert ef.clean_name("C:\\Users\\me\\scan.png") == "scan.png"
    assert ef.check("..\\..\\boot/policy.pdf", PDF).display_name == "policy.pdf"


def test_control_bidi_and_zero_width_characters_are_removed():
    nasty = "pol\x00icy\x07\u202e\u200b\u2066\ufeff\u00ad.pdf"
    assert ef.clean_name(nasty) == "policy.pdf"


def test_a_reversed_extension_trick_does_not_pass():
    with pytest.raises(ef.FileRejected):
        ef.check_name("invoice\u202egpj.exe")  # displays as "invoiceexe.jpg"; cleaned it ends in .exe


def test_names_are_cut_to_120_characters_and_keep_their_extension():
    name = ef.clean_name("a" * 300 + ".pdf")
    assert len(name) == ef.NAME_MAX and name.endswith(".pdf")


def test_reserved_characters_become_underscores():
    assert ef.clean_name('a<b>c:"d|e?f*g.pdf') == "a_b_c__d_e_f_g.pdf"


def test_storage_path_never_contains_the_file_name():
    path = ef.storage_path("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222")
    assert path == "org/11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222"
    assert ef.org_prefix("x") == "org/x/"


# ── In-memory fake ─────────────────────────────────────────────────────────────


def test_fake_put_never_overwrites_and_signed_urls_force_download():
    fake = MemoryStorage()
    fake.put("org/a/1", b"x", "application/pdf")
    with pytest.raises(StorageError):
        fake.put("org/a/1", b"y", "application/pdf")
    url = fake.create_signed_url("org/a/1", 60, "my file.pdf")
    assert "download=my%20file.pdf" in url and fake.signed[-1]["expires_in"] == 60
    with pytest.raises(StorageObjectNotFound):
        fake.create_signed_url("org/a/missing", 60, "x.pdf")
    assert fake.delete_prefix("org/a/") == 1 and fake.objects == {}


# ── Supabase REST implementation (mock transport) ──────────────────────────────

KEY = "service-role-key-for-tests-only"


def _client(handler):
    return SupabaseStorage("https://proj.example.test/", KEY, transport=httpx.MockTransport(handler))


def test_put_sends_the_key_in_headers_only_and_never_overwrites():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"Key": "evidence-files/org/a/1"})

    _client(handler).put("org/a/1", b"%PDF-1", "application/pdf")
    req = seen[0]
    assert req.method == "POST" and req.url.path == "/storage/v1/object/evidence-files/org/a/1"
    assert req.headers["authorization"] == f"Bearer {KEY}" and req.headers["x-upsert"] == "false"
    assert KEY not in str(req.url)


def test_signed_url_forces_download_and_contains_no_key():
    def handler(request):
        assert request.url.path == "/storage/v1/object/sign/evidence-files/org/a/1"
        import json
        assert json.loads(request.read()) == {"expiresIn": 60}
        return httpx.Response(200, json={"signedURL": "/object/sign/evidence-files/org/a/1?token=tok123"})

    url = _client(handler).create_signed_url("org/a/1", 60, "Board minutes.docx")
    assert url == ("https://proj.example.test/storage/v1/object/sign/evidence-files/org/a/1"
                   "?token=tok123&download=Board%20minutes.docx")
    assert KEY not in url


def test_signed_url_accepts_a_full_prefix_from_newer_storage_versions():
    def handler(request):
        return httpx.Response(200, json={"signedURL": "/storage/v1/object/sign/evidence-files/org/a/1?token=t"})

    assert _client(handler).create_signed_url("org/a/1", 60, "a.pdf").startswith(
        "https://proj.example.test/storage/v1/object/sign/")


def test_errors_carry_no_key_headers_or_body_and_logs_stay_clean(caplog):
    def handler(request):
        return httpx.Response(500, text=f"boom {KEY} {request.headers['authorization']}")

    caplog.set_level(logging.DEBUG)
    with pytest.raises(StorageError) as err:
        _client(handler).put("org/a/1", b"x", "application/pdf")
    assert KEY not in str(err.value) and "boom" not in str(err.value)
    assert KEY not in caplog.text and "Bearer" not in caplog.text


def test_network_errors_are_wrapped_without_the_url_or_key():
    def handler(request):
        raise httpx.ConnectError("could not connect to https://proj.example.test with " + KEY)

    with pytest.raises(StorageError) as err:
        _client(handler).delete("org/a/1")
    assert KEY not in str(err.value) and KEY not in repr(err.value.__cause__)


def test_a_missing_object_is_not_found_for_a_link_and_fine_for_a_delete():
    def handler(request):
        return httpx.Response(404, json={"message": "not found"})

    client = _client(handler)
    with pytest.raises(StorageObjectNotFound):
        client.create_signed_url("org/a/1", 60, "a.pdf")
    client.delete("org/a/1")  # does not raise


def test_delete_prefix_lists_folders_recursively_then_deletes_in_batches():
    deleted, state = [], {"gone": False}

    def handler(request):
        if request.url.path.endswith("/object/list/evidence-files"):
            import json
            body = json.loads(request.read())
            if state["gone"]:
                return httpx.Response(200, json=[])
            if body["prefix"] == "org/a":
                return httpx.Response(200, json=[{"name": "f1", "id": "i1", "created_at": "2026-10-19T10:00:00Z"},
                                                 {"name": "sub", "id": None}])
            if body["prefix"] == "org/a/sub":
                return httpx.Response(200, json=[{"name": "f2", "id": "i2"}])
            return httpx.Response(200, json=[])
        if request.method == "DELETE":
            import json
            deleted.extend(json.loads(request.read())["prefixes"])
            state["gone"] = True
            return httpx.Response(200, json=[])
        raise AssertionError(request.url)

    assert _client(handler).delete_prefix("org/a/") == 2
    assert sorted(deleted) == ["org/a/f1", "org/a/sub/f2"]


def test_without_configuration_it_fails_closed(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(StorageNotConfigured):
        SupabaseStorage.from_env()
    monkeypatch.setenv("SUPABASE_URL", "https://proj.example.test")
    with pytest.raises(StorageNotConfigured):  # key still missing
        SupabaseStorage.from_env()


def test_a_plain_http_remote_url_is_refused(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://proj.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", KEY)
    with pytest.raises(StorageNotConfigured):
        SupabaseStorage.from_env()
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    assert SupabaseStorage.from_env() is not None


def test_odd_listings_and_answers_become_storage_errors():
    with pytest.raises(StorageError):
        _client(lambda r: httpx.Response(200, text="<html>not json</html>")).list_objects("org/a/")
    with pytest.raises(StorageError):
        _client(lambda r: httpx.Response(200, json=["x", 1])).list_objects("org/a/")
    with pytest.raises(StorageError):
        _client(lambda r: httpx.Response(200, text="nope")).bucket_is_private()


def test_bucket_privacy_check():
    assert _client(lambda r: httpx.Response(200, json={"public": False})).bucket_is_private() is True
    assert _client(lambda r: httpx.Response(200, json={"public": True})).bucket_is_private() is False
    assert _client(lambda r: httpx.Response(404, json={})).bucket_is_private() is None


# ── Copy: nothing new claims anything ─────────────────────────────────────────

NEW_FILES = ["backend/app/compliance/evidence_files.py", "backend/app/compliance/evidence_file_store.py",
             "backend/app/storage/base.py", "backend/app/storage/memory.py", "backend/app/storage/supabase.py",
             "backend/app/storage/__init__.py", "supabase/migrations/20261019100000_compliance_evidence_files.sql",
             "backend/scripts/reconcile_evidence_files.py", "backend/tests/evidence_samples.py",
             "frontend/src/pages/compliance/EvidenceFiles.tsx"]


def _evidence_api_section() -> str:
    text = (ROOT / "backend/app/api/compliance.py").read_text()
    return text[text.index("# ── Evidence files (packet C6)"):]


def test_banned_phrases_do_not_appear_in_new_backend_copy_or_fixtures():
    blobs = {name: (ROOT / name).read_text() for name in NEW_FILES}
    blobs["api/compliance.py (evidence section)"] = _evidence_api_section()
    api_ts = (ROOT / "frontend/src/lib/api.ts").read_text()
    blobs["frontend api.ts (evidence section)"] = api_ts[api_ts.index("// ---- Evidence files attached"):]
    for name, blob in blobs.items():
        low = blob.lower()
        for phrase in BANNED:
            assert phrase not in low, f"{name}: banned phrase {phrase!r}"
