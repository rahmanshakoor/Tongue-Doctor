"""Red-flag detection scorer — precision/recall vs. expected list."""

from __future__ import annotations

from typing import Any

from eval.scoring.base import ScoreResult


class RedFlagScorer:
    """F1 of detected red-flag set against ``expected.red_flags`` (case-insensitive)."""

    dimension: str = "red_flags"
    weight: float = 0.10
    is_gate: bool = False

    def score(self, expected: dict[str, Any], actual: dict[str, Any]) -> ScoreResult:
        exp_set = {s.lower() for s in expected.get("red_flags", []) or []}
        act_set = {s.lower() for s in actual.get("red_flags", []) or []}
        if not exp_set and not act_set:
            return ScoreResult(
                dimension=self.dimension,
                score=1.0,
                weight=self.weight,
                detail={"note": "no expected red flags; none produced"},
                is_gate=self.is_gate,
            )
        true_positive = len(exp_set & act_set)
        precision = true_positive / len(act_set) if act_set else 0.0
        recall = true_positive / len(exp_set) if exp_set else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        return ScoreResult(
            dimension=self.dimension,
            score=f1,
            weight=self.weight,
            detail={
                "precision": precision,
                "recall": recall,
                "expected": sorted(exp_set),
                "actual": sorted(act_set),
            },
            is_gate=self.is_gate,
        )
