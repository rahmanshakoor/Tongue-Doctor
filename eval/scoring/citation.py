"""Citation grounding scorer — every claim has a citation."""

from __future__ import annotations

from typing import Any

from eval.scoring.base import ScoreResult


class CitationScorer:
    """Approximates "every claim has a citation" by checking citation count >= claim count.

    Phase 0 — basic implementation: 1.0 if the actual output has at least as many citations
    as the case expects (default ≥ 1), else 0.0. Phase 1 upgrades to per-claim alignment.
    """

    dimension: str = "citation"
    weight: float = 0.05
    is_gate: bool = False

    def score(self, expected: dict[str, Any], actual: dict[str, Any]) -> ScoreResult:
        min_citations = int(expected.get("min_citations", 1))
        actual_count = len(actual.get("citations", []) or [])
        passed = actual_count >= min_citations
        return ScoreResult(
            dimension=self.dimension,
            score=1.0 if passed else 0.0,
            weight=self.weight,
            detail={
                "min_citations_required": min_citations,
                "actual_count": actual_count,
            },
            is_gate=self.is_gate,
        )
