"""Prompt loader subpackage.

The repo-root ``prompts/`` directory holds the Jinja artifacts; this subpackage holds
the Python loader. The two share a name intentionally — see
``docs/PROMPT_PROCESS.md`` and ADR 0001.
"""

from tongue_doctor.prompts.loader import (
    PromptMetadata,
    PromptNotFoundError,
    PromptParseError,
    RenderedPrompt,
    load_prompt,
)

__all__ = [
    "PromptMetadata",
    "PromptNotFoundError",
    "PromptParseError",
    "RenderedPrompt",
    "load_prompt",
]
