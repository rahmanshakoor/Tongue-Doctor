"""Direct Gemini API client.

Used by the Phase 1 agent loop. The ``GEMINI_API_KEY`` (or ``GOOGLE_API_KEY``) env var
is required. Mirrors :class:`AnthropicDirectClient`'s shape but with two simplifications:

- **Structured output** rides on the SDK's native ``response_schema`` parameter; no
  forced-tool-use dance. When the caller passes ``response_schema``, the SDK forces
  a JSON-shaped response and we parse it back from ``LLMResponse.text``.
- **Async** uses the SDK's ``client.aio.models.generate_content`` path.

Schema flattening (:func:`_flatten_schema`) is required because Pydantic emits
``$defs`` / ``$ref`` for nested models but Gemini's structured-output schema does not
support refs. We inline the definitions before sending and drop ``additionalProperties``
which Gemini tolerates inconsistently.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Sequence
from copy import deepcopy
from functools import lru_cache
from typing import Any, cast

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from tongue_doctor.models.base import (
    FinishReason,
    LLMResponse,
    Message,
    StreamChunk,
    TokenUsage,
    ToolCall,
    ToolDef,
)

logger = logging.getLogger(__name__)


# Rate limiting + retry are shared across every ``GeminiDirectClient`` instance:
# Google enforces quota at the API-key / project level, not per-Python-object.
# All eight loop agents share one quota, so the throttle has to be module-level.
_RATE_LIMIT_LOCK = asyncio.Lock()
_RATE_LIMIT_LAST_CALL: float = 0.0

# Retryable HTTP status codes per Google's API conventions:
#   408 — request timeout
#   429 — rate limit / quota exhausted (the headline reason this exists)
#   500 / 502 / 503 / 504 — transient server-side errors
# Anything else (400 invalid arg, 401 unauthenticated, 403 forbidden, 404, …)
# is the caller's bug and we fail fast so the developer sees it.
_RETRYABLE_CODES = frozenset({408, 429, 500, 502, 503, 504})


async def _wait_for_rate_limit(min_interval_s: float) -> None:
    """Block until at least ``min_interval_s`` has elapsed since the last call.

    No-op when ``min_interval_s == 0`` so unit tests that don't go through the
    factory aren't penalized with synthetic latency.
    """

    if min_interval_s <= 0:
        return
    global _RATE_LIMIT_LAST_CALL
    async with _RATE_LIMIT_LOCK:
        now = time.monotonic()
        elapsed = now - _RATE_LIMIT_LAST_CALL
        if elapsed < min_interval_s:
            await asyncio.sleep(min_interval_s - elapsed)
        _RATE_LIMIT_LAST_CALL = time.monotonic()


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient errors that warrant a sleep + retry.

    We don't blanket-retry every exception — invalid-argument and auth errors
    will fail forever, so retrying just hides the real bug behind a long delay.
    """

    if isinstance(exc, genai_errors.APIError):
        return getattr(exc, "code", None) in _RETRYABLE_CODES
    # Network-level hiccups that surface as bare exceptions before the SDK can
    # wrap them. Match on the message because httpx / urllib3 paths vary by
    # environment and we don't want to import the whole error tree.
    msg = str(exc).lower()
    return any(
        keyword in msg
        for keyword in ("timed out", "connection reset", "broken pipe", "temporarily unavailable")
    )


def _format_exc(exc: BaseException) -> str:
    """One-liner describing a retryable error for the log message."""

    code = getattr(exc, "code", None)
    if code is not None:
        return f"{type(exc).__name__} code={code}: {str(exc)[:200]}"
    return f"{type(exc).__name__}: {str(exc)[:200]}"


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Direct Gemini client requires the env var; "
            "set it in .env or your shell before running the agent loop."
        )
    return genai.Client(api_key=api_key)


_FINISH_REASON_MAP: dict[str, FinishReason] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "BLOCKLIST": "content_filter",
    "SPII": "content_filter",
    "MALFORMED_FUNCTION_CALL": "error",
    "FINISH_REASON_UNSPECIFIED": "stop",
    "OTHER": "stop",
}


# Gemini's content roles are "user" and "model"; map our protocol's roles onto them.
_ROLE_MAP = {"user": "user", "assistant": "model", "tool": "user"}


def _flatten_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline ``$defs`` / ``$ref`` so the Gemini schema validator accepts the schema.

    Pydantic's ``model_json_schema()`` emits nested objects as ``{"$ref": "#/$defs/Foo"}``
    references, but Gemini's structured-output schema does not support refs. Walks the
    schema, resolves each ref to the inline definition, and strips fields Gemini does
    not accept (``additionalProperties``, ``$defs``, ``definitions``, ``$schema``,
    ``title`` on the root only — ``title`` on properties is fine).
    """

    if not isinstance(schema, dict):
        return schema

    defs: dict[str, Any] = {}
    if "$defs" in schema and isinstance(schema["$defs"], dict):
        defs = schema["$defs"]
    elif "definitions" in schema and isinstance(schema["definitions"], dict):
        defs = schema["definitions"]

    drop_keys = {"$defs", "definitions", "$schema", "additionalProperties"}

    def _resolve(node: Any, _depth: int = 0) -> Any:
        if _depth > 32:  # cycle guard
            return node
        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str):
                ref = node["$ref"]
                key = ref.rsplit("/", 1)[-1]
                target = defs.get(key)
                if target is None:
                    return {"type": "object"}
                return _resolve(deepcopy(target), _depth + 1)
            out = {
                k: _resolve(v, _depth + 1)
                for k, v in node.items()
                if k not in drop_keys
            }
            # Gemini's structured-output schema rejects non-string enum values.
            # When Pydantic emits ``Literal[1, 2, 3]`` (integer enum) we collapse
            # it to ``minimum``/``maximum`` so the model still gets a constraint.
            enum = out.get("enum")
            if isinstance(enum, list) and enum and all(not isinstance(v, str) for v in enum):
                numeric = [v for v in enum if isinstance(v, (int, float))]
                if numeric:
                    out["minimum"] = min(numeric)
                    out["maximum"] = max(numeric)
                out.pop("enum", None)
            return out
        if isinstance(node, list):
            return [_resolve(item, _depth + 1) for item in node]
        return node

    return cast(dict[str, Any], _resolve(deepcopy(schema)))


def _thinking_budget(thinking: Any) -> int | None:
    """Coerce a thinking value into a Gemini ``thinking_budget`` int, or None."""

    if thinking is None:
        return None
    if isinstance(thinking, int):
        return thinking
    if isinstance(thinking, dict):
        if "budget_tokens" in thinking:
            try:
                return int(thinking["budget_tokens"])
            except (TypeError, ValueError):
                return None
        if "thinking_budget" in thinking:
            try:
                return int(thinking["thinking_budget"])
            except (TypeError, ValueError):
                return None
    if isinstance(thinking, str):
        # Coarse string levels documented in config/models.yaml.
        return {"low": 1024, "medium": 4096, "high": 16000}.get(thinking)
    return None


class GeminiDirectClient:
    """Direct ``generativelanguage.googleapis.com`` client for Gemini.

    Authentication: ``GEMINI_API_KEY`` (or ``GOOGLE_API_KEY``) from env. Production
    will route through ``tongue_doctor.settings.load_secret`` once Secret Manager
    is wired (Phase 1b).
    """

    name: str = "gemini_direct"

    def __init__(
        self,
        *,
        model_id: str,
        thinking: Any = None,
        max_output_tokens: int = 4096,
        min_interval_seconds: float = 0.0,
        retry_delay_seconds: float = 30.0,
        max_retries: int = 5,
    ) -> None:
        self.model_id = model_id
        self.thinking = thinking
        self.max_output_tokens = max_output_tokens
        # Throttle / retry settings. The constructor default is 0 so unit tests
        # that build the client directly aren't slowed down. The factory in
        # ``tongue_doctor.models.__init__`` injects production values from
        # ``config/models.yaml`` so the live agent loop is properly paced.
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self.max_retries = max(0, int(max_retries))

    async def generate(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[ToolDef] | None = None,
        response_schema: dict[str, Any] | None = None,
        thinking: Any = None,
    ) -> LLMResponse:
        contents = self._build_contents(messages)
        config = self._build_config(
            system=system,
            tools=tools,
            response_schema=response_schema,
            thinking=thinking,
        )
        client = _client()

        # Retry loop — we sleep ``retry_delay_seconds`` between attempts so the
        # 429 backoff is long enough for Google's rolling-window quota to reset
        # (60 s window → 30 s wait gives ample headroom). On non-retryable
        # errors we re-raise immediately so real bugs surface fast.
        attempt = 0
        while True:
            await _wait_for_rate_limit(self.min_interval_seconds)
            try:
                # Cast widens the type to satisfy the SDK's union; runtime accepts list[Content].
                response = await client.aio.models.generate_content(
                    model=self.model_id,
                    contents=cast(Any, contents),
                    config=config,
                )
                return self._build_response(response)
            except Exception as exc:
                if attempt >= self.max_retries or not _is_retryable(exc):
                    raise
                logger.warning(
                    "[gemini] %s — retrying in %.0fs (attempt %d/%d)",
                    _format_exc(exc),
                    self.retry_delay_seconds,
                    attempt + 1,
                    self.max_retries,
                )
                await asyncio.sleep(self.retry_delay_seconds)
                attempt += 1

    async def generate_stream(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[ToolDef] | None = None,
        response_schema: dict[str, Any] | None = None,
        thinking: Any = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream incremental text deltas with rate-limit-aware retries.

        Same shape as :meth:`generate_stream` previously, but wrapped in the same
        rate-limit + retry loop as :meth:`generate`. Each retry attempt restarts
        the underlying SDK call from scratch via :meth:`_stream_once`, so retry
        state never leaks across attempts. The most common retryable failure
        (HTTP 429 quota exhausted) surfaces before any chunk is emitted, so in
        practice the retry is invisible — the user just waits ~30 s longer.
        Mid-stream failures after deltas have started arriving will re-stream
        from the top on the next attempt; downstream consumers parse the JSON
        only at end-of-stream so the doubled output is harmless to correctness
        though it does flicker in the chat UI.
        """

        contents = self._build_contents(messages)
        config = self._build_config(
            system=system,
            tools=tools,
            response_schema=response_schema,
            thinking=thinking,
        )
        client = _client()

        attempt = 0
        while True:
            await _wait_for_rate_limit(self.min_interval_seconds)
            try:
                async for chunk in self._stream_once(client, contents, config):
                    yield chunk
                return
            except Exception as exc:
                if attempt >= self.max_retries or not _is_retryable(exc):
                    raise
                logger.warning(
                    "[gemini stream] %s — retrying in %.0fs (attempt %d/%d)",
                    _format_exc(exc),
                    self.retry_delay_seconds,
                    attempt + 1,
                    self.max_retries,
                )
                await asyncio.sleep(self.retry_delay_seconds)
                attempt += 1

    async def _stream_once(
        self,
        client: genai.Client,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> AsyncIterator[StreamChunk]:
        """Single attempt of streaming generation.

        Encapsulates all per-attempt accumulator state (text chunks, tool calls,
        usage metadata) so a retry loop in :meth:`generate_stream` can restart
        cleanly without leaking state from a failed attempt.
        """

        text_chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        finish_reason: FinishReason = "stop"
        usage = TokenUsage(input_tokens=0, output_tokens=0)
        thinking_tokens = 0

        # The SDK's async streaming returns an async iterator directly.
        stream_iter = await client.aio.models.generate_content_stream(
            model=self.model_id,
            contents=cast(Any, contents),
            config=config,
        )
        async for partial in stream_iter:
            delta_parts: list[str] = []
            candidates = getattr(partial, "candidates", None) or []
            if candidates:
                candidate = candidates[0]
                fr = getattr(candidate, "finish_reason", None)
                if fr is not None:
                    fr_str = fr.name if hasattr(fr, "name") else str(fr)
                    finish_reason = _FINISH_REASON_MAP.get(fr_str, finish_reason)
                content = getattr(candidate, "content", None)
                parts = getattr(content, "parts", None) or [] if content else []
                for part in parts:
                    text_val = getattr(part, "text", None)
                    if text_val:
                        delta_parts.append(text_val)
                    fc = getattr(part, "function_call", None)
                    if fc and getattr(fc, "name", None):
                        args = getattr(fc, "args", None) or {}
                        tool_calls.append(
                            ToolCall(
                                name=fc.name,
                                arguments=(
                                    dict(args) if isinstance(args, dict) else {"value": args}
                                ),
                                tool_call_id=getattr(fc, "id", None) or fc.name,
                            )
                        )
            usage_metadata = getattr(partial, "usage_metadata", None)
            if usage_metadata is not None:
                usage = TokenUsage(
                    input_tokens=int(getattr(usage_metadata, "prompt_token_count", 0) or 0),
                    output_tokens=int(
                        getattr(usage_metadata, "candidates_token_count", 0) or 0
                    ),
                    cached_tokens=int(
                        getattr(usage_metadata, "cached_content_token_count", 0) or 0
                    ),
                )
                thinking_tokens = int(getattr(usage_metadata, "thoughts_token_count", 0) or 0)

            delta = "".join(delta_parts)
            if delta:
                text_chunks.append(delta)
                yield StreamChunk(delta=delta)

        final = LLMResponse(
            text="".join(text_chunks),
            tool_calls=tool_calls,
            usage=usage,
            thinking_tokens=thinking_tokens,
            model_id=self.model_id,
            finish_reason=finish_reason,
        )
        yield StreamChunk(delta="", response=final)

    def _build_contents(self, messages: Sequence[Message]) -> list[types.Content]:
        out: list[types.Content] = []
        for m in messages:
            role = _ROLE_MAP.get(m.role, "user")
            out.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=m.content)],
                )
            )
        return out

    def _build_config(
        self,
        *,
        system: str | None,
        tools: Sequence[ToolDef] | None,
        response_schema: dict[str, Any] | None,
        thinking: Any,
    ) -> types.GenerateContentConfig:
        config_kwargs: dict[str, Any] = {
            "max_output_tokens": self.max_output_tokens,
        }
        if system is not None:
            config_kwargs["system_instruction"] = system
        if response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = _flatten_schema(response_schema)
        if tools:
            config_kwargs["tools"] = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters=_flatten_schema(t.input_schema),
                        )
                        for t in tools
                    ]
                )
            ]
        budget = _thinking_budget(thinking if thinking is not None else self.thinking)
        if budget is not None:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=budget)
        return types.GenerateContentConfig(**config_kwargs)

    def _build_response(self, response: Any) -> LLMResponse:
        text_chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        finish_reason: FinishReason = "stop"

        candidates = getattr(response, "candidates", None) or []
        if candidates:
            candidate = candidates[0]
            fr = getattr(candidate, "finish_reason", None)
            fr_str: str
            if fr is None:
                fr_str = "STOP"
            elif hasattr(fr, "name"):
                fr_str = fr.name
            else:
                fr_str = str(fr)
            finish_reason = _FINISH_REASON_MAP.get(fr_str, "stop")

            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or [] if content else []
            for part in parts:
                text_val = getattr(part, "text", None)
                if text_val:
                    text_chunks.append(text_val)
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", None):
                    args = getattr(fc, "args", None) or {}
                    tool_calls.append(
                        ToolCall(
                            name=fc.name,
                            arguments=dict(args) if isinstance(args, dict) else {"value": args},
                            tool_call_id=getattr(fc, "id", None) or fc.name,
                        )
                    )

        usage_metadata = getattr(response, "usage_metadata", None)
        if usage_metadata is not None:
            usage = TokenUsage(
                input_tokens=int(getattr(usage_metadata, "prompt_token_count", 0) or 0),
                output_tokens=int(getattr(usage_metadata, "candidates_token_count", 0) or 0),
                cached_tokens=int(getattr(usage_metadata, "cached_content_token_count", 0) or 0),
            )
        else:
            usage = TokenUsage(input_tokens=0, output_tokens=0)

        thinking_tokens = 0
        if usage_metadata is not None:
            thinking_tokens = int(getattr(usage_metadata, "thoughts_token_count", 0) or 0)

        return LLMResponse(
            text="".join(text_chunks),
            tool_calls=tool_calls,
            usage=usage,
            thinking_tokens=thinking_tokens,
            model_id=self.model_id,
            finish_reason=finish_reason,
        )
