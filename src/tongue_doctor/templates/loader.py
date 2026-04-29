"""Loader for per-complaint :class:`Template` YAML files.

Resolves ``src/tongue_doctor/templates/data/<complaint>.yaml`` and validates against
:class:`Template`. Raises :class:`TemplateNotFoundError` when missing.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tongue_doctor.templates.schema import Template

_DATA_DIR = Path(__file__).resolve().parent / "data"


class TemplateNotFoundError(FileNotFoundError):
    """The named complaint template does not exist."""


def load_template(complaint: str, *, data_dir: Path | None = None) -> Template:
    """Load and validate a complaint template by name."""
    base = data_dir or _DATA_DIR
    path = base / f"{complaint}.yaml"
    if not path.is_file():
        raise TemplateNotFoundError(
            f"Complaint template {complaint!r} not found at {path}. "
            "Templates land alongside their respective Phase work."
        )
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Template {path} did not parse to a mapping.")
    return Template.model_validate(raw)
