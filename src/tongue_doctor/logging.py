"""Structured logging.

structlog with stdlib bridge. JSON output for non-TTY (Cloud Logging compatible),
human-readable for TTY. Per-case context vars (``case_id``, ``turn``, ``iteration``,
``agent``, ``trace_id``) are bound via :func:`bind_case_context` and surfaced on every line.
"""

from __future__ import annotations

import logging as stdlib_logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from tongue_doctor.settings import get_settings


def _is_tty() -> bool:
    return sys.stderr.isatty()


def _resolve_use_json() -> bool:
    renderer = get_settings().logging.renderer
    if renderer == "json":
        return True
    if renderer == "console":
        return False
    return not _is_tty()


def configure_logging() -> None:
    """Wire structlog + stdlib logging through one renderer.

    Idempotent — safe to call multiple times. Reads the active Settings.
    """
    settings = get_settings()
    level = getattr(stdlib_logging, settings.logging.level)
    use_json = _resolve_use_json()

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Processor
    if use_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=_is_tty())

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = stdlib_logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = stdlib_logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger. ``name`` defaults to the calling module's logger name."""
    return structlog.get_logger(name)


def bind_case_context(
    case_id: str,
    *,
    turn: int | None = None,
    iteration: int | None = None,
    agent: str | None = None,
    trace_id: str | None = None,
) -> None:
    """Bind per-case context vars onto structlog's contextvars.

    Cleared by :func:`clear_case_context` at request end. Required by the kickoff §10
    observability invariant: every log line within a case carries case_id + turn + iteration.
    """
    ctx: dict[str, Any] = {"case_id": case_id}
    if turn is not None:
        ctx["turn"] = turn
    if iteration is not None:
        ctx["iteration"] = iteration
    if agent is not None:
        ctx["agent"] = agent
    if trace_id is not None:
        ctx["trace_id"] = trace_id
    structlog.contextvars.bind_contextvars(**ctx)


def clear_case_context() -> None:
    """Clear all per-case context vars. Call at end of every request handler."""
    structlog.contextvars.clear_contextvars()
