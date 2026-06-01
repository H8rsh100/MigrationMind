"""Utility: file detection and dialect inference."""

from __future__ import annotations

from pathlib import Path


def detect_dialect_from_path(filepath: str | Path) -> str:
    """Infer SQL dialect from filename or path heuristics."""
    name = str(filepath).lower()
    if "mysql" in name:
        return "mysql"
    if "sqlite" in name:
        return "sqlite"
    if "mssql" in name or "sqlserver" in name:
        return "tsql"
    return "postgres"


def is_migration_file(filepath: str | Path) -> bool:
    """Heuristic: is this file likely a migration?"""
    name = Path(filepath).name.lower()
    return any(kw in name for kw in ["migrat", "schema", "alter", "create", "drop", "ddl"])


def read_sql_file(filepath: str | Path) -> str:
    """Read a SQL file, returning its content as a string."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")
    return path.read_text(encoding="utf-8")
