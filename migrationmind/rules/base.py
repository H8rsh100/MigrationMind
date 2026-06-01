"""Rules package — base class and rule registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from migrationmind.models.operation import DDLOperation, RiskLevel
from migrationmind.models.schema import SchemaSnapshot


@dataclass
class RuleResult:
    """Result from a single rule evaluation."""

    matched: bool = False
    risk_level: RiskLevel = RiskLevel.SAFE
    message: str = ""
    suggestion: str = ""


class BaseRule(ABC):
    """Abstract base class for all MigrationMind rules."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this rule."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this rule checks."""

    @abstractmethod
    def evaluate(
        self,
        operation: DDLOperation,
        schema: SchemaSnapshot | None = None,
    ) -> RuleResult:
        """
        Evaluate the rule against a DDL operation.

        Args:
            operation: The operation to evaluate.
            schema: Optional schema context for additional checks.

        Returns:
            RuleResult indicating whether the rule matched and what it found.
        """
