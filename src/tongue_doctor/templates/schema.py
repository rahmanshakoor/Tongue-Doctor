"""Per-complaint reasoning template schema (Stern-faithful, with algorithm).

Built from Stern, Cifu & Altkorn — *Symptoms to Diagnosis* (4th ed., 2020). The
schema captures Stern's actual chapter shape, not a flattened summary:

- The differential is **role-tagged** per Stern's exact taxonomy
  (Leading Hypothesis / Active Alternative — Most Common / Active Alternative —
  Must Not Miss / Other). Existing "must_not_miss" callers see a computed view.
- Every diagnosis carries its **evidence-based diagnostic test characteristics**
  (sens / spec / LR+ / LR-) so the Reasoner can do explicit Bayesian reasoning,
  not vibes.
- An **algorithm** field encodes the diagram-distilled procedure: a flat ordered
  list of decision steps with branches, derived from Stern's diagnostic-algorithm
  flowcharts (Figure N-1, N-2). Per project direction, the diagrams themselves
  are **not** persisted; the ``derived_from_figure`` string is provenance only.

Slug rule for ``complaint``: lowercase the Stern chapter title, replace
non-alphanumerics with ``_``, collapse repeats, strip leading/trailing ``_``.
Examples:

    "Chest Pain"            → "chest_pain"
    "Kidney Injury, Acute"  → "kidney_injury_acute"
    "AIDS/HIV Infection"    → "aids_hiv_infection"
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)

# --- Differential taxonomy (Stern's exact bucketing) ---


class HypothesisRole(StrEnum):
    """Stern's differential-diagnosis role assignment.

    Per Stern Ch. 1, every candidate diagnosis is placed in exactly one bucket:

    - ``LEADING``: most likely; test with high-specificity / high-LR+ to confirm.
    - ``ACTIVE_MOST_COMMON``: prevalent alternative actively on the table.
    - ``ACTIVE_MUST_NOT_MISS``: life-threatening alternative; test with
      high-sensitivity / very-low-LR- to exclude.
    - ``OTHER``: not excluded but not worth testing first.

    Stern's "Excluded" bucket is not modeled here; templates list candidates
    you would consider, not ones already ruled out for the chapter.
    """

    LEADING = "leading"
    ACTIVE_MOST_COMMON = "active_most_common"
    ACTIVE_MUST_NOT_MISS = "active_must_not_miss"
    OTHER = "other"


# --- Test-characteristic + decision-rule sub-schemas ---


class TestCharacteristic(BaseModel):
    """A diagnostic test's accuracy figures, drawn from Stern's
    "Evidence-Based Diagnosis" subsections."""

    model_config = ConfigDict(extra="forbid")

    test_name: str
    sensitivity: float | None = None  # 0.0-1.0
    specificity: float | None = None
    lr_positive: float | None = None
    lr_negative: float | None = None
    note: str = ""
    citation: str = ""


class DecisionRule(BaseModel):
    """A named clinical decision rule (HEART, POUNDing, Wells, etc.)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    purpose: str = ""
    inputs: list[str] = Field(default_factory=list)
    thresholds: list[str] = Field(default_factory=list)
    citation: str = ""


# --- Per-diagnosis structure ---


class DiagnosisHypothesis(BaseModel):
    """One candidate diagnosis, role-tagged per Stern's bucketing."""

    model_config = ConfigDict(extra="forbid")

    name: str
    role: HypothesisRole
    icd10: list[str] = Field(default_factory=list)
    pivotal_features_supporting: list[str] = Field(default_factory=list)
    fingerprint_findings: list[str] = Field(default_factory=list)
    textbook_presentation: str = ""
    disease_highlights: list[str] = Field(default_factory=list)
    evidence_based_diagnosis: list[TestCharacteristic] = Field(default_factory=list)
    treatment_classes: list[str] = Field(default_factory=list)
    notes: str = ""


# --- Algorithm distilled from Stern's flowchart figures ---


class AlgorithmAction(StrEnum):
    """What to do when a branch's condition fires."""

    NEXT_STEP = "next_step"
    ORDER_TEST = "order_test"
    CONFIRM = "confirm"
    EXCLUDE = "exclude"
    ESCALATE = "escalate"
    TREAT_EMPIRIC = "treat_empiric"
    REASSESS = "reassess"


class AlgorithmBranch(BaseModel):
    """One branch out of an algorithm step (e.g., Yes / No / Score >= 7)."""

    model_config = ConfigDict(extra="forbid")

    condition: str
    action: AlgorithmAction
    target_step: int | None = None
    target_diagnosis: str | None = None
    test_to_order: str | None = None
    escalation_reason: str | None = None
    notes: str = ""


class AlgorithmStep(BaseModel):
    """One node in the diagnostic-algorithm procedure.

    Steps are 1-indexed (matching Stern's flowchart convention). ``branches``
    must cover the meaningful conditions at this decision point; the schema
    does not enforce exhaustiveness because Stern's flowcharts sometimes leave
    the "default" path implicit in the prose.
    """

    model_config = ConfigDict(extra="forbid")

    step_num: int
    description: str
    rationale: str = ""
    branches: list[AlgorithmBranch] = Field(default_factory=list)
    derived_from_figure: str | None = None  # provenance only, e.g. "Stern Fig 9-2"


# --- Top-level Template ---


FrameworkType = Literal[
    "anatomical",
    "temporal",
    "physiologic",
    "categorical",
    "primary_vs_secondary",
    "mechanistic",
]


class RedFlagPattern(BaseModel):
    """Optional named red-flag pattern.

    Most chapters express red flags inline as ``ACTIVE_MUST_NOT_MISS``
    diagnoses; this class is preserved for back-compat and for chapters where
    a non-diagnostic red-flag *pattern* (e.g., "BP differential between arms")
    is explicitly highlighted.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    severity: str = "high"


class Template(BaseModel):
    """A per-complaint reasoning template.

    The data lives at ``src/tongue_doctor/templates/data/<complaint>.yaml``.
    Outputs that consume an unreviewed template (``reviewed_by == 'pending'``)
    must carry the research-demo disclaimer per ``SAFETY_INVARIANTS.md``.
    """

    model_config = ConfigDict(extra="forbid")

    complaint: str
    chapter_number: int
    chapter_title: str
    framework_type: FrameworkType
    framework_categories: list[str] = Field(default_factory=list)
    pivotal_points: list[str] = Field(default_factory=list)
    decision_rules: list[DecisionRule] = Field(default_factory=list)
    differential: list[DiagnosisHypothesis] = Field(default_factory=list)
    algorithm: list[AlgorithmStep] = Field(default_factory=list)
    red_flags: list[RedFlagPattern] = Field(default_factory=list)
    source_pages: tuple[int, int]
    version: int = 1
    reviewed_by: str = "pending"
    reviewed_at: str | None = None
    notes: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def must_not_miss(self) -> list[str]:
        """Stern's must-not-miss bucket — derived from role-tagged differential."""

        return [
            d.name
            for d in self.differential
            if d.role == HypothesisRole.ACTIVE_MUST_NOT_MISS
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def leading_hypotheses(self) -> list[str]:
        return [
            d.name for d in self.differential if d.role == HypothesisRole.LEADING
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def educational_treatment_classes(self) -> list[str]:
        """Flattened, deduplicated view across all diagnoses (educational only)."""

        seen: set[str] = set()
        out: list[str] = []
        for d in self.differential:
            for tc in d.treatment_classes:
                if tc in seen:
                    continue
                seen.add(tc)
                out.append(tc)
        return out

    @model_validator(mode="after")
    def _validate_algorithm_targets(self) -> Template:
        """Reject dangling ``target_step`` references in algorithm branches."""

        valid_steps = {s.step_num for s in self.algorithm}
        target_actions = {AlgorithmAction.NEXT_STEP, AlgorithmAction.REASSESS}
        for step in self.algorithm:
            for branch in step.branches:
                if (
                    branch.action in target_actions
                    and branch.target_step is not None
                    and branch.target_step not in valid_steps
                ):
                    raise ValueError(
                        f"Algorithm step {step.step_num} branch "
                        f"{branch.condition!r} references missing "
                        f"target_step={branch.target_step}; valid steps "
                        f"are {sorted(valid_steps)}."
                    )
        return self
