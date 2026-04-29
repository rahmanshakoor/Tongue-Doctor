"""Scope decision scorer — exact match."""

from __future__ import annotations

from typing import Any

from eval.scoring.base import ScoreResult


class ScopeScorer:
    """Compares ``expected.scope`` to ``actual.scope`` (in_scope / out_of_scope / escalate_to_ed)."""

    dimension: str = "scope"
    weight: float = 0.10
    is_gate: bool = False

    def score(self, expected: dict[str, Any], actual: dict[str, Any]) -> ScoreResult:
        exp = expected.get("scope")
        act = actual.get("scope")
        match = exp is not None and exp == act
        return ScoreResult(
            dimension=self.dimension,
            score=1.0 if match else 0.0,
            weight=self.weight,
            detail={"expected": exp, "actual": act},
            is_gate=self.is_gate,
        )
