"""Stage 2: Schema diff engine.

Compares a before-snapshot (from schema dump) against DDL operations
to produce a SchemaDiff describing all changes.
Also includes a schema loader that parses a schema dump SQL into
a SchemaSnapshot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    import sqlglot
    import sqlglot.expressions as exp
except ImportError as e:  # pragma: no cover
    raise ImportError("sqlglot is required: pip install sqlglot") from e

from migrationmind.models.diff import ColumnChange, ConstraintChange, IndexChange, SchemaDiff, TableChange
from migrationmind.models.operation import DDLOperation, OperationClass
from migrationmind.models.schema import ColumnModel, ConstraintModel, IndexModel, SchemaSnapshot, TableModel


# ---------------------------------------------------------------------------
# Schema loader: parse a schema dump SQL into a SchemaSnapshot
# ---------------------------------------------------------------------------

def _col_type_str(col_def: exp.ColumnDef) -> str:
    dtype = col_def.args.get("kind")
    return dtype.sql() if dtype else "unknown"


def _col_nullable(col_def: exp.ColumnDef) -> bool:
    constraints = col_def.args.get("constraints", [])
    for c in constraints:
        if isinstance(c.kind, exp.NotNullColumnConstraint):
            return False
    return True


def _col_default(col_def: exp.ColumnDef) -> Optional[str]:
    constraints = col_def.args.get("constraints", [])
    for c in constraints:
        if isinstance(c.kind, exp.DefaultColumnConstraint):
            return c.kind.this.sql() if c.kind.this else None
    return None


def load_schema_from_sql(sql_text: str, dialect: str = "postgres") -> SchemaSnapshot:
    """Parse a schema dump SQL string into a SchemaSnapshot."""
    snapshot = SchemaSnapshot(dialect=dialect)

    try:
        stmts = sqlglot.parse(sql_text, dialect=dialect, error_level=sqlglot.ErrorLevel.WARN)
    except Exception:
        stmts = []

    for stmt in stmts:
        if stmt is None:
            continue

        if isinstance(stmt, exp.Create):
            kind = (stmt.args.get("kind") or "").upper()

            if kind == "TABLE":
                table_node = stmt.find(exp.Table)
                table_name = table_node.name if table_node else ""
                if not table_name:
                    continue

                table = TableModel(name=table_name)

                # Extract columns
                schema_node = stmt.this
                if hasattr(schema_node, "expressions"):
                    for expr in schema_node.expressions:
                        if isinstance(expr, exp.ColumnDef):
                            col = ColumnModel(
                                name=expr.name,
                                data_type=_col_type_str(expr),
                                nullable=_col_nullable(expr),
                                default=_col_default(expr),
                            )
                            table.columns[col.name] = col

                        elif isinstance(expr, exp.PrimaryKey):
                            pk_cols = [c.name for c in expr.find_all(exp.Column)]
                            for pk_col in pk_cols:
                                if pk_col in table.columns:
                                    table.columns[pk_col].is_primary_key = True

                        elif isinstance(expr, exp.ForeignKey):
                            fk_cols = [c.name for c in expr.find_all(exp.Column)]
                            ref = expr.args.get("reference")
                            if ref and fk_cols:
                                ref_table = ref.find(exp.Table)
                                ref_col = ref.find(exp.Column)
                                if ref_table and ref_col and fk_cols[0] in table.columns:
                                    table.columns[fk_cols[0]].references = (
                                        f"{ref_table.name}.{ref_col.name}"
                                    )

                snapshot.tables[table_name] = table

            elif kind == "INDEX":
                idx_name = stmt.this.name if stmt.this else ""
                table_node = stmt.find(exp.Table)
                table_name = table_node.name if table_node else ""
                cols = [c.name for c in stmt.find_all(exp.Column)]
                is_unique = bool(stmt.args.get("unique"))

                if table_name and idx_name:
                    idx = IndexModel(
                        name=idx_name,
                        table=table_name,
                        columns=cols,
                        is_unique=is_unique,
                        is_concurrent=bool(stmt.args.get("concurrently")),
                    )
                    if table_name in snapshot.tables:
                        snapshot.tables[table_name].indexes[idx_name] = idx

    return snapshot


def load_schema_from_file(filepath: str | Path, dialect: str = "postgres") -> SchemaSnapshot:
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Schema file not found: {filepath}")
    return load_schema_from_sql(path.read_text(encoding="utf-8"), dialect=dialect)


# ---------------------------------------------------------------------------
# Schema diff builder: apply DDL operations to snapshot and compute diff
# ---------------------------------------------------------------------------

def build_schema_diff(
    before: SchemaSnapshot,
    operations: list[DDLOperation],
) -> SchemaDiff:
    """
    Build a SchemaDiff by simulating the effect of DDL operations on the
    before-snapshot and recording every detected change.
    """
    diff = SchemaDiff()

    for op in operations:
        table = op.target_table
        col = op.target_column
        before_table = before.get_table(table)

        if op.operation_class == OperationClass.ADD_COLUMN:
            # Determine if breaking (NOT NULL without DEFAULT on existing table)
            breaking = False
            if before_table is not None and col:
                # Check op notes for the known danger marker
                has_danger = any("NOT NULL" in n for n in op.notes)
                breaking = has_danger

            diff.column_changes.append(ColumnChange(
                table=table,
                column=col or "",
                change_type="added",
                after=col,
                breaking=breaking,
            ))

        elif op.operation_class == OperationClass.DROP_COLUMN:
            if before_table and col and col in before_table.columns:
                col_model = before_table.columns[col]
                diff.column_changes.append(ColumnChange(
                    table=table,
                    column=col,
                    change_type="removed",
                    before=f"{col} {col_model.data_type}",
                    breaking=True,  # removing a column always breaking
                ))
            else:
                diff.column_changes.append(ColumnChange(
                    table=table,
                    column=col or "",
                    change_type="removed",
                    breaking=True,
                ))

        elif op.operation_class == OperationClass.ALTER_COLUMN:
            diff.column_changes.append(ColumnChange(
                table=table,
                column=col or "",
                change_type="type_changed",
                breaking=True,
            ))

        elif op.operation_class == OperationClass.RENAME_COLUMN:
            diff.column_changes.append(ColumnChange(
                table=table,
                column=col or "",
                change_type="renamed",
                breaking=True,
            ))

        elif op.operation_class == OperationClass.RENAME_TABLE:
            diff.table_changes.append(TableChange(table=table, change_type="renamed"))

        elif op.operation_class == OperationClass.CREATE_TABLE:
            diff.table_changes.append(TableChange(table=table, change_type="added"))

        elif op.operation_class in (OperationClass.DROP_TABLE, OperationClass.TRUNCATE_TABLE):
            diff.table_changes.append(TableChange(
                table=table,
                change_type="removed" if op.operation_class == OperationClass.DROP_TABLE else "truncated",
            ))

        elif op.operation_class == OperationClass.CREATE_INDEX:
            idx_name = op.target_index or f"idx_{table}_new"
            diff.index_changes.append(IndexChange(
                index_name=idx_name,
                table=table,
                change_type="added",
            ))

        elif op.operation_class == OperationClass.DROP_INDEX:
            idx_name = op.target_index or ""
            cols: list[str] = []
            if before_table and idx_name in before_table.indexes:
                cols = before_table.indexes[idx_name].columns
            diff.index_changes.append(IndexChange(
                index_name=idx_name,
                table=table,
                change_type="removed",
                columns=cols,
            ))

        elif op.operation_class in (OperationClass.ADD_CONSTRAINT, OperationClass.ADD_FOREIGN_KEY):
            diff.constraint_changes.append(ConstraintChange(
                constraint_name=f"fk_{table}",
                table=table,
                change_type="added",
                constraint_type="FOREIGN KEY"
                if op.operation_class == OperationClass.ADD_FOREIGN_KEY
                else "CONSTRAINT",
            ))

    return diff
