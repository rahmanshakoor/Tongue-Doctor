"""Validate eval case files and (Phase 1) seed them into the eval test environment.

Phase 0 — schema validation only. Walks ``eval/cases/<slice>/*.yaml``, validates each
file's required fields, prints a summary. Phase 1 adds GCS/Firestore seeding for
multimodal fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = REPO_ROOT / "eval" / "cases"

REQUIRED_TOP_LEVEL_FIELDS = ("case_id", "complaint", "input", "expected")

app = typer.Typer(add_completion=False, help=__doc__.strip())


def _validate_one(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        with path.open(encoding="utf-8") as f:
            data: Any = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        return [f"{path}: YAML parse error: {exc}"]
    if not isinstance(data, dict):
        return [f"{path}: top level is not a mapping"]
    for key in REQUIRED_TOP_LEVEL_FIELDS:
        if key not in data:
            errors.append(f"{path}: missing required field {key!r}")
    return errors


@app.command()
def validate(slice_: str = typer.Option("", "--slice", help="Limit to one slice")) -> None:
    """Validate every case file's schema."""
    if not CASES_DIR.is_dir():
        typer.echo("No eval/cases directory.")
        raise typer.Exit(code=0)
    pattern = f"{slice_}/**/*.yaml" if slice_ else "**/*.yaml"
    files = sorted(CASES_DIR.glob(pattern))
    if not files:
        typer.echo(f"No case files matched ({slice_ or 'all slices'}).")
        raise typer.Exit(code=0)
    all_errors: list[str] = []
    for f in files:
        all_errors.extend(_validate_one(f))
    if all_errors:
        for err in all_errors:
            typer.echo(err, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"OK — {len(files)} case file(s) validated.")


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
