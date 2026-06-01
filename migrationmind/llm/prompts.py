"""LLM prompt templates for MigrationMind."""

from __future__ import annotations

RISK_SUMMARY_PROMPT = """\
You are an expert database reliability engineer reviewing a database migration.

Below is a structured JSON analysis of all DDL operations detected in the migration,
including lock types, risk levels, affected queries, and rollback complexity.

Your task:
1. Write a plain English risk summary (3-5 paragraphs) aimed at a senior engineer.
2. Be specific — mention table names, operation types, lock durations, and query impacts.
3. Call out the most dangerous operations first.
4. End with a clear recommendation: PROCEED, PROCEED WITH CAUTION, or DO NOT PROCEED.

Analysis JSON:
{analysis_json}

Write the risk summary now:
"""

REWRITE_SUGGESTION_PROMPT = """\
You are an expert database migration engineer.

The following DDL operation has been flagged as HIGH or CRITICAL risk:

Operation: {operation_class}
Table: {target_table}
Column: {target_column}
Raw SQL:
{raw_sql}

Risk reason: {risk_reason}

Your task:
1. Propose a safer migration strategy that achieves the same outcome with less lock time or risk.
2. Write the safer SQL migration steps in sequence.
3. Explain WHY your rewrite is safer.
4. Keep the rewrite practical and production-ready.

Provide the safe migration rewrite:
"""

STAKEHOLDER_REPORT_PROMPT = """\
You are a technical writer summarizing a database migration risk report for a non-technical audience
(product managers, executives, or stakeholders who are not engineers).

Here is the technical analysis:
{technical_summary}

Your task:
1. Write a SHORT (2-3 paragraph) plain-English summary.
2. Avoid jargon. Use analogies if helpful.
3. Clearly state: Is this migration safe? What is the business risk? What should the team do?
4. Be reassuring if the risk is low. Be direct if the risk is high.

Write the stakeholder summary:
"""

EDGE_CASE_PROMPT = """\
You are an expert PostgreSQL/MySQL DBA reviewing a migration analysis.

The rule-based analysis has produced the following findings:
{rule_based_findings}

Your task:
1. Identify any edge cases, gotchas, or risks that the rule engine may have MISSED.
2. Consider: implicit behavior differences between DB versions, transaction semantics,
   replication lag impacts, connection pool behavior during long locks, and any
   dialect-specific quirks.
3. List each edge case with a severity (LOW/MEDIUM/HIGH) and mitigation suggestion.

List any additional edge cases:
"""
