"""Uvicorn launcher for the agent-loop API.

::

    uv run python scripts/serve.py
    uv run python scripts/serve.py --host 0.0.0.0 --port 8000

The frontend then POSTs to ``http://<host>:<port>/api/cases/run``. OpenAPI docs
live at ``/docs`` (Swagger UI) and ``/openapi.json``.
"""

from __future__ import annotations

import os
import sys

import typer
import uvicorn

app = typer.Typer(add_completion=False, help="Start the agent-loop FastAPI server.")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host."),
    port: int = typer.Option(8000, "--port", help="Bind port."),
    reload: bool = typer.Option(False, "--reload", help="Reload on source changes (dev only)."),
) -> None:
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        typer.echo(
            "[warn] GEMINI_API_KEY (or GOOGLE_API_KEY) not set. "
            "POST /api/cases/run will fail until you set it.",
            err=True,
        )
    uvicorn.run(
        "tongue_doctor.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
