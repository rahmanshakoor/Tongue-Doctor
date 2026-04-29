"""Replay a case from a given iteration with the current code / prompts / models.

Phase 0 placeholder. Phase 1 implements the replay tool described in
``KICKOFF_PLAN.md`` §10:

1. Fetch the original :class:`CaseState` from Firestore at iteration N.
2. Reconstruct the message history from the ``turns`` subcollection.
3. Re-run subsequent steps with current code, producing a side-by-side diff.
"""

from __future__ import annotations

import sys

import typer

app = typer.Typer(add_completion=False, help=__doc__.strip())


@app.command()
def run(
    case_id: str = typer.Argument(..., help="Case ID to replay"),
    from_iteration: int = typer.Option(
        0, "--from-iteration", help="Iteration to start replay from"
    ),
) -> None:
    """Replay a case (not yet implemented)."""
    typer.echo(
        f"replay.py is a placeholder. Phase 1 wires the replay tool. "
        f"Requested: case_id={case_id}, from_iteration={from_iteration}",
        err=True,
    )
    raise typer.Exit(code=2)


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
