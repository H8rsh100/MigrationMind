"""Stage 7 orchestrator: runs all stages in sequence.

AnalysisContext is the shared object passed between stages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from migrationmind.llm.client import LLMClient
from migrationmind.llm.reasoner import run_llm_reasoning
from migrationmind.models.operation import DDLOperation
from migrationmind.models.report import RiskReport, RollbackResult
from migrationmind.models.schema import SchemaSnapshot
from migrationmind.stages.lock_engine import apply_lock_analysis
from migrationmind.stages.parser import parse_migration_file
from migrationmind.stages.query_impact import analyze_query_impact, parse_query_log_file
from migrationmind.stages.rollback_analyzer import analyze_rollback
from migrationmind.stages.schema_diff import build_schema_diff, load_schema_from_file


@dataclass
class AnalysisContext:
    """Shared context passed between pipeline stages."""

    migration_file: str
    schema_file: Optional[str] = None
    query_log_file: Optional[str] = None
    dialect: str = "postgresql"
    db_version: int = 14
    no_llm: bool = False
    llm_model: str = "gpt-4o"
    llm_api_key: Optional[str] = None

    # Populated by stages
    operations: list[DDLOperation] = field(default_factory=list)
    before_schema: Optional[SchemaSnapshot] = None
    report: Optional[RiskReport] = None


def run_pipeline(ctx: AnalysisContext) -> RiskReport:
    """
    Execute all analysis stages in sequence.

    Stages:
        1. Parse migration file → DDLOperation list
        2. Load schema + build diff
        3. Lock & downtime analysis
        4. Rollback analysis
        5. Query impact analysis
        6. LLM reasoning (optional)
        7. Assemble RiskReport

    Returns the final RiskReport.
    """

    # ── Stage 1: Parse ────────────────────────────────────────────────
    ctx.operations = parse_migration_file(ctx.migration_file)

    # ── Stage 2: Schema diff ──────────────────────────────────────────
    if ctx.schema_file:
        ctx.before_schema = load_schema_from_file(ctx.schema_file, dialect=ctx.dialect)
        diff = build_schema_diff(ctx.before_schema, ctx.operations)
    else:
        from migrationmind.models.diff import SchemaDiff
        diff = SchemaDiff()

    # ── Stage 3 & 4: Lock engine + rollback ───────────────────────────
    apply_lock_analysis(ctx.operations, db_version=ctx.db_version)
    rollback_result: RollbackResult = analyze_rollback(ctx.operations)

    # ── Stage 5: Query impact ─────────────────────────────────────────
    query_impacts = []
    if ctx.query_log_file:
        queries = parse_query_log_file(ctx.query_log_file)
        query_impacts = analyze_query_impact(
            queries,
            diff,
            before_schema=ctx.before_schema,
            dialect=ctx.dialect,
        )

    # ── Stage 6 & 7: Assemble report ─────────────────────────────────
    report = RiskReport(
        migration_file=Path(ctx.migration_file).name,
        schema_file=ctx.schema_file,
        query_log_file=ctx.query_log_file,
        dialect=ctx.dialect,
        db_version=ctx.db_version,
        operations=ctx.operations,
        query_impacts=query_impacts,
        rollback=rollback_result,
    )

    # ── Stage 6: LLM reasoning ────────────────────────────────────────
    if not ctx.no_llm:
        llm_client = LLMClient(
            model=ctx.llm_model,
            api_key=ctx.llm_api_key,
        )
        report = run_llm_reasoning(report, llm_client)

    ctx.report = report
    return report
