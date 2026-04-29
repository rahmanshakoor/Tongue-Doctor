"""Scorer protocol + per-dimension result type."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ScoreResult(BaseModel):
    """Per-dimension score for one case.

    ``score`` is in [0, 1]. ``weight`` is the dimension's contribution to the case's
    overall weighted score. ``is_gate=True`` means a score < 1 fails the case
    regardless of other dimensions (only :class:`PrescriptionLeakScorer` is a gate).
    """

    model_config = ConfigDict(extra="forbid")

    dimension: str
    score: float
    weight: float
    detail: dict[str, Any] = Field(default_factory=dict)
    is_gate: bool = False


@runtime_checkable
class Scorer(Protocol):
    """Computes one dimension of a case's score."""

    dimension: str
    weight: float
    is_gate: bool

    def score(self, expected: dict[str, Any], actual: dict[str, Any]) -> ScoreResult: ...
