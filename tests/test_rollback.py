"""Tests for Stage 5: Rollback analyzer."""

from __future__ import annotations

import pytest

from migrationmind.models.operation import DDLOperation, OperationClass, RollbackComplexity
from migrationmind.stages.rollback_analyzer import analyze_rollback, classify_rollback


def make_op(op_class: OperationClass) -> DDLOperation:
    return DDLOperation(
        operation_class=op_class,
        target_table="users",
        dialect="postgres",
    )


class TestClassifyRollback:
    def test_add_column_is_safe(self):
        op = make_op(OperationClass.ADD_COLUMN)
        complexity, desc, data_loss = classify_rollback(op)
        assert complexity == RollbackComplexity.SAFE
        assert not data_loss

    def test_drop_column_is_manual_with_data_loss(self):
        op = make_op(OperationClass.DROP_COLUMN)
        complexity, desc, data_loss = classify_rollback(op)
        assert complexity == RollbackComplexity.MANUAL
        assert data_loss

    def test_drop_table_is_irreversible(self):
        op = make_op(OperationClass.DROP_TABLE)
        complexity, _, data_loss = classify_rollback(op)
        assert complexity == RollbackComplexity.NONE
        assert data_loss

    def test_truncate_is_irreversible(self):
        op = make_op(OperationClass.TRUNCATE_TABLE)
        complexity, _, data_loss = classify_rollback(op)
        assert complexity == RollbackComplexity.NONE
        assert data_loss

    def test_rename_column_is_complex(self):
        op = make_op(OperationClass.RENAME_COLUMN)
        complexity, _, _ = classify_rollback(op)
        assert complexity == RollbackComplexity.COMPLEX

    def test_create_index_is_safe(self):
        op = make_op(OperationClass.CREATE_INDEX)
        complexity, _, data_loss = classify_rollback(op)
        assert complexity == RollbackComplexity.SAFE
        assert not data_loss


class TestAnalyzeRollback:
    def test_all_safe_ops_returns_safe(self):
        ops = [
            make_op(OperationClass.ADD_COLUMN),
            make_op(OperationClass.CREATE_TABLE),
            make_op(OperationClass.CREATE_INDEX),
        ]
        result = analyze_rollback(ops)
        assert result.complexity == RollbackComplexity.SAFE
        assert not result.data_loss_risk

    def test_drop_table_escalates_to_none(self):
        ops = [
            make_op(OperationClass.ADD_COLUMN),
            make_op(OperationClass.DROP_TABLE),
        ]
        result = analyze_rollback(ops)
        assert result.complexity == RollbackComplexity.NONE
        assert result.data_loss_risk

    def test_steps_populated(self):
        ops = [make_op(OperationClass.ADD_COLUMN)]
        result = analyze_rollback(ops)
        assert len(result.steps) == 1

    def test_populates_op_rollback_fields(self):
        op = make_op(OperationClass.DROP_COLUMN)
        analyze_rollback([op])
        assert op.rollback_complexity == RollbackComplexity.MANUAL
        assert op.rollback_description != ""

    def test_estimated_minutes_safe(self):
        ops = [make_op(OperationClass.ADD_COLUMN)]
        result = analyze_rollback(ops)
        assert result.estimated_minutes == 5

    def test_no_rollback_no_minutes(self):
        ops = [make_op(OperationClass.DROP_TABLE)]
        result = analyze_rollback(ops)
        assert result.estimated_minutes is None
