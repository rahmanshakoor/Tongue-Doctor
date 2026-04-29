"""Jinja2-based prompt loader with YAML front matter.

A prompt file looks like:

.. code-block:: jinja2

   {# ---
   name: reasoner_system
   version: 1
   created: 2026-04-29
   author: Rahman Shakoor
   notes: "Stern ch.1 diagnostic procedure, paraphrased."
   inputs: [loaded_templates, case_state]
   --- #}

   You are a clinical reasoning agent operating in a research demonstration...

The loader resolves files under ``Settings.prompts_dir`` (default: repo-root ``prompts/``)
and renders the body with caller-supplied kwargs. Missing variables raise
:class:`jinja2.UndefinedError` thanks to :class:`StrictUndefined` — this catches prompt
↔ context mismatches at render time rather than producing silently-wrong outputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field

from tongue_doctor.settings import get_settings


class PromptMetadata(BaseModel):
    """Parsed front-matter from a Jinja prompt file.

    ``created`` is typed ``Any`` because YAML 1.1 parses bare ``YYYY-MM-DD`` as
    :class:`datetime.date`; we accept either a string or a date here without coercing.
    Quote the date in front matter if a stable string is required.
    """

    model_config = ConfigDict(extra="allow", frozen=True, arbitrary_types_allowed=True)

    name: str
    version: int
    created: Any = None
    author: str | None = None
    notes: str = ""
    inputs: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class RenderedPrompt:
    """The final rendered prompt text together with its parsed metadata."""

    text: str
    metadata: PromptMetadata


class PromptNotFoundError(FileNotFoundError):
    """The named prompt file does not exist."""


class PromptParseError(ValueError):
    """Front-matter could not be parsed into a mapping."""


_FRONT_MATTER_RE = re.compile(
    r"\A\s*\{#\s*---\s*\n(?P<yaml>.*?)\n---\s*#\}\s*\n?",
    re.DOTALL,
)


def _split_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    m = _FRONT_MATTER_RE.match(raw)
    if not m:
        return {}, raw
    body = raw[m.end() :]
    yaml_text = m.group("yaml")
    parsed = yaml.safe_load(yaml_text)
    if parsed is None:
        return {}, body
    if not isinstance(parsed, dict):
        raise PromptParseError(f"Front matter did not parse to a mapping: {parsed!r}")
    return parsed, body


def _resolve_path(name: str, version: int, base_dir: Path) -> Path:
    name_path = Path(name)
    parent = name_path.parent
    leaf = f"{name_path.name}_v{version}.j2"
    return base_dir / parent / leaf


def load_prompt(
    name: str,
    /,
    version: int,
    *,
    prompts_dir: Path | None = None,
    **render_kwargs: Any,
) -> RenderedPrompt:
    """Load, parse, and render a prompt.

    ``name`` is a slash-delimited path with no extension and no ``_vN`` suffix
    (e.g. ``"reasoner/system"``). With ``version=1`` it resolves to
    ``<prompts_dir>/reasoner/system_v1.j2``.

    ``name`` is positional-only so a prompt can render ``{{ name }}`` and the caller can
    pass ``name=...`` as a render kwarg without colliding with this parameter.
    ``version`` accepts either positional or keyword form.
    """
    base_dir = prompts_dir or get_settings().prompts_dir
    full = _resolve_path(name, version, base_dir)
    if not full.is_file():
        raise PromptNotFoundError(f"Prompt {name!r} v{version} not found at {full}")

    raw = full.read_text(encoding="utf-8")
    front_matter, body = _split_front_matter(raw)
    metadata = PromptMetadata.model_validate(front_matter)

    env = Environment(
        loader=FileSystemLoader(str(base_dir)),
        autoescape=False,
        undefined=StrictUndefined,
    )
    template = env.from_string(body)
    rendered = template.render(**render_kwargs)
    return RenderedPrompt(text=rendered, metadata=metadata)
