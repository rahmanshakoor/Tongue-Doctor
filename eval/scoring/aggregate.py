"""Weighted aggregation per kickoff §11."""

from __future__ import annotations

from collections.abc import Iterable

from eval.scoring.base import ScoreResult


def aggregate(results: Iterable[ScoreResult]) -> dict[str, object]:
    """Weighted average across non-gate dimensions; any failed gate forces overall=0."""
    total = 0.0
    weight_sum = 0.0
    gate_failure = False
    failed_gates: list[str] = []

    for r in results:
        if r.is_gate:
            if r.score < 1.0:
                gate_failure = True
                failed_gates.append(r.dimension)
            continue
        total += r.score * r.weight
        weight_sum += r.weight

    overall = 0.0 if gate_failure else (total / weight_sum if weight_sum > 0 else 0.0)

    return {
        "overall": overall,
        "gate_failure": gate_failure,
        "failed_gates": failed_gates,
        "weight_sum": weight_sum,
        "raw_total": total,
    }
