"""Stage 5: Rollback complexity classifier.

Classifies how complex it is to roll back each DDL operation, and
produces an overall rollback assessment for the migration.
"""

from __future__ import annotations

from migrationmind.models.operation import DDLOperation, OperationClass, RollbackComplexity
from migrationmind.models.report import RollbackResult


# Map operation class → (complexity, description, data_loss_risk)
_ROLLBACK_MAP: dict[OperationClass, tuple[RollbackComplexity, str, bool]] = {
    OperationClass.ADD_COLUMN: (
        RollbackComplexity.SAFE,
        "DROP the added column — instant and safe.",
        False,
    ),
    OperationClass.DROP_COLUMN: (
        RollbackComplexity.MANUAL,
        "Restore column from backup. Any data written to it after drop is lost.",
        True,
    ),
    OperationClass.ALTER_COLUMN: (
        RollbackComplexity.MANUAL,
        "Revert type change. Data may have been truncated or cast — verify before rollback.",
        True,
    ),
    OperationClass.RENAME_COLUMN: (
        RollbackComplexity.COMPLEX,
        "Rename column back AND revert all application code referencing the new name.",
        False,
    ),
    OperationClass.RENAME_TABLE: (
        RollbackComplexity.COMPLEX,
        "Rename table back AND revert all application code referencing the new name.",
        False,
    ),
    OperationClass.CREATE_TABLE: (
        RollbackComplexity.SAFE,
        "DROP the created table — safe if no data was inserted.",
        False,
    ),
    OperationClass.DROP_TABLE: (
        RollbackComplexity.NONE,
        "Cannot roll back a DROP TABLE without a full backup restore.",
        True,
    ),
    OperationClass.TRUNCATE_TABLE: (
        RollbackComplexity.NONE,
        "TRUNCATE is irreversible — all row data is permanently deleted.",
        True,
    ),
    OperationClass.CREATE_INDEX: (
        RollbackComplexity.SAFE,
        "DROP the created index — instant and safe.",
        False,
    ),
    OperationClass.DROP_INDEX: (
        RollbackComplexity.SAFE,
        "Recreate the index (may require downtime or CONCURRENTLY flag).",
        False,
    ),
    OperationClass.ADD_CONSTRAINT: (
        RollbackComplexity.SAFE,
        "DROP the constraint — safe, but may require re-validation on re-add.",
        False,
    ),
    OperationClass.DROP_CONSTRAINT: (
        RollbackComplexity.SAFE,
        "Recreate the constraint — will validate all existing rows.",
        False,
    ),
    OperationClass.ADD_FOREIGN_KEY: (
        RollbackComplexity.SAFE,
        "DROP CONSTRAINT — safe, but any orphaned rows inserted during the migration remain.",
        False,
    ),
    OperationClass.DROP_FOREIGN_KEY: (
        RollbackComplexity.SAFE,
        "Re-add the foreign key — will scan the entire table for validation.",
        False,
    ),
    OperationClass.CREATE_VIEW: (
        RollbackComplexity.SAFE,
        "DROP the view — instant and safe.",
        False,
    ),
    OperationClass.DROP_VIEW: (
        RollbackComplexity.SAFE,
        "Recreate the view from the original definition.",
        False,
    ),
}

# Complexity ordering (higher = worse)
_COMPLEXITY_ORDER = {
    RollbackComplexity.SAFE: 0,
    RollbackComplexity.MANUAL: 1,
    RollbackComplexity.COMPLEX: 2,
    RollbackComplexity.NONE: 3,
}


def classify_rollback(op: DDLOperation) -> tuple[RollbackComplexity, str, bool]:
    """
    Return (complexity, description, data_loss_risk) for a single operation.
    """
    return _ROLLBACK_MAP.get(
        op.operation_class,
        (RollbackComplexity.MANUAL, "Unknown operation — manual rollback assessment required.", False),
    )


def analyze_rollback(operations: list[DDLOperation]) -> RollbackResult:
    """
    Analyze rollback complexity for the entire migration and produce
    a consolidated RollbackResult.

    Side effect: populates op.rollback_complexity and op.rollback_description
    for each operation.
    """
    worst_complexity = RollbackComplexity.SAFE
    any_data_loss = False
    all_steps: list[str] = []

    for op in operations:
        complexity, description, data_loss = classify_rollback(op)

        op.rollback_complexity = complexity
        op.rollback_description = description

        if data_loss:
            any_data_loss = True

        if _COMPLEXITY_ORDER[complexity] > _COMPLEXITY_ORDER[worst_complexity]:
            worst_complexity = complexity

        label = op.target_column or op.target_index or op.target_table
        all_steps.append(
            f"{op.operation_class.value} on `{label}`: {description}"
        )

    # Estimate total rollback time (rough heuristic)
    estimated_minutes: int | None = None
    if worst_complexity == RollbackComplexity.SAFE:
        estimated_minutes = 5
    elif worst_complexity == RollbackComplexity.MANUAL:
        estimated_minutes = 30
    elif worst_complexity == RollbackComplexity.COMPLEX:
        estimated_minutes = 60
    elif worst_complexity == RollbackComplexity.NONE:
        estimated_minutes = None  # not possible without restore

    notes = ""
    if any_data_loss:
        notes = (
            "⚠ This migration has operations with DATA LOSS risk. "
            "Ensure you have a verified backup before proceeding."
        )
    if worst_complexity == RollbackComplexity.NONE:
        notes += (
            " One or more operations are IRREVERSIBLE — "
            "rollback requires a full database restore from backup."
        )

    return RollbackResult(
        complexity=worst_complexity,
        estimated_minutes=estimated_minutes,
        steps=all_steps,
        data_loss_risk=any_data_loss,
        notes=notes.strip(),
    )
