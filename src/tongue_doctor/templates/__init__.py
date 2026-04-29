"""Per-complaint reasoning templates.

Phase 0 ships the schema and loader. Per-complaint data (``chest_pain.yaml``, ...)
lands alongside its Phase work. Templates capture must-not-miss lists, red-flag
patterns, pivotal features, default workup, and educational treatment classes —
extracted from Stern et al. and cross-validated against Harrison's / UpToDate /
specialty guidelines.
"""

from tongue_doctor.templates.loader import TemplateNotFoundError, load_template
from tongue_doctor.templates.schema import RedFlagPattern, Template

__all__ = [
    "RedFlagPattern",
    "Template",
    "TemplateNotFoundError",
    "load_template",
]
