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
