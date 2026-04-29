"""Complaint template schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RedFlagPattern(BaseModel):
    """A red-flag pattern recognized inside a complaint template."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    severity: str = "high"


class Template(BaseModel):
    """A per-complaint reasoning template.

    ``reviewed_by`` defaults to ``"pending"``. Outputs that consume an unreviewed
    template must carry the research-demo disclaimer (per ``SAFETY_INVARIANTS.md``).
    """

    model_config = ConfigDict(extra="forbid")

    complaint: str
    version: int = 1
    reviewed_by: str = "pending"
    reviewed_at: str | None = None
    must_not_miss: list[str] = Field(default_factory=list)
    red_flags: list[RedFlagPattern] = Field(default_factory=list)
    pivotal_features: list[str] = Field(default_factory=list)
    default_workup: list[str] = Field(default_factory=list)
    educational_treatment_classes: list[str] = Field(default_factory=list)
    notes: str = ""
