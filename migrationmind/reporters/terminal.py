"""Stage 7: Rich-based terminal reporter.

Produces a colorful, formatted terminal output for the risk report.
"""

from __future__ import annotations

from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import print as rprint

from migrationmind.models.operation import RiskLevel, RollbackComplexity
from migrationmind.models.report import RiskReport

console = Console()


# Risk level → (color, symbol)
_RISK_STYLE: dict[RiskLevel, tuple[str, str]] = {
    RiskLevel.SAFE: ("bright_green", "✓"),
    RiskLevel.LOW: ("green", "✓"),
    RiskLevel.MEDIUM: ("yellow", "⚠"),
    RiskLevel.HIGH: ("red", "✗"),
    RiskLevel.CRITICAL: ("bold red", "✗✗"),
}

_ROLLBACK_STYLE: dict[RollbackComplexity, str] = {
    RollbackComplexity.SAFE: "green",
    RollbackComplexity.MANUAL: "yellow",
    RollbackComplexity.COMPLEX: "dark_orange",
    RollbackComplexity.NONE: "bold red",
}


def _risk_badge(level: RiskLevel) -> Text:
    color, symbol = _RISK_STYLE.get(level, ("white", "?"))
    return Text(f" {symbol} {level.value.upper()} ", style=f"bold {color}")


def _score_bar(score: int) -> str:
    """ASCII progress bar for risk score."""
    filled = score // 5
    empty = 20 - filled
    bar = "█" * filled + "░" * empty
    return f"[{bar}] {score}/100"


def print_report(report: RiskReport, console: Optional[Console] = None) -> None:
    """Print a full risk report to the terminal using Rich."""
    con = console or Console()

    # ── Header ─────────────────────────────────────────────────────────
    overall_level = report.overall_risk_level
    overall_color, _ = _RISK_STYLE.get(overall_level, ("white", "?"))

    header = Table.grid(padding=(0, 1))
    header.add_column(style="bold white")
    header.add_column()
    header.add_row(
        "🧠 MigrationMind Risk Report",
        Text(f"— {report.migration_file}", style="dim white"),
    )

    con.print()
    con.print(Panel(header, style=f"bold {overall_color}", box=box.DOUBLE_EDGE))

    # ── Overall score ──────────────────────────────────────────────────
    score_text = Text()
    score_text.append("Risk Score: ", style="bold white")
    score_text.append(f"{overall_level.value.upper()} ", style=f"bold {overall_color}")
    score_text.append(_score_bar(report.overall_risk_score), style=overall_color)

    con.print(score_text)
    con.print(
        f"  Dialect: [cyan]{report.dialect}[/cyan]  |  "
        f"DB Version: [cyan]{report.db_version}[/cyan]  |  "
        f"Operations: [cyan]{len(report.operations)}[/cyan]"
    )
    con.print()

    # ── Operations table ───────────────────────────────────────────────
    con.print("[bold white]Operations Detected[/bold white]")
    con.print("─" * 80)

    for op in report.operations:
        risk_color, symbol = _RISK_STYLE.get(op.risk_level, ("white", "?"))

        # Operation header line
        op_label = op.target_column or op.target_index or op.target_table
        con.print(
            f"  [{risk_color}]{symbol}[/{risk_color}] "
            f"[bold]{op.operation_class.value}[/bold] "
            f"on [cyan]{op.target_table}[/cyan]"
            + (f".[yellow]{op.target_column}[/yellow]" if op.target_column else "")
        )

        # Lock type & duration
        lock_info = f"Lock: [magenta]{op.lock_type.value}[/magenta]"
        if op.estimated_duration_min is not None and op.estimated_duration_max is not None:
            if op.estimated_duration_max < 0.1:
                dur = "instant (<1s)"
            else:
                dur = f"{op.estimated_duration_min:.1f}–{op.estimated_duration_max:.1f} min"
            lock_info += f"  |  Est. duration: [bold {risk_color}]{dur}[/bold {risk_color}]"
        con.print(f"     {lock_info}")

        # Rollback
        rb_color = _ROLLBACK_STYLE.get(op.rollback_complexity, "white")
        con.print(
            f"     Rollback: [{rb_color}]{op.rollback_complexity.value.upper()}[/{rb_color}]"
            + (f" — {op.rollback_description}" if op.rollback_description else "")
        )

        # Notes
        for note in op.notes[:3]:
            con.print(f"     [dim]→ {note}[/dim]")

        # Affected queries
        if op.affected_queries:
            con.print(f"     [yellow]⚡ {len(op.affected_queries)} affected queries[/yellow]")

        con.print()

    # ── Query impacts ──────────────────────────────────────────────────
    if report.query_impacts:
        con.print(f"[bold white]Affected Queries ({len(report.query_impacts)})[/bold white]")
        con.print("─" * 80)
        for qi in report.query_impacts:
            sev_color, _ = _RISK_STYLE.get(qi.severity, ("white", "?"))
            con.print(
                f"  [{sev_color}]→[/{sev_color}] "
                f"[dim]{qi.query[:100]}{'...' if len(qi.query) > 100 else ''}[/dim]"
            )
            con.print(f"     [italic]{qi.description}[/italic]")
        con.print()

    # ── Rollback summary ───────────────────────────────────────────────
    rb_color = _ROLLBACK_STYLE.get(report.rollback.complexity, "white")
    con.print(f"[bold white]Rollback Complexity: [{rb_color}]{report.rollback.complexity.value.upper()}[/{rb_color}][/bold white]")
    if report.rollback.estimated_minutes:
        con.print(f"  Estimated rollback window: [cyan]~{report.rollback.estimated_minutes} min[/cyan]")
    if report.rollback.data_loss_risk:
        con.print("  [bold red]⚠  DATA LOSS RISK — ensure backup before proceeding[/bold red]")
    if report.rollback.notes:
        con.print(f"  [dim]{report.rollback.notes}[/dim]")
    con.print()

    # ── LLM Summary ───────────────────────────────────────────────────
    if report.plain_english_summary and not report.plain_english_summary.startswith("[LLM"):
        con.print(Panel(
            report.plain_english_summary,
            title="[bold cyan]AI Risk Analysis[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        ))
        con.print()

    # ── Safe rewrite ───────────────────────────────────────────────────
    if report.safe_rewrite_sql:
        con.print(Panel(
            f"[green]{report.safe_rewrite_sql[:1000]}[/green]",
            title="[bold green]Suggested Safe Rewrite[/bold green]",
            border_style="green",
            box=box.ROUNDED,
        ))
        con.print()

    # ── Footer ─────────────────────────────────────────────────────────
    con.print(f"[dim]Generated by MigrationMind • {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}[/dim]")
    con.print()
