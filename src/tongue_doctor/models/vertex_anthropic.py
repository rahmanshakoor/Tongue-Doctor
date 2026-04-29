"""Claude via Vertex AI Model Garden, with direct-API fallback per ADR 0004.

Phase 0 — class skeleton; ``generate()`` raises :class:`NotImplementedError`.
Phase 1 wires the ``anthropic[vertex]`` SDK's ``AnthropicVertex`` client and the
``UNAVAILABLE`` → :class:`AnthropicDirectClient` fallback path.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tongue_doctor.models.base import LLMClient, LLMResponse, Message, ToolDef


class VertexAnthropicClient:
    """Claude in primary region, falling back to ``fallback_region``, then to direct API."""

    name: str = "vertex_anthropic"

    def __init__(
        self,
        *,
        model_id: str,
        region: str,
        fallback_region: str | None = None,
        project: str = "",
        thinking: Any = None,
        max_output_tokens: int = 8192,
        direct_fallback: LLMClient | None = None,
    ) -> None:
        self.model_id = model_id
        self.region = region
        self.fallback_region = fallback_region
        self.project = project
        self.thinking = thinking
        self.max_output_tokens = max_output_tokens
        self._direct_fallback = direct_fallback

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
            "VertexAnthropicClient.generate is implemented in Phase 1. "
            "Wire anthropic[vertex] AnthropicVertex; on UNAVAILABLE in primary region, retry "
            "in fallback_region; on UNAVAILABLE there too, delegate to self._direct_fallback "
            "if configured (see ADR 0004)."
        )
