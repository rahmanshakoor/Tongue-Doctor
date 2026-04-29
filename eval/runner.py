"""Eval runner.

Discover cases under ``eval/cases/<slice>/``, run them through the diagnostic loop,
score each result against the ten dimensions, write a JSON report under
``eval/reports/runs/<run_id>.json``.

Phase 0 — ``run_case`` raises :class:`NotImplementedError` because the diagnostic
loop is not yet wired. Cases are still discovered and the report skeleton is still
written so plumbing is verifiable end-to-end.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from eval.scoring.base import Scorer
from eval.scoring.citation import CitationScorer
from eval.scoring.differential import DifferentialScorer
from eval.scoring.disclaimer import DisclaimerScorer
from eval.scoring.multimodal import MultimodalScorer
from eval.scoring.must_not_miss import MustNotMissScorer
from eval.scoring.prescription import PrescriptionLeakScorer
from eval.scoring.problem_representation import ProblemRepresentationScorer
from eval.scoring.red_flags import RedFlagScorer
from eval.scoring.scope import ScopeScorer
from eval.scoring.workup import WorkupScorer

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = REPO_ROOT / "eval" / "cases"
REPORTS_DIR = REPO_ROOT / "eval" / "reports" / "runs"


def get_default_scorers() -> list[Scorer]:
    """Active scorer set. Order matches the kickoff §11 weight table."""
    return [
        ScopeScorer(),
        RedFlagScorer(),
        ProblemRepresentationScorer(),
        DifferentialScorer(),
        MustNotMissScorer(),
        WorkupScorer(),
        MultimodalScorer(),
        CitationScorer(),
        DisclaimerScorer(),
        PrescriptionLeakScorer(),
    ]


def discover_cases(slice_: str) -> list[Path]:
    slice_dir = CASES_DIR / slice_
    if not slice_dir.is_dir():
        return []
    return sorted(slice_dir.glob("*.yaml"))


def load_case(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if not isinstance(loaded, dict):
        raise ValueError(f"Case file {path} did not parse to a mapping.")
    return loaded


async def run_case(case: dict[str, Any], scorers: list[Scorer]) -> dict[str, Any]:
    """Run one case through the diagnostic loop and apply every scorer.

    Phase 0 raises :class:`NotImplementedError`. Phase 1 wires
    :meth:`tongue_doctor.orchestrator.DiagnosticLoop.handle_message` and assembles
    ``actual`` from the resulting :class:`UserFacingOutput` and the final
    :class:`CaseState`, then invokes each scorer.
    """
    raise NotImplementedError(
        "Eval pipeline call lands in Phase 1. Wire DiagnosticLoop.handle_message and "
        "pass the actual output + final CaseState to scorers."
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def run_eval(slice_: str, run_id: str | None = None) -> dict[str, Any]:
    """Discover, run, score, write report. Returns the run summary dict."""
    if run_id is None:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    cases = discover_cases(slice_)
    scorers = get_default_scorers()

    summary: dict[str, Any] = {
        "run_id": run_id,
        "slice": slice_,
        "case_count": len(cases),
        "started_at": _now_iso(),
        "results": [],
        "scorers": [s.dimension for s in scorers],
    }

    if not cases:
        summary["note"] = (
            f"No cases found in eval/cases/{slice_}/. Author cases per docs/EVAL_PROCESS.md."
        )

    for case_path in cases:
        try:
            case = load_case(case_path)
        except (yaml.YAMLError, ValueError) as exc:
            summary["results"].append(
                {
                    "case_id": case_path.stem,
                    "status": "load_error",
                    "reason": str(exc),
                }
            )
            continue

        case_id = case.get("case_id", case_path.stem)
        try:
            result = asyncio.run(run_case(case, scorers))
        except NotImplementedError as exc:
            result = {
                "case_id": case_id,
                "status": "skipped",
                "reason": str(exc),
            }
        summary["results"].append(result)

    summary["finished_at"] = _now_iso()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{run_id}.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tongue-Doctor eval runner")
    parser.add_argument(
        "--slice",
        dest="slice_",
        default="chest_pain",
        help="Eval slice (complaint dir under eval/cases/)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run identifier (timestamp by default)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = run_eval(args.slice_, run_id=args.run_id)
    print(f"Eval run {summary['run_id']} completed: {summary['case_count']} case(s).")
    if "note" in summary:
        print(summary["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
