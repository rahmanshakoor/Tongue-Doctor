"""FastAPI application entry point for Cloud Run.

The Phase 0 app exposes only health + version endpoints. Real routes (chat, attachment
upload, streaming) land in Phase 4 once IAP is wired. The boot sequence is intentionally
minimal: configure logging, configure tracing, register endpoints.
"""

from __future__ import annotations

from fastapi import FastAPI

from tongue_doctor import __version__
from tongue_doctor.logging import configure_logging
from tongue_doctor.tracing import configure_tracing


def create_app() -> FastAPI:
    configure_logging()
    configure_tracing()

    app = FastAPI(
        title="Tongue-Doctor (research demo)",
        version=__version__,
        description=(
            "Multi-agent clinical reasoning research demonstration. "
            "Not a clinical tool. Outputs are not validated and must not be used "
            "to make medical decisions."
        ),
        docs_url=None,
        redoc_url=None,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/version")
    def version() -> dict[str, str]:
        return {"version": __version__, "service": "tongue-doctor"}

    return app


app = create_app()
