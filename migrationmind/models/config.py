"""User configuration model."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class SQLDialect(str, Enum):
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SQLITE = "sqlite"
    MSSQL = "mssql"
    BIGQUERY = "bigquery"


class OutputFormat(str, Enum):
    TERMINAL = "terminal"
    JSON = "json"
    MARKDOWN = "markdown"


class UserConfig(BaseModel):
    """Runtime configuration for a MigrationMind analysis."""

    dialect: SQLDialect = SQLDialect.POSTGRESQL
    db_version: int = 14
    output_format: OutputFormat = OutputFormat.TERMINAL
    litellm_model: str = "gpt-4o"
    max_tokens: int = 4096
    no_llm: bool = False
    db_path: str = "~/.migrationmind/history.db"
    api_key: Optional[str] = None
