"""The pack as a neutral document: headings, paragraphs, bullets and tables.

The HTML and the PDF are two renderings of this one structure, so they carry the same text, source
labels and disclaimer. It is built from a snapshot's frozen content plus the DPO section and the issue
time. The DPO section is read when the pack is issued (for the window the snapshot fixes) and stored with
the pack, so one pack never changes, but two packs from one snapshot can show different counts; the section
says so.

Wording rule (plan section 0): evidence is labelled and organised, never judged. Do not write
"compliant", "certified", "satisfies", "is met" and the like; the tests scan every rendering for them.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.app.compliance.register import DISCLAIMER

PACK_VERSION = "cyphward-ndpa-pack-v1"
PENDING = "reference pending review"
MAX_REFERENCES = 12          # evidence references shown in one table cell
MAX_REFERENCE_CHARS = 280    # and the longest one
NOT_A_CAR = ("This document is not a Compliance Audit Return and does not replace one. A Compliance Audit Return "
             "for a data controller or processor of major importance is filed by a licensed DPCO. A DPCO may use "
             "this pack as supporting evidence.")
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
STATUS_RANK = {"gap": 0, "not_assessed": 1, "awaiting_input": 2}
KIND_TITLES = {"readiness_pack": "NDPA readiness evidence pack",
               "dpo_section": "DPO six-monthly data-security section"}


def when(value: Optional[str]) -> str:
    if not value:
        return "not recorded"
    return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M UTC")


def day(value: Optional[str]) -> str:
    return datetime.fromisoformat(value).strftime("%Y-%m-%d") if value else "not recorded"


def clause_label(req: Dict[str, Any]) -> str:
    return req["clause"] if req["clause_verified"] else f"{req['clause']} · {PENDING}"


def evidence_references(req: Dict[str, Any], attestations: Dict[str, Dict[str, Any]]) -> str:
    parts: List[str] = []
    for d in req["domains"]:
        if d.get("source"):
            scan = f", scan {d['scan_id'][:8]}" if d.get("scan_id") else ""
            parts.append(f"{d['domain']}: {d['status_label']}, {d['source_label']}, observed {when(d.get('observed_at'))}{scan}")
    for f in req["findings"]:
        parts.append(f"Finding: {f['title']} ({f['severity']}, {f['status']})")
    for a in req["answers"]:
        if a.get("owner_name") or a.get("expires_at"):
            who = a.get("owner_name") or "owner not recorded"
            att = attestations.get(a["question_key"], {})
            link = f", link {att['evidence_link']}" if att.get("evidence_link") else ""
            parts.append(f"Customer answer by {who}, answered {day(att.get('attested_at'))}, "
                         f"expires {day(a.get('expires_at'))}{link}")
    if len(parts) > MAX_REFERENCES:
        # A table cell cannot grow without limit (a PDF row cannot split across pages); the rest stay in the snapshot.
        hidden = len(parts) - MAX_REFERENCES
        parts = [p[:MAX_REFERENCE_CHARS] for p in parts[:MAX_REFERENCES]]
        parts.append(f"and {hidden} more references, all of them in the snapshot this pack was made from")
    return "; ".join(p[:MAX_REFERENCE_CHARS] for p in parts) if parts else "No evidence recorded."


def _worst_severity(req: Dict[str, Any]) -> int:
    return min([SEVERITY_RANK.get(f["severity"], 4) for f in req["findings"]] or [9])


def prioritised_gaps(requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    open_items = [r for r in requirements if r["status"] in STATUS_RANK]
    return sorted(open_items, key=lambda r: (STATUS_RANK[r["status"]], _worst_severity(r), r["group"], r["key"]))


def _dpo_blocks(dpo: Dict[str, Any], snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    req = next((r for r in snapshot["compliance"]["requirements"] if r["key"] == "gaid.dpo.six_monthly_report"), None)
    ref = clause_label(req) if req else f"GAID 2025 Art. 13 · {PENDING}"
    w, sc, fi, inc = dpo["window"], dpo["scans"], dpo["findings"], dpo["incidents"]
    sev = ("critical", "high", "medium", "low")
    return [
        {"type": "heading", "text": "DPO six-monthly data-security section"},
        {"type": "para", "text": f"Supporting evidence for the data-security part of a DPO's six-monthly report ({ref}). "
                                 f"Window: {when(w['start'])} to {when(w['end'])}. Counts only; no incident titles or notes appear here."},
        {"type": "para", "text": NOT_A_CAR},
        {"type": "para", "text": "These counts were read on the day this pack was issued, for a window the snapshot fixes. This pack "
                                 "never changes, but another pack issued later from the same snapshot can show different counts."},
        {"type": "table", "head": ["Measure", "Count"], "rows": [
            ["Scans run in the window", str(sc["run"])],
            ["Scans by outcome", ", ".join(f"{k} {v}" for k, v in sorted(sc["by_status"].items())) or "none"],
            ["Verified domains", str(sc["verified_domains"])],
            ["Completed scans: every declared check finished", str(sc["coverage"]["complete"])],
            ["Completed scans: partial coverage", str(sc["coverage"]["partial"])],
            ["Completed scans: not assessed", str(sc["coverage"]["unassessed"])],
            ["Completed scans: coverage not recorded", str(sc["coverage"]["unknown"])],
            ["Findings opened", ", ".join(f"{s} {fi['opened'][s]}" for s in sev)],
            ["Findings resolved", ", ".join(f"{s} {fi['resolved'][s]}" for s in sev)],
            ["Findings open at the snapshot", ", ".join(f"{s} {fi['open_at_snapshot'].get(s, 0)}" for s in sev)],
            ["Incidents logged", str(inc["logged"])],
            ["Incidents by status", ", ".join(f"{k} {v}" for k, v in inc["by_status"].items())],
            ["Incidents by severity", ", ".join(f"{k} {v}" for k, v in inc["by_severity"].items())],
            ["Incidents with the Commission notified", str(inc["commission_notified"])],
        ]},
        {"type": "heading", "text": "Notices and consent observations"},
        {"type": "table", "head": ["Observation", "Status", "Source", "Last observed"],
         "rows": [[o["title"], o["status_label"], o["source_label"] or "No source", when(o["observed_at"])]
                  for o in dpo["observations"]]},
    ]


def build(kind: str, snapshot_row: Dict[str, Any], snapshot: Dict[str, Any], issued_at: datetime,
          dpo: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    comp, scope = snapshot["compliance"], snapshot["scope"]
    ready = comp["readiness"]
    attestations = {a["question_key"]: a for a in comp["attestations"]}
    reqs = comp["requirements"]
    pending = sum(1 for r in reqs if not r["clause_verified"])
    meta = [
        ("Organisation", scope["org_name"]),
        ("Issued", when(issued_at.isoformat())),
        ("Snapshot", f"{snapshot_row['seq']} · sha256 {snapshot_row['content_sha256']}"),
        ("Snapshot frozen", when(snapshot["generated_at"])),
        ("Assessment dates", f"observations {when(snapshot['dates']['earliest_observation'])} to "
                             f"{when(snapshot['dates']['latest_observation'])}"),
        ("Register", f"{comp['register']['title']} · version {comp['register']['version']}"),
        ("Domains in scope", ", ".join(d["domain"] for d in scope["domains"]) or "none verified"),
        ("Pack version", PACK_VERSION),
    ]
    blocks: List[Dict[str, Any]] = [
        {"type": "para", "text": DISCLAIMER},
        {"type": "para", "text": NOT_A_CAR},
    ]
    if kind == "readiness_pack":
        blocks += [{"type": "heading", "text": "Readiness at a glance"},
                   {"type": "para", "text": f"{ready['with_evidence']} of {ready['applicable']} applicable requirements have "
                                            f"evidence ({ready['present']} with evidence present, {ready['gap']} gaps) · "
                                            f"{ready['awaiting_input']} awaiting input or upcoming checks · "
                                            f"{ready['not_assessed']} not assessed."}]
        if ready["with_evidence"] == 0:
            blocks.append({"type": "para", "text": "Nothing has been recorded as evidence yet. This pack therefore lists what "
                                                   "Cyphward looks for, and why each item has no evidence, and says nothing "
                                                   "either way about your obligations."})
        if pending:
            blocks.append({"type": "para", "text": f"{pending} legal references in this register are marked '{PENDING}': "
                                                   "a qualified reviewer has not yet confirmed the clause text."})
        blocks.append({"type": "heading", "text": "Requirements, status and sources"})
        groups = {g["key"]: g["title"] for g in comp["groups"]}
        for key in dict.fromkeys(r["group"] for r in reqs):
            blocks.append({"type": "heading", "text": groups.get(key, key), "level": 3})
            blocks.append({"type": "table", "head": ["Requirement", "Status", "Source", "Evidence reference"], "rows": [
                [f"{r['title']} ({clause_label(r)})", r["status_label"], r["source_label"] or "No source",
                 evidence_references(r, attestations)] for r in reqs if r["group"] == key]})
        blocks.append({"type": "heading", "text": "Prioritised gaps and open items"})
        gaps = prioritised_gaps(reqs)
        if gaps:
            blocks.append({"type": "table", "head": ["Priority", "Requirement", "Status", "Why", "Suggested next step"], "rows": [
                [str(i), r["title"], r["status_label"], r["reason_text"], r["remediation_hint"]]
                for i, r in enumerate(gaps, 1)]})
        else:
            blocks.append({"type": "para", "text": "No open items in this snapshot."})
        if dpo:
            blocks += _dpo_blocks(dpo, snapshot)
    else:
        blocks += _dpo_blocks(dpo, snapshot)
    blocks.append({"type": "heading", "text": "About this pack"})
    blocks.append({"type": "bullets", "items": [
        "Source labels: Tool observed and Externally observed come from Cyphward's checks; Customer attested is an answer "
        "given by your team; Practitioner reviewed is reserved for a qualified reviewer.",
        f"Generated from snapshot {snapshot_row['seq']}. Later scans and answers do not change this pack; issue a new "
        "pack to reflect them.",
        "Cyphward organises evidence. It does not give legal advice or decide whether an obligation has been fulfilled.",
    ]})
    return {"title": KIND_TITLES[kind], "meta": meta, "blocks": blocks}
