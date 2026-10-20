
from enum import Enum

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Finding(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    explanation: str = Field(min_length=1, max_length=3000)
    evidence_paths: list[str] = Field(default_factory=list)
    confidence: Confidence


class InvestigationReport(BaseModel):
    summary: str = Field(min_length=1, max_length=3000)
    findings: list[Finding] = Field(default_factory=list)
    root_cause_hypotheses: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
