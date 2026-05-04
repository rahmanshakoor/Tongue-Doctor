"""Shared runtime helpers for the 6 concrete agents.

Each agent loads its prompt, calls the LLM, and parses a typed response. This
module owns that boilerplate so the agents themselves stay short.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from tongue_doctor.models.base import LLMClient, LLMResponse, Message, StreamChunk
from tongue_doctor.prompts.loader import load_prompt
from tongue_doctor.templates.loader import _DATA_DIR
from tongue_doctor.templates.schema import Template

# Callback signature shared by streaming helpers: receives one text delta at a
# time. Sync callbacks are wrapped via the helper below; async callbacks are
# awaited directly. Returning a coroutine is fine — both shapes are accepted.
ChunkCallback = Callable[[str], Awaitable[None] | None]


def template_catalog(data_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return ``[{slug, chapter_number, chapter_title, framework_type}, …]`` for every template on disk.

    The catalog is read once at agent init; templates are stable across a process.
    """

    base = data_dir or _DATA_DIR
    out: list[dict[str, Any]] = []
    if not base.is_dir():
        return out
    for path in sorted(base.glob("*.yaml")):
        try:
            import yaml

            with path.open(encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            slug = raw.get("complaint", path.stem)
            ch = raw.get("chapter_number")
            title = raw.get("chapter_title", "")
            framework = raw.get("framework_type", "")
            out.append(
                {
                    "slug": slug,
                    "chapter_number": int(ch) if ch is not None else 0,
                    "chapter_title": title,
                    "framework_type": framework,
                }
            )
        except (OSError, yaml.YAMLError):
            continue
    return out


def _safe_parse(
    model: type[BaseModel],
    text: str,
    *,
    finish_reason: str = "",
) -> BaseModel:
    """Parse JSON into a Pydantic model, with a helpful error if the model misbehaves."""

    if finish_reason == "length":
        raise ValueError(
            f"LLM output for {model.__name__} was truncated (finish_reason=length). "
            f"The agent's max_output_tokens is too low for this prompt — bump it in "
            f"config/models.yaml.\nraw text (truncated): "
            f"{text[:500]}{'…' if len(text) > 500 else ''}"
        )
    try:
        return model.model_validate_json(text)
    except ValidationError as e:
        raise ValueError(
            f"LLM output failed schema validation for {model.__name__}: {e}\n"
            f"raw text: {text[:500]}{'…' if len(text) > 500 else ''}"
        ) from e


async def _emit(on_chunk: ChunkCallback | None, delta: str) -> None:
    """Invoke ``on_chunk`` with ``delta``, awaiting if it returns a coroutine."""

    if on_chunk is None or not delta:
        return
    result = on_chunk(delta)
    if result is not None:
        await result


async def _stream_or_call(
    client: LLMClient,
    *,
    rendered_text: str,
    response_schema: dict[str, Any] | None,
    on_chunk: ChunkCallback | None,
) -> tuple[LLMResponse, int]:
    """Run a single LLM request, streaming when the client supports it.

    When ``on_chunk`` is given **and** the client implements ``generate_stream``,
    text deltas are forwarded to ``on_chunk`` as they arrive. Otherwise we fall
    back to a single :meth:`LLMClient.generate` call and emit the full text as
    one delta — same callback contract, no streaming dramatics.
    """

    t0 = time.perf_counter()
    stream_fn = getattr(client, "generate_stream", None)
    if on_chunk is not None and callable(stream_fn):
        final_response: LLMResponse | None = None
        async for chunk in stream_fn(
            messages=[Message(role="user", content=rendered_text)],
            response_schema=response_schema,
        ):
            assert isinstance(chunk, StreamChunk)
            if chunk.delta:
                await _emit(on_chunk, chunk.delta)
            if chunk.response is not None:
                final_response = chunk.response
        if final_response is None:
            raise RuntimeError(
                "generate_stream completed without yielding a final aggregated response"
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return final_response, latency_ms

    response = await client.generate(
        messages=[Message(role="user", content=rendered_text)],
        response_schema=response_schema,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    if on_chunk is not None and response.text:
        await _emit(on_chunk, response.text)
    return response, latency_ms


async def call_structured(
    client: LLMClient,
    *,
    prompt_name: str,
    prompt_version: int,
    prompt_kwargs: dict[str, Any],
    response_model: type[BaseModel],
    prompts_dir: Path | None = None,
    on_chunk: ChunkCallback | None = None,
) -> tuple[BaseModel, LLMResponse, int]:
    """Render the prompt, call the LLM with a JSON response_schema, return ``(parsed, raw, latency_ms)``.

    When ``on_chunk`` is given the client streams (if supported) and forwards
    every text delta — for structured output that means raw JSON tokens, which
    is what the chat-mode CLI surfaces under each agent's panel before parsing.
    """

    rendered = load_prompt(
        prompt_name,
        prompt_version,
        prompts_dir=prompts_dir,
        **prompt_kwargs,
    )
    response, latency_ms = await _stream_or_call(
        client,
        rendered_text=rendered.text,
        response_schema=response_model.model_json_schema(),
        on_chunk=on_chunk,
    )
    parsed = _safe_parse(
        response_model,
        response.text,
        finish_reason=response.finish_reason,
    )
    return parsed, response, latency_ms


async def call_text(
    client: LLMClient,
    *,
    prompt_name: str,
    prompt_version: int,
    prompt_kwargs: dict[str, Any],
    prompts_dir: Path | None = None,
    on_chunk: ChunkCallback | None = None,
) -> tuple[str, LLMResponse, int]:
    """Render the prompt, call the LLM for free-form text (e.g. Reasoner), return ``(text, raw, latency_ms)``."""

    rendered = load_prompt(
        prompt_name,
        prompt_version,
        prompts_dir=prompts_dir,
        **prompt_kwargs,
    )
    response, latency_ms = await _stream_or_call(
        client,
        rendered_text=rendered.text,
        response_schema=None,
        on_chunk=on_chunk,
    )
    return response.text, response, latency_ms


def usage_metadata(response: LLMResponse) -> dict[str, Any]:
    """Build the ``AgentResult.metadata`` payload from an LLMResponse."""

    return {
        "model_id": response.model_id,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cached_tokens": response.usage.cached_tokens,
        "thinking_tokens": response.thinking_tokens,
        "finish_reason": response.finish_reason,
    }


__all__ = [
    "ChunkCallback",
    "Template",
    "call_structured",
    "call_text",
    "template_catalog",
    "usage_metadata",
]
