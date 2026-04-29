"""Workup recommendation scorer — overlap with must / should lists."""

from __future__ import annotations

from typing import Any

from eval.scoring.base import ScoreResult


class WorkupScorer:
    """Same shape as :class:`DifferentialScorer` but for workup tests / referrals."""

    dimension: str = "workup"
    weight: float = 0.10
    is_gate: bool = False

    def score(self, expected: dict[str, Any], actual: dict[str, Any]) -> ScoreResult:
        exp_must = {s.lower() for s in expected.get("workup_recommended_must_include", []) or []}
        exp_should = {
            s.lower() for s in expected.get("workup_recommended_should_include", []) or []
        }
        actual_set = {s.lower() for s in actual.get("workup_recommended", []) or []}
        must_score = len(exp_must & actual_set) / len(exp_must) if exp_must else 1.0
        should_score = len(exp_should & actual_set) / len(exp_should) if exp_should else 1.0
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
                "actual": sorted(actual_set),
            },
            is_gate=self.is_gate,
        )
