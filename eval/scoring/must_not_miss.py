"""Must-not-miss coverage scorer."""

from __future__ import annotations

from typing import Any

from eval.scoring.base import ScoreResult


class MustNotMissScorer:
    """Fraction of expected must-not-miss diagnoses that were considered."""

    dimension: str = "must_not_miss"
    weight: float = 0.20
    is_gate: bool = False

    def score(self, expected: dict[str, Any], actual: dict[str, Any]) -> ScoreResult:
        exp_set = {s.lower() for s in expected.get("must_not_miss_considered", []) or []}
        act_set = {s.lower() for s in actual.get("must_not_miss_considered", []) or []}
        if not exp_set:
            return ScoreResult(
                dimension=self.dimension,
                score=1.0,
                weight=self.weight,
                detail={"note": "no must-not-miss expected"},
                is_gate=self.is_gate,
            )
        coverage = len(exp_set & act_set) / len(exp_set)
        return ScoreResult(
            dimension=self.dimension,
            score=coverage,
            weight=self.weight,
            detail={
                "coverage": coverage,
                "expected": sorted(exp_set),
                "actual": sorted(act_set),
                "missing": sorted(exp_set - act_set),
            },
            is_gate=self.is_gate,
        )
