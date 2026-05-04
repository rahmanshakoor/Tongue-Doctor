"""HTTP API for the agent loop.

Trial-grade ``FastAPI`` surface so a separate frontend (Next.js / mobile / etc.)
can POST a case description and render the structured agent trace. Mounted by
``tongue_doctor.app.create_app()``; standalone via ``scripts/serve.py``.
"""

from tongue_doctor.api.app import create_app
from tongue_doctor.api.routes import router

__all__ = ["create_app", "router"]
