"""Models for schema diff results."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ColumnChange(BaseModel):
    """A change to a column between two schema snapshots."""

    table: str
    column: str
    change_type: str  # added, removed, type_changed, nullable_changed, default_changed, renamed
    before: Optional[str] = None  # human-readable before value
    after: Optional[str] = None   # human-readable after value
    breaking: bool = False


class IndexChange(BaseModel):
    """A change to an index."""

    index_name: str
    table: str
    change_type: str  # added, removed
    columns: list[str] = Field(default_factory=list)
    is_unique: bool = False


class ConstraintChange(BaseModel):
    """A change to a constraint."""

    constraint_name: str
    table: str
    change_type: str  # added, removed, modified
    constraint_type: str


class TableChange(BaseModel):
    """A change to a table."""

    table: str
    change_type: str  # added, removed, renamed


class SchemaDiff(BaseModel):
    """Full diff between two schema snapshots."""

    column_changes: list[ColumnChange] = Field(default_factory=list)
    index_changes: list[IndexChange] = Field(default_factory=list)
    constraint_changes: list[ConstraintChange] = Field(default_factory=list)
    table_changes: list[TableChange] = Field(default_factory=list)

    @property
    def has_breaking_changes(self) -> bool:
        return any(c.breaking for c in self.column_changes)

    @property
    def removed_columns(self) -> list[ColumnChange]:
        return [c for c in self.column_changes if c.change_type == "removed"]

    @property
    def removed_indexes(self) -> list[IndexChange]:
        return [i for i in self.index_changes if i.change_type == "removed"]

    @property
    def added_not_null_columns(self) -> list[ColumnChange]:
        """Columns added as NOT NULL without a default — very dangerous."""
        return [
            c for c in self.column_changes
            if c.change_type == "added" and c.breaking
        ]

    def summary(self) -> dict:
        return {
            "table_changes": len(self.table_changes),
            "column_changes": len(self.column_changes),
            "index_changes": len(self.index_changes),
            "constraint_changes": len(self.constraint_changes),
            "breaking_changes": sum(1 for c in self.column_changes if c.breaking),
        }
