"""Application configuration — reads from .env and environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from cwd or home dir
load_dotenv(Path.cwd() / ".env")
load_dotenv(Path.home() / ".migrationmind" / ".env")


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


class Settings:
    """Lazy-loaded settings from environment / .env."""

    @property
    def litellm_model(self) -> str:
        return get("LITELLM_MODEL", "gpt-4o")

    @property
    def openai_api_key(self) -> str:
        return get("OPENAI_API_KEY", "")

    @property
    def anthropic_api_key(self) -> str:
        return get("ANTHROPIC_API_KEY", "")

    @property
    def google_api_key(self) -> str:
        return get("GOOGLE_API_KEY", "")

    @property
    def default_dialect(self) -> str:
        return get("MIGRATIONMIND_DIALECT", "postgresql")

    @property
    def default_db_version(self) -> int:
        return int(get("MIGRATIONMIND_DB_VERSION", "14"))

    @property
    def default_output(self) -> str:
        return get("MIGRATIONMIND_OUTPUT", "terminal")

    @property
    def db_path(self) -> str:
        return get("MIGRATIONMIND_DB_PATH", str(Path.home() / ".migrationmind" / "history.db"))

    @property
    def max_tokens(self) -> int:
        return int(get("MIGRATIONMIND_MAX_TOKENS", "4096"))

    @property
    def no_llm(self) -> bool:
        return get("MIGRATIONMIND_NO_LLM", "false").lower() == "true"


settings = Settings()
