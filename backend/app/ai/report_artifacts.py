"""Local-only typed report experiment. No model code, writes or external data fetches."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.core import config
from backend.app.core.database import get_db
from backend.app.core.runtime_guard import database_is_local


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Metric = Literal["assessment_scores", "scan_volume", "findings_discovered", "findings_resolved", "severity", "finding_status", "categories", "remediation_status"]
Severity = Literal["critical", "high", "medium", "low", "info"]
CATALOG = {
    "assessment_scores": {"title": "Recorded assessment scores", "id": "scan-scores", "unit": "Score / 100", "temporal": True, "kind": "line"},
    "scan_volume": {"title": "Completed assessment activity", "id": "scan-volume", "unit": "Assessments", "temporal": True, "kind": "bar"},
    "findings_discovered": {"title": "Recorded finding discoveries", "id": "discoveries", "unit": "Findings", "temporal": True, "kind": "line"},
    "findings_resolved": {"title": "Recorded finding resolutions", "id": "resolutions", "unit": "Findings", "temporal": True, "kind": "line"},
    "severity": {"title": "Unresolved findings by severity", "id": "severity", "unit": "Findings", "temporal": False, "kind": "bar"},
    "finding_status": {"title": "Finding workflow", "id": "resolution", "unit": "Findings", "temporal": False, "kind": "donut"},
    "categories": {"title": "Unresolved findings by category", "id": "categories", "unit": "Findings", "temporal": False, "kind": "bar"},
    "remediation_status": {"title": "Remediation task workflow", "id": "remediation-status", "unit": "Tasks", "temporal": False, "kind": "bar"},
}


class ChartSelection(StrictModel):
    metric: Metric
    kind: Literal["line", "bar", "area", "donut"]

    @model_validator(mode="after")
    def meaningful_encoding(self):
        temporal = CATALOG[self.metric]["temporal"]
        if temporal and self.kind == "donut":
            raise ValueError("A time series needs a line, bar or area chart.")
        if not temporal and self.kind in ("line", "area"):
            raise ValueError("Current category counts have no historical trend; use bar or donut.")
        return self


class ArtifactReference(StrictModel):
    id: UUID
    version: int = Field(ge=1, le=100)
    days: int = Field(default=90, ge=1, le=365)
    chart_style: Literal["line", "bar", "area"] = "line"
    charts: list[ChartSelection] | None = Field(default=None, max_length=8)
    include_metrics: bool = True
    include_tables: bool = True
    heading: str | None = Field(default=None, max_length=300)
    severities: list[Severity] = Field(default_factory=list, max_length=5)


class ChartPoint(StrictModel):
    label: str = Field(max_length=200)
    value: float = Field(ge=0, le=1_000_000_000, allow_inf_nan=False)


class ReportChart(StrictModel):
    id: str
    title: str
    kind: Literal["line", "bar", "area", "donut"]
    metric: Metric
    x_type: Literal["temporal", "ordinal"]
    unit: str
    note: str
    points: list[ChartPoint] = Field(max_length=100)


class ReportTable(StrictModel):
    title: str
    columns: list[str] = Field(max_length=8)
    rows: list[list[str | float | int | None]] = Field(max_length=100)


class ReportArtifact(StrictModel):
    schema_version: Literal[1] = 1
    id: UUID
    version: int = Field(ge=1, le=101)
    org_id: UUID
    title: str
    generated_at: datetime
    days: int = Field(ge=1, le=365)
    chart_style: Literal["line", "bar", "area"]
    severities: list[Severity] = Field(default_factory=list, max_length=5)
    sample: bool
    summary: str
    metrics: list[dict[str, str]]
    charts: list[ReportChart] = Field(max_length=8)
    tables: list[ReportTable] = Field(max_length=4)
    limitations: list[str]
    sources: list[str]


def lab_enabled() -> bool:
    return (
        os.getenv("CYPHWARD_ARTIFACT_LAB") == "true"
        and os.getenv("CYPHWARD_ENV", "development") == "development"
        and database_is_local(config.DATABASE_URL)
    )


def production_reports_enabled() -> bool:
    return (
        os.getenv("CYPHWARD_ENV", "development") == "production"
        and os.getenv("CYPHWARD_ARTIFACT_REPORTS") == "true"
    )


def enabled() -> bool:
    return lab_enabled() or production_reports_enabled()


def table_only_requested(message: str) -> bool:
    """Honor an explicit latest-turn format restriction, even after a chart view."""
    text = message.lower()
    return bool(re.search(r"\b(?:only|just)\s+(?:(?:a|the)\s+)?tables?\b|\btables?[- ]only\b", text)
                or (re.search(r"\btables?\b", text) and re.search(r"\b(?:no|without)\s+(?:charts?|graphs?)\b", text)))


def wants_report(message: str, previous: ArtifactReference | None = None) -> bool:
    if not enabled():
        return False
    text = message.lower()
    if re.search(r"\b(report|table|chart|graph|visuali[sz]e|performance|dashboard)\b", text):
        return True
    return previous is not None and bool(re.search(
        r"\b(change|update|revise|instead|bar|line|pie|donut|last|past|refresh|regenerate)\b", text))


def build_report(org: dict, message: str, previous: ArtifactReference | None = None, artifact_id: UUID | None = None,
                 *, charts: list[ChartSelection] | None = None, include_metrics: bool | None = None,
                 include_tables: bool | None = None, heading: str | None = None,
                 severities: list[Severity] | None = None, include_catalog: bool = False) -> dict:
    """One repeatable-read tenant-scoped snapshot, bounded rows, host-derived numbers."""
    if not enabled():
        raise ValueError("Report charts are not enabled on this server.")
    text = message.lower()
    days = previous.days if previous else 90
    match = re.search(r"\b(\d{1,3})[ -]?(?:days?|day)\b", text)
    if match:
        days = int(match.group(1))
    elif "week" in text:
        days = 7
    elif "month" in text:
        days = 30
    if not 1 <= days <= 365:
        raise ValueError("Choose a period of 1 to 365 days.")
    style = previous.chart_style if previous else "line"
    if "bar" in text:
        style = "bar"
    elif "line" in text:
        style = "line"
    elif "area" in text:
        style = "area"
    selection = charts if charts is not None else (previous.charts if previous else None)
    if charts is None and previous and previous.charts and re.search(r"\b(line|bar|area)\b", text):
        selection = [ChartSelection(metric=c.metric, kind=style if CATALOG[c.metric]["temporal"] else c.kind) for c in previous.charts]
    if table_only_requested(message) and not include_catalog:
        selection = []
        include_metrics = False
        include_tables = True
    if include_catalog:
        selection = [ChartSelection(metric=m, kind=c["kind"]) for m, c in CATALOG.items()]
    if selection is None:
        selection = [ChartSelection(metric="assessment_scores", kind=style), ChartSelection(metric="severity", kind="bar"), ChartSelection(metric="finding_status", kind="donut")]
    include_metrics = include_metrics if include_metrics is not None else (previous.include_metrics if previous else True)
    include_tables = include_tables if include_tables is not None else (previous.include_tables if previous else True)
    severities = severities if severities is not None else (previous.severities if previous else [])
    severity_arg = severities or None
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    oid = org["id"]
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '5s'")
                cur.execute("SELECT severity, status, count(*) AS n FROM findings WHERE org_id=%s GROUP BY severity,status", (oid,))
                findings = cur.fetchall()
                if severities:
                    findings = [r for r in findings if r["severity"] in severities]
                cur.execute("SELECT count(*) AS n FROM assets WHERE org_id=%s", (oid,))
                assets = cur.fetchone()["n"]
                cur.execute("SELECT count(*) AS n FROM domains WHERE org_id=%s AND verification_status='verified'", (oid,))
                verified = cur.fetchone()["n"]
                cur.execute("""SELECT status, count(*) AS n FROM scans WHERE org_id=%s
                    AND status='completed' AND completed_at >= %s AND completed_at <= now() GROUP BY status""", (oid, since))
                scan_counts = cur.fetchall()
                cur.execute("""SELECT id, score, completed_at, domain_id FROM scans
                    WHERE org_id=%s AND status='completed' AND completed_at >= %s AND completed_at <= now()
                    ORDER BY completed_at DESC, id DESC LIMIT 60""", (oid, since))
                scans = list(reversed(cur.fetchall()))
                cur.execute("""SELECT title,severity,status FROM findings WHERE org_id=%s AND status!='resolved'
                    AND (%s::text[] IS NULL OR severity=ANY(%s::text[]))
                    ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, id
                    LIMIT 20""", (oid, severity_arg, severity_arg))
                priorities = cur.fetchall()
                cur.execute("""SELECT category, count(*) AS n FROM findings WHERE org_id=%s AND status!='resolved'
                    AND (%s::text[] IS NULL OR severity=ANY(%s::text[])) GROUP BY category ORDER BY n DESC,category LIMIT 12""", (oid, severity_arg, severity_arg))
                categories = cur.fetchall()
                cur.execute("SELECT status, count(*) AS n FROM remediation_tasks WHERE org_id=%s GROUP BY status ORDER BY status", (oid,))
                tasks = cur.fetchall()
                bucket = "day" if days <= 90 else "week"
                timelines = {}
                for metric, table, column, extra in (
                    ("scan_volume", "scans", "completed_at", "AND status='completed'"),
                    ("findings_discovered", "findings", "first_seen_at", ""),
                    ("findings_resolved", "findings", "resolved_at", ""),
                ):
                    # Identifiers/cadence come only from the host's constant catalog.
                    filtering = "AND (%s::text[] IS NULL OR severity=ANY(%s::text[]))" if table == "findings" else ""
                    args = (oid, since, severity_arg, severity_arg) if filtering else (oid, since)
                    cur.execute(f"""SELECT date_trunc('{bucket}',{column} AT TIME ZONE 'UTC') AS bucket, count(*) AS n
                        FROM {table} WHERE org_id=%s AND {column} >= %s AND {column} <= now() {extra} {filtering}
                        GROUP BY bucket ORDER BY bucket LIMIT 100""", args)
                    timelines[metric] = cur.fetchall()
    severity = {s: 0 for s in ("critical", "high", "medium", "low", "info")}
    states: dict[str, int] = {}
    for row in findings:
        states[row["status"]] = states.get(row["status"], 0) + row["n"]
        if row["status"] != "resolved":
            severity[row["severity"]] = severity.get(row["severity"], 0) + row["n"]
    total = sum(states.values())
    resolved = states.get("resolved", 0)
    open_count = total - resolved
    completed = next((r["n"] for r in scan_counts if r["status"] == "completed"), 0)
    from backend.app.core.demo_org import DEMO_ORG_ID
    sample = str(oid) == DEMO_ORG_ID
    summary = (f"{org['name']} has {open_count} unresolved findings and {resolved} recorded as resolved. "
               f"{completed} assessments completed in the last {days} days. "
               f"{verified} domains are currently verified and {assets} assets are recorded.")
    all_charts = {
        "assessment_scores": ReportChart(id="scan-scores", metric="assessment_scores", x_type="temporal", title="Recorded assessment scores", kind=style, unit="Score / 100",
            note="Each point is one completed assessment, within its own domain and scope; these are not comparable organization-wide trend scores. Latest 60 assessments; unscored assessments are omitted.",
            points=[ChartPoint(label=r["completed_at"].isoformat(), value=r["score"]) for r in scans if r["score"] is not None]),
        "severity": ReportChart(id="severity", metric="severity", x_type="ordinal", title="Unresolved findings by severity", kind="bar", unit="Findings",
            note="Current recorded inventory, not historical severity counts.",
            points=[ChartPoint(label=s.title(), value=n) for s, n in severity.items() if not severities or s in severities]),
        "finding_status": ReportChart(id="resolution", metric="finding_status", x_type="ordinal", title="Finding workflow", kind="donut", unit="Findings",
            note="Current workflow status; a resolved status alone does not establish an evidence-verified fix.",
            points=[ChartPoint(label=s.replace("_", " ").title(), value=n) for s, n in sorted(states.items())]),
        "categories": ReportChart(id="categories", metric="categories", x_type="ordinal", title="Unresolved findings by category", kind="bar", unit="Findings",
            note="Top 12 current unresolved finding categories; this is not a category trend.", points=[ChartPoint(label=r["category"] or "Uncategorized", value=r["n"]) for r in categories]),
        "remediation_status": ReportChart(id="remediation-status", metric="remediation_status", x_type="ordinal", title="Remediation task workflow", kind="bar", unit="Tasks",
            note="Current task statuses; task workflow alone does not prove a verified fix. Severity filters do not apply to tasks.", points=[ChartPoint(label=r["status"].replace("_", " ").title(), value=r["n"]) for r in tasks]),
    }
    for metric, rows in timelines.items():
        info = CATALOG[metric]
        note = f"Recorded events grouped by UTC {bucket}; only nonempty buckets are shown."
        if metric == "findings_resolved":
            note += " A recorded resolution is not automatically evidence of a verified fix."
        if metric == "scan_volume":
            note += " Counts completed assessments, not protected assets or prevented attacks."
        all_charts[metric] = ReportChart(id=info["id"], metric=metric, x_type="temporal", title=info["title"], kind=info["kind"], unit=info["unit"], note=note,
            points=[ChartPoint(label=r["bucket"].replace(tzinfo=timezone.utc).isoformat(), value=r["n"]) for r in rows])
    rendered = []
    for choice in selection:
        chart = all_charts[choice.metric].model_copy(update={"kind": choice.kind})
        if any(r.id == chart.id for r in rendered):
            chart.id += f"-{len(rendered)}"
        rendered.append(chart)
    if len(rendered) == 1:
        summary = f"{rendered[0].title} for {org['name']}. " + (f"Last {days} days." if rendered[0].x_type == "temporal" else "Current recorded inventory; historical category changes are unavailable.")
    artifact = ReportArtifact(
        id=previous.id if previous else (artifact_id or uuid4()), version=previous.version + 1 if previous else 1,
        org_id=UUID(str(oid)), title=heading or (previous.heading if previous else None) or f"{org['name']} · Security performance", generated_at=now,
        days=days, chart_style=style, sample=sample, summary=summary, severities=severities,
        metrics=[{"label": "Unresolved findings", "value": str(open_count)},
                 {"label": "Recorded resolved", "value": str(resolved)},
                 {"label": f"Completed / {days} days", "value": str(completed)},
                 {"label": "Inventoried assets", "value": str(assets)}] if include_metrics else [],
        charts=rendered,
        tables=[
            ReportTable(title="Priority findings · current inventory (up to 20)", columns=["Finding", "Severity", "Status"],
                rows=[[r["title"], r["severity"], r["status"]] for r in priorities]),
            ReportTable(title="Completed assessments · selected period (latest 60)", columns=["Completed (UTC)", "Score / 100", "Scan ID"],
                rows=[[r["completed_at"].isoformat(), r["score"], str(r["id"])] for r in scans]),
        ] if include_tables else [],
        limitations=[
            ("Lab preview. Report versions live in this browser tab and reset on reload."
             if lab_enabled() else
             "Report versions live in this browser tab and reset on reload."),
            "Period selection applies to completed assessments and discovery/resolution events; inventory counts describe the current state.",
            "Security telemetry does not measure revenue, uptime, employee productivity or financial performance.",
            "Synthetic sample data." if sample else "Recorded data is evidence of assessed scope, not proof of a secure or compliant organization.",
            "Finding severity filter: " + (", ".join(severities) if severities else "all severities") + ". This does not filter assessment scores, scan activity, assets or tasks.",
        ],
        sources=["findings: current tenant-scoped inventory", "scans: completed assessments within selected period", "assets / domains: current tenant-scoped inventory"],
    )
    return artifact.model_dump(mode="json")
