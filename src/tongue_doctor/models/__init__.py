"""LLM client factory.

:func:`get_client` resolves a configured :class:`LLMClient` by ``model_assignment_key``
(``"reasoner"``, ``"devils_advocate"``, ...) using ``config/models.yaml``.
"""

from __future__ import annotations

from typing import Any

from tongue_doctor.models.anthropic_direct import AnthropicDirectClient
from tongue_doctor.models.base import (
    FinishReason,
    LLMClient,
    LLMResponse,
    Message,
    Role,
    TokenUsage,
    ToolCall,
    ToolDef,
)
from tongue_doctor.models.gemini_direct import GeminiDirectClient
from tongue_doctor.models.vertex_anthropic import VertexAnthropicClient
from tongue_doctor.models.vertex_gemini import VertexGeminiClient
from tongue_doctor.settings import get_settings


def _gemini_thinking_kwargs(spec: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "thinking",
        "thinking_complex_differential",
        "thinking_ecg",
        "thinking_documents",
        "thinking_default",
    )
    return {k: spec[k] for k in keys if k in spec}


def _rate_limit_kwargs(spec: dict[str, Any], rate_limit_defaults: dict[str, Any]) -> dict[str, Any]:
    """Resolve the per-client rate-limit / retry knobs.

    Precedence: per-agent override in the spec dict wins over the global
    ``rate_limit`` block in ``config/models.yaml``. Both are optional; missing
    keys get the constructor's defaults.
    """

    out: dict[str, Any] = {}
    for key in ("min_interval_seconds", "retry_delay_seconds", "max_retries"):
        if key in spec:
            out[key] = spec[key]
        elif key in rate_limit_defaults:
            out[key] = rate_limit_defaults[key]
    return out


def get_client(model_assignment_key: str) -> LLMClient:
    """Resolve a configured :class:`LLMClient` from ``config/models.yaml``.

    Raises :class:`KeyError` if the key has no entry, :class:`ValueError` for unknown providers.
    """
    settings = get_settings()
    spec_obj = settings.models.get(model_assignment_key)
    if spec_obj is None:
        raise KeyError(
            f"No model assignment for {model_assignment_key!r} in config/models.yaml. "
            f"Known keys: {sorted(settings.models.keys())}"
        )
    if not isinstance(spec_obj, dict):
        raise ValueError(
            f"Model spec for {model_assignment_key!r} must be a mapping; got {type(spec_obj).__name__}."
        )
    spec: dict[str, Any] = spec_obj
    provider = spec.get("provider")
    model_id_obj = spec.get("model")
    if not isinstance(model_id_obj, str):
        raise ValueError(f"Model spec for {model_assignment_key!r} is missing a 'model' string.")
    model_id: str = model_id_obj
    max_output_tokens = int(spec.get("max_output_tokens", 4096))

    if provider == "vertex_gemini":
        return VertexGeminiClient(
            model_id=model_id,
            region=settings.gcp.region,
            fallback_region=settings.gcp.fallback_region,
            project=settings.gcp.project,
            max_output_tokens=max_output_tokens,
            **_gemini_thinking_kwargs(spec),
        )
    if provider == "vertex_anthropic":
        return VertexAnthropicClient(
            model_id=model_id,
            region=settings.gcp.region,
            fallback_region=settings.gcp.fallback_region,
            project=settings.gcp.project,
            thinking=spec.get("thinking"),
            max_output_tokens=max_output_tokens,
        )
    if provider == "anthropic_direct":
        return AnthropicDirectClient(
            model_id=model_id,
            thinking=spec.get("thinking"),
            max_output_tokens=max_output_tokens,
        )
    if provider == "gemini_direct":
        # ``rate_limit`` is an optional top-level block in ``config/models.yaml``
        # — when present, it sets defaults for every gemini_direct agent. Per-
        # agent overrides win when the spec dict has its own keys.
        rate_limit_defaults_obj = settings.models.get("rate_limit") or {}
        rate_limit_defaults = (
            rate_limit_defaults_obj if isinstance(rate_limit_defaults_obj, dict) else {}
        )
        return GeminiDirectClient(
            model_id=model_id,
            thinking=spec.get("thinking"),
            max_output_tokens=max_output_tokens,
            **_rate_limit_kwargs(spec, rate_limit_defaults),
        )
    raise ValueError(
        f"Unknown provider {provider!r} for {model_assignment_key!r}. "
        "Known providers: anthropic_direct, gemini_direct, vertex_anthropic, vertex_gemini."
    )


__all__ = [
    "AnthropicDirectClient",
    "FinishReason",
    "GeminiDirectClient",
    "LLMClient",
    "LLMResponse",
    "Message",
    "Role",
    "TokenUsage",
    "ToolCall",
    "ToolDef",
    "VertexAnthropicClient",
    "VertexGeminiClient",
    "get_client",
]
