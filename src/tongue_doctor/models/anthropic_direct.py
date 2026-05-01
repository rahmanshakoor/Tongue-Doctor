"""Direct Anthropic API client.

Used by the Stern template extractor (vision + structured outputs) and any
Phase 1 agent that needs Claude without going through Vertex Model Garden. The
``ANTHROPIC_API_KEY`` env var is required; Secret Manager wiring is deferred
until Phase 1 (Decision K — research-demo direct-API posture).

Two entry points:

- :meth:`AnthropicDirectClient.generate` matches the :class:`LLMClient` protocol
  (text-only). Structured outputs ride on a forced tool-use call: when
  ``response_schema`` is passed, the client adds an internal ``submit_response``
  tool and forces ``tool_choice`` to it, so the model must produce a JSON object
  that matches the schema. The consumer reads it back from
  ``LLMResponse.tool_calls[0].arguments``.

- :meth:`AnthropicDirectClient.generate_multimodal` is a single-turn vision call
  that takes ``text`` plus a list of PNG byte strings (and optional captions)
  and forwards them as Anthropic image content blocks. The same forced-tool
  structured-output channel is supported.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import TextBlock, ToolUseBlock

from tongue_doctor.models.base import (
    FinishReason,
    LLMResponse,
    Message,
    TokenUsage,
    ToolCall,
    ToolDef,
)


@lru_cache(maxsize=1)
def _client() -> AsyncAnthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Direct Anthropic client requires the env var; "
            "set it in .env or your shell before running extraction."
        )
    return AsyncAnthropic(api_key=api_key)


_FINISH_REASON_MAP: dict[str, FinishReason] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_use",
    "stop_sequence": "stop",
    "pause_turn": "stop",
}

_FORCED_TOOL_NAME = "submit_response"


class AnthropicDirectClient:
    """Direct ``api.anthropic.com`` client for Claude.

    Authentication: ``ANTHROPIC_API_KEY`` from env (Phase 0a posture). Production
    will route through ``tongue_doctor.settings.load_secret`` once Secret Manager
    is wired.
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
        sdk_messages = [{"role": m.role, "content": m.content} for m in messages]
        request = self._build_request(
            sdk_messages=sdk_messages,
            system=system,
            tools=tools,
            response_schema=response_schema,
            thinking=thinking,
        )
        return await self._call(request)

    async def generate_multimodal(
        self,
        text: str,
        images: Sequence[bytes],
        *,
        image_captions: Sequence[str] | None = None,
        image_media_type: str = "image/png",
        system: str | None = None,
        response_schema: dict[str, Any] | None = None,
        thinking: Any = None,
    ) -> LLMResponse:
        """Single-turn multimodal call: one user message with text + images.

        ``image_captions`` (if provided) must be the same length as ``images``;
        each caption is emitted as a text block immediately *before* its image
        so the model sees ``"Figure 9-1: ..." [image]`` as a labeled pair.
        """

        if image_captions is not None and len(image_captions) != len(images):
            raise ValueError(
                f"image_captions has {len(image_captions)} entries, expected {len(images)}"
            )

        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for i, png in enumerate(images):
            if image_captions is not None:
                content.append({"type": "text", "text": image_captions[i]})
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_media_type,
                        "data": base64.standard_b64encode(png).decode("ascii"),
                    },
                }
            )

        request = self._build_request(
            sdk_messages=[{"role": "user", "content": content}],
            system=system,
            tools=None,
            response_schema=response_schema,
            thinking=thinking,
        )
        return await self._call(request)

    def _build_request(
        self,
        *,
        sdk_messages: list[dict[str, Any]],
        system: str | None,
        tools: Sequence[ToolDef] | None,
        response_schema: dict[str, Any] | None,
        thinking: Any,
    ) -> dict[str, Any]:
        sdk_tools: list[dict[str, Any]] = []
        if tools is not None:
            sdk_tools.extend(
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            )

        tool_choice: dict[str, Any] | None = None
        if response_schema is not None:
            sdk_tools.append(
                {
                    "name": _FORCED_TOOL_NAME,
                    "description": (
                        "Submit a single response object matching the JSON schema. "
                        "Use this tool exactly once; do not return free text."
                    ),
                    "input_schema": response_schema,
                }
            )
            tool_choice = {"type": "tool", "name": _FORCED_TOOL_NAME}

        request: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": self.max_output_tokens,
            "messages": sdk_messages,
        }
        if system is not None:
            request["system"] = system
        if sdk_tools:
            request["tools"] = sdk_tools
        if tool_choice is not None:
            request["tool_choice"] = tool_choice
        thinking_param = thinking if thinking is not None else self.thinking
        if thinking_param is not None:
            request["thinking"] = thinking_param
        return request

    async def _call(self, request: dict[str, Any]) -> LLMResponse:
        client = _client()
        msg = await client.messages.create(**request)

        text_chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                text_chunks.append(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_calls.append(
                    ToolCall(
                        name=block.name,
                        arguments=dict(block.input)
                        if isinstance(block.input, dict)
                        else {"value": block.input},
                        tool_call_id=block.id,
                    )
                )

        cached = getattr(msg.usage, "cache_read_input_tokens", 0) or 0
        usage = TokenUsage(
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            cached_tokens=cached,
        )

        finish_reason: FinishReason = _FINISH_REASON_MAP.get(
            msg.stop_reason or "", "stop"
        )

        return LLMResponse(
            text="".join(text_chunks),
            tool_calls=tool_calls,
            usage=usage,
            thinking_tokens=0,
            model_id=self.model_id,
            finish_reason=finish_reason,
        )
