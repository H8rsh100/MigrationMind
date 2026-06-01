"""Tests for reporters: JSON and Markdown output."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from migrationmind.models.operation import DDLOperation, LockType, OperationClass, RiskLevel, RollbackComplexity
from migrationmind.models.report import QueryImpact, RiskReport, RollbackResult
from migrationmind.reporters.json_reporter import render_json
from migrationmind.reporters.markdown import render_markdown


def _make_report() -> RiskReport:
    op = DDLOperation(
        operation_class=OperationClass.ADD_COLUMN,
        target_table="users",
        target_column="last_active",
        dialect="postgresql",
        raw_sql="ALTER TABLE users ADD COLUMN last_active TIMESTAMP;",
        risk_level=RiskLevel.HIGH,
        lock_type=LockType.ACCESS_EXCLUSIVE,
        estimated_duration_min=2.0,
        estimated_duration_max=8.0,
        rollback_complexity=RollbackComplexity.SAFE,
        rollback_description="DROP the column.",
        notes=["Full table rewrite required."],
    )
    return RiskReport(
        migration_file="0042_add_last_active.sql",
        dialect="postgresql",
        db_version=14,
        operations=[op],
        query_impacts=[
            QueryImpact(
                query="SELECT * FROM users WHERE email = ?",
                impact_type="index_missing",
                severity=RiskLevel.MEDIUM,
                description="Index dropped, expect slowdown.",
                affected_table="users",
            )
        ],
        rollback=RollbackResult(
            complexity=RollbackComplexity.SAFE,
            estimated_minutes=5,
            data_loss_risk=False,
            notes="",
        ),
        generated_at=datetime(2024, 1, 15, 12, 0, 0),
    )


class TestJsonReporter:
    def test_renders_valid_json(self):
        report = _make_report()
        json_str = render_json(report)
        data = json.loads(json_str)
        assert isinstance(data, dict)

    def test_contains_key_fields(self):
        report = _make_report()
        data = json.loads(render_json(report))
        assert data["migration_file"] == "0042_add_last_active.sql"
        assert data["dialect"] == "postgresql"
        assert len(data["operations"]) == 1
        assert len(data["query_impacts"]) == 1

    def test_operation_has_risk_level(self):
        report = _make_report()
        data = json.loads(render_json(report))
        assert data["operations"][0]["risk_level"] == "high"


class TestMarkdownReporter:
    def test_renders_string(self):
        report = _make_report()
        md = render_markdown(report)
        assert isinstance(md, str)
        assert len(md) > 100

    def test_contains_migration_filename(self):
        report = _make_report()
        md = render_markdown(report)
        assert "0042_add_last_active.sql" in md

    def test_contains_operation_class(self):
        report = _make_report()
        md = render_markdown(report)
        assert "ADD_COLUMN" in md

    def test_contains_risk_emoji(self):
        report = _make_report()
        md = render_markdown(report)
        assert "🔴" in md or "🚨" in md  # HIGH or CRITICAL

    def test_contains_query_impact_table(self):
        report = _make_report()
        md = render_markdown(report)
        assert "index_missing" in md

    def test_contains_rollback_section(self):
        report = _make_report()
        md = render_markdown(report)
        assert "Rollback" in md
