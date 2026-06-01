"""Markdown reporter — formats risk reports for GitHub PR comments."""

from __future__ import annotations

from pathlib import Path

from migrationmind.models.operation import RiskLevel, RollbackComplexity
from migrationmind.models.report import RiskReport

_RISK_EMOJI: dict[RiskLevel, str] = {
    RiskLevel.SAFE: "✅",
    RiskLevel.LOW: "🟢",
    RiskLevel.MEDIUM: "🟡",
    RiskLevel.HIGH: "🔴",
    RiskLevel.CRITICAL: "🚨",
}

_ROLLBACK_EMOJI: dict[RollbackComplexity, str] = {
    RollbackComplexity.SAFE: "✅",
    RollbackComplexity.MANUAL: "⚠️",
    RollbackComplexity.COMPLEX: "🔧",
    RollbackComplexity.NONE: "🚫",
}


def render_markdown(report: RiskReport) -> str:
    """Render a RiskReport as a GitHub-flavored Markdown string."""
    lines: list[str] = []

    overall_emoji = _RISK_EMOJI.get(report.overall_risk_level, "❓")

    # ── Header ─────────────────────────────────────────────────────────
    lines.append(f"## 🧠 MigrationMind Risk Report — `{report.migration_file}`")
    lines.append("")
    lines.append(
        f"**Risk Score:** {overall_emoji} **{report.overall_risk_level.value.upper()}** "
        f"({report.overall_risk_score}/100)  |  "
        f"**Dialect:** {report.dialect} {report.db_version}  |  "
        f"**Operations:** {len(report.operations)}"
    )
    lines.append("")

    # ── Operations ─────────────────────────────────────────────────────
    lines.append("### Operations Detected")
    lines.append("")

    for op in report.operations:
        emoji = _RISK_EMOJI.get(op.risk_level, "❓")
        rb_emoji = _ROLLBACK_EMOJI.get(op.rollback_complexity, "❓")

        col_part = f".`{op.target_column}`" if op.target_column else ""
        lines.append(
            f"<details><summary>{emoji} **{op.operation_class.value}** on "
            f"`{op.target_table}`{col_part} — {op.risk_level.value.upper()}</summary>"
        )
        lines.append("")
        lines.append(f"**Lock type:** `{op.lock_type.value}`")

        if op.estimated_duration_min is not None and op.estimated_duration_max is not None:
            if op.estimated_duration_max < 0.1:
                dur = "instant (<1 second)"
            else:
                dur = f"{op.estimated_duration_min:.1f}–{op.estimated_duration_max:.1f} minutes"
            lines.append(f"  \n**Estimated duration:** {dur}")

        lines.append(f"  \n**Rollback:** {rb_emoji} `{op.rollback_complexity.value.upper()}`")
        if op.rollback_description:
            lines.append(f" — {op.rollback_description}")

        if op.notes:
            lines.append("")
            lines.append("**Notes:**")
            for note in op.notes:
                lines.append(f"- {note}")

        if op.safe_rewrite:
            lines.append("")
            lines.append("**💡 Suggested safe rewrite:**")
            lines.append("```sql")
            lines.append(op.safe_rewrite[:800])
            lines.append("```")

        lines.append("")
        lines.append("</details>")
        lines.append("")

    # ── Query Impacts ──────────────────────────────────────────────────
    if report.query_impacts:
        lines.append(f"### ⚡ Affected Queries ({len(report.query_impacts)})")
        lines.append("")
        lines.append("| Severity | Impact Type | Affected Table | Description |")
        lines.append("|----------|-------------|----------------|-------------|")
        for qi in report.query_impacts:
            sev_emoji = _RISK_EMOJI.get(qi.severity, "❓")
            lines.append(
                f"| {sev_emoji} {qi.severity.value.upper()} "
                f"| `{qi.impact_type}` "
                f"| `{qi.affected_table}` "
                f"| {qi.description[:120]} |"
            )
        lines.append("")

    # ── Rollback Summary ───────────────────────────────────────────────
    rb_emoji = _ROLLBACK_EMOJI.get(report.rollback.complexity, "❓")
    lines.append(f"### Rollback Complexity: {rb_emoji} {report.rollback.complexity.value.upper()}")
    if report.rollback.estimated_minutes:
        lines.append(f"- Estimated rollback window: **~{report.rollback.estimated_minutes} minutes**")
    if report.rollback.data_loss_risk:
        lines.append("- 🚨 **DATA LOSS RISK** — ensure you have a verified backup before running this migration")
    if report.rollback.notes:
        lines.append(f"- {report.rollback.notes}")
    lines.append("")

    # ── AI Summary ────────────────────────────────────────────────────
    if report.plain_english_summary and not report.plain_english_summary.startswith("[LLM"):
        lines.append("<details><summary>🤖 AI Risk Analysis (click to expand)</summary>")
        lines.append("")
        lines.append(report.plain_english_summary)
        lines.append("")
        lines.append("</details>")
        lines.append("")

    if report.stakeholder_summary:
        lines.append("<details><summary>📊 Stakeholder Summary</summary>")
        lines.append("")
        lines.append(report.stakeholder_summary)
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # ── Footer ─────────────────────────────────────────────────────────
    lines.append(
        f"---\n*Generated by [MigrationMind](https://github.com/H8rsh100/MigrationMind) "
        f"• {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}*"
    )

    return "\n".join(lines)


def save_markdown(report: RiskReport, output_path: str | Path) -> Path:
    """Write the markdown report to a file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")
    return path
