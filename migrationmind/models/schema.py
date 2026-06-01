"""Pydantic models for schema snapshots."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ColumnModel(BaseModel):
    """Represents a single column in a table."""

    name: str
    data_type: str
    nullable: bool = True
    default: Optional[str] = None
    is_primary_key: bool = False
    references: Optional[str] = None  # "table.column" for FK

    def type_compatible_with(self, other: "ColumnModel") -> bool:
        """Rough check for type compatibility (same base type family)."""
        def _base(t: str) -> str:
            return t.split("(")[0].strip().lower()

        return _base(self.data_type) == _base(other.data_type)


class IndexModel(BaseModel):
    """Represents a database index."""

    name: str
    table: str
    columns: list[str] = Field(default_factory=list)
    is_unique: bool = False
    is_primary: bool = False
    method: str = "btree"  # btree, hash, gin, gist, etc.
    is_concurrent: bool = False  # for CREATE INDEX CONCURRENTLY


class ConstraintModel(BaseModel):
    """Represents a table constraint."""

    name: str
    table: str
    constraint_type: str  # PRIMARY KEY, UNIQUE, FOREIGN KEY, CHECK
    columns: list[str] = Field(default_factory=list)
    references_table: Optional[str] = None
    references_columns: list[str] = Field(default_factory=list)


class TableModel(BaseModel):
    """Represents a single database table."""

    name: str
    schema: str = "public"
    columns: dict[str, ColumnModel] = Field(default_factory=dict)
    indexes: dict[str, IndexModel] = Field(default_factory=dict)
    constraints: dict[str, ConstraintModel] = Field(default_factory=dict)

    # Optional size metadata (from pg_stat_user_tables etc.)
    estimated_row_count: Optional[int] = None
    size_bytes: Optional[int] = None

    @property
    def column_names(self) -> set[str]:
        return set(self.columns.keys())


class SchemaSnapshot(BaseModel):
    """A point-in-time snapshot of a database schema."""

    dialect: str = "postgresql"
    db_version: int = 14
    tables: dict[str, TableModel] = Field(default_factory=dict)
    views: dict[str, str] = Field(default_factory=dict)  # name -> definition

    def get_table(self, name: str) -> Optional[TableModel]:
        return self.tables.get(name) or self.tables.get(name.lower())

    def has_table(self, name: str) -> bool:
        return self.get_table(name) is not None

    def has_column(self, table: str, column: str) -> bool:
        t = self.get_table(table)
        if t is None:
            return False
        return column in t.columns or column.lower() in t.columns
