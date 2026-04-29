"""Differential and Evidence schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    """A single supporting or against-evidence item for a differential.

    ``source`` is a structured string: ``user`` | ``retrieval:<index>:<chunk_id>`` |
    ``template:<complaint>`` | ``attachment:<attachment_id>``.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    source: str
    weight: float = 1.0


class Differential(BaseModel):
    """A condition under consideration for a case, with prior/posterior and evidence."""

    model_config = ConfigDict(extra="forbid")

    condition: str
    snomed_id: str | None = None
    prior_probability: float = 0.0
    posterior_probability: float = 0.0
    supporting_evidence: list[Evidence] = Field(default_factory=list)
    against_evidence: list[Evidence] = Field(default_factory=list)
    must_not_miss: bool = False
    authority_tier_min: Literal[1, 2, 3] = 3
