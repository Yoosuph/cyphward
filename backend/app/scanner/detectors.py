"""
Detector identity for findings — shared by the baseline diff
(backend.app.workflows.inngest_workflow) and the remediation recheck
(backend.app.api.remediation).

Findings must be traced to the detector/rule that produced them:
resolution and re-verification decisions key on the detector, never on a
mutable display title alone. Nuclei findings carry a stable template id;
deterministic security-check findings use their (static) check title.
"""
from typing import Any, Dict

NUCLEI_CATEGORY = "Nuclei Scan"

SHARED_CHECK_CATEGORIES = {
    "DNS & Email Security",
    "HTTP Headers",
    "SSL/TLS",
    "Exposure",
    "Information Disclosure",
    "Security Configuration",
}


def classify_detector(category: Any, evidence: Any) -> Dict[str, Any]:
    """
    Which detector produced a finding. Order matters: nuclei evidence wins
    over category because template_id is the only globally stable rule id
    we store today.
    """
    ev = evidence if isinstance(evidence, dict) else {}
    cat = (category or "").strip()
    if cat == NUCLEI_CATEGORY or ev.get("template_id"):
        return {"name": "nuclei", "template_id": ev.get("template_id")}
    if cat in SHARED_CHECK_CATEGORIES:
        return {"name": "security_checks", "template_id": None}
    return {"name": "unknown", "template_id": None}


def detector_key(category: Any, evidence: Any, title: Any) -> str:
    """
    Stable identity component for one finding on one asset:
    detector name + rule (nuclei template id, else the check's static title).
    """
    det = classify_detector(category, evidence)
    ev = evidence if isinstance(evidence, dict) else {}
    rule = ev.get("template_id") or (title or "").strip()
    return f"{det['name']}:{rule}"
