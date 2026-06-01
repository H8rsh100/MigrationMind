"""Stage 4: Lock type and downtime estimation engine.

Maps DDL operations to PostgreSQL/MySQL lock types and estimates
lock duration based on operation type, database version, and
optional table size metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from migrationmind.models.operation import DDLOperation, LockType, OperationClass, RiskLevel


@dataclass
class LockEstimate:
    lock_type: LockType
    risk_level: RiskLevel
    duration_min: Optional[float]   # minutes lower bound
    duration_max: Optional[float]   # minutes upper bound
    notes: list[str]


# Rows-per-minute throughput for DDL ops (conservative estimates)
_ROWS_PER_MIN_TABLE_REWRITE = 2_000_000   # ~2M rows/min full rewrite
_ROWS_PER_MIN_FK_SCAN = 5_000_000         # ~5M rows/min FK validation


def _estimate_duration(row_count: Optional[int], rows_per_min: int) -> tuple[Optional[float], Optional[float]]:
    """Return (min_minutes, max_minutes) or (None, None) if no row count."""
    if row_count is None:
        return None, None
    mid = row_count / rows_per_min
    return round(mid * 0.7, 2), round(mid * 1.8, 2)  # ±40% variance


def analyze_lock(op: DDLOperation, db_version: int = 14, row_count: Optional[int] = None) -> LockEstimate:
    """
    Classify the lock type and estimate duration for a single DDL operation.

    Args:
        op: The DDL operation to analyze.
        db_version: Major version of the database (e.g. 14 for Postgres 14).
        row_count: Optional table row count for duration estimation.

    Returns:
        LockEstimate with lock type, risk level, estimated duration, and notes.
    """
    dialect = op.dialect.lower()
    notes: list[str] = []

    # ------------------------------------------------------------------
    # ADD COLUMN
    # ------------------------------------------------------------------
    if op.operation_class == OperationClass.ADD_COLUMN:
        has_default = any("DEFAULT" in n.upper() or "default" in n.lower() for n in op.notes)
        has_not_null_danger = any("NOT NULL" in n for n in op.notes)

        if dialect in ("postgres", "postgresql"):
            if db_version >= 11 and has_default and not has_not_null_danger:
                # PG 11+: ADD COLUMN with DEFAULT is metadata-only
                notes.append("PostgreSQL 11+: ADD COLUMN with DEFAULT is instant (metadata-only).")
                return LockEstimate(
                    lock_type=LockType.ACCESS_EXCLUSIVE,
                    risk_level=RiskLevel.LOW,
                    duration_min=0.0,
                    duration_max=0.01,
                    notes=notes,
                )
            elif db_version < 11 and has_default:
                # PG < 11: full table rewrite
                dur_min, dur_max = _estimate_duration(row_count, _ROWS_PER_MIN_TABLE_REWRITE)
                notes.append(
                    f"PostgreSQL {db_version}: ADD COLUMN with DEFAULT triggers full table rewrite."
                )
                if row_count:
                    notes.append(
                        f"Estimated lock: {dur_min}–{dur_max} min ({row_count:,} rows)."
                    )
                else:
                    notes.append("Table size unknown — lock duration unpredictable (could be minutes).")
                return LockEstimate(
                    lock_type=LockType.ACCESS_EXCLUSIVE,
                    risk_level=RiskLevel.HIGH,
                    duration_min=dur_min,
                    duration_max=dur_max,
                    notes=notes,
                )
            elif has_not_null_danger:
                dur_min, dur_max = _estimate_duration(row_count, _ROWS_PER_MIN_TABLE_REWRITE)
                notes.append("NOT NULL column without DEFAULT — will fail on non-empty tables.")
                return LockEstimate(
                    lock_type=LockType.ACCESS_EXCLUSIVE,
                    risk_level=RiskLevel.CRITICAL,
                    duration_min=dur_min,
                    duration_max=dur_max,
                    notes=notes,
                )
            else:
                # Nullable, no default — safe in all PG versions
                notes.append("Nullable ADD COLUMN with no DEFAULT — instant, safe.")
                return LockEstimate(
                    lock_type=LockType.ACCESS_EXCLUSIVE,
                    risk_level=RiskLevel.SAFE,
                    duration_min=0.0,
                    duration_max=0.01,
                    notes=notes,
                )

        elif dialect == "mysql":
            # MySQL: ADD COLUMN always rebuilds table (except instant algo)
            dur_min, dur_max = _estimate_duration(row_count, _ROWS_PER_MIN_TABLE_REWRITE)
            notes.append(
                "MySQL: ADD COLUMN typically rebuilds the table. "
                "Use ALGORITHM=INSTANT if MySQL 8.0.29+ for zero-lock."
            )
            return LockEstimate(
                lock_type=LockType.EXCLUSIVE,
                risk_level=RiskLevel.MEDIUM,
                duration_min=dur_min,
                duration_max=dur_max,
                notes=notes,
            )

    # ------------------------------------------------------------------
    # DROP COLUMN
    # ------------------------------------------------------------------
    elif op.operation_class == OperationClass.DROP_COLUMN:
        if dialect in ("postgres", "postgresql"):
            dur_min, dur_max = _estimate_duration(row_count, _ROWS_PER_MIN_TABLE_REWRITE)
            notes.append(
                "DROP COLUMN acquires AccessExclusiveLock — blocks all reads and writes. "
                "Space is not reclaimed until VACUUM runs."
            )
            if row_count and row_count > 1_000_000:
                notes.append(
                    f"⚠ Large table ({row_count:,} rows) — consider using a maintenance window."
                )
            return LockEstimate(
                lock_type=LockType.ACCESS_EXCLUSIVE,
                risk_level=RiskLevel.HIGH,
                duration_min=dur_min,
                duration_max=dur_max,
                notes=notes,
            )
        elif dialect == "mysql":
            dur_min, dur_max = _estimate_duration(row_count, _ROWS_PER_MIN_TABLE_REWRITE)
            notes.append("MySQL DROP COLUMN triggers full table rebuild.")
            return LockEstimate(
                lock_type=LockType.EXCLUSIVE,
                risk_level=RiskLevel.HIGH,
                duration_min=dur_min,
                duration_max=dur_max,
                notes=notes,
            )

    # ------------------------------------------------------------------
    # ALTER COLUMN (type change)
    # ------------------------------------------------------------------
    elif op.operation_class == OperationClass.ALTER_COLUMN:
        dur_min, dur_max = _estimate_duration(row_count, _ROWS_PER_MIN_TABLE_REWRITE)
        notes.append(
            "ALTER COLUMN type change requires a full table rewrite in most cases. "
            "Implicit casts may silently truncate data."
        )
        return LockEstimate(
            lock_type=LockType.ACCESS_EXCLUSIVE,
            risk_level=RiskLevel.HIGH,
            duration_min=dur_min,
            duration_max=dur_max,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # RENAME COLUMN / TABLE
    # ------------------------------------------------------------------
    elif op.operation_class in (OperationClass.RENAME_COLUMN, OperationClass.RENAME_TABLE):
        notes.append(
            "RENAME is a metadata-only operation — very fast. "
            "⚠ Application code referencing the old name will break immediately."
        )
        return LockEstimate(
            lock_type=LockType.ACCESS_EXCLUSIVE,
            risk_level=RiskLevel.MEDIUM,
            duration_min=0.0,
            duration_max=0.01,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # CREATE INDEX
    # ------------------------------------------------------------------
    elif op.operation_class == OperationClass.CREATE_INDEX:
        is_concurrent = any("CONCURRENTLY" in n.upper() for n in op.notes)
        if dialect in ("postgres", "postgresql") and is_concurrent:
            dur_min, dur_max = _estimate_duration(row_count, 1_000_000)
            notes.append(
                "CREATE INDEX CONCURRENTLY — no table lock, reads and writes proceed normally. "
                "Takes ~2× longer than blocking index build."
            )
            return LockEstimate(
                lock_type=LockType.SHARE_UPDATE_EXCLUSIVE,
                risk_level=RiskLevel.LOW,
                duration_min=dur_min,
                duration_max=dur_max,
                notes=notes,
            )
        else:
            dur_min, dur_max = _estimate_duration(row_count, 1_500_000)
            notes.append(
                "CREATE INDEX without CONCURRENTLY acquires ShareLock — "
                "blocks writes for the duration of the index build."
            )
            return LockEstimate(
                lock_type=LockType.SHARE,
                risk_level=RiskLevel.MEDIUM,
                duration_min=dur_min,
                duration_max=dur_max,
                notes=notes,
            )

    # ------------------------------------------------------------------
    # DROP INDEX
    # ------------------------------------------------------------------
    elif op.operation_class == OperationClass.DROP_INDEX:
        notes.append(
            "DROP INDEX acquires AccessExclusiveLock briefly. "
            "In PostgreSQL, use DROP INDEX CONCURRENTLY to avoid blocking."
        )
        return LockEstimate(
            lock_type=LockType.ACCESS_EXCLUSIVE,
            risk_level=RiskLevel.LOW,
            duration_min=0.0,
            duration_max=0.05,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # ADD FOREIGN KEY
    # ------------------------------------------------------------------
    elif op.operation_class == OperationClass.ADD_FOREIGN_KEY:
        dur_min, dur_max = _estimate_duration(row_count, _ROWS_PER_MIN_FK_SCAN)
        notes.append(
            "ADD FOREIGN KEY scans the entire table to validate existing rows. "
            "Duration is proportional to row count. "
            "In PostgreSQL, use NOT VALID + VALIDATE CONSTRAINT to reduce lock time."
        )
        return LockEstimate(
            lock_type=LockType.SHARE_ROW_EXCLUSIVE,
            risk_level=RiskLevel.MEDIUM,
            duration_min=dur_min,
            duration_max=dur_max,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # CREATE TABLE
    # ------------------------------------------------------------------
    elif op.operation_class == OperationClass.CREATE_TABLE:
        notes.append("CREATE TABLE — no lock on existing objects. Safe.")
        return LockEstimate(
            lock_type=LockType.NONE,
            risk_level=RiskLevel.SAFE,
            duration_min=0.0,
            duration_max=0.0,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # DROP TABLE
    # ------------------------------------------------------------------
    elif op.operation_class == OperationClass.DROP_TABLE:
        notes.append(
            "DROP TABLE is immediate but irreversible. "
            "Acquires AccessExclusiveLock and removes all data permanently."
        )
        return LockEstimate(
            lock_type=LockType.ACCESS_EXCLUSIVE,
            risk_level=RiskLevel.CRITICAL,
            duration_min=0.0,
            duration_max=0.05,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # TRUNCATE
    # ------------------------------------------------------------------
    elif op.operation_class == OperationClass.TRUNCATE_TABLE:
        notes.append(
            "TRUNCATE acquires AccessExclusiveLock and removes all rows instantly. Irreversible."
        )
        return LockEstimate(
            lock_type=LockType.ACCESS_EXCLUSIVE,
            risk_level=RiskLevel.CRITICAL,
            duration_min=0.0,
            duration_max=0.01,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # ADD CONSTRAINT
    # ------------------------------------------------------------------
    elif op.operation_class == OperationClass.ADD_CONSTRAINT:
        notes.append(
            "ADD CONSTRAINT scans existing rows for violations. "
            "Duration proportional to table size."
        )
        dur_min, dur_max = _estimate_duration(row_count, _ROWS_PER_MIN_FK_SCAN)
        return LockEstimate(
            lock_type=LockType.SHARE_ROW_EXCLUSIVE,
            risk_level=RiskLevel.MEDIUM,
            duration_min=dur_min,
            duration_max=dur_max,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------
    notes.append("Unknown operation — unable to classify lock type.")
    return LockEstimate(
        lock_type=LockType.NONE,
        risk_level=RiskLevel.LOW,
        duration_min=None,
        duration_max=None,
        notes=notes,
    )


def apply_lock_analysis(
    operations: list[DDLOperation],
    db_version: int = 14,
    table_row_counts: Optional[dict[str, int]] = None,
) -> list[DDLOperation]:
    """
    Enrich a list of DDLOperation objects with lock type and risk level.

    Args:
        operations: Parsed DDL operations.
        db_version: Database major version.
        table_row_counts: Optional mapping of table_name -> row count.

    Returns:
        The same list with risk_level, lock_type, duration fields populated.
    """
    row_counts = table_row_counts or {}

    for op in operations:
        row_count = row_counts.get(op.target_table)
        estimate = analyze_lock(op, db_version=db_version, row_count=row_count)

        op.risk_level = estimate.risk_level
        op.lock_type = estimate.lock_type
        op.estimated_duration_min = estimate.duration_min
        op.estimated_duration_max = estimate.duration_max
        op.notes.extend(estimate.notes)

    return operations
