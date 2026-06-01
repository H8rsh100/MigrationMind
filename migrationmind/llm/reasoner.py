"""Stage 6: LLM reasoning layer.

Takes the structured analysis output and calls the LLM to produce:
- Plain English risk summary
- Stakeholder-friendly report
- Safe migration rewrite suggestions
- Edge case detection
"""

from __future__ import annotations

import json
from typing import Optional

from migrationmind.llm.client import LLMClient
from migrationmind.llm.prompts import (
    EDGE_CASE_PROMPT,
    REWRITE_SUGGESTION_PROMPT,
    RISK_SUMMARY_PROMPT,
    STAKEHOLDER_REPORT_PROMPT,
)
from migrationmind.models.operation import RiskLevel
from migrationmind.models.report import RiskReport


def run_llm_reasoning(
    report: RiskReport,
    client: LLMClient,
) -> RiskReport:
    """
    Enrich a RiskReport with LLM-generated summaries and rewrites.

    Modifies the report in-place and returns it.
    """

    # Build compact analysis JSON for the prompt
    analysis = {
        "migration_file": report.migration_file,
        "dialect": report.dialect,
        "db_version": report.db_version,
        "overall_risk_score": report.overall_risk_score,
        "overall_risk_level": report.overall_risk_level.value,
        "operations": [
            {
                "operation": op.operation_class.value,
                "table": op.target_table,
                "column": op.target_column,
                "risk_level": op.risk_level.value,
                "lock_type": op.lock_type.value,
                "duration_min_minutes": op.estimated_duration_min,
                "duration_max_minutes": op.estimated_duration_max,
                "rollback_complexity": op.rollback_complexity.value,
                "rollback_description": op.rollback_description,
                "notes": op.notes,
                "affected_queries": op.affected_queries,
            }
            for op in report.operations
        ],
        "query_impacts": [
            {
                "query": qi.query,
                "impact_type": qi.impact_type,
                "severity": qi.severity.value,
                "description": qi.description,
            }
            for qi in report.query_impacts
        ],
        "rollback": {
            "complexity": report.rollback.complexity.value,
            "estimated_minutes": report.rollback.estimated_minutes,
            "data_loss_risk": report.rollback.data_loss_risk,
            "notes": report.rollback.notes,
        },
    }

    analysis_json = json.dumps(analysis, indent=2)

    # Stage 6a: Plain English risk summary
    summary_prompt = RISK_SUMMARY_PROMPT.format(analysis_json=analysis_json)
    report.plain_english_summary = client.complete(summary_prompt)

    # Stage 6b: Stakeholder summary
    if report.plain_english_summary and not report.plain_english_summary.startswith("[LLM"):
        stakeholder_prompt = STAKEHOLDER_REPORT_PROMPT.format(
            technical_summary=report.plain_english_summary
        )
        report.stakeholder_summary = client.complete(stakeholder_prompt)

    # Stage 6c: Safe rewrite suggestions for high-risk ops
    rewrite_sqls: list[str] = []
    for op in report.operations:
        if op.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            risk_reason = "; ".join(op.notes[:2]) if op.notes else op.risk_level.value
            rewrite_prompt = REWRITE_SUGGESTION_PROMPT.format(
                operation_class=op.operation_class.value,
                target_table=op.target_table,
                target_column=op.target_column or "N/A",
                raw_sql=op.raw_sql[:500],
                risk_reason=risk_reason,
            )
            rewrite = client.complete(rewrite_prompt)
            if rewrite and not rewrite.startswith("[LLM"):
                op.safe_rewrite = rewrite
                rewrite_sqls.append(f"-- Rewrite for: {op.operation_class.value} on {op.target_table}\n{rewrite}")

    if rewrite_sqls:
        report.safe_rewrite_sql = "\n\n".join(rewrite_sqls)

    # Stage 6d: Edge case detection
    rule_findings = json.dumps(
        {
            "operations": [
                {"op": op.operation_class.value, "table": op.target_table, "notes": op.notes}
                for op in report.operations
            ]
        },
        indent=2,
    )
    edge_prompt = EDGE_CASE_PROMPT.format(rule_based_findings=rule_findings)
    edge_cases = client.complete(edge_prompt)
    if edge_cases and not edge_cases.startswith("[LLM"):
        # Append to the plain english summary
        if report.plain_english_summary:
            report.plain_english_summary += f"\n\n## Additional Edge Cases\n{edge_cases}"

    return report
