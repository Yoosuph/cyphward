"""The branded (v2) evidence pack: cover, summary, footers, page numbers, one legend, frozen-record page (PR-B).

Pure: the documents are built from the real register through the real status view, then rendered to HTML and
to a real PDF whose text is extracted and scanned. Layout is also run with worst-case content.
"""
import hashlib
import re
import uuid
from pathlib import Path
from datetime import datetime, timezone
from html import unescape
from unittest import mock

import pytest

from backend.app.compliance import status as cstatus
from backend.app.compliance.register import DISCLAIMER, REGISTER
from backend.app.packs import branded, document, render
from backend.app.snapshots import builder
from backend.tests import test_pack_row_consistency as base

SHA = "84f60b156390" + "ab" * 26
BANNED = base.BANNED
ISSUED = datetime(2026, 10, 19, 14, 45, tzinfo=timezone.utc)


def make(observed="present", answers="yes", org="INNOVATECH Nigeria Limited", findings=0, domains=1, kind="readiness_pack",
         dpo=None, v1=False, verified=(), domain_len=0):
    ctx = base._ctx(observed, answers)

    def attach(org_id, views):
        for v in views:
            v["findings"] = [{"id": str(i), "title": f"Strict-Transport-Security header missing on host{i}.example.com",
                              "severity": "high", "status": "open"} for i in range(findings)] if v["group"] == "security" else []
            v["informational_findings"] = []
    with mock.patch.object(cstatus, "_context", lambda o: ctx), mock.patch.object(cstatus, "_attach_findings", attach):
        comp = builder._compliance("org", base.NOW)
    snap = {"generated_at": base.NOW.isoformat(), "scope": {"org_name": org, "domains": [
        {"domain": f"d{i}.example.com" + "x" * domain_len} for i in range(domains)]},
        "dates": {"earliest_observation": base.NOW.isoformat(), "latest_observation": base.NOW.isoformat()},
        "compliance": comp}
    for r in comp["requirements"]:
        if r["key"] in verified:
            r["clause_verified"] = True
    row = {"id": str(uuid.uuid4()), "seq": 3, "content_sha256": SHA}
    pack_id = str(uuid.uuid4())
    return document.build(kind, row, snap, ISSUED, dpo, pack_id=None if v1 else pack_id), row, pack_id


def texts(doc):
    html = render.to_html(doc)
    pdf = render.to_pdf(doc)
    return html, " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split()), pdf, " ".join(render.pdf_extract_text(pdf).split())


CASES = {"full data": dict(), "all not assessed": dict(observed="none", answers="none"),
         "600 findings": dict(observed="gap", answers="no", findings=600)}


@pytest.mark.parametrize("case", CASES)
def test_cover_summary_footer_page_numbers_legend_and_frozen_record_in_both_renderings(case):
    doc, row, pack_id = make(**CASES[case])
    html, flat, pdf, pdf_text = texts(doc)
    pages = len(re.findall(rb"/Type /Page\b", pdf))
    assert pages >= 5
    for text in (flat, pdf_text):
        assert "INNOVATECH Nigeria Limited" in text and "NDPA readiness evidence pack" in text
        assert pack_id in text and "2026-10-19 14:45 UTC" in text
        assert "Summary" in text and "Readiness at a glance" in text and "Top prioritised gaps" in text
        assert "register" in text.lower() and REGISTER["version"] in text
        assert DISCLAIMER in text and "not a Compliance Audit Return" in text
        assert text.count("reference pending review") == 1
        assert "† = reference pending review" in text
        assert f"Frozen record: snapshot {row['id']}, sha256 {SHA}" in text
        assert "Prepared with Cyphward" in text
    assert "Cyphward logo" in html and "<svg" in html
    # HTML footer on every printed page and page counters; PDF: footer and "Page X of Y" on every page.
    assert "counter(page)" in html and "counter(pages)" in html and "@bottom-left" in html and document.SHORT_DISCLAIMER in html.split("</style>")[0]
    assert pdf_text.count("Prepared with Cyphward") == pages
    assert pdf_text.count(f"{document.SHORT_DISCLAIMER} Prepared with Cyphward") == pages
    for n in range(1, pages + 1):
        assert f"Page {n} of {pages}" in pdf_text
    assert f"Page {pages + 1} of" not in pdf_text
    # The frozen record is on the last page.
    assert pdf_text.rindex("Frozen record: snapshot") > pdf_text.index(f"Page {pages - 1} of {pages}")


def test_readiness_is_counts_never_a_percentage_and_names_gaps_and_awaiting():
    doc, *_ = make("gap", "no")
    summary = " ".join(b.get("text", "") for b in doc["summary"] if b["type"] == "para")
    stats = next(b for b in doc["summary"] if b["type"] == "stats")["items"]
    assert [label for label, _ in stats] == ["With evidence", "Gaps", "Awaiting input", "Not assessed", "Applicable"]
    html, flat, pdf, pdf_text = texts(doc)
    assert "%" not in summary and "percent" not in flat.lower()
    assert "awaiting input or upcoming checks" in flat and "awaiting input or upcoming checks" in pdf_text


def test_all_not_assessed_pack_says_nothing_has_been_recorded():
    doc, *_ = make("none", "none")
    html, flat, pdf, pdf_text = texts(doc)
    for text in (flat, pdf_text):
        assert "0 of" in text and "Nothing has been recorded as evidence yet" in text and "Evidence present" not in text


def test_every_unverified_row_has_the_marker_and_the_phrase_appears_once():
    doc, *_ = make()
    rows = [r for b in doc["blocks"] if b["type"] == "table" and b["head"][0] == "Requirement" for r in b["rows"]]
    unverified = [r for r in REGISTER["requirements"] if not r["clause_verified"]]
    assert len(rows) == len(REGISTER["requirements"])
    for req in unverified:
        assert any(row[0] == f"{req['title']} ({req['clause']} †)" for row in rows), req["key"]
    assert all("reference pending review" not in c for b in doc["blocks"] if b["type"] == "table" for r in b["rows"] for c in r)


@pytest.mark.parametrize("case", CASES)
def test_no_verdict_language_in_the_html_or_the_extracted_pdf_text(case):
    html, flat, pdf, pdf_text = texts(make(**CASES[case])[0])
    for text in (flat.lower(), pdf_text.lower()):
        assert [w for w in BANNED if w in text] == []


def test_worst_case_content_lays_out_without_error_and_stays_bounded():
    doc, row, pack_id = make("gap", "no", org="Ọ̀ṣun " + "Very Long Organisation Name " * 30, findings=600, domains=500)
    html, flat, pdf, pdf_text = texts(doc)
    assert pdf.startswith(b"%PDF") and len(pdf) < 3_000_000
    assert "Osun Very Long" in pdf_text and re.search(r"and \d+ more", pdf_text)  # the scope line is capped by characters
    assert len(doc["cover"]["org"]) <= document.MAX_NAME_CHARS
    assert f"Frozen record: snapshot {row['id']}" in pdf_text
    assert pdf_text.count("Header finding") == 0 and pdf_text.count("Strict-Transport-Security") <= 12 * 40


def test_markup_in_names_is_escaped_in_html_and_literal_in_the_pdf():
    doc, *_ = make(org='<script>alert(1)</script> & "Co"')
    html, flat, pdf, pdf_text = texts(doc)
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert '<script>alert(1)</script>&"Co"' in pdf_text.replace(" ", "")  # reportlab splits runs at entities


DPO = {"window": {"start": "2026-04-19T00:00:00+00:00", "end": "2026-10-19T00:00:00+00:00"},
           "scans": {"run": 4, "by_status": {"completed": 4}, "verified_domains": 1,
                     "coverage": {"complete": 3, "partial": 1, "unassessed": 0, "unknown": 0}},
           "findings": {"opened": dict.fromkeys(("critical", "high", "medium", "low"), 1),
                        "resolved": dict.fromkeys(("critical", "high", "medium", "low"), 0),
                        "open_at_snapshot": {}},
           "incidents": {"logged": 2, "by_status": {"open": 2}, "by_severity": {"high": 2}, "commission_notified": 0},
           "observations": []}


def test_dpo_section_pack_has_the_same_frame():
    dpo = DPO
    doc, row, pack_id = make(kind="dpo_section", dpo=dpo)
    html, flat, pdf, pdf_text = texts(doc)
    pages = len(re.findall(rb"/Type /Page\b", pdf))
    for text in (flat, pdf_text):
        assert "DPO six-monthly data-security section" in text and pack_id in text
        assert f"Frozen record: snapshot {row['id']}, sha256 {SHA}" in text
        assert text.count("reference pending review") == 1
    assert f"Page {pages} of {pages}" in pdf_text


def test_v1_documents_still_build_and_render_in_the_original_layout():
    """Without a pack id the original layout is built; its renderer path is unchanged."""
    ctx = base._ctx("present", "yes")
    with mock.patch.object(cstatus, "_context", lambda o: ctx), mock.patch.object(
            cstatus, "_attach_findings", lambda o, views: [v.update(findings=[], informational_findings=[]) for v in views]):
        comp = builder._compliance("org", base.NOW)
    snap = {"generated_at": base.NOW.isoformat(), "scope": {"org_name": "Old Co", "domains": []},
            "dates": {"earliest_observation": None, "latest_observation": None}, "compliance": comp}
    doc = document.build("readiness_pack", {"seq": 1, "content_sha256": SHA}, snap, ISSUED, None)
    assert "version" not in doc and ("Pack version", document.PACK_VERSION_V1_1) in doc["meta"]
    html = render.to_html(doc)
    assert "cyphward-ndpa-pack-v1.1" in html and "Prepared with Cyphward" not in html and "runfoot" not in html
    assert document.PACK_VERSION == "cyphward-ndpa-pack-v2" and document.PACK_VERSION_V1 == "cyphward-ndpa-pack-v1"
    assert render.to_pdf(doc).startswith(b"%PDF")


def test_the_logo_shapes_are_the_favicons():
    svg = ((Path(__file__).resolve().parents[2] / "frontend/public/favicon.svg").read_text())
    for points in (branded.OUTER, branded.INNER, branded.DIAMOND):
        first = points[0]
        assert f"M{first[1]:g} {first[2]:g}" in svg


def test_line_breaks_in_the_organisation_name_stay_on_one_line():
    doc, *_ = make(org="Acme\u2028Ltd\nAlso: forged")
    assert doc["cover"]["org"] == "Acme Ltd Also: forged"
    html, flat, pdf, pdf_text = texts(doc)
    assert "<br>" not in html.split('class="org">')[1].split("</p>")[0]


def test_a_verified_clause_has_no_dagger_and_the_others_do_and_the_legend_stays_single():
    key = REGISTER["requirements"][0]["key"]
    doc, *_ = make(verified=(key,))
    rows = {r[0]: r for b in doc["blocks"] if b["type"] == "table" and b["head"][0] == "Requirement" for r in b["rows"]}
    plain = [r for r in REGISTER["requirements"] if r["key"] == key][0]
    assert f"{plain['title']} ({plain['clause']})" in rows
    assert sum(1 for k in rows if k.endswith("\u2020)")) == len(REGISTER["requirements"]) - 1
    html, flat, pdf, pdf_text = texts(doc)
    for text in (flat, pdf_text):
        assert text.count("reference pending review") == 1 and f"{plain['title']} ({plain['clause']})" in text


def test_the_dagger_is_kept_in_branded_pdfs_only_and_v1_bytes_are_unchanged():
    """v1/v1.1 PDFs fold a dagger to '?' exactly as before; the golden hash is the stored-byte rendering on main."""
    doc = {"title": "Dagger \u2020 Co", "meta": [("Organisation", "Dagger \u2020 Co")],
           "blocks": [{"type": "para", "text": "Dagger \u2020 Co: caf\u00e9"}]}
    pdf = render.to_pdf(doc)
    assert "Dagger ? Co" in render.pdf_extract_text(pdf) and "\u2020" not in render.pdf_extract_text(pdf)
    assert render.pdf_text("a\u2020b") == "a?b"
    assert hashlib.sha256(pdf).hexdigest() == V1_DAGGER_GOLDEN
    assert branded.pdf_text("a\u2020b") == "a\u2020b"


@pytest.mark.parametrize("count,length", [(17, 253), (40, 110), (500, 30), (3, 5000)])
def test_long_domain_lists_never_break_the_layout(count, length):
    doc, row, pid = make(domains=count, domain_len=length)
    assert len(doc["summary"][4]["rows"][1][1]) <= document.MAX_DOMAINS_CHARS + 60
    html, flat, pdf, pdf_text = texts(doc)
    assert pdf.startswith(b"%PDF") and f"Frozen record: snapshot {row['id']}" in pdf_text


def test_a_blank_organisation_name_falls_back_and_a_non_latin_one_gets_a_clear_note():
    doc, *_ = make(org=" \u200b\n ")
    assert doc["cover"]["org"] == "Organisation"
    doc, *_ = make(org="\u0634\u0631\u0643\u0629 \u0627\u0644\u0646\u0648\u0631 Ltd")
    html, flat, pdf, pdf_text = texts(doc)
    cover = pdf_text.split("Page 1 of")[0]
    assert "?" not in cover and "cannot show" in cover and "Organisation (name shown in the HTML version)" in cover
    assert "Ltd" not in cover  # never a leftover fragment of the real name
    assert pdf_text.count("Organisation (name shown in the HTML version)") >= 2  # cover and facts table
    assert "\u0634\u0631\u0643\u0629" in html
    doc, *_ = make(org='\u05d7\u05d1\u05e8\u05d4 "X"')
    cover = texts(doc)[3].split("Page 1 of")[0]
    assert "Organisation (name shown in the HTML version)" in cover and '"' not in cover.split("PREPARED FOR")[1].split("ISSUED")[0].replace("The organisation name contains", "")


def test_bidi_and_zero_width_controls_are_stripped_from_user_text():
    assert document.flat("a\u202eb\u200bc\u2066d\ufeffe", True) == "a b c d e"
    assert document.flat("a\u202eb") == "a\u202eb"  # v1 is unchanged


def test_dpo_legend_does_not_describe_requirement_rows():
    doc, *_ = make(kind="dpo_section", dpo=DPO)
    legend = next(b for b in doc["blocks"] if b["type"] == "legend")["text"]
    assert "reference pending review" in legend and "Each row" not in legend


def test_html_print_footer_is_a_page_margin_box_not_a_fixed_overlay():
    html = render.to_html(make()[0])
    assert "position:fixed" not in html and "@bottom-left" in html and "@bottom-right" in html


V1_DAGGER_GOLDEN = "a9f8c554652fe9af3d6036d3481b655cb66933100e7d37a934c41dc932a0393a"  # sha256 of the PDF the v1 renderer on main produced for the document above


ZW = "​‌‮﻿"  # zero-width space, ZWNJ, RLO, BOM: v1 keeps them exactly as issued


def v1_fixture():
    """A deterministic snapshot whose user-supplied text carries invisible and bidi characters."""
    reqs = []
    for n, r in enumerate(REGISTER["requirements"][:3]):
        reqs.append({
            "key": r["key"], "group": r["group"], "title": r["title"], "clause": r["clause"],
            "clause_verified": False, "summary": r["summary"], "status": "present", "status_label": "Evidence present",
            "reason": "x", "reason_text": "Reason text.", "source": "customer_attested",
            "source_label": "Customer attested", "remediation_hint": "Do the thing.",
            "sources": [{"source": "customer_attested", "source_label": "Customer attested", "status": "present",
                         "status_label": "Evidence present", "reason": "x"}],
            "domains": [{"domain": f"d{n}{ZW}.example.com", "status": "present", "status_label": "Evidence present",
                         "source": "tool_observed", "source_label": "Tool observed", "observed_at": "2026-10-17T14:48:00+00:00",
                         "scan_id": "654136c6-0000-0000-0000-000000000000"}],
            "findings": [{"title": f"Finding{ZW} {n}", "severity": "high", "status": "open"}],
            "answers": [{"question_key": f"q{n}", "owner_name": f"Ada{ZW}\nOwner", "expires_at": "2027-08-15T00:00:00+00:00"}]})
    comp = {"readiness": {"with_evidence": 3, "present": 3, "gap": 0, "awaiting_input": 0, "not_assessed": 0, "applicable": 3},
            "register": {"title": "Register", "version": "v1"},
            "attestations": [{"question_key": f"q{n}", "attested_at": "2026-10-14T10:00:00+00:00",
                              "evidence_link": f"https://example.test/a{ZW}b"} for n in range(3)],
            "groups": [{"key": g, "title": g} for g in dict.fromkeys(r["group"] for r in reqs)], "requirements": reqs}
    snap = {"generated_at": "2026-10-17T14:50:00+00:00", "scope": {"org_name": f"Org{ZW} Ltd", "domains": [{"domain": f"a{ZW}.example.com"}]},
            "dates": {"earliest_observation": "2026-10-17T14:48:00+00:00", "latest_observation": "2026-10-17T14:49:00+00:00"},
            "compliance": comp}
    return {"id": "00000000-0000-0000-0000-000000000001", "seq": 1, "content_sha256": "0" * 64}, snap


def test_v1_packs_built_through_document_build_reproduce_the_hashes_main_produced():
    row, snap = v1_fixture()
    doc = document.build("readiness_pack", row, snap, ISSUED, None)  # no pack id: the v1.1 layout
    assert hashlib.sha256(render.to_html(doc).encode()).hexdigest() == V1_BUILD_HTML_GOLDEN
    assert hashlib.sha256(render.to_pdf(doc)).hexdigest() == V1_BUILD_PDF_GOLDEN


def test_v2_strips_bidi_and_zero_width_space_but_keeps_zwnj_and_zwj():
    assert document.flat("a‮b​c﻿d⁦e", True) == "a b c d e"
    assert document.flat("می‌خواهم a‍b", True) == "می‌خواهم a‍b"
    row, snap = v1_fixture()
    doc = document.build("readiness_pack", row, snap, ISSUED, None, pack_id=str(uuid.uuid4()))
    cells = " ".join(c for b in doc["blocks"] if b["type"] == "table" for r in b["rows"] for c in r)
    assert "‮" not in cells and "​" not in cells and "﻿" not in cells and "Ada \u200c Owner" in cells


V1_BUILD_HTML_GOLDEN = "724644f09b0ee9702538034969467b9d855152f80e369ab591e67829d7ae1836"  # pinned from main (v1.1 builder and renderer) before this change
V1_BUILD_PDF_GOLDEN = "b47d76464b052c93da2741fa299be777793111a9b61000d04fe4f2a70856d270"
