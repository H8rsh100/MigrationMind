"""Tests for Stage 3: Query impact analyzer."""

from __future__ import annotations

import pytest

from migrationmind.models.diff import ColumnChange, IndexChange, SchemaDiff
from migrationmind.models.operation import RiskLevel
from migrationmind.stages.query_impact import analyze_query_impact, parse_query_log


class TestParseQueryLog:
    def test_extracts_select_queries(self):
        log = """
SELECT * FROM users WHERE email = 'a@b.com';
SELECT id, name FROM products WHERE price > 100;
"""
        queries = parse_query_log(log)
        assert len(queries) == 2
        assert all(q.upper().startswith("SELECT") for q in queries)

    def test_deduplicates(self):
        log = "SELECT * FROM users;\nSELECT * FROM users;\n"
        queries = parse_query_log(log)
        assert len(queries) == 1

    def test_empty_log(self):
        assert parse_query_log("") == []

    def test_ignores_non_sql(self):
        log = "INFO: connection established\nDEBUG: something\n"
        queries = parse_query_log(log)
        assert queries == []


class TestAnalyzeQueryImpact:
    def _make_diff_with_removed_col(self, table="users", col="email") -> SchemaDiff:
        return SchemaDiff(
            column_changes=[
                ColumnChange(table=table, column=col, change_type="removed", breaking=True)
            ]
        )

    def _make_diff_with_removed_index(self, table="users", idx="idx_users_email") -> SchemaDiff:
        return SchemaDiff(
            index_changes=[
                IndexChange(
                    index_name=idx,
                    table=table,
                    change_type="removed",
                    columns=["email"],
                )
            ]
        )

    def test_detects_column_removal_impact(self):
        queries = ["SELECT email FROM users WHERE id = 1;"]
        diff = self._make_diff_with_removed_col()
        impacts = analyze_query_impact(queries, diff)
        assert len(impacts) >= 1
        assert impacts[0].impact_type == "column_missing"
        assert impacts[0].severity == RiskLevel.CRITICAL

    def test_detects_index_removal_impact(self):
        queries = ["SELECT * FROM users WHERE email = 'x@y.com';"]
        diff = self._make_diff_with_removed_index()
        impacts = analyze_query_impact(queries, diff)
        assert any(i.impact_type == "index_missing" for i in impacts)

    def test_no_impact_on_unrelated_query(self):
        queries = ["SELECT * FROM products WHERE price > 100;"]
        diff = self._make_diff_with_removed_col()
        impacts = analyze_query_impact(queries, diff)
        assert impacts == []

    def test_empty_queries(self):
        diff = self._make_diff_with_removed_col()
        impacts = analyze_query_impact([], diff)
        assert impacts == []

    def test_empty_diff(self):
        queries = ["SELECT email FROM users;"]
        impacts = analyze_query_impact(queries, SchemaDiff())
        assert impacts == []
