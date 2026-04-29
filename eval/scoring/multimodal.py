"""Multimodal extraction scorer — per-modality structural comparison.

Phase 0 placeholder: the structural compare per modality (ECG rhythm match, rate ±10
bpm tolerance, finding-set Jaccard) lands with the first multimodal handler in Phase 2.
"""

from __future__ import annotations

from typing import Any

from eval.scoring.base import ScoreResult


class MultimodalScorer:
    dimension: str = "multimodal"
    weight: float = 0.10
    is_gate: bool = False

    def score(self, expected: dict[str, Any], actual: dict[str, Any]) -> ScoreResult:
        if not expected.get("ecg_findings_expected") and not expected.get("attachments"):
            return ScoreResult(
                dimension=self.dimension,
                score=1.0,
                weight=self.weight,
                detail={"note": "no multimodal expected"},
                is_gate=self.is_gate,
            )
        return ScoreResult(
            dimension=self.dimension,
            score=0.0,
            weight=self.weight,
            detail={
                "phase": 0,
                "note": "structural multimodal comparison lands with the first handler (Phase 2).",
            },
            is_gate=self.is_gate,
        )
