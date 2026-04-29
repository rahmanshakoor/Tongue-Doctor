"""Regression detection.

Compare the most recent run on a slice to the previous green run on the same slice and
return per-dimension deltas. Phase 0 ships discovery + loading; the per-dimension diff
lands once scoring produces real numbers in Phase 1.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).resolve().parent / "reports" / "runs"


def latest_report_for_slice(
    slice_: str,
    *,
    exclude: str | None = None,
) -> dict[str, Any] | None:
    """Return the most recent run on ``slice_``, optionally excluding a run_id."""
    if not REPORTS_DIR.is_dir():
        return None
    runs = sorted(REPORTS_DIR.glob("*.json"))
    for path in reversed(runs):
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("slice") != slice_:
            continue
        if exclude is not None and data.get("run_id") == exclude:
            continue
        return data
    return None


def diff_runs(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Per-case, per-dimension score deltas between two runs."""
    raise NotImplementedError(
        "Regression diff lands in Phase 1 once scoring produces numeric scores."
    )
