"""Pydantic models for DDL operations."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class OperationClass(str, Enum):
    ADD_COLUMN = "ADD_COLUMN"
    DROP_COLUMN = "DROP_COLUMN"
    ALTER_COLUMN = "ALTER_COLUMN"
    RENAME_COLUMN = "RENAME_COLUMN"
    RENAME_TABLE = "RENAME_TABLE"
    CREATE_TABLE = "CREATE_TABLE"
    DROP_TABLE = "DROP_TABLE"
    TRUNCATE_TABLE = "TRUNCATE_TABLE"
    CREATE_INDEX = "CREATE_INDEX"
    DROP_INDEX = "DROP_INDEX"
    ADD_CONSTRAINT = "ADD_CONSTRAINT"
    DROP_CONSTRAINT = "DROP_CONSTRAINT"
    ADD_FOREIGN_KEY = "ADD_FOREIGN_KEY"
    DROP_FOREIGN_KEY = "DROP_FOREIGN_KEY"
    CREATE_VIEW = "CREATE_VIEW"
    DROP_VIEW = "DROP_VIEW"
    UNKNOWN = "UNKNOWN"


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LockType(str, Enum):
    NONE = "none"
    ROW_SHARE = "row_share"
    ROW_EXCLUSIVE = "row_exclusive"
    SHARE_UPDATE_EXCLUSIVE = "share_update_exclusive"
    SHARE = "share"
    SHARE_ROW_EXCLUSIVE = "share_row_exclusive"
    EXCLUSIVE = "exclusive"
    ACCESS_EXCLUSIVE = "access_exclusive"


class RollbackComplexity(str, Enum):
    SAFE = "safe"           # trivially reversible (DROP added column)
    MANUAL = "manual"       # reversible but needs manual work or backup
    COMPLEX = "complex"     # reversible but app code must also change
    NONE = "none"           # irreversible (TRUNCATE, DROP TABLE with data)


class DDLOperation(BaseModel):
    """Represents a single DDL operation extracted from a migration file."""

    operation_class: OperationClass = OperationClass.UNKNOWN
    target_table: str = ""
    target_column: Optional[str] = None
    target_index: Optional[str] = None
    dialect: str = "postgresql"
    raw_sql: str = ""

    # Populated by rule engine
    risk_level: RiskLevel = RiskLevel.SAFE
    lock_type: LockType = LockType.NONE
    estimated_duration_min: Optional[float] = None  # minutes
    estimated_duration_max: Optional[float] = None  # minutes
    rollback_complexity: RollbackComplexity = RollbackComplexity.SAFE
    rollback_description: str = ""

    # Populated by query impact stage
    affected_queries: list[str] = Field(default_factory=list)

    # Human-readable notes from rule engine
    notes: list[str] = Field(default_factory=list)

    # LLM-generated fields
    llm_summary: Optional[str] = None
    safe_rewrite: Optional[str] = None

    @property
    def risk_score(self) -> int:
        """Numeric risk score 0-100."""
        mapping = {
            RiskLevel.SAFE: 0,
            RiskLevel.LOW: 20,
            RiskLevel.MEDIUM: 40,
            RiskLevel.HIGH: 70,
            RiskLevel.CRITICAL: 90,
        }
        base = mapping.get(self.risk_level, 0)
        # Boost for long locks
        if self.estimated_duration_max and self.estimated_duration_max > 5:
            base = min(100, base + 10)
        # Boost for irreversible ops
        if self.rollback_complexity == RollbackComplexity.NONE:
            base = min(100, base + 10)
        return base
