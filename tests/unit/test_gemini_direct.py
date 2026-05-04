"""Unit tests for :class:`GeminiDirectClient`.

The Gemini SDK is mocked so these tests exercise our adapter logic — message-role
mapping, structured-output schema flattening, finish-reason mapping, usage parsing —
without making real API calls.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tongue_doctor.models.base import Message, ToolDef
from tongue_doctor.models.gemini_direct import (
    GeminiDirectClient,
    _flatten_schema,
    _thinking_budget,
)

# --- _flatten_schema ---


def test_flatten_schema_inlines_refs() -> None:
    schema = {
        "type": "object",
        "properties": {
            "alt": {"$ref": "#/$defs/Alt"},
            "alts": {"type": "array", "items": {"$ref": "#/$defs/Alt"}},
        },
        "required": ["alt"],
        "$defs": {"Alt": {"type": "object", "properties": {"name": {"type": "string"}}}},
    }
    flat = _flatten_schema(schema)
    assert "$defs" not in flat
    assert flat["properties"]["alt"]["type"] == "object"
    assert flat["properties"]["alt"]["properties"]["name"]["type"] == "string"
    assert flat["properties"]["alts"]["items"]["properties"]["name"]["type"] == "string"


def test_flatten_schema_strips_additional_properties() -> None:
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "additionalProperties": False,
    }
    flat = _flatten_schema(schema)
    assert "additionalProperties" not in flat


def test_flatten_schema_handles_unresolvable_ref() -> None:
    schema = {"type": "object", "properties": {"x": {"$ref": "#/$defs/Missing"}}}
    flat = _flatten_schema(schema)
    # Falls back to a permissive object placeholder rather than crashing.
    assert flat["properties"]["x"] == {"type": "object"}


def test_flatten_schema_returns_input_unchanged_when_not_dict() -> None:
    assert _flatten_schema("not a dict") == "not a dict"  # type: ignore[arg-type]


def test_flatten_schema_collapses_integer_enums_to_min_max() -> None:
    """Gemini rejects integer enums; the helper coerces them to min/max bounds."""

    schema = {
        "type": "object",
        "properties": {
            "tier": {"type": "integer", "enum": [1, 2, 3]},
        },
    }
    flat = _flatten_schema(schema)
    assert "enum" not in flat["properties"]["tier"]
    assert flat["properties"]["tier"]["minimum"] == 1
    assert flat["properties"]["tier"]["maximum"] == 3


def test_flatten_schema_preserves_string_enums() -> None:
    """String enums are valid in Gemini's schema and pass through unchanged."""

    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["approve", "revise", "refuse"]},
        },
    }
    flat = _flatten_schema(schema)
    assert flat["properties"]["verdict"]["enum"] == ["approve", "revise", "refuse"]


# --- _thinking_budget ---


@pytest.mark.parametrize(
    "thinking,expected",
    [
        (None, None),
        (1024, 1024),
        ({"budget_tokens": 8000}, 8000),
        ({"thinking_budget": 4096}, 4096),
        ("low", 1024),
        ("medium", 4096),
        ("high", 16000),
        ("nonsense", None),
        ({"unrelated": "thing"}, None),
    ],
)
def test_thinking_budget_coercion(thinking: Any, expected: int | None) -> None:
    assert _thinking_budget(thinking) == expected


# --- generate(): SDK mocking ---


def _fake_response(*, text: str = "", finish_reason: str = "STOP", function_calls: list[Any] | None = None) -> MagicMock:
    parts: list[MagicMock] = []
    if text:
        p = MagicMock()
        p.text = text
        p.function_call = None
        parts.append(p)
    for fc in function_calls or []:
        p = MagicMock()
        p.text = None
        p.function_call = fc
        parts.append(p)

    candidate = MagicMock()
    fr = MagicMock()
    fr.name = finish_reason
    candidate.finish_reason = fr
    candidate.content = MagicMock(parts=parts)

    response = MagicMock()
    response.candidates = [candidate]
    response.usage_metadata = MagicMock(
        prompt_token_count=42,
        candidates_token_count=21,
        cached_content_token_count=0,
        thoughts_token_count=7,
    )
    return response


@pytest.fixture(autouse=True)
def _clear_client_cache() -> None:
    # The cached genai.Client may be initialized in earlier tests with no env var;
    # clearing here keeps each test independent.
    from tongue_doctor.models.gemini_direct import _client

    _client.cache_clear()


@pytest.mark.asyncio
async def test_generate_text_only_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(return_value=_fake_response(text="hello world"))
    fake_client = MagicMock(aio=fake_aio)

    with patch("tongue_doctor.models.gemini_direct.genai.Client", return_value=fake_client):
        client = GeminiDirectClient(model_id="gemini-3.1-pro-preview")
        response = await client.generate([Message(role="user", content="hi")])

    assert response.text == "hello world"
    assert response.finish_reason == "stop"
    assert response.usage.input_tokens == 42
    assert response.usage.output_tokens == 21
    assert response.thinking_tokens == 7
    assert response.model_id == "gemini-3.1-pro-preview"

    # Verify the SDK call args
    fake_aio.models.generate_content.assert_awaited_once()
    kwargs = fake_aio.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-3.1-pro-preview"
    contents = kwargs["contents"]
    assert len(contents) == 1
    assert contents[0].role == "user"


@pytest.mark.asyncio
async def test_generate_maps_assistant_role_to_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(return_value=_fake_response(text="ok"))
    fake_client = MagicMock(aio=fake_aio)

    with patch("tongue_doctor.models.gemini_direct.genai.Client", return_value=fake_client):
        client = GeminiDirectClient(model_id="gemini-3.1-pro-preview")
        await client.generate(
            [
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
                Message(role="user", content="how are you?"),
            ]
        )

    contents = fake_aio.models.generate_content.call_args.kwargs["contents"]
    assert [c.role for c in contents] == ["user", "model", "user"]


@pytest.mark.asyncio
async def test_generate_with_response_schema_sets_json_mime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(return_value=_fake_response(text='{"x":1}'))
    fake_client = MagicMock(aio=fake_aio)

    schema = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
        "additionalProperties": False,  # must be stripped
    }
    with patch("tongue_doctor.models.gemini_direct.genai.Client", return_value=fake_client):
        client = GeminiDirectClient(model_id="gemini-3.1-pro-preview")
        await client.generate(
            [Message(role="user", content="emit json")],
            response_schema=schema,
        )

    config = fake_aio.models.generate_content.call_args.kwargs["config"]
    # The config is a GenerateContentConfig; assert via its attributes.
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None
    flat = config.response_schema
    assert "additionalProperties" not in flat
    assert flat["properties"]["x"]["type"] == "integer"


@pytest.mark.asyncio
async def test_generate_with_system_passes_system_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(return_value=_fake_response(text="ack"))
    fake_client = MagicMock(aio=fake_aio)

    with patch("tongue_doctor.models.gemini_direct.genai.Client", return_value=fake_client):
        client = GeminiDirectClient(model_id="gemini-3.1-pro-preview")
        await client.generate(
            [Message(role="user", content="hi")],
            system="You are a clinician.",
        )

    config = fake_aio.models.generate_content.call_args.kwargs["config"]
    assert config.system_instruction == "You are a clinician."


@pytest.mark.asyncio
async def test_generate_with_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    fake_fc = MagicMock()
    fake_fc.name = "lookup"
    fake_fc.args = {"q": "kidney stone"}
    fake_fc.id = "call_1"

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(
        return_value=_fake_response(text="", finish_reason="STOP", function_calls=[fake_fc]),
    )
    fake_client = MagicMock(aio=fake_aio)

    tool = ToolDef(
        name="lookup",
        description="look up a clinical fact",
        input_schema={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
    )
    with patch("tongue_doctor.models.gemini_direct.genai.Client", return_value=fake_client):
        client = GeminiDirectClient(model_id="gemini-3.1-pro-preview")
        response = await client.generate(
            [Message(role="user", content="find a fact")],
            tools=[tool],
        )

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "lookup"
    assert response.tool_calls[0].arguments == {"q": "kidney stone"}


@pytest.mark.asyncio
async def test_generate_finish_reason_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(
        return_value=_fake_response(text="trimmed", finish_reason="MAX_TOKENS"),
    )
    fake_client = MagicMock(aio=fake_aio)

    with patch("tongue_doctor.models.gemini_direct.genai.Client", return_value=fake_client):
        client = GeminiDirectClient(model_id="gemini-3.1-pro-preview")
        response = await client.generate([Message(role="user", content="long")])

    assert response.finish_reason == "length"


@pytest.mark.asyncio
async def test_generate_raises_when_env_var_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    client = GeminiDirectClient(model_id="gemini-3.1-pro-preview")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        await client.generate([Message(role="user", content="hi")])


def test_factory_dispatches_gemini_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_client('reasoner')`` returns a GeminiDirectClient when models.yaml says so."""

    # Sanity: verify dispatch by overriding settings cache with a stub.
    from unittest.mock import patch as _patch

    from tongue_doctor.models import get_client
    from tongue_doctor.settings import reset_settings_cache

    fake_settings = MagicMock()
    fake_settings.models = {
        "reasoner": {
            "provider": "gemini_direct",
            "model": "gemini-3.1-pro-preview",
            "thinking": "medium",
            "max_output_tokens": 4096,
        }
    }
    fake_settings.gcp.region = "us"
    fake_settings.gcp.fallback_region = "us"
    fake_settings.gcp.project = ""

    with _patch("tongue_doctor.models.get_settings", return_value=fake_settings):
        client = get_client("reasoner")

    assert isinstance(client, GeminiDirectClient)
    assert client.model_id == "gemini-3.1-pro-preview"
    reset_settings_cache()
