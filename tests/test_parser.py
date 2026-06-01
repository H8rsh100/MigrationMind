"""Tests for Stage 1: SQL migration parser."""

from __future__ import annotations

import pytest

from migrationmind.models.operation import OperationClass
from migrationmind.stages.parser import parse_migration


class TestParseAddColumn:
    def test_add_nullable_column(self):
        sql = "ALTER TABLE users ADD COLUMN bio TEXT;"
        ops = parse_migration(sql)
        assert len(ops) == 1
        assert ops[0].operation_class == OperationClass.ADD_COLUMN
        assert ops[0].target_table == "users"
        assert ops[0].target_column == "bio"

    def test_add_not_null_without_default_flagged(self):
        sql = "ALTER TABLE users ADD COLUMN score INTEGER NOT NULL;"
        ops = parse_migration(sql)
        assert any("NOT NULL" in n for n in ops[0].notes)

    def test_multiple_alter_table_actions(self):
        sql = """
        ALTER TABLE orders
            ADD COLUMN notes TEXT,
            DROP COLUMN old_ref;
        """
        ops = parse_migration(sql)
        classes = [op.operation_class for op in ops]
        assert OperationClass.ADD_COLUMN in classes
        assert OperationClass.DROP_COLUMN in classes


class TestParseCreateTable:
    def test_create_table(self):
        sql = """
        CREATE TABLE audit_log (
            id BIGSERIAL PRIMARY KEY,
            action VARCHAR(100) NOT NULL
        );
        """
        ops = parse_migration(sql)
        assert len(ops) == 1
        assert ops[0].operation_class == OperationClass.CREATE_TABLE
        assert ops[0].target_table == "audit_log"


class TestParseDropTable:
    def test_drop_table(self):
        sql = "DROP TABLE legacy_sessions;"
        ops = parse_migration(sql)
        assert ops[0].operation_class == OperationClass.DROP_TABLE
        assert any("irreversible" in n.lower() for n in ops[0].notes)


class TestParseCreateIndex:
    def test_create_index(self):
        sql = "CREATE INDEX idx_users_email ON users (email);"
        ops = parse_migration(sql)
        assert ops[0].operation_class == OperationClass.CREATE_INDEX
        assert ops[0].target_table == "users"

    def test_create_index_notes_no_concurrent(self):
        sql = "CREATE INDEX idx_users_email ON users (email);"
        ops = parse_migration(sql)
        assert any("CONCURRENTLY" in n or "lock" in n.lower() for n in ops[0].notes)


class TestParseDropIndex:
    def test_drop_index_via_alter(self):
        sql = "DROP INDEX idx_users_email;"
        ops = parse_migration(sql)
        assert ops[0].operation_class == OperationClass.DROP_INDEX


class TestParseTruncate:
    def test_truncate(self):
        sql = "TRUNCATE TABLE sessions;"
        ops = parse_migration(sql)
        assert ops[0].operation_class == OperationClass.TRUNCATE_TABLE
        assert any("irreversible" in n.lower() for n in ops[0].notes)


class TestMultiStatement:
    def test_multi_operation_migration(self):
        sql = """
        ALTER TABLE users ADD COLUMN last_active TIMESTAMP NOT NULL DEFAULT NOW();
        DROP INDEX idx_users_email;
        CREATE TABLE audit_log (id BIGSERIAL PRIMARY KEY, action TEXT NOT NULL);
        """
        ops = parse_migration(sql)
        assert len(ops) >= 3
        classes = [op.operation_class for op in ops]
        assert OperationClass.ADD_COLUMN in classes
        assert OperationClass.DROP_INDEX in classes
        assert OperationClass.CREATE_TABLE in classes


class TestEmptyInput:
    def test_empty_string(self):
        ops = parse_migration("")
        assert ops == []

    def test_comments_only(self):
        ops = parse_migration("-- just a comment\n-- another comment")
        assert ops == []
