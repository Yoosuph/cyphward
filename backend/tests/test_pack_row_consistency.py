"""A requirement row's Status, Source and Evidence always describe the same evidence item (PR-A).

Before this rule, a requirement with BOTH an observed result and a customer answer showed the headline
status and source from the answer side (`attestations.merge`) next to evidence text that listed the observed
side first. The property below runs the real register through every combination of observed result x customer
answer and checks, on every surface (the /comply view, the frozen snapshot content, the pack document, the
HTML and the text extracted from the PDF), that the row's (status, source) pair is one of the requirement's
`sources` pairs and that its evidence text names that same source first.

Pure: no database. The statuses come from the real mapping and truth table, not from hand-built views.
"""
import itertools
import re
from datetime import datetime, timedelta, timezone
from html import unescape

import pytest

from backend.app.compliance import mapping, status as cstatus
from backend.app.compliance.register import REGISTER
from backend.app.packs import document, render
from backend.app.snapshots import builder

NOW = datetime.now(timezone.utc)
DOMAIN = {"id": "11111111-1111-1111-1111-111111111111", "domain": "cyphward.com"}
SCAN = "654136c6-0000-0000-0000-000000000000"
SOURCE_LABELS = cstatus.SOURCE_LABELS
BANNED = ("compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit",
          "compliance score", "fully meets", "meets the requirement", "is met", "partial compliance",
          "fully compliant", "is compliant", "satisfy ndpa", "adequate", "adequacy", "guarantee")
OBSERVED = ("none", "present", "gap", "not_assessed", "expired")
ANSWERS = ("none", "yes", "no", "not_sure", "expired")


def _observed_row(kind):
    if kind == "none":
        return None
    expired = kind == "expired"
    return {"status": "present" if expired else kind, "observed_at": NOW - timedelta(days=2),
            "expires_at": NOW - timedelta(days=1) if expired else NOW + timedelta(days=30),
            "scan_id": SCAN, "finding_ids": [], "details": {"reason": "checks_conclusive"}}


def _answers(kind):
    if kind == "none":
        return {}
    from backend.app.compliance import questionnaire as qn
    rows = {}
    for q in qn.QUESTIONS:
        values = qn.values_for(q)
        value = {"yes": "date" if "date" in values else "yes", "no": "no" if "no" in values else qn.NOT_SURE,
                 "not_sure": qn.NOT_SURE, "expired": "yes" if "yes" in values else "date"}[kind]
        body = {"value": value}
        if value == "date":
            body["date"] = (NOW - timedelta(days=30)).date().isoformat()
        expires = NOW - timedelta(days=1) if kind == "expired" else NOW + timedelta(days=300)
        rows[q["key"]] = {"id": f"id-{q['key']}", "question_key": q["key"], "answer": body, "owner_user_id": "u",
                          "owner_name": "Ada Owner", "attested_at": NOW - timedelta(days=5), "expires_at": expires,
                          "evidence_link": None}
    return rows


def _ctx(observed, answers):
    row = _observed_row(observed)
    latest = {}
    if row:
        latest = {r["key"]: {DOMAIN["id"]: {**row, "requirement_key": r["key"], "domain_id": DOMAIN["id"]}}
                  for r in REGISTER["requirements"]}
    return {"domains": [DOMAIN], "latest": latest, "live": [], "history": [], "answers": _answers(answers)}


@pytest.fixture
def surfaces(monkeypatch):
    """(view, snapshot requirement, document row, html row, pdf-text) per requirement for one combination."""
    def build(observed, answers):
        ctx = _ctx(observed, answers)

        def attach(org_id, views):
            for v in views:
                v["findings"], v["informational_findings"] = [], []
        monkeypatch.setattr(cstatus, "_context", lambda org_id: ctx)
        monkeypatch.setattr(cstatus, "_attach_findings", attach)
        views = [cstatus._requirement_view(r, ctx, NOW) for r in REGISTER["requirements"]]
        comp = builder._compliance("org", NOW)
        snapshot = {"generated_at": NOW.isoformat(), "scope": {"org_name": "INNOVATECH", "domains": [DOMAIN]},
                    "dates": {"earliest_observation": None, "latest_observation": None}, "compliance": comp}
        doc = document.build("readiness_pack", {"seq": 1, "content_sha256": "0" * 64}, snapshot, NOW, None)
        return views, comp["requirements"], doc, render.to_html(doc), render.pdf_extract_text(render.to_pdf(doc))
    return build


def _doc_rows(doc):
    rows = {}
    reqs = {r["title"]: r for r in REGISTER["requirements"]}
    for block in doc["blocks"]:
        if block["type"] == "table" and block["head"][:2] == ["Requirement", "Status"]:
            for row in block["rows"]:
                title = row[0].split(" (")[0]
                rows[next(k for t, k in ((r["title"], r["key"]) for r in reqs.values()) if t == title)] = row
    return rows


def _norm(text):
    return " ".join(render.pdf_text(text).split())


def check_pair(item, status_key, source_key, status_label, source_label, sources):
    """The headline pair is one of the requirement's source pairs."""
    pairs = {(s["source"], s["status"]) for s in sources}
    assert (source_key, status_key) in pairs, (item, source_key, status_key, pairs)


COMBINATIONS = list(itertools.product(OBSERVED, ANSWERS))


@pytest.mark.parametrize("observed,answers", COMBINATIONS)
def test_status_source_and_evidence_describe_the_same_item_on_every_surface(surfaces, observed, answers):
    views, snap_reqs, doc, html, pdf_text = surfaces(observed, answers)
    rows = _doc_rows(doc)
    plain_html = _norm(unescape(re.sub(r"<[^>]+>", " ", html)))
    checked_sourced = 0
    for view, snap in zip(views, snap_reqs):
        key = view["key"]
        # /comply view and snapshot content agree and carry the headline pair in `sources`.
        assert (view["status"], view["source"]) == (snap["status"], snap["source"])
        row = rows[key]
        assert row[1] == view["status_label"] and row[2] == (view["source_label"] or "No source")
        if not view["source"]:
            assert row[3] == "No evidence recorded."
            continue
        checked_sourced += 1
        for sources in (view["sources"], snap["sources"]):
            check_pair(key, view["status"], view["source"], None, None, sources)
            assert sources[0]["source"] == view["source"] and sources[0]["headline"] is True
            assert sum(1 for s in sources if s.get("headline")) == 1
        # The evidence text names the headline source first, and any other source on an "Also:" line.
        lines = row[3].split("\n")
        assert lines[0].startswith(f"{SOURCE_LABELS[view['source']]}: "), (key, row[3])
        assert [l for l in lines[1:] if not l.startswith("Also: ")] == []
        also = {s["source"] for s in view["sources"]} - {view["source"]}
        assert len(lines) - 1 == len(also)
        first_label = min((row[3].find(label), label) for label in SOURCE_LABELS.values() if label in row[3])[1]
        assert first_label == view["source_label"]
        # HTML and PDF carry the identical row (HTML splits lines with <br>; the PDF draws cells in row order).
        assert _norm(" ".join(row)) in pdf_text, key
        assert _norm(row[3]) in plain_html and _norm(row[1]) in plain_html
    assert checked_sourced > 0 or (observed == "none" and answers == "none")
    for text in (plain_html.lower(), pdf_text.lower()):
        assert not [w for w in BANNED if w in text]


def test_the_property_covers_the_mixed_source_requirement(surfaces):
    views, *_ = surfaces("not_assessed", "none")
    dpo = next(v for v in views if v["key"] == "gaid.dpo.contact_published")
    assert {s["source"] for s in dpo["sources"]} == {"externally_observed", "customer_attested"}


def test_production_combination_dpo_contact_published(surfaces):
    """INNOVATECH, readiness pack: observed side not assessed, customer answer missing."""
    views, snap_reqs, doc, html, pdf_text = surfaces("not_assessed", "none")
    view = next(v for v in views if v["key"] == "gaid.dpo.contact_published")
    row = _doc_rows(doc)["gaid.dpo.contact_published"]
    assert (row[1], row[2]) == ("Awaiting your input", "Customer attested")
    first, second = row[3].split("\n")
    # The evidence under the headline is the headline source's own: no observed status next to it.
    assert first == "Customer attested: Awaiting your input; no answer recorded yet"
    assert "Not assessed" not in first and "654136c6" not in first
    assert second.startswith("Also: Externally observed: cyphward.com: Not assessed, observed ")
    assert second.endswith("scan 654136c6")
    assert view["sources"][0]["source"] == "customer_attested" and view["sources"][0]["headline"]
    assert _norm(first) in pdf_text and _norm(second) in pdf_text


def test_observed_headline_lists_its_own_evidence_first_and_the_answer_second(surfaces):
    views, snap_reqs, doc, html, pdf_text = surfaces("present", "no")
    row = _doc_rows(doc)["gaid.dpo.contact_published"]
    assert (row[1], row[2]) == ("Evidence present", "Externally observed")
    first, second = row[3].split("\n")
    assert first.startswith("Externally observed: cyphward.com: Evidence present, observed ")
    assert second.startswith("Also: Customer attested: Gap; Customer answer by Ada Owner")


def test_old_snapshot_without_headline_or_synthesised_sources_still_renders_consistently():
    """Snapshots frozen before this rule have `sources` in a fixed order and none for single-source rows."""
    old = {"key": "k", "source": "customer_attested", "source_label": "Customer attested", "status": "awaiting_input",
           "status_label": "Awaiting your input",
           "sources": [{"source": "externally_observed", "source_label": "Externally observed", "status": "awaiting_input",
                        "status_label": "Awaiting your input", "reason": "x"},
                       {"source": "customer_attested", "source_label": "Customer attested", "status": "awaiting_input",
                        "status_label": "Awaiting your input", "reason": "y"}],
           "domains": [{"domain": "cyphward.com", "status_label": "Not assessed", "source": "externally_observed",
                        "source_label": "Externally observed", "observed_at": "2026-10-17T14:48:00+00:00",
                        "scan_id": SCAN}],
           "findings": [], "answers": []}
    text = document.evidence_references(old, {})
    assert text.split("\n")[0].startswith("Customer attested: ")
    assert text.split("\n")[1].startswith("Also: Externally observed: cyphward.com: Not assessed")
    single = {**old, "sources": [], "source": "tool_observed", "source_label": "Tool observed", "status": "gap",
              "status_label": "Gap", "domains": [{**old["domains"][0], "source": "tool_observed",
                                                    "source_label": "Tool observed"}]}
    assert document.evidence_references(single, {}).startswith("Tool observed: cyphward.com: Not assessed")


def test_cell_stays_bounded_with_two_sources_and_hundreds_of_references():
    req = {"key": "k", "source": "externally_observed", "source_label": "Externally observed", "status": "gap",
           "status_label": "Gap", "sources": [
               {"source": "customer_attested", "source_label": "Customer attested", "status": "present",
                "status_label": "Evidence present"}],
           "domains": [{"domain": f"d{i}.example.com", "status_label": "Gap", "source": "externally_observed",
                        "source_label": "Externally observed", "observed_at": NOW.isoformat(), "scan_id": SCAN}
                       for i in range(400)],
           "findings": [{"title": "T" * 500, "severity": "high", "status": "open"} for _ in range(600)],
           "answers": [{"question_key": "q", "owner_name": "O" * 500, "expires_at": NOW.isoformat()}]}
    text = document.evidence_references(req, {})
    lines = text.split("\n")
    assert len(lines) == 2 and lines[1].startswith("Also: Customer attested")
    assert text.count("; ") <= document.MAX_REFERENCES + 1
    assert len(text) <= (document.MAX_REFERENCES + 2) * (document.MAX_REFERENCE_CHARS + 8) + 200
    assert "more references" in lines[0]
