"""Per-dimension scorers for the eval harness.

Concrete scorers live in sibling modules and are explicitly assembled by the runner —
no auto-registration. This keeps the active scorer set visible at the call site.
"""

from eval.scoring.base import Scorer, ScoreResult

__all__ = ["ScoreResult", "Scorer"]
