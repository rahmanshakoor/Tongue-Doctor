"""Extract Stern's *Symptoms to Diagnosis* into structured templates.

Phase 0 placeholder. Blocked on open kickoff item 23 (textbook access). When unblocked,
this script:

1. Reads the user-provided digital copy.
2. Extracts Chapter 1 (the diagnostic procedure) into the Reasoner system prompt template.
3. Extracts each per-complaint chapter into a :class:`Template` YAML under
   ``src/tongue_doctor/templates/data/``.
4. Cross-validates against Harrison's / UpToDate / specialty guidelines per kickoff §4.
5. Records ``reviewed_by: pending`` on every template until a physician reviews.
"""

from __future__ import annotations

import sys

import typer

app = typer.Typer(add_completion=False, help=__doc__.strip())


@app.command()
def run() -> None:
    """Run the extraction pipeline (not yet implemented)."""
    typer.echo(
        "extract_stern.py is a placeholder. Blocked on open kickoff item 23 — "
        "Stern textbook access. See docs/KICKOFF_PLAN.md §13.",
        err=True,
    )
    raise typer.Exit(code=2)


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
