"""Per-agent typed output schemas.

These Pydantic models are the agents' structured outputs. Each model is the
``response_schema`` we pass to :meth:`LLMClient.generate`; the LLM is forced to
emit JSON that matches it. Agents then ``.model_validate_json()`` the response.

The Reasoner is intentionally not represented here — its output is the structured
markdown trace defined by ``prompts/reasoner/system_v1.j2`` (named section headers,
Stern vocabulary). Downstream agents read that trace as a string.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# --- Router ---


class RouterOutput(BaseModel):
    """Router's chief-complaint → template-slug decision.

    ``template_slug`` is the **primary** chapter — the one whose framework, algorithm,
    and source pages drive the rest of the loop.

    ``ancillary_template_slugs`` is the list of additional Stern chapters whose
    differentials, must-not-miss diagnoses, decision rules, and pivotal points should
    be **merged into** the primary's content before the Reasoner runs. This is how
    multi-system cases (head + chest + GI + general) get reasoned over the union
    of relevant chapters instead of the single-chapter default. Keep it ≤ 5;
    leave empty for clear single-system cases.

    ``confidence`` is the router's self-assessed certainty (0.0-1.0) on the primary.
    ``requires_clarification`` short-circuits the loop when the user message is too
    vague to route — the orchestrator then asks the ``clarification_question``.

    All free-text fields carry ``max_length`` caps that propagate into the Gemini
    JSON ``response_schema``. The cap prevents repetition / degenerate-generation
    collapses where a model gets stuck inside a string field and emits a thesaurus
    until ``max_output_tokens`` is hit. The numbers are sized for the longest
    legitimate output we've seen in practice + ~50% headroom.
    """

    model_config = ConfigDict(extra="forbid")

    template_slug: str = Field(max_length=128)
    chapter_number: int
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=600)
    ancillary_template_slugs: list[str] = Field(default_factory=list, max_length=5)
    fallback_slug: str | None = Field(default=None, max_length=128)
    requires_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=400)


# --- Must-Not-Miss Sweeper ---


class MustNotMissEntry(BaseModel):
    """One must-not-miss diagnosis evaluated against the case."""

    model_config = ConfigDict(extra="forbid")

    diagnosis: str = Field(max_length=300)
    considered_in_trace: bool
    test_to_rule_out: str = Field(max_length=500)
    lr_negative: float | None = None
    test_result_in_case: str = Field(default="", max_length=600)
    gap: str = Field(default="", max_length=600)


class MustNotMissSweep(BaseModel):
    """Audit of every ``ACTIVE_MUST_NOT_MISS`` diagnosis from the template."""

    model_config = ConfigDict(extra="forbid")

    sweep: list[MustNotMissEntry] = Field(default_factory=list, max_length=25)
    gaps_identified: list[str] = Field(default_factory=list, max_length=12)
    requires_escalation: bool = False
    summary: str = Field(default="", max_length=1000)


# --- Synthesizer ---


ConfidenceBand = Literal["low", "moderate", "high"]


class WorkupItem(BaseModel):
    """One item in the recommended workup."""

    model_config = ConfigDict(extra="forbid")

    step: str = Field(max_length=300)
    rationale: str = Field(max_length=800)
    lr_plus_or_minus: str | None = Field(default=None, max_length=120)
    citation: str | None = Field(default=None, max_length=300)


class SynthesisCitation(BaseModel):
    """A citation rendered in the synthesis (matches :class:`schemas.output.Citation`).

    ``authority_tier`` is bounded to 1-3 via ``Field(ge=1, le=3)`` rather than
    ``Literal[1, 2, 3]`` because Gemini's structured-output schema only accepts
    string enums; integer enums fail with ``Input should be a valid string`` at
    schema-validation time. The orchestrator copies the value into the locked-down
    :class:`schemas.output.Citation` (which keeps the Literal) and Pydantic's
    Literal coercion accepts 1, 2, or 3 there.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=120)
    source: str = Field(max_length=120)
    citation: str = Field(max_length=400)
    authority_tier: int = Field(ge=1, le=3)


class SynthesisOutput(BaseModel):
    """Pure rendering of the Judge's verdict for the user-facing surface.

    The Synthesizer **does not make clinical decisions** — those are the Judge's
    sole responsibility. Per the "no overlapping prompts" directive, this output
    carries only the rendered ``body_markdown``, the disclaimer text, and any
    citations the renderer felt useful to surface. The leading diagnosis,
    confidence band, recommended workup, active/excluded alternatives, treatment
    classes, and red flags live on :class:`JudgeVerdict` and are read from there.

    ``body_markdown`` cap is generous (8000) — it's the user-facing answer and
    can legitimately be a several-paragraph differential summary with workup,
    red flags, citations. Anything longer is almost certainly degenerate.
    """

    model_config = ConfigDict(extra="forbid")

    body_markdown: str = Field(max_length=8000)
    research_demo_disclaimer: str = Field(max_length=600)
    citations: list[SynthesisCitation] = Field(default_factory=list, max_length=20)


# --- Safety Reviewer ---


SafetyVerdictKind = Literal["approve", "revise", "refuse"]
CitationCompleteness = Literal["complete", "partial", "missing"]


class SafetyVerdict(BaseModel):
    """Post-hoc safety review of the synthesis."""

    model_config = ConfigDict(extra="forbid")

    verdict: SafetyVerdictKind
    refusal_reason: str | None = Field(default=None, max_length=600)
    required_fixes: list[str] = Field(default_factory=list, max_length=10)
    prescription_leak_detected: bool = False
    phi_detected: bool = False
    disclaimer_present: bool = False
    citation_completeness: CitationCompleteness = "partial"
    summary: str = Field(default="", max_length=400)


# --- Judge (weighs Defender↔Critic transcripts, issues final verdict) ---


class JudgeVerdict(BaseModel):
    """Judge's final ruling after the convergence dialectic.

    The verdict supersedes the Reasoner's initial leading hypothesis when the
    Critic's case dominates. The ``closing_statement`` is the Synthesizer's input
    for the user-facing body.
    """

    model_config = ConfigDict(extra="forbid")

    leading_diagnosis: str = Field(max_length=300)
    confidence_band: ConfidenceBand
    # The Judge is the sole decider and tends to be (legitimately) verbose. Caps
    # are sized for thorough clinical reasoning + the longest legitimate
    # closing-paragraph summary we want to render to the user. Anti-degeneration
    # ceiling stays in place — runaway repetition would still hit these.
    verdict_rationale: str = Field(max_length=4000)
    defender_strengths: list[str] = Field(default_factory=list, max_length=10)
    defender_weaknesses: list[str] = Field(default_factory=list, max_length=10)
    critic_strengths: list[str] = Field(default_factory=list, max_length=10)
    critic_weaknesses: list[str] = Field(default_factory=list, max_length=10)
    active_alternatives: list[str] = Field(default_factory=list, max_length=10)
    excluded_alternatives: list[str] = Field(default_factory=list, max_length=10)
    recommended_workup: list[WorkupItem] = Field(default_factory=list, max_length=15)
    red_flags_to_monitor: list[str] = Field(default_factory=list, max_length=12)
    educational_treatment_classes: list[str] = Field(default_factory=list, max_length=12)
    citations: list[SynthesisCitation] = Field(default_factory=list, max_length=25)
    closing_statement: str = Field(max_length=3000)
    rounds_held: int = Field(ge=1, default=1)


class ConvergenceCheck(BaseModel):
    """The convergence checker's per-round verdict.

    Tiny JSON output (bool + short reason + list) is safe from field-stuffing
    degeneration because the structure is constrained to small atomic answers.
    Rendered into the trace so the Judge / CLI can see *why* the loop stopped
    where it did.
    """

    model_config = ConfigDict(extra="forbid")

    converged: bool
    reason: str = Field(max_length=400)
    new_points_this_round: list[str] = Field(default_factory=list, max_length=6)


class DialecticRound(BaseModel):
    """A single round of the Defender ↔ Critic convergence dialectic.

    Both transcripts are free-form structured markdown (not JSON) — the agents
    follow a section-header template internally but the orchestrator stores
    the prose verbatim. The Judge reads this prose directly. The
    ``convergence_check`` is set on every round; ``converged=True`` indicates
    the loop terminated after this round.
    """

    model_config = ConfigDict(extra="forbid")

    round: int = Field(ge=1)
    defender_markdown: str = Field(max_length=12000)
    critic_markdown: str = Field(max_length=12000)
    convergence_check: ConvergenceCheck | None = None


__all__ = [
    "CitationCompleteness",
    "ConfidenceBand",
    "ConvergenceCheck",
    "DialecticRound",
    "JudgeVerdict",
    "MustNotMissEntry",
    "MustNotMissSweep",
    "RouterOutput",
    "SafetyVerdict",
    "SafetyVerdictKind",
    "SynthesisCitation",
    "SynthesisOutput",
    "WorkupItem",
]
