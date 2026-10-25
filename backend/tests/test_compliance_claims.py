"""Compliance-claim integrity (review P1 — compliance claim integrity, line 35).

Security posture can supply technical evidence to a compliance programme;
it cannot certify NDPA compliance or produce a licensed DPCO filing. The
board-report verdict must therefore read as a readiness note with an
explicit non-certification disclaimer — never "Partial Compliance" or a
claim that findings "satisfy" a statute.
"""
import asyncio

from backend.app.ai.heuristic_provider import HeuristicAIProvider

BANNED = ("partial compliance", "fully compliant", "is compliant",
          "satisfy ndpa", "satisfies ndpa", "certified",
          "ndpa 2023 compliant", "cbn compliant")


def _summary(score_data, findings=None):
    return asyncio.run(HeuristicAIProvider().generate_executive_summary(
        "Acme Traders", score_data, findings or []))


def test_verdict_with_scan_is_readiness_note_not_certification():
    res = _summary({"score": 72, "grade": "B", "posture_label": "Fair",
                    "counts": {"critical": 1, "high": 2, "medium": 3}},
                   [{"severity": "high", "title": "HSTS Missing"}])
    verdict = res["compliance_verdict"].lower()
    for phrase in BANNED:
        assert phrase not in verdict, f"certifying language leaked: {phrase}"
    assert "not a compliance certification or filing" in res["compliance_verdict"]


def test_verdict_without_scan_refuses_determination():
    res = _summary({"score": None, "grade": None, "posture_label": None,
                    "counts": {}})
    verdict = res["compliance_verdict"].lower()
    for phrase in BANNED:
        assert phrase not in verdict, f"certifying language leaked: {phrase}"
    assert "does not determine legal compliance" in res["compliance_verdict"]


# ── Compliance readiness (packet C1): register, API copy and page ─────────
import json
import pathlib
import re

from backend.app.compliance import register as compliance_register
from backend.app.compliance import status as compliance_status

READINESS_BANNED = ("compliant", "certified", "satisfies", "satisfied", "passes audit", "pass the audit",
                    "compliance score", "fully meets", "meets the requirement", "is met")
ROOT = pathlib.Path(__file__).resolve().parents[2]


def _strings(value, keys=False):
    if isinstance(value, dict):
        for k, v in value.items():
            if keys:
                yield str(k)
            yield from _strings(v, keys)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, keys)
    elif isinstance(value, str):
        yield value


def _assert_clean(texts, where):
    for text in texts:
        lowered = text.lower()
        for phrase in READINESS_BANNED:
            assert phrase not in lowered, f"{where}: verdict language {phrase!r} in {text!r}"


def test_register_has_no_verdict_language():
    raw = json.loads(compliance_register.REGISTER_FILE.read_text())
    _assert_clean(_strings(raw, keys=True), "register")


def test_questionnaire_has_no_verdict_language():
    from backend.app.compliance import questionnaire as compliance_questionnaire
    raw = json.loads(compliance_questionnaire.QUESTIONNAIRE_FILE.read_text())
    _assert_clean(_strings(raw, keys=True), "questionnaire")


def _synthetic_context():
    d1 = {"id": "11111111-1111-4111-8111-111111111111", "domain": "acme.test"}
    d2 = {"id": "22222222-2222-4222-8222-222222222222", "domain": "shop.test"}
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    present = {"status": "present", "observed_at": now, "expires_at": now + timedelta(days=5), "scan_id": "s",
               "finding_ids": [], "details": {"reason": "checks_conclusive", "open_ports": {"acme.test": [443]}}}
    gap = {**present, "status": "gap", "finding_ids": ["f1"], "details": {"reason": "open_findings"}}
    old = {**present, "expires_at": now - timedelta(days=1)}
    latest = {r["key"]: {d1["id"]: present, d2["id"]: present} for r in compliance_register.tool_requirements()}
    latest["ndpa.s39.web_security_headers"] = {d1["id"]: present, d2["id"]: old}
    latest["ndpa.s39.email_anti_spoofing"] = {d1["id"]: gap}
    live = [{"id": "f1", "title": "Missing Email DMARC Authentication Policy", "category": "DNS & Email Security",
             "evidence": {}, "status": "open", "domain_id": d1["id"]},
            {"id": "f2", "title": "Robots.txt Discloses Sensitive Endpoint Paths", "category": "Exposure",
             "evidence": {}, "status": "open", "domain_id": None}]
    history = [{"scan_id": "s", "domain_id": d1["id"], "completed_at": now, "state": "complete"},
               {"scan_id": "t", "domain_id": d2["id"], "completed_at": now, "state": "partial"}]
    return {"domains": [d1, d2], "latest": latest, "live": live, "history": history}


def test_api_copy_and_field_names_have_no_verdict_language(monkeypatch):
    ctx = _synthetic_context()
    monkeypatch.setattr(compliance_status, "_context", lambda org_id: ctx)
    monkeypatch.setattr(compliance_status, "_plan", lambda org: "growth")
    monkeypatch.setattr(compliance_status, "_findings", lambda org_id, ids: {})
    monkeypatch.setattr(compliance_status, "execute_query", lambda *a, **k: [])
    payload = compliance_status.overview({"id": "org"})
    statuses = {r["status"] for g in payload["groups"] for r in g["requirements"]}
    assert {"present", "gap", "not_assessed"} <= statuses, "exercise every status"
    _assert_clean(_strings(payload, keys=True), "overview")
    for req in compliance_register.requirements():
        _assert_clean(_strings(compliance_status.requirement_detail({"id": "org"}, req["key"]), keys=True), req["key"])
    _assert_clean(compliance_status.STATUS_LABELS.values(), "status labels")
    _assert_clean(compliance_status.REASON_TEXT.values(), "reason text")
    _assert_clean([compliance_status.C1_NOTE], "note")


def test_disclaimer_is_the_plan_text_and_is_always_returned(monkeypatch):
    assert compliance_register.DISCLAIMER == (
        "Readiness evidence, not legal advice or a compliance determination. Filing of Compliance Audit Returns "
        "for UHL/EHL organisations must go through a licensed DPCO.")
    monkeypatch.setattr(compliance_status, "_context", lambda org_id: _synthetic_context())
    monkeypatch.setattr(compliance_status, "_plan", lambda org: "starter")
    monkeypatch.setattr(compliance_status, "_findings", lambda org_id, ids: {})
    assert compliance_status.overview({"id": "org"})["disclaimer"] == compliance_register.DISCLAIMER
    assert compliance_status.requirement_detail({"id": "org"}, "gaid.dpo.designated")["disclaimer"] == \
        compliance_register.DISCLAIMER


def test_compliance_page_copy_has_no_verdict_language():
    pages = ROOT / "frontend" / "src" / "pages"
    for path in [pages / "Compliance.tsx", pages / "Reviews.tsx", *sorted((pages / "compliance").glob("*.tsx"))]:
        source = path.read_text()
        # User-visible text: JSX text nodes and string literals.
        texts = re.findall(r">([^<>{}]+)<", source) + re.findall(r"'([^'\n]{3,})'|`([^`\n]{3,})`|\"([^\"\n]{3,})\"", source)
        flat = [t if isinstance(t, str) else " ".join(x for x in t if x) for t in texts]
        _assert_clean(flat, path.name)
    assert "data.disclaimer" in (pages / "Compliance.tsx").read_text(), "the page renders the API disclaimer"


def test_scan_page_privacy_copy_has_no_verdict_language():
    source = (ROOT / "frontend" / "src" / "pages" / "Scans.tsx").read_text()
    section = source[source.index("function PrivacyDetails"):source.index("function TargetScope")]
    section += source[source.index("const PRIVACY_STAGE"):source.index("const PROCESSING")]
    texts = re.findall(r">([^<>{}]+)<", section) + re.findall(r"\"([^\"\n]{3,})\"", section)
    _assert_clean(texts, "Scans.tsx privacy")
    assert "Heuristic" in section


def test_document_draft_copy_has_no_verdict_language():
    """Packet C5: the fixed copy of the AI-drafted documents, before and after any model wording."""
    from backend.app.compliance import documents as docs
    fixed = [docs.LABEL, docs.FOOTER, *docs.TITLES.values(), *docs.SOURCE_LABELS.values()]
    for gaps in docs.FIXED_GAPS.values():
        fixed += [label for _, label in gaps]
    _assert_clean(fixed, "document copy")
    assert docs.LABEL == "Draft — not legal advice"
    for kind in docs.KINDS:
        inputs = docs.build_inputs(kind, {"org_name": "Acme", "domains": [], "answers": {}, "observed": {}})
        _assert_clean([docs.build_template(inputs), docs.reviewer_notes(inputs)], kind)


C5B_BANNED = ("compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit",
              "compliance score", "fully meets", "meets the requirement", "is met", "partial compliance",
              "fully compliant", "is compliant", "satisfy ndpa", "adequate", "adequacy", "guarantee")


def test_c5b_copy_has_no_verdict_language():
    """Packet C5b: the note shown when a value cannot be used, the instruction to the model, the startup warning
    and the fixed rewording check's own explanation. Banned wording appears only in the data of negative tests."""
    from backend.app.compliance import document_check as check
    from backend.app.compliance import documents as docs
    texts = [docs.WORDING_NOTE, docs.SYSTEM_PROMPT, check.__doc__]
    inputs = docs.build_inputs("privacy_policy", {"org_name": "Customer Satisfaction Ltd", "domains": ["x.example"],
                                                  "answers": {}, "observed": {}})
    texts += [docs.build_template(inputs), docs.reviewer_notes(inputs)]
    for text in texts:
        lowered = text.lower()
        for phrase in C5B_BANNED:
            assert phrase not in lowered, f"C5b copy: {phrase!r}"
        assert docs.banned_hits(text) == []
