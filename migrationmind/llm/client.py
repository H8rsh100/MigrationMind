"""LiteLLM wrapper with retry logic and token management."""

from __future__ import annotations

import json
import os
import time
from typing import Optional

try:
    import litellm
    from litellm import completion
except ImportError:
    litellm = None  # type: ignore
    completion = None  # type: ignore


class LLMClient:
    """
    Thin wrapper around LiteLLM providing:
    - Configurable model selection
    - Automatic retry with exponential backoff
    - Token limit enforcement
    - Graceful degradation when LLM is unavailable
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        max_tokens: int = 4096,
        max_retries: int = 3,
        timeout: float = 60.0,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.timeout = timeout

        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """
        Call the LLM with the given prompt and return the text response.

        Returns empty string on failure (graceful degradation).
        """
        if completion is None:
            return "[LLM unavailable — install litellm: pip install litellm]"

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = completion(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    timeout=self.timeout,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                last_error = exc
                wait = 2 ** attempt
                time.sleep(wait)

        return f"[LLM call failed after {self.max_retries} retries: {last_error}]"

    def complete_json(self, prompt: str, system: Optional[str] = None) -> dict:
        """Like complete() but attempts to parse JSON from the response."""
        raw = self.complete(prompt, system=system)
        try:
            # Strip markdown code fences if present
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1])
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"raw": raw, "parse_error": True}
