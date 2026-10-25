"""Bounded local artifact contract, tenant query scoping, empty data and keyed SSE."""
import asyncio
import json
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from uuid import UUID

import pytest

from backend.app.ai import report_artifacts as artifacts
from backend.app.api import ai
from conftest import ALICE, ORG_A, ORG_B


@pytest.fixture
def lab(monkeypatch):
    monkeypatch.setenv("CYPHWARD_ENV", "development")
    monkeypatch.setenv("CYPHWARD_ARTIFACT_LAB", "true")
    monkeypatch.setattr(artifacts.config, "DATABASE_URL", "postgresql://cyphward_app@127.0.0.1/cyphward_test")


@pytest.mark.parametrize("env,url,flag", [
    ("production", "postgresql://postgres@localhost/local", "true"),
    ("development", "postgresql://postgres@example.com/live", "true"),
    ("development", "postgresql://postgres@localhost/local", "false"),
])
def test_lab_stays_off_outside_opted_in_local_runtime(monkeypatch, env, url, flag):
    monkeypatch.setenv("CYPHWARD_ENV", env)
    monkeypatch.setenv("CYPHWARD_ARTIFACT_LAB", flag)
    monkeypatch.delenv("CYPHWARD_ARTIFACT_REPORTS", raising=False)
    monkeypatch.setattr(artifacts.config, "DATABASE_URL", url)
    assert not artifacts.wants_report("generate a performance report with charts")
    with pytest.raises(ValueError):
        artifacts.build_report({"id": ORG_A}, "report")


@pytest.fixture
def prod_reports(monkeypatch):
    monkeypatch.setenv("CYPHWARD_ENV", "production")
    monkeypatch.setenv("CYPHWARD_ARTIFACT_REPORTS", "true")
    monkeypatch.delenv("CYPHWARD_ARTIFACT_LAB", raising=False)
    monkeypatch.setattr(artifacts.config, "DATABASE_URL", "postgresql://postgres@db.example.com/cyphward")


def test_production_reports_need_the_production_flag(monkeypatch):
    monkeypatch.setenv("CYPHWARD_ENV", "production")
    monkeypatch.delenv("CYPHWARD_ARTIFACT_REPORTS", raising=False)
    monkeypatch.setattr(artifacts.config, "DATABASE_URL", "postgresql://postgres@db.example.com/cyphward")
    assert not artifacts.enabled()
    monkeypatch.setenv("CYPHWARD_ARTIFACT_REPORTS", "true")
    assert artifacts.enabled() and artifacts.production_reports_enabled()
    assert not artifacts.lab_enabled()


def test_production_reports_flag_does_not_unlock_the_lab(monkeypatch):
    monkeypatch.setenv("CYPHWARD_ENV", "development")
    monkeypatch.setenv("CYPHWARD_ARTIFACT_REPORTS", "true")
    monkeypatch.delenv("CYPHWARD_ARTIFACT_LAB", raising=False)
    monkeypatch.setattr(artifacts.config, "DATABASE_URL", "postgresql://cyphward_app@127.0.0.1/cyphward_test")
    assert not artifacts.enabled()


def test_production_live_planner_follows_the_reports_flag(prod_reports, monkeypatch):
    from backend.app.ai.artifact_assistant import live_enabled
    monkeypatch.delenv("CYPHWARD_ARTIFACT_AI", raising=False)
    assert artifacts.wants_report("generate a performance report with charts")
    assert not live_enabled()
    monkeypatch.setenv("CYPHWARD_ARTIFACT_AI", "live")
    assert live_enabled()


def test_production_limitations_are_not_labelled_lab(prod_reports, monkeypatch):
    stub_snapshot(monkeypatch)
    result = artifacts.build_report({"id": ORG_A, "name": "Tenant A"}, "report")
    assert result["org_id"] == ORG_A
    assert any("browser tab" in text for text in result["limitations"])
    assert not any("Lab preview" in text or "Local experiment" in text for text in result["limitations"])


def test_report_intent_and_revision(lab):
    assert artifacts.wants_report("Generate charts for organisation performance")
    assert not artifacts.wants_report("How do I verify a domain?")
    ref = artifacts.ArtifactReference(id=UUID(ORG_A), version=1)
    assert artifacts.wants_report("Use bars instead", ref)
    assert not artifacts.wants_report("How do I fix DMARC?", ref)


def stub_snapshot(monkeypatch, *, empty=False):
    queries = []
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def execute(self, sql, params=()):
            if sql.startswith("SELECT"):
                assert "org_id=%s" in sql
                assert params[0] == ORG_A
            queries.append((sql, params))
            if sql.startswith("SELECT severity"):
                self.rows = [] if empty else [{"severity": "high", "status": "open", "n": 3}, {"severity": "low", "status": "resolved", "n": 2}]
            elif sql.startswith("SELECT count"):
                self.rows = [{"n": 0 if empty else 1}]
            elif sql.startswith("SELECT status"):
                self.rows = [] if empty else [{"status": "open" if "remediation_tasks" in sql else "completed", "n": 2}]
            elif sql.startswith("SELECT id, score"):
                self.rows = [] if empty else [{"id": UUID(ORG_B), "score": None, "completed_at": datetime.now(timezone.utc), "domain_id": UUID(ORG_A)}, {"id": UUID(ORG_A), "score": 70, "completed_at": datetime.now(timezone.utc), "domain_id": UUID(ORG_A)}]
            elif sql.startswith("SELECT title"):
                self.rows = [] if empty else [{"title": "Recorded finding", "severity": "high", "status": "open"}]
            elif sql.startswith("SELECT category"):
                self.rows = [] if empty else [{"category": "Email authentication", "n": 3}]
            elif sql.startswith("SELECT date_trunc"):
                self.rows = []
        def fetchall(self): return self.rows
        def fetchone(self): return self.rows[0]
    class Connection:
        def transaction(self): return nullcontext()
        def cursor(self): return Cursor()
    @contextmanager
    def db(): yield Connection()
    monkeypatch.setattr(artifacts, "get_db", db)
    return queries


def test_report_numbers_empty_scores_and_append_only_reference(lab, monkeypatch):
    queries = stub_snapshot(monkeypatch)
    ref = artifacts.ArtifactReference(id=UUID(ORG_B), version=4)
    result = artifacts.build_report({"id": ORG_A, "name": "Tenant A"}, "Use bar charts for last 30 days", ref)
    assert result["org_id"] == ORG_A
    assert result["id"] == ORG_B and result["version"] == 5
    assert ref.version == 4
    assert result["days"] == 30 and result["charts"][0]["kind"] == "bar"
    assert result["charts"][0]["points"][0]["value"] == 70
    assert len(result["charts"][0]["points"]) == 1  # null scores are never zero
    assert result["metrics"][0]["value"] == "3"
    assert "3 unresolved" in result["summary"]
    assert any("REPEATABLE READ READ ONLY" in sql for sql, _ in queries)
    assert any("LIMIT 60" in sql for sql, _ in queries)
    count_query = next(sql for sql, _ in queries if sql.startswith("SELECT status") and "FROM scans" in sql)
    assert "completed_at >=" in count_query and "completed_at <= now()" in count_query
    assert "created_at >=" not in count_query  # a scan may finish in a later reporting period


def test_empty_org_has_no_invented_trend(lab, monkeypatch):
    stub_snapshot(monkeypatch, empty=True)
    result = artifacts.build_report({"id": ORG_A, "name": "Empty org"}, "report")
    assert result["charts"][0]["points"] == []
    assert all(m["value"] == "0" for m in result["metrics"])
    assert result["tables"][0]["rows"] == []


def test_keyed_stream_separates_chart_payload_from_text(lab, monkeypatch):
    stub_snapshot(monkeypatch)
    async def run():
        response = await ai.cyphbot_chat_stream(ai.CyphBotChatRequest(message="performance report"), {"id": ORG_A, "name": "Tenant A"})
        return [json.loads(chunk.removeprefix("data: ")) async for chunk in response.body_iterator]
    events = asyncio.run(run())
    assert events[0]["status"] == "loading"
    assert events[0]["id"] == events[2]["artifact"]["id"]
    assert "artifact" not in events[1] and "token" in events[1]
    assert events[-1]["done"] is True


def test_report_failure_is_terminal_error(lab, monkeypatch):
    def fail(*_): raise RuntimeError("database credentials must not leak")
    monkeypatch.setattr(ai, "build_report", fail)
    async def run():
        response = await ai.cyphbot_chat_stream(ai.CyphBotChatRequest(message="report"), {"id": ORG_A})
        return [json.loads(chunk.removeprefix("data: ")) async for chunk in response.body_iterator]
    events = asyncio.run(run())
    assert events[-1]["done"] and "error" in events[-1]
    assert "credentials" not in str(events)


def test_chat_auth_cannot_be_bypassed_with_artifact_context(client, auth_headers, lab):
    assert client.post("/api/v1/ai/chat", json={"message": "report"}).status_code == 401
    assert client.post("/api/v1/ai/chat", headers=auth_headers(ALICE, org=ORG_B), json={"message": "report"}).status_code == 403


def test_only_line_means_one_chart_with_no_extra_cards_or_tables(lab, monkeypatch):
    stub_snapshot(monkeypatch)
    result = artifacts.build_report({"id": ORG_A, "name": "Tenant A"}, "last 14 days", charts=[artifacts.ChartSelection(metric="assessment_scores", kind="line")], include_metrics=False, include_tables=False)
    assert result["days"] == 14
    assert len(result["charts"]) == 1 and result["charts"][0]["kind"] == "line"
    assert result["metrics"] == result["tables"] == []


def test_filters_and_selection_survive_refresh(lab, monkeypatch):
    stub_snapshot(monkeypatch)
    ref = artifacts.ArtifactReference(id=UUID(ORG_A), version=2, days=14, charts=[artifacts.ChartSelection(metric="severity", kind="bar")], include_metrics=False, include_tables=False, severities=["high"], heading="Custom heading")
    result = artifacts.build_report({"id": ORG_A, "name": "Tenant A"}, "refresh", ref)
    assert result["version"] == 3 and result["days"] == 14
    assert result["title"] == "Custom heading" and result["severities"] == ["high"]
    assert result["charts"][0]["points"] == [{"label": "High", "value": 3.0}]
    assert len(result["charts"]) == 1 and not result["metrics"] and not result["tables"]


@pytest.mark.parametrize("metric,kind", [("severity", "line"), ("finding_status", "area"), ("assessment_scores", "donut"), ("sales", "bar")])
def test_invalid_metric_or_misleading_encoding_is_rejected(metric, kind):
    with pytest.raises(ValueError):
        artifacts.ChartSelection(metric=metric, kind=kind)


def test_catalog_is_complete_bounded_and_scoped(lab, monkeypatch):
    queries = stub_snapshot(monkeypatch)
    result = artifacts.build_report({"id": ORG_A, "name": "Tenant A"}, "last 365 days", include_catalog=True)
    assert len(result["charts"]) == len(artifacts.CATALOG) == 8
    assert any("date_trunc('week'" in sql for sql, _ in queries)
    for sql, params in queries:
        if sql.startswith("SELECT"):
            assert params[0] == ORG_A and "org_id=%s" in sql


def test_table_only_report_and_refresh_preserve_empty_chart_selection(lab, monkeypatch):
    stub_snapshot(monkeypatch)
    report = artifacts.build_report({"id": ORG_A, "name": "Tenant A"}, "Use just a table to explain findings")
    assert report["charts"] == [] and report["metrics"] == []
    assert report["tables"][0]["rows"][0][0] == "Recorded finding"
    ref = artifacts.ArtifactReference(id=report["id"], version=1, charts=[], include_metrics=False, include_tables=True)
    refreshed = artifacts.build_report({"id": ORG_A, "name": "Tenant A"}, "refresh", ref)
    assert refreshed["charts"] == [] and refreshed["tables"]
