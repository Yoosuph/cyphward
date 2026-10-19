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

PACK_VERSION_V1 = "cyphward-ndpa-pack-v1"  # the original layout; its stored bytes are served as stored
PACK_VERSION = "cyphward-ndpa-pack-v2"     # the branded layout, used for every newly issued pack
MARK = "\u2020"  # dagger: tied to the one legend that explains it
LEGEND = (f"{MARK} = reference pending review: a qualified reviewer has not yet confirmed the clause text of this "
          "legal reference. Each row's Status and Source describe one evidence item (the first line of its "
          "evidence); another source, if any, follows on an 'Also:' line.")
SHORT_DISCLAIMER = "Readiness evidence, not legal advice or a compliance determination."
MAX_DOMAINS_SHOWN = 40
MAX_NAME_CHARS = 160
TOP_GAPS = 6
PENDING = "reference pending review"
MAX_REFERENCES = 8           # evidence references shown in one table cell
MAX_REFERENCE_CHARS = 200    # and the longest one (8 x 200 characters fits a PDF row at any letter width)
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


OBSERVED_SOURCES = ("tool_observed", "externally_observed")


def evidence_items(req: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The requirement's evidence items, the headline one first (works on snapshots frozen before `headline` existed).

    One rule: the Status and Source columns describe `items[0]`, and its evidence is written first; any other
    source follows on its own labelled line ("Also: ...")."""
    head = req.get("source")
    if not head:
        return []
    items = [dict(s) for s in req.get("sources") or []]
    if not any(s["source"] == head for s in items):
        items.append({"source": head, "source_label": req["source_label"], "status": req["status"],
                      "status_label": req["status_label"]})
    for item in items:
        if item["source"] == head:  # the headline item carries the row's own status
            item["status"], item["status_label"] = req["status"], req["status_label"]
    return sorted(items, key=lambda i: i["source"] != head)


def _segment_parts(item: Dict[str, Any], req: Dict[str, Any], attestations: Dict[str, Dict[str, Any]],
                   with_findings: bool) -> List[str]:
    parts: List[str] = []
    if item["source"] in OBSERVED_SOURCES:
        for d in req["domains"]:
            if d.get("source") == item["source"]:
                scan = f", scan {d['scan_id'][:8]}" if d.get("scan_id") else ""
                parts.append(f"{d['domain']}: {d['status_label']}, observed {when(d.get('observed_at'))}{scan}")
        if with_findings:
            for f in req["findings"]:
                parts.append(f"Finding: {f['title']} ({f['severity']}, {f['status']})")
        return parts or [f"{item['status_label']}, nothing observed yet"]
    for a in req["answers"]:
        if a.get("owner_name") or a.get("expires_at"):
            who = a.get("owner_name") or "owner not recorded"
            att = attestations.get(a["question_key"], {})
            link = f", link {att['evidence_link']}" if att.get("evidence_link") else ""
            parts.append(f"Customer answer by {who}, answered {day(att.get('attested_at'))}, "
                         f"expires {day(a.get('expires_at'))}{link}")
    return [item["status_label"]] + (parts or ["no answer recorded yet"])


def _capped(parts: List[str], limit: int) -> List[str]:
    if len(parts) <= limit:
        return [p[:MAX_REFERENCE_CHARS] for p in parts]
    # A table cell cannot grow without limit (a PDF row cannot split across pages); the rest stay in the snapshot.
    hidden = len(parts) - limit
    return [p[:MAX_REFERENCE_CHARS] for p in parts[:limit]] + [
        f"and {hidden} more references, all of them in the snapshot this pack was made from"]


def evidence_references(req: Dict[str, Any], attestations: Dict[str, Dict[str, Any]]) -> str:
    items = evidence_items(req)
    if not items:
        return "No evidence recorded."
    first_observed = next((i["source"] for i in items if i["source"] in OBSERVED_SOURCES), None)
    lines = []
    for n, item in enumerate(items):
        parts = _segment_parts(item, req, attestations, item["source"] == first_observed)
        parts = _capped(parts, (MAX_REFERENCES if len(items) == 1 else MAX_REFERENCES - 3 * (len(items) - 1)) if n == 0
                        else 2)
        lines.append(("Also: " if n else "") + f"{item['source_label']}: " + "; ".join(parts))
    return "\n".join(lines)


def _worst_severity(req: Dict[str, Any]) -> int:
    return min([SEVERITY_RANK.get(f["severity"], 4) for f in req["findings"]] or [9])


def prioritised_gaps(requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    open_items = [r for r in requirements if r["status"] in STATUS_RANK]
    return sorted(open_items, key=lambda r: (STATUS_RANK[r["status"]], _worst_severity(r), r["group"], r["key"]))


def _dpo_blocks(dpo: Dict[str, Any], snapshot: Dict[str, Any], label=None) -> List[Dict[str, Any]]:
    label = label or clause_label
    req = next((r for r in snapshot["compliance"]["requirements"] if r["key"] == "gaid.dpo.six_monthly_report"), None)
    ref = label(req) if req else (f"GAID 2025 Art. 13 · {PENDING}" if label is clause_label else f"GAID 2025 Art. 13 {MARK}")
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


def build_v1(kind: str, snapshot_row: Dict[str, Any], snapshot: Dict[str, Any], issued_at: datetime,
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
        ("Pack version", PACK_VERSION_V1),
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


# ── Version 2: the branded layout ───────────────────────────────────────────


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def _domains_line(scope: Dict[str, Any]) -> str:
    names = [d["domain"] for d in scope["domains"]]
    shown = ", ".join(names[:MAX_DOMAINS_SHOWN]) or "none verified"
    return shown + (f" and {len(names) - MAX_DOMAINS_SHOWN} more" if len(names) > MAX_DOMAINS_SHOWN else "")


def _requirement_rows(reqs: List[Dict[str, Any]], key: str, attestations: Dict[str, Dict[str, Any]]) -> List[List[str]]:
    rows = []
    for r in reqs:
        if r["group"] == key:
            clause = r["clause"] if r["clause_verified"] else f"{r['clause']} {MARK}"
            rows.append([f"{r['title']} ({clause})", r["status_label"], r["source_label"] or "No source",
                         evidence_references(r, attestations)])
    return rows


def _marked(req: Dict[str, Any]) -> str:
    return req["clause"] if req["clause_verified"] else f"{req['clause']} {MARK}"


def build_v2(kind: str, snapshot_row: Dict[str, Any], snapshot: Dict[str, Any], issued_at: datetime,
             dpo: Optional[Dict[str, Any]], pack_id: str) -> Dict[str, Any]:
    """The branded pack: cover, summary, body with one legend, closing page with the frozen-record line.

    The pack's own hash cannot appear inside it; the snapshot's content hash does, so a reader can match the
    pack to the frozen record (the issue response and the pack list carry the pack's own hashes)."""
    comp, scope = snapshot["compliance"], snapshot["scope"]
    ready = comp["readiness"]
    attestations = {a["question_key"]: a for a in comp["attestations"]}
    reqs = comp["requirements"]
    pending = sum(1 for r in reqs if not r["clause_verified"])
    org = _short(scope["org_name"] or "Organisation", MAX_NAME_CHARS)
    issued = when(issued_at.isoformat())
    dates = snapshot["dates"]
    scope_facts = [
        ("Organisation", org),
        ("Domains in scope", _domains_line(scope)),
        ("Assessment dates", f"observations {when(dates['earliest_observation'])} to {when(dates['latest_observation'])}"),
        ("Snapshot frozen", f"{when(snapshot['generated_at'])} (snapshot {snapshot_row['seq']})"),
        ("Register", f"{comp['register']['title']} · version {comp['register']['version']}"),
        ("Issued", issued),
        ("Pack ID", pack_id),
        ("Pack version", PACK_VERSION),
    ]
    summary: List[Dict[str, Any]] = [{"type": "heading", "text": "Summary"},
                                     {"type": "notice", "text": DISCLAIMER}, {"type": "notice", "text": NOT_A_CAR},
                                     {"type": "heading", "text": "Scope and dates", "level": 3},
                                     {"type": "facts", "rows": scope_facts}]
    body: List[Dict[str, Any]] = []
    if kind == "readiness_pack":
        gaps = prioritised_gaps(reqs)
        summary += [
            {"type": "heading", "text": "Readiness at a glance", "level": 3},
            {"type": "stats", "items": [("With evidence", ready["with_evidence"]), ("Gaps", ready["gap"]),
                                        ("Awaiting input", ready["awaiting_input"]),
                                        ("Not assessed", ready["not_assessed"]),
                                        ("Applicable", ready["applicable"])]},
            {"type": "para", "text": f"{ready['with_evidence']} of {ready['applicable']} applicable requirements have "
                                     f"evidence ({ready['present']} with evidence present, {ready['gap']} gaps). "
                                     f"{ready['awaiting_input']} are awaiting input or upcoming checks and "
                                     f"{ready['not_assessed']} are not assessed."}]
        if ready["with_evidence"] == 0:
            summary.append({"type": "para", "text": "Nothing has been recorded as evidence yet. This pack therefore lists "
                                                    "what Cyphward looks for, and why each item has no evidence, and says "
                                                    "nothing either way about your obligations."})
        summary.append({"type": "heading", "text": "Top prioritised gaps and open items", "level": 3})
        if gaps:
            top = gaps[:TOP_GAPS]
            summary.append({"type": "table", "head": ["Priority", "Requirement", "Status", "Why"], "rows": [
                [str(i), r["title"], r["status_label"], r["reason_text"]] for i, r in enumerate(top, 1)]})
            if len(gaps) > len(top):
                summary.append({"type": "para", "text": f"{len(gaps) - len(top)} more open items are listed in the "
                                                        "prioritised list in the body of this pack."})
        else:
            summary.append({"type": "para", "text": "No open items in this snapshot."})
        body += [{"type": "heading", "text": "Requirements, status and sources"},
                 {"type": "legend", "text": LEGEND}]
        if pending:
            body.append({"type": "para", "text": f"{pending} of {len(reqs)} requirements below carry the {MARK} marker."})
        groups = {g["key"]: g["title"] for g in comp["groups"]}
        for key in dict.fromkeys(r["group"] for r in reqs):
            body.append({"type": "heading", "text": groups.get(key, key), "level": 3})
            body.append({"type": "table", "head": ["Requirement", "Status", "Source", "Evidence reference"],
                         "rows": _requirement_rows(reqs, key, attestations)})
        body.append({"type": "heading", "text": "Prioritised gaps and open items"})
        if gaps:
            body.append({"type": "table", "head": ["Priority", "Requirement", "Status", "Why", "Suggested next step"],
                         "rows": [[str(i), r["title"], r["status_label"], r["reason_text"], r["remediation_hint"]]
                                  for i, r in enumerate(gaps, 1)]})
        else:
            body.append({"type": "para", "text": "No open items in this snapshot."})
        if dpo:
            body += _dpo_blocks(dpo, snapshot, _marked)
    else:
        w, sc = dpo["window"], dpo["scans"]
        summary += [{"type": "heading", "text": "At a glance", "level": 3},
                    {"type": "stats", "items": [("Scans run", sc["run"]), ("Verified domains", sc["verified_domains"]),
                                                ("Incidents logged", dpo["incidents"]["logged"])]},
                    {"type": "para", "text": f"Window: {when(w['start'])} to {when(w['end'])}. Counts only; no incident "
                                             "titles or notes appear in this pack."}]
        body += [{"type": "legend", "text": LEGEND}] + _dpo_blocks(dpo, snapshot, _marked)
    closing = [{"type": "heading", "text": "About this pack"},
               {"type": "bullets", "items": [
                   "Source labels: Tool observed and Externally observed come from Cyphward's checks; Customer attested "
                   "is an answer given by your team; Practitioner reviewed is reserved for a qualified reviewer.",
                   f"Generated from snapshot {snapshot_row['seq']}. Later scans and answers do not change this pack; "
                   "issue a new pack to reflect them.",
                   "Cyphward organises evidence. It does not give legal advice or decide whether an obligation has been "
                   "fulfilled."]},
               {"type": "heading", "text": "Frozen record"},
               {"type": "notice", "text": f"Frozen record: snapshot {snapshot_row['id']}, sha256 {snapshot_row['content_sha256']}"},
               {"type": "para", "text": "This is the content hash of the frozen snapshot this pack was made from. A "
                                        "document cannot contain its own hash: the pack's own hashes are returned when it "
                                        "is issued and listed with the pack."}]
    return {"version": PACK_VERSION, "kind": kind, "title": KIND_TITLES[kind], "pack_id": pack_id,
            "cover": {"org": org, "issued": issued, "pack_id": pack_id, "register": comp["register"]["version"]},
            "summary": summary, "blocks": body, "closing": closing,
            "footer": SHORT_DISCLAIMER, "prepared": f"Prepared with Cyphward · Pack {pack_id[:8]}", "meta": []}


def build(kind: str, snapshot_row: Dict[str, Any], snapshot: Dict[str, Any], issued_at: datetime,
          dpo: Optional[Dict[str, Any]], pack_id: Optional[str] = None) -> Dict[str, Any]:
    """The document of a new pack (v2, which needs its pack id) or, without one, the original v1 layout."""
    if pack_id is None:
        return build_v1(kind, snapshot_row, snapshot, issued_at, dpo)
    return build_v2(kind, snapshot_row, snapshot, issued_at, dpo, pack_id)
