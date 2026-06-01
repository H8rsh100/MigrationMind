"""Stage 3: Query impact analysis.

Parses query log files and cross-matches queries against the schema diff
to identify which queries will fail or degrade after the migration runs.
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

from migrationmind.models.diff import SchemaDiff
from migrationmind.models.operation import DDLOperation, OperationClass, RiskLevel
from migrationmind.models.report import QueryImpact
from migrationmind.models.schema import SchemaSnapshot


# ---------------------------------------------------------------------------
# Query log parsers
# ---------------------------------------------------------------------------

# Postgres slow query log pattern (simplified)
_PG_QUERY_RE = re.compile(
    r"(?:LOG|STATEMENT|duration:.*?ms\s+statement:)\s+(SELECT|INSERT|UPDATE|DELETE|WITH).*",
    re.IGNORECASE | re.DOTALL,
)

# MySQL slow query log pattern
_MYSQL_QUERY_RE = re.compile(
    r"^(SELECT|INSERT|UPDATE|DELETE|WITH)\b.*?;",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)

# Generic: any line that looks like a SQL statement
_GENERIC_SQL_RE = re.compile(
    r"^\s*(SELECT|INSERT|UPDATE|DELETE|WITH)\b.*",
    re.IGNORECASE,
)


def parse_query_log(log_text: str) -> list[str]:
    """
    Extract individual SQL query strings from a slow query log.

    Supports Postgres and MySQL slow query log formats, plus raw SQL files.
    Returns a deduplicated list of query strings.
    """
    queries: list[str] = []

    # Try MySQL slow log format first (multi-line statements ending with ;)
    mysql_matches = _MYSQL_QUERY_RE.findall(log_text)
    if mysql_matches:
        # Full match extraction
        for m in re.finditer(
            r"(SELECT|INSERT|UPDATE|DELETE|WITH)\b.*?;",
            log_text,
            re.IGNORECASE | re.DOTALL,
        ):
            q = m.group(0).strip()
            if len(q) < 2000:  # skip absurdly long queries
                queries.append(q)
        if queries:
            return list(dict.fromkeys(queries))  # deduplicate, preserve order

    # Try Postgres log format
    for line in log_text.splitlines():
        m = _GENERIC_SQL_RE.match(line)
        if m:
            queries.append(line.strip())

    return list(dict.fromkeys(queries))


def parse_query_log_file(filepath: str | Path) -> list[str]:
    """Read a query log file and extract SQL queries."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Query log not found: {filepath}")
    return parse_query_log(path.read_text(encoding="utf-8", errors="ignore"))


# ---------------------------------------------------------------------------
# Query reference extractor
# ---------------------------------------------------------------------------

def _extract_references(query: str, dialect: str = "postgres") -> dict[str, set[str]]:
    """
    Extract table -> set of column references from a SQL query.

    Returns: {"table_name": {"col1", "col2", ...}, ...}
    """
    refs: dict[str, set[str]] = {}

    try:
        stmts = sqlglot.parse(query, dialect=dialect, error_level=sqlglot.ErrorLevel.WARN)
    except Exception:
        return refs

    for stmt in stmts:
        if stmt is None:
            continue

        # Collect all Column references
        for col_node in stmt.find_all(exp.Column):
            table_node = col_node.args.get("table")
            col_name = col_node.name
            table_name = table_node.name if table_node else ""

            if table_name:
                refs.setdefault(table_name, set()).add(col_name)
            elif col_name:
                # No explicit table qualifier — add to wildcard bucket
                refs.setdefault("*", set()).add(col_name)

        # Also capture unqualified table scans (FROM clause)
        for table_node in stmt.find_all(exp.Table):
            tname = table_node.name
            if tname:
                refs.setdefault(tname, set())

    return refs


# ---------------------------------------------------------------------------
# Impact analysis
# ---------------------------------------------------------------------------

def analyze_query_impact(
    queries: list[str],
    diff: SchemaDiff,
    before_schema: Optional[SchemaSnapshot] = None,
    dialect: str = "postgres",
) -> list[QueryImpact]:
    """
    Cross-match extracted query references against the schema diff.

    Returns a list of QueryImpact describing every query that will be
    broken or degraded by the migration.
    """
    impacts: list[QueryImpact] = []

    # Build lookup sets for fast matching
    removed_cols: dict[str, set[str]] = {}
    for cc in diff.removed_columns:
        removed_cols.setdefault(cc.table.lower(), set()).add(cc.column.lower())

    removed_indexes: dict[str, list] = {}
    for ic in diff.removed_indexes:
        removed_indexes.setdefault(ic.table.lower(), []).append(ic)

    renamed_cols: dict[str, set[str]] = {}
    for cc in diff.column_changes:
        if cc.change_type == "renamed":
            renamed_cols.setdefault(cc.table.lower(), set()).add(cc.column.lower())

    type_changed_cols: dict[str, set[str]] = {}
    for cc in diff.column_changes:
        if cc.change_type == "type_changed":
            type_changed_cols.setdefault(cc.table.lower(), set()).add(cc.column.lower())

    for query in queries:
        refs = _extract_references(query, dialect=dialect)

        for table, cols in refs.items():
            tl = table.lower()

            # Check column removal
            if tl in removed_cols:
                for col in cols:
                    if col.lower() in removed_cols[tl]:
                        impacts.append(QueryImpact(
                            query=query[:300],
                            impact_type="column_missing",
                            severity=RiskLevel.CRITICAL,
                            description=(
                                f"Column `{col}` on table `{table}` is being dropped. "
                                "This query will raise a column-not-found error."
                            ),
                            affected_table=table,
                            affected_column=col,
                        ))

            # Check renamed columns
            if tl in renamed_cols:
                for col in cols:
                    if col.lower() in renamed_cols[tl]:
                        impacts.append(QueryImpact(
                            query=query[:300],
                            impact_type="column_renamed",
                            severity=RiskLevel.HIGH,
                            description=(
                                f"Column `{col}` on `{table}` is being renamed. "
                                "This query will fail after migration."
                            ),
                            affected_table=table,
                            affected_column=col,
                        ))

            # Check type changes
            if tl in type_changed_cols:
                for col in cols:
                    if col.lower() in type_changed_cols[tl]:
                        impacts.append(QueryImpact(
                            query=query[:300],
                            impact_type="type_mismatch",
                            severity=RiskLevel.MEDIUM,
                            description=(
                                f"Column `{col}` on `{table}` has a type change. "
                                "Implicit cast may fail or cause data truncation."
                            ),
                            affected_table=table,
                            affected_column=col,
                        ))

            # Check index removal → performance impact
            if tl in removed_indexes:
                for idx_change in removed_indexes[tl]:
                    idx_cols = set(c.lower() for c in idx_change.columns)
                    if not idx_cols or cols.intersection(idx_cols) or not cols:
                        impacts.append(QueryImpact(
                            query=query[:300],
                            impact_type="index_missing",
                            severity=RiskLevel.MEDIUM,
                            description=(
                                f"Index `{idx_change.index_name}` on `{table}` is being dropped. "
                                "Queries using these columns may experience 10–200× slowdowns."
                            ),
                            affected_table=table,
                        ))

    return impacts
