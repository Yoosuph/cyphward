"""NDPA readiness evidence packs and the DPO six-monthly section against the real, migrated test database (packet C4).

Runs only against the owned loopback `cyphward_test` database through the restricted `cyphward_app` role.
"""
import asyncio
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from backend.app.compliance import attestation_store as store
from backend.app.compliance import reminders
from backend.app.compliance.register import DISCLAIMER, REGISTER
from backend.app.core.cron_claim import COMPLIANCE_REMINDERS_CRON_NAME
from backend.app.packs import render
from backend.tests.test_scan_admission_postgres import disposable_postgres_url  # noqa: F401 (fixture)
from backend.tests.test_snapshots_postgres import _assessed_org, _create, world  # noqa: F401 (fixtures)

H = lambda world, uid, org: world.headers(uid, org)  # noqa: E731
BANNED = ("compliant", "certified", "satisfies", "satisfied", "passes audit", "pass the audit", "compliance score",
          "fully meets", "meets the requirement", "is met", "partial compliance", "fully compliant", "is compliant",
          "satisfy ndpa", "ndpa 2023 compliant", "cbn compliant")
NOT_A_CAR = "not a compliance audit return"


def _issue(world, org, user, **body):
    return world.client.post("/api/v1/packs", json=body, headers=H(world, user, org))


def _get(world, org, user, path):
    return world.client.get(f"/api/v1/packs{path}", headers=H(world, user, org))


def _collapse(text):
    return " ".join(text.split())


def _pack(world, org, owner, **body):
    resp = _issue(world, org, owner, **body)
    assert resp.status_code == 201, resp.text
    return resp.json()["pack"]


def _texts(world, org, owner, pack):
    html = _get(world, org, owner, f"/{pack['id']}/html").content.decode()
    pdf = _get(world, org, owner, f"/{pack['id']}/pdf").content
    return html, _collapse(render.pdf_extract_text(pdf)), pdf


# ── Content ──────────────────────────────────────────────────────────────


def test_pack_carries_scope_dates_register_statuses_sources_gaps_disclaimer_and_pending_markers(world):
    org, owner, domain, scan, finding = _assessed_org(world)
    store.record({"id": org}, owner, question_key="breach.response_plan", answer={"value": "yes"}, owner_user_id=owner,
                 evidence_link="https://example.test/plan")
    pack = _pack(world, org, owner)
    html, pdf_text, _ = _texts(world, org, owner, pack)
    snap = world.rows("SELECT seq, content_sha256 FROM assessment_snapshots WHERE id = %s", (pack["snapshot_id"],))[0]
    for text in (html, pdf_text):
        flat = _collapse(re.sub(r"<[^>]+>", " ", text)).replace("&amp;", "&").replace("&#x27;", "'")
        assert DISCLAIMER in flat
        assert NOT_A_CAR in flat.lower()
        assert "assessed.snapshot.test" in flat
        assert REGISTER["version"] in flat
        assert snap["content_sha256"] in flat
        assert "reference pending review" in flat
        assert "Tool observed" in flat and "Customer attested" in flat
        assert "Prioritised gaps" in flat
        assert "https://example.test/plan" in flat
    assert html.count("reference pending review") >= len(REGISTER["requirements"])
    assert pack["kind"] == "readiness_pack" and pack["html_sha256"] and pack["pdf_sha256"]


def test_every_unverified_clause_is_marked_in_html_and_pdf(world):
    org, owner, *_ = _assessed_org(world)
    pack = _pack(world, org, owner)
    html, pdf_text, _ = _texts(world, org, owner, pack)
    for req in REGISTER["requirements"]:
        if not req["clause_verified"]:
            marker = f"{req['clause']} · reference pending review"
            assert marker in html
            assert render.pdf_text(f"{req['clause']} · reference pending review") in pdf_text


def test_a_pack_with_nothing_assessed_renders_honestly(world):
    org = world.make_org()
    owner = world.make_person(org, "owner")
    world.make_domain(org, "empty.snapshot.test")
    pack = _pack(world, org, owner)
    html, pdf_text, _ = _texts(world, org, owner, pack)
    for text in (_collapse(re.sub(r"<[^>]+>", " ", html)), pdf_text):
        assert "0 of" in text and "have evidence" in text
        assert "Nothing has been recorded as evidence yet" in text
        assert "Evidence present" not in text
        assert "Not assessed" in text or "Awaiting your input" in text
    assert NOT_A_CAR in html.lower()


def test_a_non_latin_organisation_name_issues_and_the_pdf_folds_it(world):
    org = world.make_org(name="Ọ̀ṣun Ventures — Lagos")
    owner = world.make_person(org, "owner")
    world.make_domain(org, "osun.snapshot.test")
    pack = _pack(world, org, owner)
    html, pdf_text, pdf = _texts(world, org, owner, pack)
    assert "Ọ̀ṣun Ventures" in html and "Osun Ventures - Lagos" in pdf_text and pdf.startswith(b"%PDF")


# ── Immutability and bytes ───────────────────────────────────────────────


def test_redownload_is_byte_identical_and_later_changes_do_not_touch_an_issued_pack(world):
    org, owner, domain, scan, finding = _assessed_org(world)
    pack = _pack(world, org, owner)
    first = (_get(world, org, owner, f"/{pack['id']}/html").content, _get(world, org, owner, f"/{pack['id']}/pdf").content)
    world.make_finding(org, domain, world.make_scan(org, domain, coverage=None), title="Later critical", severity="critical")
    store.record({"id": org}, owner, question_key="breach.response_plan", answer={"value": "no"}, owner_user_id=owner)
    again = (_get(world, org, owner, f"/{pack['id']}/html").content, _get(world, org, owner, f"/{pack['id']}/pdf").content)
    assert again == first
    import hashlib
    assert hashlib.sha256(first[0]).hexdigest() == pack["html_sha256"]
    assert hashlib.sha256(first[1]).hexdigest() == pack["pdf_sha256"]
    resp = _get(world, org, owner, f"/{pack['id']}/pdf")
    assert resp.headers["etag"] == f'"{pack["pdf_sha256"]}"' and resp.headers["content-type"] == "application/pdf"
    assert b"Later critical" not in first[0]


def test_a_second_issue_makes_a_new_pack_and_leaves_the_first(world):
    org, owner, *_ = _assessed_org(world)
    first = _pack(world, org, owner)
    second = _pack(world, org, owner)
    assert first["id"] != second["id"] and first["snapshot_id"] != second["snapshot_id"]
    assert _get(world, org, owner, "").json()["total"] == 2
    kept = world.rows("SELECT html_sha256 FROM evidence_packs WHERE id = %s", (first["id"],))[0]
    assert kept["html_sha256"] == first["html_sha256"]


def test_a_pack_can_be_issued_again_from_the_same_snapshot(world):
    org, owner, *_ = _assessed_org(world)
    snap = _create(world, org, owner).json()["snapshot"]["id"]
    a = _pack(world, org, owner, snapshot_id=snap)
    b = _pack(world, org, owner, snapshot_id=snap)
    assert a["id"] != b["id"] and a["snapshot_id"] == b["snapshot_id"] == snap


def test_the_app_role_cannot_update_or_delete_a_pack_and_the_owner_cannot_edit_it(world):
    org, owner, *_ = _assessed_org(world)
    pack = _pack(world, org, owner)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        world.as_app("UPDATE evidence_packs SET html = 'x' WHERE id = %s", (pack["id"],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        world.as_app("DELETE FROM evidence_packs WHERE id = %s", (pack["id"],))
    admin = os.environ.get("CYPHWARD_TEST_DATABASE_ADMIN_URL")
    if admin:
        with psycopg.connect(admin) as conn:
            with pytest.raises(psycopg.errors.RaiseException):
                conn.execute("UPDATE evidence_packs SET html = 'x' WHERE id = %s", (pack["id"],))


def test_an_altered_snapshot_is_refused(world, monkeypatch):
    org, owner, *_ = _assessed_org(world)
    from backend.app.snapshots import store as snapshots
    stored = _create(world, org, owner).json()["snapshot"]["id"]   # a snapshot already in the database
    monkeypatch.setattr(snapshots, "verify", lambda row: False)    # ... whose content no longer matches its hash
    assert _issue(world, org, owner, snapshot_id=stored).status_code == 409
    assert world.rows("SELECT count(*) AS n FROM evidence_packs WHERE org_id = %s", (org,))[0]["n"] == 0


# ── Tenants, roles, plan ─────────────────────────────────────────────────


def test_another_organisations_pack_and_snapshot_are_not_found(world):
    org_a, owner_a, *_ = _assessed_org(world)
    org_b, owner_b, *_ = _assessed_org(world)
    pack = _pack(world, org_a, owner_a)
    for path in ("", "/html", "/pdf"):
        assert _get(world, org_b, owner_b, f"/{pack['id']}{path}").status_code == 404
    assert _get(world, org_b, owner_b, "").json()["total"] == 0
    assert _get(world, org_b, owner_b, "/not-a-uuid").status_code == 404
    other = _issue(world, org_b, owner_b, snapshot_id=pack["snapshot_id"])
    assert other.status_code == 404
    assert world.rows("SELECT count(*) AS n FROM evidence_packs WHERE org_id = %s", (org_b,))[0]["n"] == 0
    bad = _issue(world, org_a, owner_a, request_key="x")
    assert bad.status_code == 422


def test_the_database_refuses_a_pack_on_another_organisations_snapshot(world):
    org_a, owner_a, *_ = _assessed_org(world)
    org_b = world.make_org()
    snap = _create(world, org_a, owner_a).json()["snapshot"]["id"]
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        world.setup.execute("INSERT INTO evidence_packs (org_id, snapshot_id, kind, pack_version, issued_at, html, html_sha256, "
                            "pdf, pdf_sha256) VALUES (%s, %s, 'readiness_pack', 'v', now(), 'x', repeat('a', 64), 'x', repeat('b', 64))",
                            (org_b, snap))
    world.setup.rollback()


def test_members_download_but_only_owners_and_admins_issue(world):
    org, owner, *_ = _assessed_org(world)
    member = world.make_person(org, "member")
    admin = world.make_person(org, "admin")
    assert _issue(world, org, member).status_code == 403
    pack = _pack(world, org, admin)
    assert _get(world, org, member, "").json()["total"] == 1
    assert _get(world, org, member, f"/{pack['id']}/pdf").status_code == 200
    assert _get(world, org, member, f"/{pack['id']}/html").status_code == 200


def test_starter_gets_the_growth_plan_treatment_everywhere(world):
    org, owner, *_ = _assessed_org(world, plan="starter")
    assert _issue(world, org, owner).status_code == 403
    assert _get(world, org, owner, "").status_code == 403
    assert _get(world, org, owner, f"/{uuid4()}/pdf").status_code == 403


# ── Concurrency ──────────────────────────────────────────────────────────


def test_concurrent_issue_with_one_key_makes_one_pack_and_distinct_requests_make_distinct_packs(world):
    org, owner, *_ = _assessed_org(world)
    headers = H(world, owner, org)
    with ThreadPoolExecutor(5) as pool:
        same = list(pool.map(lambda _: world.client.post("/api/v1/packs", json={"request_key": "pack-key-0001"}, headers=headers), range(5)))
    assert all(r.status_code == 201 for r in same), [r.text for r in same]
    assert len({r.json()["pack"]["id"] for r in same}) == 1
    with ThreadPoolExecutor(4) as pool:
        many = list(pool.map(lambda _: world.client.post("/api/v1/packs", json={}, headers=headers), range(4)))
    assert all(r.status_code == 201 for r in many)
    assert len({r.json()["pack"]["id"] for r in many}) == 4
    assert world.rows("SELECT count(*) AS n FROM evidence_packs WHERE org_id = %s", (org,))[0]["n"] == 5


# ── DPO section ──────────────────────────────────────────────────────────


def test_dpo_section_counts_scans_findings_and_incidents_without_titles_or_notes(world):
    org, owner, domain, scan, finding = _assessed_org(world)
    world.setup.execute("UPDATE findings SET status = 'resolved', resolved_at = now() WHERE id = %s", (finding,))
    world.make_finding(org, domain, scan, title="Opened one", severity="critical")
    now = datetime.now(timezone.utc)
    world.setup.execute(
        "INSERT INTO compliance_incidents (org_id, title, severity, status, detected_at, became_aware_at, notified_commission_at, notes) "
        "VALUES (%s, 'SECRET-INCIDENT-TITLE', 'high', 'open', %s, %s, %s, 'SECRET-NOTES')",
        (org, now - timedelta(days=3), now - timedelta(days=3), now - timedelta(days=2)))
    world.setup.execute(
        "INSERT INTO compliance_incidents (org_id, title, severity, status, detected_at, became_aware_at) "
        "VALUES (%s, 'Old incident', 'low', 'closed', %s, %s)", (org, now - timedelta(days=400), now - timedelta(days=400)))
    world.setup.commit()
    pack = _pack(world, org, owner)
    dpo = world.rows("SELECT dpo, window_start, window_end FROM evidence_packs WHERE id = %s", (pack["id"],))[0]
    data = dpo["dpo"]
    assert data["scans"]["run"] == 1 and data["scans"]["coverage"]["complete"] == 1
    assert data["findings"]["opened"]["critical"] == 1 and data["findings"]["opened"]["high"] == 1
    assert data["findings"]["resolved"]["high"] == 1
    assert data["incidents"]["logged"] == 1 and data["incidents"]["by_status"]["open"] == 1
    assert data["incidents"]["commission_notified"] == 1
    assert {o["group"] for o in data["observations"]} == {"notices", "consent"}
    assert (dpo["window_end"] - dpo["window_start"]).days == 183
    html, pdf_text, _ = _texts(world, org, owner, pack)
    for text in (html, pdf_text, json.dumps(data)):
        assert "SECRET-INCIDENT-TITLE" not in text and "SECRET-NOTES" not in text and "Old incident" not in text
    assert "DPO six-monthly data-security section" in html and "DPO six-monthly data-security section" in pdf_text
    assert "Arts. 11" in html and NOT_A_CAR in html.lower()


def test_the_dpo_section_can_be_issued_on_its_own_and_left_out_of_the_pack(world):
    org, owner, *_ = _assessed_org(world)
    solo = _pack(world, org, owner, kind="dpo_section")
    html, pdf_text, _ = _texts(world, org, owner, solo)
    assert solo["kind"] == "dpo_section" and "Requirements, status and sources" not in html
    assert "Scans run in the window" in html and "Scans run in the window" in pdf_text
    lean = _pack(world, org, owner, include_dpo=False)
    lean_html, _, _ = _texts(world, org, owner, lean)
    assert "Scans run in the window" not in lean_html and lean["window_start"] is None


def test_dpo_window_is_fixed_by_the_snapshot_not_by_when_the_pack_is_issued(world):
    org, owner, domain, *_ = _assessed_org(world)
    snap = _create(world, org, owner).json()["snapshot"]["id"]
    world.make_scan(org, domain)  # a scan after the snapshot must not count
    pack = _pack(world, org, owner, snapshot_id=snap)
    count = world.rows("SELECT (dpo->'scans'->>'run')::int AS n FROM evidence_packs WHERE id = %s", (pack["id"],))[0]["n"]
    assert count == 1


# ── Claim language ───────────────────────────────────────────────────────


def test_no_claim_language_in_html_pdf_text_or_dpo_section(world):
    org, owner, *_ = _assessed_org(world)
    store.record({"id": org}, owner, question_key="breach.response_plan", answer={"value": "yes"}, owner_user_id=owner)
    for kwargs in ({}, {"kind": "dpo_section"}):
        pack = _pack(world, org, owner, **kwargs)
        html, pdf_text, _ = _texts(world, org, owner, pack)
        for text in (html.lower(), pdf_text.lower()):
            for phrase in BANNED:
                assert phrase not in text, f"{phrase} in {pack['kind']}"


# ── Deletion ─────────────────────────────────────────────────────────────


def test_deleting_the_organisation_removes_its_packs_and_reminders(world):
    org, owner, *_ = _assessed_org(world)
    other, other_owner, *_ = _assessed_org(world)
    _pack(world, org, owner)
    _pack(world, other, other_owner)
    world.setup.execute("INSERT INTO dpo_reminders (org_id, period_key) VALUES (%s, '2026-H2')", (org,))
    world.setup.commit()
    world.setup.execute("DELETE FROM organizations WHERE id = %s", (org,))
    world.setup.commit()
    assert world.rows("SELECT count(*) AS n FROM evidence_packs WHERE org_id = %s", (org,))[0]["n"] == 0
    assert world.rows("SELECT count(*) AS n FROM dpo_reminders WHERE org_id = %s", (org,))[0]["n"] == 0
    assert world.rows("SELECT count(*) AS n FROM evidence_packs WHERE org_id = %s", (other,))[0]["n"] == 1


# ── Six-monthly reminder ─────────────────────────────────────────────────


@pytest.fixture
def mail(monkeypatch):
    sent = []

    async def fake_send(to, subject, html, text=None, name=None, kind="system", reply_to=None):
        sent.append({"to": to, "subject": subject, "html": html, "text": text})
        return {"success": True}

    monkeypatch.setattr(reminders.mailer, "send_email_async", fake_send)
    return sent


@pytest.fixture
def run_days(world):
    days = []

    def next_day():
        d = date(2040, 1, 1) + timedelta(days=uuid4().int % 20000)
        days.append(d)
        return d

    yield next_day
    for d in days:
        world.setup.execute("DELETE FROM cron_runs WHERE cron_name = %s AND run_day = %s", (COMPLIANCE_REMINDERS_CRON_NAME, d))
    world.setup.commit()


def _notes(world, org):
    return world.rows("SELECT type, title, link FROM notifications WHERE org_id = %s AND type = 'compliance_report_due'", (org,))


def test_owners_and_admins_get_one_reminder_per_half_year_and_not_after_a_pack_is_issued(world, mail, run_days):
    org, owner, *_ = _assessed_org(world)
    admin = world.make_person(org, "admin")
    world.make_person(org, "member")
    other, other_owner, *_ = _assessed_org(world)
    starter, starter_owner, *_ = _assessed_org(world, plan="starter")
    now = datetime(2040, 8, 1, 7, 0, tzinfo=timezone.utc)
    result = asyncio.run(reminders.run_compliance_reminders(now=now, run_day=run_days()))
    assert result["claimed"] is True and result["dpo_reminded"] >= 2
    assert len(_notes(world, org)) == 1 and _notes(world, org)[0]["link"] == "/comply"
    assert _notes(world, starter) == []
    to = {m["to"] for m in mail if "Six-monthly" in m["subject"]}
    assert any(f"snap-{owner[:8]}" in t for t in to) and any(f"snap-{admin[:8]}" in t for t in to)
    assert not any("member" in m["subject"] for m in mail)
    body = next(m for m in mail if "Six-monthly" in m["subject"])
    assert NOT_A_CAR in body["text"].lower() and "Compliance Audit Return" in body["text"]
    for phrase in BANNED:
        assert phrase not in (body["text"] + body["html"]).lower()
    # a second run in the same half-year does not repeat it
    asyncio.run(reminders.run_compliance_reminders(now=now + timedelta(days=3), run_day=run_days()))
    assert len(_notes(world, org)) == 1
    # a new half-year reminds again
    asyncio.run(reminders.run_compliance_reminders(now=datetime(2041, 1, 5, 7, 0, tzinfo=timezone.utc), run_day=run_days()))
    assert len(_notes(world, org)) == 2
    assert world.rows("SELECT count(*) AS n FROM dpo_reminders WHERE org_id = %s", (org,))[0]["n"] == 2


def test_an_organisation_that_issued_a_pack_this_half_year_is_not_reminded(world, mail, run_days):
    org, owner, *_ = _assessed_org(world)
    _pack(world, org, owner)
    now = datetime.now(timezone.utc) + timedelta(minutes=5)
    asyncio.run(reminders.run_compliance_reminders(now=now, run_day=run_days()))
    assert _notes(world, org) == []


# ── Quota: a pack is one report-sized unit; its own snapshot is not counted again ───────────────────────


def _limit(monkeypatch, n):
    from backend.app.core import plans
    monkeypatch.setitem(plans.PLANS["growth"], "monthly_reports", n)


def _usage(org):
    from backend.app.core.plans import usage_for_org
    return usage_for_org(org)["monthly_reports"]


def test_a_pack_with_a_fresh_snapshot_uses_exactly_one_unit_even_on_the_last_one(world, monkeypatch):
    _limit(monkeypatch, 2)
    org, owner, *_ = _assessed_org(world)
    assert _create(world, org, owner).status_code == 201          # 1 unit used
    first = _issue(world, org, owner)                             # the last unit: pack + its fresh snapshot
    assert first.status_code == 201 and _usage(org) == 2
    blocked = _issue(world, org, owner)
    assert blocked.status_code == 402 and "quota reached" in blocked.json()["detail"]
    assert _usage(org) == 2, "a refused pack must not leave a snapshot behind that uses another unit"
    assert world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["n"] == 2


def test_a_pack_made_from_an_existing_snapshot_takes_over_its_unit(world, monkeypatch):
    _limit(monkeypatch, 1)
    org, owner, *_ = _assessed_org(world)
    snap = _create(world, org, owner).json()["snapshot"]["id"]
    assert _usage(org) == 1
    made = _issue(world, org, owner, snapshot_id=snap)
    assert made.status_code == 201 and _usage(org) == 1, "the pack replaces the snapshot's unit"
    again = _issue(world, org, owner, snapshot_id=snap)
    assert again.status_code == 402, "a second pack is a new unit"


def test_a_retried_pack_request_key_is_not_charged_twice(world, monkeypatch):
    _limit(monkeypatch, 1)
    org, owner, *_ = _assessed_org(world)
    first = _issue(world, org, owner, request_key="pack-retry-0001")
    again = _issue(world, org, owner, request_key="pack-retry-0001")
    assert first.status_code == 201 and again.status_code == 201 and again.json()["created"] is False
    assert _usage(org) == 1


def test_a_pack_and_a_snapshot_cannot_both_take_the_last_unit(world, monkeypatch):
    _limit(monkeypatch, 2)
    org, owner, *_ = _assessed_org(world)
    assert _create(world, org, owner).status_code == 201
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(f.result().status_code for f in [pool.submit(_issue, world, org, owner), pool.submit(_create, world, org, owner)])
    assert codes == [201, 402]
    assert _usage(org) == 2


def test_another_organisations_packs_do_not_use_this_ones_quota(world, monkeypatch):
    _limit(monkeypatch, 1)
    a, owner_a, *_ = _assessed_org(world, name="Pack quota A")
    b, owner_b, *_ = _assessed_org(world, name="Pack quota B")
    assert _issue(world, a, owner_a).status_code == 201
    assert _issue(world, b, owner_b).status_code == 201
    assert _issue(world, a, owner_a).status_code == 402


# ── Busy: the same bounded build slots and lock wait as snapshots ─────────────────────────────────────


def test_a_busy_slot_or_a_held_lock_gives_a_clean_503_and_issues_nothing(world, monkeypatch):
    import threading
    from backend.app.snapshots import store as snapshot_store
    org, owner, *_ = _assessed_org(world)
    snap = _create(world, org, owner).json()["snapshot"]["id"]
    monkeypatch.setattr(snapshot_store, "_BUILD_SLOTS", threading.BoundedSemaphore(1))
    monkeypatch.setattr(snapshot_store, "BUSY_WAIT_SECONDS", 0.2)
    snapshot_store._BUILD_SLOTS.acquire()
    busy = _issue(world, org, owner, snapshot_id=snap)
    assert busy.status_code == 503 and busy.headers["Retry-After"] == "5"
    snapshot_store._BUILD_SLOTS.release()
    monkeypatch.setattr(snapshot_store, "LOCK_WAIT_MS", 300)
    holder = psycopg.connect(world.url)
    try:
        holder.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"snapshot:{org}",))
        assert _issue(world, org, owner, snapshot_id=snap).status_code == 503
    finally:
        holder.rollback()
        holder.close()
    assert world.rows("SELECT count(*) AS n FROM evidence_packs WHERE org_id = %s", (org,))[0]["n"] == 0
    assert _issue(world, org, owner, snapshot_id=snap).status_code == 201


# ── Retention ───────────────────────────────────────────────────────────────────────────────────────


def test_packs_show_when_they_become_eligible_for_removal_and_follow_the_setting(world):
    org, owner, *_ = _assessed_org(world)
    pack = _issue(world, org, owner).json()["pack"]
    issued, until = datetime.fromisoformat(pack["issued_at"]), datetime.fromisoformat(pack["retain_until"])
    assert until.year == issued.year + 3 and until.month == issued.month
    assert world.client.put("/api/v1/snapshots/retention", json={"months": 24}, headers=H(world, owner, org)).status_code == 200
    listing = _get(world, org, owner, "").json()
    assert listing["retention_months"] == 24 and "24 months" in listing["retention"]
    assert datetime.fromisoformat(listing["packs"][0]["retain_until"]).year == issued.year + 2
    assert "Names of answer owners" in listing["retention"]


def test_the_retention_text_and_pack_list_never_claim_compliance(world):
    org, owner, *_ = _assessed_org(world)
    _issue(world, org, owner)
    text = json.dumps(_get(world, org, owner, "").json()).lower()
    for phrase in BANNED + ("certification", "adequate", "adequacy", "guarantee"):
        assert phrase not in text, phrase


# ── Review round 1: no orphan snapshots, big packs render, honest errors ────────────────────────────────


def _counts(world, org):
    return (world.rows("SELECT count(*) AS n FROM assessment_snapshots WHERE org_id = %s", (org,))[0]["n"],
            world.rows("SELECT count(*) AS n FROM evidence_packs WHERE org_id = %s", (org,))[0]["n"], _usage(org))


def test_a_pack_with_a_fresh_snapshot_commits_both_or_neither(world, monkeypatch):
    org, owner, *_ = _assessed_org(world)

    def boom(doc):
        raise RuntimeError("the PDF could not be drawn")

    monkeypatch.setattr(render, "to_pdf", boom)
    with pytest.raises(RuntimeError):
        _issue(world, org, owner)
    assert _counts(world, org) == (0, 0, 0), "a failed render must leave no snapshot, no pack and no charge"


def test_concurrent_retries_with_one_key_make_one_snapshot_one_pack_and_one_unit(world, monkeypatch):
    _limit(monkeypatch, 5)
    org, owner, *_ = _assessed_org(world)
    with ThreadPoolExecutor(max_workers=5) as pool:
        replies = [f.result() for f in [pool.submit(_issue, world, org, owner, request_key="one-key-0000001") for _ in range(5)]]
    assert {r.status_code for r in replies} == {201}
    assert len({r.json()["pack"]["id"] for r in replies}) == 1
    assert _counts(world, org) == (1, 1, 1)


def test_a_busy_fresh_issue_leaves_nothing_behind(world, monkeypatch):
    import threading
    from backend.app.snapshots import store as snapshot_store
    org, owner, *_ = _assessed_org(world)
    monkeypatch.setattr(snapshot_store, "_BUILD_SLOTS", threading.BoundedSemaphore(1))
    monkeypatch.setattr(snapshot_store, "BUSY_WAIT_SECONDS", 0.2)
    snapshot_store._BUILD_SLOTS.acquire()
    assert _issue(world, org, owner).status_code == 503
    snapshot_store._BUILD_SLOTS.release()
    assert _counts(world, org) == (0, 0, 0)


def test_a_request_key_used_for_a_snapshot_without_a_pack_is_a_409_not_a_charge(world, monkeypatch):
    _limit(monkeypatch, 5)
    org, owner, *_ = _assessed_org(world)
    assert _create(world, org, owner, request_key="shared-key-00001").status_code == 201
    clash = _issue(world, org, owner, request_key="shared-key-00001")
    assert clash.status_code == 409 and _counts(world, org) == (1, 0, 1)


def test_a_request_key_reused_for_a_different_pack_is_a_409(world):
    org, owner, *_ = _assessed_org(world)
    assert _issue(world, org, owner, kind="readiness_pack", request_key="reuse-key-00001").status_code == 201
    assert _issue(world, org, owner, kind="dpo_section", request_key="reuse-key-00001").status_code == 409
    assert _issue(world, org, owner, kind="readiness_pack", request_key="reuse-key-00001").json()["created"] is False


def test_a_requirement_with_hundreds_of_linked_findings_still_renders_a_pdf_and_html(world):
    from backend.app.packs import document
    org, owner, *_ = _assessed_org(world)
    snap = _create(world, org, owner).json()["snapshot"]
    row = world.rows("SELECT * FROM assessment_snapshots WHERE id = %s", (snap["id"],))[0]
    content = row["content"]
    target = next(r for r in content["compliance"]["requirements"] if r["group"] == "security")
    # Findings only exist on a requirement that has a source (the view derives one from them).
    target.update(source="tool_observed", source_label="Tool observed", sources=[])
    target["findings"] = [{"id": str(i), "title": f"Header finding number {i} on a long host name example.snapshot.test",
                           "severity": "high", "status": "open"} for i in range(600)]
    doc = document.build("readiness_pack", row, content, datetime.now(timezone.utc), None)
    pdf, html = render.to_pdf(doc), render.to_html(doc)
    text = " ".join(render.pdf_extract_text(pdf).split())
    assert pdf.startswith(b"%PDF")
    assert re.search(r"and \d{3} more references", text) and re.search(r"and \d{3} more references", html)
    assert text.count("Header finding number") <= 12 * 40, "only a handful of the findings are listed in each cell"


def test_the_pack_list_total_is_the_real_count_and_a_bad_id_is_a_404(world):
    org, owner, *_ = _assessed_org(world)
    for _ in range(3):
        _pack(world, org, owner)
    assert _get(world, org, owner, "").json()["total"] == 3
    for suffix in ("/not-a-uuid", "/not-a-uuid/pdf", "/not-a-uuid/html"):
        assert _get(world, org, owner, suffix).status_code == 404


def test_the_dpo_section_says_when_its_counts_were_read(world):
    org, owner, *_ = _assessed_org(world)
    pack = _pack(world, org, owner)
    text = _collapse(world.rows("SELECT html FROM evidence_packs WHERE id = %s", (pack["id"],))[0]["html"])
    assert "These counts were read on the day this pack was issued" in text


def test_the_pack_scan_for_claim_language_uses_the_full_banned_list(world):
    org, owner, *_ = _assessed_org(world)
    pack = _pack(world, org, owner)
    html = world.rows("SELECT html, pdf FROM evidence_packs WHERE id = %s", (pack["id"],))[0]
    texts = [_collapse(html["html"]).lower(), _collapse(render.pdf_extract_text(bytes(html["pdf"]))).lower()]
    for text in texts:
        scrubbed = text.replace("tls certificate", "").replace("certificate", "")
        for phrase in BANNED + ("certification", "adequate", "adequacy", "guarantee"):
            assert phrase not in scrubbed, phrase


def test_a_pack_without_the_dpo_section_does_not_stop_the_six_monthly_reminder(world, mail, run_days):
    org, owner, *_ = _assessed_org(world)
    _pack(world, org, owner, kind="readiness_pack", include_dpo=False)
    assert world.rows("SELECT dpo FROM evidence_packs WHERE org_id = %s", (org,))[0]["dpo"] is None
    now = datetime.now(timezone.utc) + timedelta(minutes=5)
    asyncio.run(reminders.run_compliance_reminders(now=now, run_day=run_days()))
    assert len(_notes(world, org)) == 1


def test_the_worst_case_cell_still_fits_a_pdf_row(world):
    """8 references of the longest allowed size, in the widest letters and as one unbroken string, in every group."""
    from backend.app.packs import document
    org, owner, *_ = _assessed_org(world)
    snap = _create(world, org, owner).json()["snapshot"]
    row = world.rows("SELECT * FROM assessment_snapshots WHERE id = %s", (snap["id"],))[0]
    content = row["content"]
    for kind, title in (("wide capitals", "WWWWMMMM " * 40), ("unbroken", "A" * 400), ("mixed", "Header Finding Title With Words " * 12)):
        for req in content["compliance"]["requirements"]:
            req["findings"] = [{"id": str(i), "title": title, "severity": "high", "status": "open"} for i in range(900)]
        doc = document.build("readiness_pack", row, content, datetime.now(timezone.utc), None)
        assert render.to_pdf(doc).startswith(b"%PDF"), kind
        assert render.to_html(doc), kind


def test_dpo_contact_row_shows_one_source_first_and_the_other_on_an_also_line(world):
    """The production mix: an observed (externally observed, not assessed) result and no customer answer."""
    org, owner, domain, scan, _ = _assessed_org(world)
    world.setup.execute(
        "INSERT INTO compliance_evidence (org_id, domain_id, requirement_key, register_version, source, status, "
        "observed_at, scan_id, details) VALUES (%s, %s, 'gaid.dpo.contact_published', %s, 'externally_observed', "
        "'not_assessed', now(), %s, '{}')", (org, domain, REGISTER["version"], scan))
    world.setup.commit()
    pack = _pack(world, org, owner)
    html, pdf_text, _ = _texts(world, org, owner, pack)
    snap = world.rows("SELECT content FROM assessment_snapshots WHERE id = %s", (pack["snapshot_id"],))[0]["content"]
    req = next(r for r in snap["compliance"]["requirements"] if r["key"] == "gaid.dpo.contact_published")
    assert (req["status"], req["source"]) == ("awaiting_input", "customer_attested")
    assert req["sources"][0]["headline"] is True and req["sources"][0]["source"] == req["source"]
    assert {s["source"] for s in req["sources"]} == {"externally_observed", "customer_attested"}
    headline = "Customer attested: Awaiting your input; no answer recorded yet"
    other = f"Also: Externally observed: assessed.snapshot.test: Not assessed, observed"
    flat = _collapse(re.sub(r"<[^>]+>", " ", html))
    for text in (pdf_text, flat):
        assert headline in text and other in text
        assert text.index(headline) < text.index(other)
        assert f"scan {scan[:8]}" in text
