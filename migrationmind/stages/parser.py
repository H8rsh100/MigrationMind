"""Stage 1: SQLGlot-based migration file parser.

Parses migration SQL files into a list of DDLOperation objects regardless
of dialect (PostgreSQL, MySQL, SQLite, MSSQL).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

try:
    import sqlglot
    import sqlglot.expressions as exp
except ImportError as e:  # pragma: no cover
    raise ImportError("sqlglot is required: pip install sqlglot") from e

from migrationmind.models.operation import DDLOperation, OperationClass


# Map sqlglot expression types to our OperationClass
_EXPR_TO_OP: dict[type, OperationClass] = {
    exp.AlterTable: OperationClass.UNKNOWN,  # handled specially
    exp.Create: OperationClass.UNKNOWN,       # handled specially
    exp.Drop: OperationClass.UNKNOWN,         # handled specially
    exp.TruncateTable: OperationClass.TRUNCATE_TABLE,
}


def _infer_dialect(filepath: str) -> str:
    """Infer dialect from file path or content heuristics."""
    path = Path(filepath)
    name = path.name.lower()
    if "mysql" in name:
        return "mysql"
    if "sqlite" in name:
        return "sqlite"
    if "mssql" in name or "sqlserver" in name:
        return "tsql"
    return "postgres"  # default


def _extract_table_name(node: exp.Expression) -> str:
    """Extract table name string from an expression node."""
    table_node = node.find(exp.Table)
    if table_node:
        return table_node.name or ""
    return ""


def _parse_alter_table(stmt: exp.AlterTable, raw_sql: str, dialect: str) -> list[DDLOperation]:
    """Parse ALTER TABLE into one or more DDLOperation objects."""
    ops: list[DDLOperation] = []
    table_name = stmt.this.name if stmt.this else ""

    for action in stmt.args.get("actions", []):
        op = DDLOperation(raw_sql=raw_sql.strip(), dialect=dialect, target_table=table_name)

        if isinstance(action, exp.AddColumn):
            op.operation_class = OperationClass.ADD_COLUMN
            col = action.find(exp.ColumnDef)
            op.target_column = col.name if col else None

            # Check for NOT NULL without default — dangerous
            if col:
                constraints = col.args.get("constraints", [])
                has_not_null = any(
                    isinstance(c.kind, exp.NotNullColumnConstraint) for c in constraints
                )
                has_default = any(
                    isinstance(c.kind, exp.DefaultColumnConstraint) for c in constraints
                )
                if has_not_null and not has_default:
                    op.notes.append(
                        "NOT NULL column added without DEFAULT — "
                        "will fail on non-empty tables unless backfilled first."
                    )

        elif isinstance(action, exp.Drop):
            kind = (action.args.get("kind") or "").upper()
            if kind == "COLUMN":
                op.operation_class = OperationClass.DROP_COLUMN
                op.target_column = action.this.name if action.this else None
            elif kind in ("INDEX", "KEY"):
                op.operation_class = OperationClass.DROP_INDEX
                op.target_index = action.this.name if action.this else None
            elif kind in ("CONSTRAINT", "PRIMARY"):
                op.operation_class = OperationClass.DROP_CONSTRAINT
            else:
                op.operation_class = OperationClass.UNKNOWN

        elif isinstance(action, exp.AlterColumn):
            op.operation_class = OperationClass.ALTER_COLUMN
            op.target_column = action.this.name if action.this else None

        elif isinstance(action, exp.RenameColumn):
            op.operation_class = OperationClass.RENAME_COLUMN
            op.target_column = action.this.name if action.this else None

        elif isinstance(action, exp.AddConstraint):
            constraint = action.find(exp.ForeignKey)
            if constraint:
                op.operation_class = OperationClass.ADD_FOREIGN_KEY
            else:
                op.operation_class = OperationClass.ADD_CONSTRAINT

        else:
            op.operation_class = OperationClass.UNKNOWN

        ops.append(op)

    if not ops:
        # Fallback: emit single UNKNOWN op for the whole ALTER
        ops.append(DDLOperation(
            operation_class=OperationClass.UNKNOWN,
            target_table=table_name,
            raw_sql=raw_sql.strip(),
            dialect=dialect,
        ))

    return ops


def _parse_create(stmt: exp.Create, raw_sql: str, dialect: str) -> list[DDLOperation]:
    """Parse CREATE TABLE / CREATE INDEX / CREATE VIEW."""
    kind = (stmt.args.get("kind") or "").upper()
    op = DDLOperation(raw_sql=raw_sql.strip(), dialect=dialect)

    if kind == "TABLE":
        op.operation_class = OperationClass.CREATE_TABLE
        op.target_table = stmt.this.name if stmt.this else ""

    elif kind == "INDEX":
        op.operation_class = OperationClass.CREATE_INDEX
        # index name is stmt.this; table is in stmt.args["this"].args["table"]
        idx = stmt.this
        op.target_index = idx.name if idx else None
        table_node = stmt.find(exp.Table)
        op.target_table = table_node.name if table_node else ""

        # Check CONCURRENTLY flag
        if stmt.args.get("concurrently"):
            op.notes.append("CONCURRENTLY flag detected — no table lock in PostgreSQL.")
        else:
            op.notes.append("No CONCURRENTLY — will acquire ShareLock and block writes in MySQL.")

    elif kind == "VIEW":
        op.operation_class = OperationClass.CREATE_VIEW
        op.target_table = stmt.this.name if stmt.this else ""

    else:
        op.operation_class = OperationClass.UNKNOWN
        op.target_table = stmt.this.name if stmt.this else ""

    return [op]


def _parse_drop(stmt: exp.Drop, raw_sql: str, dialect: str) -> list[DDLOperation]:
    """Parse DROP TABLE / DROP INDEX / DROP VIEW."""
    kind = (stmt.args.get("kind") or "").upper()
    op = DDLOperation(raw_sql=raw_sql.strip(), dialect=dialect)

    if kind == "TABLE":
        op.operation_class = OperationClass.DROP_TABLE
        op.target_table = stmt.this.name if stmt.this else ""
        op.notes.append("DROP TABLE is irreversible without a backup.")

    elif kind in ("INDEX", "KEY"):
        op.operation_class = OperationClass.DROP_INDEX
        op.target_index = stmt.this.name if stmt.this else None
        op.target_table = _extract_table_name(stmt)

    elif kind == "VIEW":
        op.operation_class = OperationClass.DROP_VIEW
        op.target_table = stmt.this.name if stmt.this else ""

    else:
        op.operation_class = OperationClass.UNKNOWN
        op.target_table = stmt.this.name if stmt.this else ""

    return [op]


def parse_migration(
    sql_text: str,
    dialect: str = "postgres",
    filepath: Optional[str] = None,
) -> list[DDLOperation]:
    """
    Parse a SQL migration string into a list of DDLOperation objects.

    Args:
        sql_text: Raw SQL text of the migration file.
        dialect: SQL dialect hint (postgres, mysql, sqlite, tsql).
        filepath: Optional file path for dialect inference.

    Returns:
        List of DDLOperation instances, one per DDL statement found.
    """
    if filepath:
        dialect = _infer_dialect(filepath)

    operations: list[DDLOperation] = []

    try:
        statements = sqlglot.parse(sql_text, dialect=dialect, error_level=sqlglot.ErrorLevel.WARN)
    except Exception:
        # Fallback: try without dialect
        try:
            statements = sqlglot.parse(sql_text, error_level=sqlglot.ErrorLevel.WARN)
        except Exception:
            statements = []

    for stmt in statements:
        if stmt is None:
            continue

        raw_sql = stmt.sql(dialect=dialect)

        if isinstance(stmt, exp.AlterTable):
            operations.extend(_parse_alter_table(stmt, raw_sql, dialect))

        elif isinstance(stmt, exp.Create):
            operations.extend(_parse_create(stmt, raw_sql, dialect))

        elif isinstance(stmt, exp.Drop):
            operations.extend(_parse_drop(stmt, raw_sql, dialect))

        elif isinstance(stmt, exp.TruncateTable):
            table_node = stmt.find(exp.Table)
            table_name = table_node.name if table_node else ""
            operations.append(DDLOperation(
                operation_class=OperationClass.TRUNCATE_TABLE,
                target_table=table_name,
                raw_sql=raw_sql.strip(),
                dialect=dialect,
                notes=["TRUNCATE is irreversible — all rows permanently deleted."],
            ))

        # Skip DML (INSERT/UPDATE/DELETE) and DCL (GRANT/REVOKE) silently

    return operations


def parse_migration_file(filepath: str | Path) -> list[DDLOperation]:
    """Convenience wrapper that reads a file then calls parse_migration."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Migration file not found: {filepath}")

    sql_text = path.read_text(encoding="utf-8")
    dialect = _infer_dialect(str(filepath))
    return parse_migration(sql_text, dialect=dialect, filepath=str(filepath))
