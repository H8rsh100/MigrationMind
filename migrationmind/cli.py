"""MigrationMind CLI — built with Typer.

Commands:
  migrationmind analyze   — run full analysis pipeline
  migrationmind init      — scaffold a config file
  migrationmind history   — show past analysis runs
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm

from migrationmind import __version__
from migrationmind.config import settings
from migrationmind.models.config import OutputFormat, SQLDialect
from migrationmind.reporters.json_reporter import render_json, save_json
from migrationmind.reporters.markdown import render_markdown, save_markdown
from migrationmind.reporters.terminal import print_report
from migrationmind.stages.pipeline import AnalysisContext, run_pipeline

app = typer.Typer(
    name="migrationmind",
    help="🧠 AI-powered database migration risk analyzer.",
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"MigrationMind v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", callback=version_callback, is_eager=True,
        help="Show version and exit."
    ),
) -> None:
    """🧠 MigrationMind — AI-powered database migration risk analyzer."""


# ─────────────────────────────────────────────────────────────────────────────
# analyze command
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def analyze(
    migration: str = typer.Option(
        ..., "--migration", "-m",
        help="Path to the migration SQL file to analyze.",
    ),
    schema: Optional[str] = typer.Option(
        None, "--schema", "-s",
        help="Path to the current schema dump SQL file.",
    ),
    queries: Optional[str] = typer.Option(
        None, "--queries", "-q",
        help="Path to a slow query log or query pattern file.",
    ),
    dialect: SQLDialect = typer.Option(
        SQLDialect.POSTGRESQL, "--dialect", "-d",
        help="SQL dialect: postgresql, mysql, sqlite, mssql.",
    ),
    db_version: int = typer.Option(
        14, "--db-version",
        help="Database major version (e.g. 14 for PostgreSQL 14).",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.TERMINAL, "--output", "-o",
        help="Output format: terminal, json, markdown.",
    ),
    output_file: Optional[str] = typer.Option(
        None, "--output-file", "-f",
        help="Write output to this file (required for json/markdown).",
    ),
    no_llm: bool = typer.Option(
        False, "--no-llm",
        help="Skip LLM reasoning stage (faster, no API key required).",
    ),
    model: str = typer.Option(
        settings.litellm_model, "--model",
        help="LiteLLM model name (e.g. gpt-4o, claude-3-5-sonnet, gemini/gemini-2.0-flash).",
    ),
) -> None:
    """
    [bold]Analyze a database migration for risk.[/bold]

    Runs a multi-stage analysis pipeline:
    Parse → Schema Diff → Lock Engine → Rollback → Query Impact → LLM → Report
    """
    # Validate inputs
    migration_path = Path(migration)
    if not migration_path.exists():
        console.print(f"[bold red]Error:[/bold red] Migration file not found: {migration}")
        raise typer.Exit(1)

    if schema and not Path(schema).exists():
        console.print(f"[bold red]Error:[/bold red] Schema file not found: {schema}")
        raise typer.Exit(1)

    if queries and not Path(queries).exists():
        console.print(f"[bold yellow]Warning:[/bold yellow] Query log not found: {queries} — skipping query analysis.")
        queries = None

    # Show what we're about to do
    console.print(f"\n[bold cyan]🧠 MigrationMind[/bold cyan] [dim]v{__version__}[/dim]")
    console.print(f"  Migration: [cyan]{migration}[/cyan]")
    if schema:
        console.print(f"  Schema:    [cyan]{schema}[/cyan]")
    if queries:
        console.print(f"  Queries:   [cyan]{queries}[/cyan]")
    console.print(f"  Dialect:   [cyan]{dialect.value} {db_version}[/cyan]")
    console.print(f"  LLM:       [cyan]{'disabled' if no_llm else model}[/cyan]")
    console.print()

    # Run pipeline
    with console.status("[bold green]Analyzing migration…[/bold green]", spinner="dots"):
        ctx = AnalysisContext(
            migration_file=migration,
            schema_file=schema,
            query_log_file=queries,
            dialect=dialect.value,
            db_version=db_version,
            no_llm=no_llm or settings.no_llm,
            llm_model=model,
            llm_api_key=settings.openai_api_key or None,
        )
        report = run_pipeline(ctx)

    # Render output
    if output == OutputFormat.TERMINAL:
        print_report(report, console=console)

    elif output == OutputFormat.JSON:
        json_str = render_json(report)
        if output_file:
            path = save_json(report, output_file)
            console.print(f"[green]✓[/green] JSON report saved to: [cyan]{path}[/cyan]")
        else:
            typer.echo(json_str)

    elif output == OutputFormat.MARKDOWN:
        md_str = render_markdown(report)
        if output_file:
            path = save_markdown(report, output_file)
            console.print(f"[green]✓[/green] Markdown report saved to: [cyan]{path}[/cyan]")
        else:
            typer.echo(md_str)

    # Exit with non-zero code if HIGH or CRITICAL risk (for CI/CD)
    if report.overall_risk_level.value in ("high", "critical"):
        raise typer.Exit(2)


# ─────────────────────────────────────────────────────────────────────────────
# init command
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing config."),
) -> None:
    """Scaffold a [bold].env[/bold] config file in the current directory."""
    env_path = Path.cwd() / ".env"
    if env_path.exists() and not force:
        if not Confirm.ask(f"[yellow]{env_path}[/yellow] already exists. Overwrite?"):
            raise typer.Exit()

    template = Path(__file__).parent.parent / ".env.example"
    if template.exists():
        env_path.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        env_path.write_text(
            "LITELLM_MODEL=gpt-4o\nOPENAI_API_KEY=sk-...\nMIGRATIONMIND_DIALECT=postgresql\n",
            encoding="utf-8",
        )

    console.print(f"[green]✓[/green] Created {env_path}")
    console.print("[dim]Edit it to set your LLM API key and database dialect.[/dim]")


# ─────────────────────────────────────────────────────────────────────────────
# history command
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def history() -> None:
    """Show past analysis runs stored in the local SQLite database."""
    console.print("[dim]History tracking coming soon in v0.2.[/dim]")
    console.print(
        f"[dim]Database path: {settings.db_path}[/dim]"
    )


if __name__ == "__main__":
    app()
