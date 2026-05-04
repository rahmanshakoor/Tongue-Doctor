"""Provider-agnostic LLM client protocol and shared types.

The :class:`LLMClient` protocol is the only interface the orchestrator and agents see.
Concrete implementations (Vertex Gemini, Vertex Anthropic, direct Anthropic API) live
alongside in this package and satisfy the protocol structurally.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["user", "assistant", "tool"]
FinishReason = Literal["stop", "length", "tool_use", "content_filter", "error"]


class Message(BaseModel):
    """One message in a chat turn."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str
    tool_call_id: str | None = None
    name: str | None = None


class ToolDef(BaseModel):
    """A tool the model may call. ``input_schema`` is JSON Schema."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    """A tool invocation produced by the model."""

    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any]
    tool_call_id: str


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0


class LLMResponse(BaseModel):
    """Provider-agnostic generate() result."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: TokenUsage
    thinking_tokens: int = 0
    model_id: str
    finish_reason: FinishReason


class StreamChunk(BaseModel):
    """One streamed chunk from :meth:`LLMClient.generate_stream`.

    During streaming the SDK emits ``delta``-bearing chunks (token-level text). The
    *final* chunk carries the aggregated :class:`LLMResponse` in ``response`` so the
    caller can record usage / finish_reason without re-walking the stream.
    """

    model_config = ConfigDict(extra="forbid")

    delta: str = ""
    response: LLMResponse | None = None


@runtime_checkable
class LLMClient(Protocol):
    """The interface every concrete client implements.

    Concrete implementations live in :mod:`tongue_doctor.models.vertex_gemini`,
    :mod:`tongue_doctor.models.vertex_anthropic`, and
    :mod:`tongue_doctor.models.anthropic_direct`.

    Phase 0 ships skeletons whose ``generate`` raises :class:`NotImplementedError`.
    The factory in :mod:`tongue_doctor.models` resolves an implementation from
    ``config/models.yaml`` via a ``model_assignment_key`` (e.g. ``"reasoner"``).

    Streaming (``generate_stream``) is an optional structural extension —
    clients that implement it expose token-level deltas to the chat-mode CLI;
    clients that don't fall back to a single :meth:`generate` call. See
    :func:`tongue_doctor.agents._runtime.call_text_stream`.
    """

    name: str
    model_id: str

    async def generate(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[ToolDef] | None = None,
        response_schema: dict[str, Any] | None = None,
        thinking: Any = None,
    ) -> LLMResponse: ...
