"""FastAPI application factory for the agent-loop API.

This module is the trial-grade frontend-facing surface. CORS is open (``*``) for
development; restrict via the ``FRONTEND_ORIGIN`` env var when deploying.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tongue_doctor import __version__
from tongue_doctor.api.routes import router as agent_router


def _cors_origins() -> list[str]:
    origin = os.environ.get("FRONTEND_ORIGIN", "").strip()
    if not origin:
        return ["*"]
    return [o.strip() for o in origin.split(",") if o.strip()]


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tongue-Doctor agent loop (research demo)",
        version=__version__,
        description=(
            "Multi-agent clinical reasoning research demonstration. "
            "Not a clinical tool. Outputs are not validated and must not be used "
            "to make medical decisions."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(agent_router)
    return app
