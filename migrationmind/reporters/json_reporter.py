"""JSON reporter — outputs structured JSON for CI/CD pipeline integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from migrationmind.models.report import RiskReport


def render_json(report: RiskReport, indent: int = 2) -> str:
    """Serialize the full RiskReport to a JSON string."""
    return json.dumps(report.to_dict(), indent=indent, default=str)


def save_json(report: RiskReport, output_path: str | Path, indent: int = 2) -> Path:
    """Write the JSON report to a file and return the path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_json(report, indent=indent), encoding="utf-8")
    return path
