"""Direct Anthropic API client, used as a fallback for :class:`VertexAnthropicClient`.

Phase 0 — class skeleton; ``generate()`` raises :class:`NotImplementedError`.
Phase 1 wires :class:`anthropic.AsyncAnthropic` with the API key from Secret Manager.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tongue_doctor.models.base import LLMResponse, Message, ToolDef


class AnthropicDirectClient:
    """Direct ``api.anthropic.com`` client for Claude.

    Authentication: ``ANTHROPIC_API_KEY`` resolved via
    :func:`tongue_doctor.settings.load_secret`.
    """

    name: str = "anthropic_direct"

    def __init__(
        self,
        *,
        model_id: str,
        thinking: Any = None,
        max_output_tokens: int = 8192,
    ) -> None:
        self.model_id = model_id
        self.thinking = thinking
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
            "AnthropicDirectClient.generate is implemented in Phase 1. "
            "Use anthropic.AsyncAnthropic with ANTHROPIC_API_KEY from Secret Manager."
        )
