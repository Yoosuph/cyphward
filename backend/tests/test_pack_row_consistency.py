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

from backend.app.compliance import attestations, mapping, status as cstatus
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


DOMAIN2 = {"id": "22222222-2222-2222-2222-222222222222", "domain": "shop.cyphward.com"}
HSTS = ("Strict-Transport-Security (HSTS) Header Missing", "HTTP Headers")
DMARC = ("Missing Email DMARC Authentication Policy", "DNS & Email Security")


def _observed_row(kind):
    if kind == "none":
        return None
    expired = kind == "expired"
    return {"status": "present" if expired else kind, "observed_at": NOW - timedelta(days=2),
            "expires_at": NOW - timedelta(days=1) if expired else NOW + timedelta(days=30),
            "scan_id": SCAN, "finding_ids": [], "details": {"reason": "checks_conclusive"}}


def _answer_row(q, value, expired=False):
    body = {"value": value}
    if value == "date":
        body["date"] = (NOW - timedelta(days=30)).date().isoformat()
    return {"id": f"id-{q['key']}", "question_key": q["key"], "answer": body, "owner_user_id": "u",
            "owner_name": "Ada Owner", "attested_at": NOW - timedelta(days=5),
            "expires_at": NOW - timedelta(days=1) if expired else NOW + timedelta(days=300), "evidence_link": None}


def _answers(kind):
    """none / yes / no / not_sure / expired for every question, or `mixed` (a different state per question) or
    `partial` (only every other question answered)."""
    if kind == "none":
        return {}
    from backend.app.compliance import questionnaire as qn
    rows = {}
    cycle = ("yes", "no", "not_sure", "expired")
    for n, q in enumerate(qn.QUESTIONS):
        values = qn.values_for(q)
        state = kind if kind in cycle else (cycle[n % 4] if kind == "mixed" else ("yes" if n % 2 else None))
        if state is None:
            continue
        value = {"yes": "date" if "date" in values else "yes", "no": "no" if "no" in values else qn.NOT_SURE,
                 "not_sure": qn.NOT_SURE, "expired": "yes" if "yes" in values else "date"}[state]
        rows[q["key"]] = _answer_row(q, value, expired=state == "expired")
    return rows


def _live(on):
    from backend.tests.test_compliance_mapping import finding
    if not on:
        return []
    return [finding(*HSTS, fid="hsts-1", domain_id=DOMAIN["id"]), finding(*DMARC, fid="dmarc-1", domain_id=DOMAIN2["id"]),
            finding(*HSTS, fid="loose-1", domain_id=None)]


def _ctx(observed, answers, second=None, live=False):
    """One or two verified domains with their own observed results, an answer pattern, optional live findings."""
    domains, latest = [DOMAIN], {}
    for domain, kind in ((DOMAIN, observed), (DOMAIN2, second)):
        if domain is DOMAIN2 and second is None:
            continue
        if domain is DOMAIN2:
            domains.append(DOMAIN2)
        row = _observed_row(kind)
        if row:
            for r in REGISTER["requirements"]:
                latest.setdefault(r["key"], {})[domain["id"]] = {**row, "requirement_key": r["key"],
                                                                 "domain_id": domain["id"]}
    return {"domains": domains, "latest": latest, "live": _live(live), "history": [], "answers": _answers(answers)}


@pytest.fixture
def surfaces(monkeypatch):
    """(views, snapshot requirements, document, html, pdf text) for one combination, from the real code paths."""
    def build(observed, answers, second=None, live=False, org="INNOVATECH", owner=None):
        ctx = _ctx(observed, answers, second, live)
        if owner:
            for row in ctx["answers"].values():
                row["owner_name"] = owner
        monkeypatch.setattr(cstatus, "_context", lambda org_id: ctx)
        monkeypatch.setattr(cstatus, "_findings", lambda org_id, ids: {
            i: {"id": i, "title": f"Open finding {i}", "severity": "high", "status": "open"} for i in ids})
        views = [cstatus._requirement_view(r, ctx, NOW) for r in REGISTER["requirements"]]
        cstatus._attach_findings("org", views)
        comp = builder._compliance("org", NOW)
        snapshot = {"generated_at": NOW.isoformat(), "scope": {"org_name": org, "domains": ctx["domains"]},
                    "dates": {"earliest_observation": None, "latest_observation": None}, "compliance": comp}
        doc = document.build("readiness_pack", {"seq": 1, "content_sha256": "0" * 64}, snapshot, NOW, None)
        return views, comp["requirements"], doc, render.to_html(doc), render.pdf_extract_text(render.to_pdf(doc))
    build.ctx = _ctx
    return build


def _doc_rows(doc):
    by_title = {r["title"]: r["key"] for r in REGISTER["requirements"]}
    rows = {}
    for block in doc["blocks"]:
        if block["type"] == "table" and block["head"][:2] == ["Requirement", "Status"]:
            for row in block["rows"]:
                rows[by_title[row[0].split(" (")[0]]] = row
    return rows


def _norm(text):
    return " ".join(render.pdf_text(text).split())


def expected_headline(observed_status, attested_status):
    """The headline rule, written down independently of `attestations.merge`: a present item wins (the observed
    one when both are), then an observed gap, otherwise the customer's answer."""
    if observed_status == "present":
        return "externally_observed", "present"
    if attested_status == "present":
        return "customer_attested", "present"
    if observed_status == "gap":
        return "externally_observed", "gap"
    return "customer_attested", attested_status


OBSERVED_PAIRS = [("none", None), ("present", None), ("gap", None), ("not_assessed", None), ("expired", None),
                  ("present", "gap"), ("gap", "not_assessed"), ("not_assessed", "present"), ("expired", "none")]
ANSWERS = ("none", "yes", "no", "not_sure", "expired", "mixed", "partial")
COMBINATIONS = [(o, a, o2, live) for (o, o2) in OBSERVED_PAIRS for a in ANSWERS for live in (False, True)]


@pytest.mark.parametrize("observed,answers,second,live", COMBINATIONS)
def test_status_source_and_evidence_describe_the_same_item_on_every_surface(surfaces, observed, answers, second, live):
    views, snap_reqs, doc, html, pdf_text = surfaces(observed, answers, second, live)
    rows = _doc_rows(doc)
    plain_html = _norm(unescape(re.sub(r"<[^>]+>", " ", html)))
    for view, snap in zip(views, snap_reqs):
        key = view["key"]
        assert (view["status"], view["source"]) == (snap["status"], snap["source"])
        row = rows[key]
        assert row[1] == view["status_label"] and row[2] == (view["source_label"] or "No source")
        if not view["source"]:
            assert row[3] == "No evidence recorded."
            continue
        for sources in (view["sources"], snap["sources"]):
            pairs = {(s["source"], s["status"]) for s in sources}
            assert (view["source"], view["status"]) in pairs, (key, view["source"], view["status"], pairs)
            assert sources[0]["source"] == view["source"] and sources[0]["headline"] is True
            assert sum(1 for s in sources if s.get("headline")) == 1
        lines = row[3].split("\n")
        assert lines[0].startswith(f"{SOURCE_LABELS[view['source']]}: {view['status_label']}"), (key, row[3])
        assert [l for l in lines[1:] if not l.startswith("Also: ")] == []
        others = [s for s in view["sources"] if not s["headline"]]
        assert len(lines) - 1 == len(others)
        # The same secondary source reads the same on /comply (Compliance.tsx joins "<label>: <status label>") and in the pack.
        for line, other in zip(lines[1:], others):
            assert line.startswith(f"Also: {other['source_label']}: {other['status_label']}"), (key, line)
        first_label = min((row[3].find(label), label) for label in SOURCE_LABELS.values() if label in row[3])[1]
        assert first_label == view["source_label"]
        assert _norm(" ".join(row)) in pdf_text, key
        assert _norm(row[3]) in plain_html and _norm(row[1]) in plain_html
    for text in (plain_html.lower(), pdf_text.lower()):
        assert not [w for w in BANNED if w in text]


@pytest.mark.parametrize("observed,answers,second,live", COMBINATIONS)
def test_merge_raw_sources_follow_the_headline_rule_before_any_presentation(observed, answers, second, live):
    """Checked on `attestations.merge`'s own output and against an independent statement of the rule."""
    ctx = _ctx(observed, answers, second, live)
    mixed_seen = 0
    for req in REGISTER["requirements"]:
        obs = mapping.requirement_status(req, domains=ctx["domains"], latest_rows=ctx["latest"].get(req["key"], {}),
                                         live_findings=ctx["live"], history=ctx["history"])
        att = attestations.requirement_outcome(req["key"], ctx["answers"], NOW)
        sourced = any(d.get("source") for d in obs["domains"])
        merged = attestations.merge(obs, att, sourced)
        head = merged.get("headline_source")
        if head:
            item = next(s for s in merged["sources"] if s["source"] == head)
            assert item["status"] == merged["status"] and item["reason"] == merged["reason"], req["key"]
        if att is not None and sourced:
            mixed_seen += 1
            assert (head, merged["status"]) == expected_headline(obs["status"], att["status"]), req["key"]
    assert mixed_seen >= 1 or observed == "none"


def test_the_property_covers_the_mixed_source_requirement(surfaces):
    views, *_ = surfaces("not_assessed", "none")
    dpo = next(v for v in views if v["key"] == "gaid.dpo.contact_published")
    assert {s["source"] for s in dpo["sources"]} == {"externally_observed", "customer_attested"}


def test_domains_with_different_statuses_and_findings_only_evidence_are_covered(surfaces):
    views, snap_reqs, doc, html, pdf_text = surfaces("present", "mixed", "gap", True)
    kinds = {(v["source"], v["status"]) for v in views if v["source"]}
    assert len(kinds) >= 4 and {"externally_observed", "customer_attested", "tool_observed"} <= {k[0] for k in kinds}
    assert any(v["findings"] for v in views), "evidence that comes from linked findings"
    assert any(len({d["status"] for d in v["domains"]}) > 1 for v in views), "domains with different statuses"


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
    assert second.startswith("Also: Externally observed: Awaiting your input; cyphward.com: Not assessed, observed ")
    assert second.endswith("scan 654136c6")
    assert view["sources"][0]["source"] == "customer_attested" and view["sources"][0]["headline"]
    assert _norm(first) in pdf_text and _norm(second) in pdf_text


def test_observed_headline_lists_its_own_evidence_first_and_the_answer_second(surfaces):
    views, snap_reqs, doc, html, pdf_text = surfaces("present", "no")
    row = _doc_rows(doc)["gaid.dpo.contact_published"]
    assert (row[1], row[2]) == ("Evidence present", "Externally observed")
    first, second = row[3].split("\n")
    assert first.startswith("Externally observed: Evidence present; cyphward.com: Evidence present, observed ")
    assert second.startswith("Also: Customer attested: Gap; Customer answer by Ada Owner")


# ── The mutation guards: a wrong merge must be CAUGHT, not presented ────────


def _mutated(monkeypatch, how):
    real = attestations.merge

    def merge(observed, attested, observed_sourced):
        result = real(observed, attested, observed_sourced)
        if not (attested and observed_sourced):
            return result
        if how == "mislabel_present_answer" and result["headline_source"] == "customer_attested" \
                and result["status"] == "present":
            return {**result, "headline_source": "externally_observed"}
        if how == "observed_status_customer_source" and result["headline_source"] == "customer_attested" \
                and result["status"] != observed["status"]:
            return {**result, "status": observed["status"], "reason": observed["reason"]}
        return result
    monkeypatch.setattr(attestations, "merge", merge)


@pytest.mark.parametrize("how", ["mislabel_present_answer", "observed_status_customer_source"])
def test_a_merge_that_mislabels_the_headline_is_refused_not_rendered(surfaces, monkeypatch, how):
    """Reviewer's two mutations. Without the guard both rendered an inconsistent row and the old tests passed."""
    _mutated(monkeypatch, how)
    caught = 0
    for observed, answers, second, live in COMBINATIONS:
        try:
            surfaces(observed, answers, second, live)
        except attestations.HeadlineMismatch:
            caught += 1
    assert caught > 0


def test_the_guard_itself_rejects_a_pair_that_is_not_one_of_the_sources():
    sources = [{"source": "externally_observed", "status": "awaiting_input"},
               {"source": "customer_attested", "status": "present"}]
    attestations.check_headline("present", "customer_attested", sources)
    for bad in (("present", "externally_observed"), ("awaiting_input", "customer_attested"), ("gap", "tool_observed")):
        with pytest.raises(attestations.HeadlineMismatch):
            attestations.check_headline(*bad, sources)


def test_a_snapshot_whose_row_disagrees_with_its_sources_is_refused_by_the_pack_builder():
    bad = {"key": "k", "source": "customer_attested", "source_label": "Customer attested", "status": "present",
           "status_label": "Evidence present", "domains": [], "findings": [], "answers": [],
           "sources": [{"source": "customer_attested", "source_label": "Customer attested", "status": "awaiting_input",
                        "status_label": "Awaiting your input"}]}
    with pytest.raises(attestations.HeadlineMismatch):
        document.evidence_references(bad, {})


# ── User-supplied text cannot forge an evidence line ───────────────────────

NASTY = ["\n", "\r", "\r\n", "\u2028", "\u2029", "\u0085", "\x0b", "\x0c"]


@pytest.mark.parametrize("sep", NASTY)
def test_a_line_break_in_user_text_never_forges_an_also_line(surfaces, sep):
    forged = f"Ada{sep}Also: Externally observed: Evidence present; cyphward.com: forged"
    views, snap_reqs, doc, html, pdf_text = surfaces("present", "yes", owner=forged)
    rows = _doc_rows(doc)
    for key, row in rows.items():
        view = next(v for v in views if v["key"] == key)
        lines = row[3].split("\n")
        assert len(lines) == max(1, len(view["sources"])) if view["source"] else len(lines) == 1, (key, lines)
        assert not any(l.startswith("Also: Externally observed: Evidence present; cyphward.com: forged") for l in lines)
    dpo = rows["gaid.dpo.designated"]
    assert "Ada Also: Externally observed: Evidence present; cyphward.com: forged" in dpo[3]  # one line, inert
    assert "\u2028" not in html and "\u0085" not in html


def test_flat_collapses_every_break_and_control_character():
    assert document.flat("a\nb\r\nc\u2028d\u2029e\u0085f\x00g\x1fh   i") == "a b c d e f g h i"


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
    assert text.split("\n")[1].startswith("Also: Externally observed: Awaiting your input; cyphward.com: Not assessed")
    single = {**old, "sources": [], "source": "tool_observed", "source_label": "Tool observed", "status": "gap",
              "status_label": "Gap", "domains": [{**old["domains"][0], "source": "tool_observed",
                                                    "source_label": "Tool observed"}]}
    assert document.evidence_references(single, {}).startswith("Tool observed: Gap; cyphward.com: Not assessed")


def test_cell_stays_bounded_with_two_sources_and_hundreds_of_references():
    req = {"key": "k", "source": "externally_observed", "source_label": "Externally observed", "status": "gap",
           "status_label": "Gap", "sources": [
               {"source": "customer_attested", "source_label": "Customer attested", "status": "present",
                "status_label": "Evidence present"},
               {"source": "externally_observed", "source_label": "Externally observed", "status": "gap",
                "status_label": "Gap"}],
           "domains": [{"domain": f"d{i}.example.com", "status_label": "Gap", "source": "externally_observed",
                        "source_label": "Externally observed", "observed_at": NOW.isoformat(), "scan_id": SCAN}
                       for i in range(400)],
           "findings": [{"title": "T" * 500, "severity": "high", "status": "open"} for _ in range(600)],
           "answers": [{"question_key": "q", "owner_name": "O" * 500, "expires_at": NOW.isoformat()}]}
    text = document.evidence_references(req, {})
    lines = text.split("\n")
    assert len(lines) == 2 and lines[1].startswith("Also: Customer attested")
    assert len(text) <= (document.MAX_REFERENCES + 2) * (document.MAX_REFERENCE_CHARS + 8) + 300
    assert "more references" in lines[0]


def test_template_versions_are_distinct():
    assert document.PACK_VERSION_V1_1 == "cyphward-ndpa-pack-v1.1" and document.PACK_VERSION_V1 == "cyphward-ndpa-pack-v1"
    assert document.PACK_VERSION == "cyphward-ndpa-pack-v2"  # v2 supersedes both for new packs
