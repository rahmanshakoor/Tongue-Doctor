"""OpenTelemetry tracing wired to Cloud Trace when enabled.

When ``settings.tracing.enabled`` is False (the scaffold default), the global tracer
is a no-op. When enabled, spans are exported via the GCP Cloud Trace exporter.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Span, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from tongue_doctor import __version__
from tongue_doctor.settings import get_settings

_TRACER: Tracer | None = None


def configure_tracing() -> None:
    """Wire the OTel TracerProvider. Idempotent.

    Cloud Trace exporter is attached only when ``settings.tracing.enabled`` is True
    *and* a GCP project is configured. Otherwise a TracerProvider is installed without
    any exporter — spans are created but go nowhere.
    """
    global _TRACER
    settings = get_settings()

    resource = Resource.create(
        {
            "service.name": "tongue-doctor",
            "service.version": __version__,
            "deployment.environment": settings.env,
        }
    )

    provider = TracerProvider(resource=resource)

    if settings.tracing.enabled:
        if not settings.gcp.project:
            raise RuntimeError(
                "tracing.enabled=true but GOOGLE_CLOUD_PROJECT is unset "
                "(open kickoff item 21). Disable tracing or supply a project ID."
            )
        try:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        except ImportError as exc:
            raise RuntimeError(
                "tracing.enabled=true but opentelemetry-exporter-gcp-trace is not installed."
            ) from exc

        exporter = CloudTraceSpanExporter(project_id=settings.gcp.project)  # type: ignore[no-untyped-call]
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer("tongue_doctor")


def get_tracer() -> Tracer:
    """Return the package tracer, configuring on first use."""
    if _TRACER is None:
        configure_tracing()
    assert _TRACER is not None
    return _TRACER


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[Span]:
    """Convenience wrapper for ``tracer.start_as_current_span``."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name, attributes=attributes) as s:
        yield s  # type: ignore[misc]
