"""Tests for Stage 2: Schema diff engine."""

from __future__ import annotations

import pytest

from migrationmind.models.operation import DDLOperation, OperationClass
from migrationmind.models.schema import ColumnModel, SchemaSnapshot, TableModel
from migrationmind.stages.schema_diff import build_schema_diff, load_schema_from_sql


def _make_snapshot() -> SchemaSnapshot:
    snapshot = SchemaSnapshot(dialect="postgres")
    table = TableModel(name="users")
    table.columns["email"] = ColumnModel(name="email", data_type="VARCHAR(255)", nullable=False)
    table.columns["username"] = ColumnModel(name="username", data_type="VARCHAR(100)", nullable=False)
    snapshot.tables["users"] = table
    return snapshot


class TestLoadSchemaFromSql:
    def test_parses_create_table(self):
        sql = """
        CREATE TABLE users (
            id BIGSERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL
        );
        """
        snapshot = load_schema_from_sql(sql)
        assert "users" in snapshot.tables
        assert "id" in snapshot.tables["users"].columns
        assert "email" in snapshot.tables["users"].columns

    def test_parses_multiple_tables(self):
        sql = """
        CREATE TABLE users (id BIGSERIAL PRIMARY KEY);
        CREATE TABLE orders (id BIGSERIAL PRIMARY KEY);
        """
        snapshot = load_schema_from_sql(sql)
        assert "users" in snapshot.tables
        assert "orders" in snapshot.tables

    def test_empty_sql_returns_empty_snapshot(self):
        snapshot = load_schema_from_sql("")
        assert snapshot.tables == {}


class TestBuildSchemaDiff:
    def test_add_column_appears_in_diff(self):
        before = _make_snapshot()
        ops = [DDLOperation(
            operation_class=OperationClass.ADD_COLUMN,
            target_table="users",
            target_column="bio",
            dialect="postgres",
        )]
        diff = build_schema_diff(before, ops)
        added = [c for c in diff.column_changes if c.change_type == "added"]
        assert len(added) == 1
        assert added[0].column == "bio"

    def test_drop_column_marked_breaking(self):
        before = _make_snapshot()
        ops = [DDLOperation(
            operation_class=OperationClass.DROP_COLUMN,
            target_table="users",
            target_column="email",
            dialect="postgres",
        )]
        diff = build_schema_diff(before, ops)
        removed = [c for c in diff.column_changes if c.change_type == "removed"]
        assert len(removed) == 1
        assert removed[0].breaking is True

    def test_create_table_appears_as_table_change(self):
        before = _make_snapshot()
        ops = [DDLOperation(
            operation_class=OperationClass.CREATE_TABLE,
            target_table="audit_log",
            dialect="postgres",
        )]
        diff = build_schema_diff(before, ops)
        added_tables = [t for t in diff.table_changes if t.change_type == "added"]
        assert any(t.table == "audit_log" for t in added_tables)

    def test_drop_index_appears_in_index_changes(self):
        before = _make_snapshot()
        ops = [DDLOperation(
            operation_class=OperationClass.DROP_INDEX,
            target_table="users",
            target_index="idx_users_email",
            dialect="postgres",
        )]
        diff = build_schema_diff(before, ops)
        removed_idxs = [i for i in diff.index_changes if i.change_type == "removed"]
        assert len(removed_idxs) == 1

    def test_has_breaking_changes_property(self):
        before = _make_snapshot()
        ops = [DDLOperation(
            operation_class=OperationClass.DROP_COLUMN,
            target_table="users",
            target_column="email",
            dialect="postgres",
        )]
        diff = build_schema_diff(before, ops)
        assert diff.has_breaking_changes is True
