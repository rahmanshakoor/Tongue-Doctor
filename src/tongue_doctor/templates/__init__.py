"""Per-complaint reasoning templates.

Phase 0 ships the schema and loader. Per-complaint data (``chest_pain.yaml``, ...)
lands when each chapter is extracted from Stern. The schema is Stern-faithful:
role-tagged differential (Leading / Active-Most-Common / Active-Must-Not-Miss /
Other), per-diagnosis test characteristics, and a flat algorithm distilled from
the chapter's diagnostic-algorithm flowcharts.
"""

from tongue_doctor.templates.loader import TemplateNotFoundError, load_template
from tongue_doctor.templates.schema import (
    AlgorithmAction,
    AlgorithmBranch,
    AlgorithmStep,
    DecisionRule,
    DiagnosisHypothesis,
    FrameworkType,
    HypothesisRole,
    RedFlagPattern,
    Template,
    TestCharacteristic,
)

__all__ = [
    "AlgorithmAction",
    "AlgorithmBranch",
    "AlgorithmStep",
    "DecisionRule",
    "DiagnosisHypothesis",
    "FrameworkType",
    "HypothesisRole",
    "RedFlagPattern",
    "Template",
    "TemplateNotFoundError",
    "TestCharacteristic",
    "load_template",
]
