"""Top-3 differential scorer — set overlap with expected must / should lists."""

from __future__ import annotations

from typing import Any

from eval.scoring.base import ScoreResult


class DifferentialScorer:
    """``must_include`` weighted higher than ``should_include``.

    Score = (matched_must / total_must) * 0.7 + (matched_should / total_should) * 0.3.
    Comparison is case-insensitive.
    """

    dimension: str = "differential"
    weight: float = 0.20
    is_gate: bool = False

    def score(self, expected: dict[str, Any], actual: dict[str, Any]) -> ScoreResult:
        exp_must = {s.lower() for s in expected.get("top_3_differential_must_include", []) or []}
        exp_should = {
            s.lower() for s in expected.get("top_3_differential_should_include", []) or []
        }
        actual_top = {s.lower() for s in actual.get("top_3_differential", []) or []}

        must_score = len(exp_must & actual_top) / len(exp_must) if exp_must else 1.0
        should_score = len(exp_should & actual_top) / len(exp_should) if exp_should else 1.0
        combined = 0.7 * must_score + 0.3 * should_score
        return ScoreResult(
            dimension=self.dimension,
            score=combined,
            weight=self.weight,
            detail={
                "must_score": must_score,
                "should_score": should_score,
                "expected_must": sorted(exp_must),
                "expected_should": sorted(exp_should),
                "actual_top_3": sorted(actual_top),
            },
            is_gate=self.is_gate,
        )
