"""Prompt loader: front-matter parsing, version resolution, strict-undefined rendering."""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import UndefinedError
from pydantic import ValidationError

from tongue_doctor.prompts.loader import (
    PromptNotFoundError,
    PromptParseError,
    load_prompt,
)


def test_loads_echo_v1() -> None:
    rendered = load_prompt("_fixtures/echo", version=1, text="hello")
    assert "You said: hello" in rendered.text
    assert rendered.metadata.name == "echo"
    assert rendered.metadata.version == 1
    assert rendered.metadata.author == "Rahman Shakoor"
    assert "text" in rendered.metadata.inputs


def test_load_prompt_missing_file_raises() -> None:
    with pytest.raises(PromptNotFoundError):
        load_prompt("_fixtures/does_not_exist", version=1)


def test_load_prompt_strict_undefined() -> None:
    """Missing render kwargs raise UndefinedError — catches prompt ↔ context mismatch."""
    with pytest.raises(UndefinedError):
        load_prompt("_fixtures/echo", version=1)


def test_load_prompt_version_mismatch_raises() -> None:
    with pytest.raises(PromptNotFoundError):
        load_prompt("_fixtures/echo", version=99)


def test_load_prompt_no_front_matter_validation_fails(tmp_path: Path) -> None:
    """A prompt without ``name`` + ``version`` in front matter fails validation."""
    bad = tmp_path / "broken_v1.j2"
    bad.write_text("Just body, no front matter.\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_prompt("broken", version=1, prompts_dir=tmp_path)


def test_load_prompt_malformed_front_matter_raises(tmp_path: Path) -> None:
    """Front matter that is YAML but not a mapping is rejected."""
    bad = tmp_path / "scalar_v1.j2"
    bad.write_text("{# ---\n- item1\n- item2\n--- #}\nbody", encoding="utf-8")
    with pytest.raises(PromptParseError):
        load_prompt("scalar", version=1, prompts_dir=tmp_path)


def test_load_prompt_renders_nested_path(tmp_path: Path) -> None:
    nested = tmp_path / "agent" / "purpose_v1.j2"
    nested.parent.mkdir(parents=True)
    nested.write_text(
        "{# ---\nname: agent_purpose\nversion: 1\n--- #}\nHello {{ name }}",
        encoding="utf-8",
    )
    rendered = load_prompt("agent/purpose", 1, prompts_dir=tmp_path, name="World")
    assert rendered.text.strip() == "Hello World"
    assert rendered.metadata.name == "agent_purpose"
