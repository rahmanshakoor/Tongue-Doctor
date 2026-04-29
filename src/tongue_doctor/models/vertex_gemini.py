"""Gemini via Vertex AI.

Phase 0 — class skeleton; ``generate()`` raises :class:`NotImplementedError`.
Phase 1 wires :mod:`google.cloud.aiplatform` (or the GenAI SDK) and the streaming path.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tongue_doctor.models.base import LLMResponse, Message, ToolDef


class VertexGeminiClient:
    """Gemini chat completions via Vertex AI in the configured GCP region.

    Cross-region calls are accepted per ADR 0004 — the orchestrator passes
    ``fallback_region`` and the client retries there on regional unavailability.
    """

    name: str = "vertex_gemini"

    def __init__(
        self,
        *,
        model_id: str,
        region: str,
        fallback_region: str | None = None,
        project: str = "",
        thinking: Any = None,
        thinking_complex_differential: Any = None,
        thinking_ecg: Any = None,
        thinking_documents: Any = None,
        thinking_default: Any = None,
        max_output_tokens: int = 4096,
    ) -> None:
        self.model_id = model_id
        self.region = region
        self.fallback_region = fallback_region
        self.project = project
        self.thinking = thinking
        self.thinking_complex_differential = thinking_complex_differential
        self.thinking_ecg = thinking_ecg
        self.thinking_documents = thinking_documents
        self.thinking_default = thinking_default
        self.max_output_tokens = max_output_tokens

    async def generate(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[ToolDef] | None = None,
        response_schema: dict[str, Any] | None = None,
        thinking: Any = None,
    ) -> LLMResponse:
        raise NotImplementedError(
            "VertexGeminiClient.generate is implemented in Phase 1. "
            "Wire google-cloud-aiplatform's GenerativeModel here; respect thinking budget per call."
        )
