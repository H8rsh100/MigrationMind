"""Tests for Stage 4: Lock engine."""

from __future__ import annotations

import pytest

from migrationmind.models.operation import DDLOperation, LockType, OperationClass, RiskLevel
from migrationmind.stages.lock_engine import analyze_lock, apply_lock_analysis


def make_op(op_class: OperationClass, notes: list[str] | None = None) -> DDLOperation:
    return DDLOperation(
        operation_class=op_class,
        target_table="users",
        target_column="col",
        dialect="postgres",
        notes=notes or [],
    )


class TestAddColumnLock:
    def test_nullable_no_default_is_safe(self):
        op = make_op(OperationClass.ADD_COLUMN)
        est = analyze_lock(op, db_version=14)
        assert est.risk_level == RiskLevel.SAFE

    def test_pg11_with_default_is_low_risk(self):
        op = make_op(OperationClass.ADD_COLUMN, notes=["some DEFAULT note"])
        est = analyze_lock(op, db_version=11)
        assert est.risk_level == RiskLevel.LOW
        assert est.duration_max <= 0.1

    def test_pg10_with_default_is_high_risk(self):
        op = make_op(OperationClass.ADD_COLUMN, notes=["DEFAULT NOW()"])
        est = analyze_lock(op, db_version=10)
        assert est.risk_level == RiskLevel.HIGH
        assert est.lock_type == LockType.ACCESS_EXCLUSIVE

    def test_not_null_without_default_is_critical(self):
        op = make_op(OperationClass.ADD_COLUMN, notes=["NOT NULL column added without DEFAULT"])
        est = analyze_lock(op, db_version=14)
        assert est.risk_level == RiskLevel.CRITICAL

    def test_duration_estimate_with_row_count(self):
        op = make_op(OperationClass.ADD_COLUMN, notes=["DEFAULT NOW()"])
        est = analyze_lock(op, db_version=10, row_count=4_000_000)
        assert est.duration_min is not None
        assert est.duration_max is not None
        assert est.duration_max > est.duration_min


class TestDropColumnLock:
    def test_drop_column_is_high(self):
        op = make_op(OperationClass.DROP_COLUMN)
        est = analyze_lock(op, db_version=14)
        assert est.risk_level == RiskLevel.HIGH
        assert est.lock_type == LockType.ACCESS_EXCLUSIVE


class TestCreateIndexLock:
    def test_concurrent_index_is_low(self):
        op = make_op(OperationClass.CREATE_INDEX, notes=["CONCURRENTLY flag detected"])
        est = analyze_lock(op, db_version=14)
        assert est.risk_level == RiskLevel.LOW
        assert est.lock_type == LockType.SHARE_UPDATE_EXCLUSIVE

    def test_blocking_index_is_medium(self):
        op = make_op(OperationClass.CREATE_INDEX, notes=["No CONCURRENTLY"])
        est = analyze_lock(op, db_version=14)
        assert est.risk_level == RiskLevel.MEDIUM
        assert est.lock_type == LockType.SHARE


class TestDropTableLock:
    def test_drop_table_is_critical(self):
        op = make_op(OperationClass.DROP_TABLE)
        est = analyze_lock(op)
        assert est.risk_level == RiskLevel.CRITICAL


class TestTruncateLock:
    def test_truncate_is_critical(self):
        op = make_op(OperationClass.TRUNCATE_TABLE)
        est = analyze_lock(op)
        assert est.risk_level == RiskLevel.CRITICAL


class TestCreateTableLock:
    def test_create_table_is_safe(self):
        op = make_op(OperationClass.CREATE_TABLE)
        est = analyze_lock(op)
        assert est.risk_level == RiskLevel.SAFE
        assert est.lock_type == LockType.NONE


class TestApplyLockAnalysis:
    def test_enriches_operations_in_place(self):
        ops = [
            make_op(OperationClass.CREATE_TABLE),
            make_op(OperationClass.DROP_TABLE),
        ]
        result = apply_lock_analysis(ops, db_version=14)
        assert result[0].risk_level == RiskLevel.SAFE
        assert result[1].risk_level == RiskLevel.CRITICAL

    def test_uses_row_count_for_duration(self):
        ops = [make_op(OperationClass.DROP_COLUMN)]
        apply_lock_analysis(ops, db_version=14, table_row_counts={"users": 10_000_000})
        assert ops[0].estimated_duration_max is not None
