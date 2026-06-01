"""Models for the final risk report."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from migrationmind.models.operation import DDLOperation, RiskLevel, RollbackComplexity


class QueryImpact(BaseModel):
    """A query affected by the migration."""

    query: str
    impact_type: str  # column_missing, index_missing, type_mismatch, will_block
    severity: RiskLevel = RiskLevel.MEDIUM
    description: str = ""
    affected_table: str = ""
    affected_column: Optional[str] = None


class RollbackResult(BaseModel):
    """Rollback analysis result for the entire migration."""

    complexity: RollbackComplexity = RollbackComplexity.SAFE
    estimated_minutes: Optional[int] = None
    steps: list[str] = Field(default_factory=list)
    data_loss_risk: bool = False
    notes: str = ""


class RiskReport(BaseModel):
    """The complete risk analysis report for a migration."""

    migration_file: str
    schema_file: Optional[str] = None
    query_log_file: Optional[str] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    dialect: str = "postgresql"
    db_version: int = 14

    operations: list[DDLOperation] = Field(default_factory=list)
    query_impacts: list[QueryImpact] = Field(default_factory=list)
    rollback: RollbackResult = Field(default_factory=RollbackResult)

    # LLM-generated
    plain_english_summary: Optional[str] = None
    stakeholder_summary: Optional[str] = None
    safe_rewrite_sql: Optional[str] = None

    @property
    def overall_risk_score(self) -> int:
        """Aggregate risk score 0-100."""
        if not self.operations:
            return 0
        scores = [op.risk_score for op in self.operations]
        return min(100, max(scores) + (len([s for s in scores if s > 0]) - 1) * 5)

    @property
    def overall_risk_level(self) -> RiskLevel:
        score = self.overall_risk_score
        if score >= 80:
            return RiskLevel.CRITICAL
        elif score >= 60:
            return RiskLevel.HIGH
        elif score >= 35:
            return RiskLevel.MEDIUM
        elif score >= 10:
            return RiskLevel.LOW
        return RiskLevel.SAFE

    @property
    def affected_tables(self) -> set[str]:
        return {op.target_table for op in self.operations if op.target_table}

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
