"""Problem-representation scorer — LLM-as-judge over keyword overlap."""

from __future__ import annotations

from typing import Any

from eval.scoring.base import ScoreResult


class ProblemRepresentationScorer:
    """Scores how well the system's problem representation captures the expected keywords.

    Uses an LLM judge (Phase 1 wiring). Phase 0 returns 0 with a placeholder note so
    the runner can still produce a complete report.
    """

    dimension: str = "problem_representation"
    weight: float = 0.05
    is_gate: bool = False

    def score(self, expected: dict[str, Any], actual: dict[str, Any]) -> ScoreResult:
        keywords = expected.get("problem_representation_keywords", [])
        return ScoreResult(
            dimension=self.dimension,
            score=0.0,
            weight=self.weight,
            detail={
                "phase": 0,
                "note": "LLM-judge wiring lands in Phase 1.",
                "expected_keywords": keywords,
            },
            is_gate=self.is_gate,
        )
