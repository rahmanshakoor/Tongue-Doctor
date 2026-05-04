"""Snapshot tests for the 5 new agent prompts (Router, DA, MNM, Synth, Safety).

We anchor on stable structural landmarks (headers, vocabulary, key field names)
rather than byte-comparing the rendered text. The Reasoner v1 prompt has its own
snapshot test (see ``tests/unit/test_reasoner_prompt.py``).
"""

from __future__ import annotations

import json
from typing import Any

from tongue_doctor.prompts.loader import load_prompt
from tongue_doctor.templates import (
    AlgorithmAction,
    AlgorithmBranch,
    AlgorithmStep,
    DecisionRule,
    DiagnosisHypothesis,
    HypothesisRole,
    Template,
)
from tongue_doctor.templates import TestCharacteristic as DiagTest  # avoid pytest collection
from tongue_doctor.templates.schema import RedFlagPattern


def _fixture_template() -> Template:
    return Template(
        complaint="chest_pain",
        chapter_number=9,
        chapter_title="Chest Pain",
        framework_type="anatomical",
        framework_categories=["Cardiac", "Pulmonary", "Vascular", "GI", "MSK"],
        pivotal_points=["duration", "vital signs", "CHD risk factors"],
        decision_rules=[DecisionRule(name="HEART Score", purpose="Risk-stratify ED chest pain")],
        differential=[
            DiagnosisHypothesis(
                name="Stable angina",
                role=HypothesisRole.LEADING,
                treatment_classes=["antiplatelet", "statin", "beta-blocker"],
                evidence_based_diagnosis=[
                    DiagTest(
                        test_name="ECG stress test",
                        sensitivity=0.68,
                        specificity=0.77,
                        lr_positive=2.96,
                        lr_negative=0.42,
                        citation="Stern p.171",
                    )
                ],
            ),
            DiagnosisHypothesis(
                name="GERD",
                role=HypothesisRole.ACTIVE_MOST_COMMON,
                evidence_based_diagnosis=[
                    DiagTest(
                        test_name="PPI trial response",
                        sensitivity=0.78,
                        specificity=0.55,
                    )
                ],
            ),
            DiagnosisHypothesis(
                name="Acute MI",
                role=HypothesisRole.ACTIVE_MUST_NOT_MISS,
                evidence_based_diagnosis=[
                    DiagTest(
                        test_name="High-sensitivity troponin",
                        sensitivity=0.95,
                        specificity=0.90,
                        lr_positive=9.5,
                        lr_negative=0.06,
                        citation="Stern p.169",
                    )
                ],
            ),
            DiagnosisHypothesis(
                name="Aortic dissection",
                role=HypothesisRole.ACTIVE_MUST_NOT_MISS,
            ),
        ],
        algorithm=[
            AlgorithmStep(
                step_num=1,
                description="Assess vital signs",
                branches=[
                    AlgorithmBranch(
                        condition="Unstable",
                        action=AlgorithmAction.ESCALATE,
                        escalation_reason="ED triage",
                    )
                ],
            )
        ],
        red_flags=[
            RedFlagPattern(name="Hypotension", description="Concern for shock"),
        ],
        source_pages=(164, 185),
    )


_SAMPLE_REASONER_TRACE = """
# Step 1 — Problem List
- Crushing substernal chest pain, 30 minutes
- Diaphoresis
- Smoker, 30 pack-years

# Step 6 — Ranked Differential
- Leading Hypothesis: Acute MI
- Active Alternative — Most Common: GERD
- Active Alternative — Must Not Miss: Aortic dissection, PE

# Decision
- Status: committing
- Confidence band: high
"""


_SCORED_CHUNK_FIXTURE: list[dict[str, Any]] = [
    {
        "chunk": {
            "source": "stern",
            "citation": "Stern Ch. 9 p.169",
            "source_location": "p.169",
            "text": "ST-elevation MI requires immediate reperfusion therapy.",
            "authority_tier": 3,
        }
    }
]


class _DotDict(dict[str, Any]):
    """Light dict that supports both attribute and item access — for fixture chunks."""

    def __getattr__(self, key: str) -> Any:
        try:
            v = self[key]
        except KeyError as e:
            raise AttributeError(key) from e
        if isinstance(v, dict) and not isinstance(v, _DotDict):
            return _DotDict(v)
        return v


def _scored_hits() -> list[Any]:
    return [_DotDict(h) for h in _SCORED_CHUNK_FIXTURE]


# --- Router ---


def test_router_prompt_renders_with_catalog() -> None:
    catalog = [
        {"slug": "chest_pain", "chapter_number": 9, "chapter_title": "Chest Pain", "framework_type": "anatomical"},
        {"slug": "headache", "chapter_number": 20, "chapter_title": "Headache", "framework_type": "categorical"},
    ]
    rendered = load_prompt(
        "router/system",
        version=1,
        user_message="55M with crushing chest pain radiating to left arm",
        template_catalog=catalog,
    )
    assert rendered.metadata.name == "router_system"
    text = rendered.text
    assert "chest_pain" in text
    assert "headache" in text
    assert "Chapter 9 — Chest Pain".lower() in text.lower() or "9" in text
    assert "JSON" in text
    assert "requires_clarification" in text
    assert "55M with crushing chest pain" in text  # user_message echoed


def test_router_prompt_handles_empty_catalog() -> None:
    rendered = load_prompt(
        "router/system",
        version=1,
        user_message="not feeling well",
        template_catalog=[],
    )
    assert "not feeling well" in rendered.text


# --- Critic (replaces Devil's Advocate) ---


def test_critic_prompt_renders_with_full_context() -> None:
    template = _fixture_template()
    rendered = load_prompt(
        "critic/system",
        version=1,
        case_summary="55M crushing chest pain",
        reasoner_trace=_SAMPLE_REASONER_TRACE,
        template=template,
        retrieved_chunks=_scored_hits(),
        mnm_sweep=None,
        round=1,
        prior_rounds=[],
        current_defender="",
    )
    text = rendered.text.lower()
    # Bias taxonomy still appears
    assert "premature closure" in text
    assert "anchoring" in text
    assert "confirmation bias" in text
    # Must-not-miss diagnoses from the template are surfaced
    assert "aortic dissection" in text
    # Concession is allowed and named in the prompt
    assert "concession" in text or "no material errors" in text
    # Section headers from the structured-prose output spec
    assert "verdict on the leading hypothesis" in text
    assert "bottom line" in text


# --- Must-Not-Miss Sweeper ---


def test_must_not_miss_sweeper_prompt_renders_full_list() -> None:
    template = _fixture_template()
    rendered = load_prompt(
        "must_not_miss_sweeper/system",
        version=1,
        case_summary="55M crushing chest pain",
        reasoner_trace=_SAMPLE_REASONER_TRACE,
        template=template,
        retrieved_chunks=_scored_hits(),
    )
    text = rendered.text
    # All must-not-miss diagnoses are listed for the LLM to audit
    assert "Acute MI" in text
    assert "Aortic dissection" in text
    # LR- value from the troponin test characteristic is surfaced
    assert "0.06" in text
    # Output schema field names appear so the LLM matches them
    assert "considered_in_trace" in text
    assert "test_to_rule_out" in text
    assert "gap" in text


# --- Synthesizer ---


def test_synthesizer_prompt_renders_judge_verdict() -> None:
    """Synthesizer is now a pure renderer — its prompt receives the Judge's verdict
    as JSON and the reviewed_by status. No more da_critique / reasoner_trace inputs."""

    judge_verdict_json = json.dumps(
        {
            "leading_diagnosis": "Acute MI",
            "confidence_band": "moderate",
            "verdict_rationale": "Prosecutor's case dominates.",
            "active_alternatives": ["Aortic dissection"],
            "excluded_alternatives": [],
            "recommended_workup": [
                {
                    "step": "Troponin + ECG",
                    "rationale": "LR- 0.06",
                    "lr_plus_or_minus": "LR- 0.06",
                    "citation": "Stern p.169",
                }
            ],
            "red_flags_to_monitor": ["Hypotension"],
            "educational_treatment_classes": ["antiplatelet"],
            "citations": [],
            "closing_statement": "After dialectic, MI is the leading dx.",
            "rounds_held": 2,
        },
        indent=2,
    )
    rendered = load_prompt(
        "synthesizer/system",
        version=1,
        judge_verdict_json=judge_verdict_json,
        reviewed_by="pending",
    )
    text = rendered.text
    # Hard constraints surfaced
    assert "drug names" in text.lower() or "specific drug" in text.lower()
    assert "research demonstration" in text.lower()
    # Output schema field names appear
    assert "body_markdown" in text
    assert "research_demo_disclaimer" in text
    assert "citations" in text
    # Judge verdict embedded for rendering
    assert "Acute MI" in text
    assert "Troponin" in text


def test_synthesizer_prompt_signals_pending_review() -> None:
    rendered = load_prompt(
        "synthesizer/system",
        version=1,
        judge_verdict_json="{}",
        reviewed_by="pending",
    )
    assert "pending" in rendered.text


# --- Defender (replaces Prosecutor) ---


def test_defender_prompt_renders_with_full_context() -> None:
    template = _fixture_template()
    rendered = load_prompt(
        "defender/system",
        version=1,
        case_summary="55M crushing chest pain",
        reasoner_trace=_SAMPLE_REASONER_TRACE,
        template=template,
        retrieved_chunks=_scored_hits(),
        mnm_sweep=None,
        round=1,
        prior_rounds=[],
    )
    text = rendered.text
    # Steel-manning framing — but with explicit permission to concede
    assert "steel-man" in text.lower()
    assert "concession" in text.lower() or "cannot defend" in text.lower()
    # Section headers from the structured-prose output spec
    assert "Position" in text
    assert "Bottom line" in text
    # Round 1 = opening
    assert "opening round" in text.lower()


# --- Judge ---


def test_judge_prompt_renders_dialectic_transcript() -> None:
    template = _fixture_template()
    # The Judge now reads structured-prose Defender / Critic transcripts plus
    # the per-round convergence verdict, not the legacy ProsecutorArgument /
    # DevilsAdvocateOutput JSON args.
    round1 = _DotDict({
        "round": 1,
        "defender_markdown": (
            "## Defender — Round 1\n\n### Position\n"
            "I defend Acute MI with high confidence given crushing pain + risk factors.\n\n"
            "### Bottom line\nLeading hypothesis is well-supported."
        ),
        "critic_markdown": (
            "## Critic — Round 1\n\n### Verdict on the leading hypothesis\n"
            "I find no material errors. Aortic dissection has no tearing-pain support in the case.\n\n"
            "### Bottom line\nNo material concerns."
        ),
        "convergence_check": _DotDict({
            "converged": True,
            "reason": "Both sides agree the leading dx is well-supported.",
            "new_points_this_round": [],
        }),
    })
    mnm = _DotDict({
        "requires_escalation": False,
        "gaps_identified": ["Troponin not yet drawn"],
        "sweep": [
            _DotDict({
                "diagnosis": "Acute MI",
                "considered_in_trace": True,
                "test_to_rule_out": "Troponin",
                "lr_negative": 0.06,
                "test_result_in_case": "",
                "gap": "Troponin not yet drawn",
            }),
        ],
    })
    rendered = load_prompt(
        "judge/system",
        version=1,
        case_summary="55M crushing chest pain",
        reasoner_trace=_SAMPLE_REASONER_TRACE,
        template=template,
        retrieved_chunks=_scored_hits(),
        rounds=[round1],
        converged=True,
        mnm_sweep=mnm,
    )
    text = rendered.text
    # Sole-decider scope appears (case-insensitive — prompt uses "SOLE decider")
    assert "sole decider" in text.lower()
    # Output schema fields (renamed from prosecutor_*/devils_advocate_*)
    assert "leading_diagnosis" in text
    assert "confidence_band" in text
    assert "verdict_rationale" in text
    assert "closing_statement" in text
    assert "defender_strengths" in text
    assert "critic_strengths" in text
    assert "active_alternatives" in text
    # Round transcript injection
    assert "Round 1" in text
    assert "well-supported" in text
    assert "no material errors" in text


# --- Safety Reviewer ---


def test_safety_reviewer_prompt_lists_hard_checks() -> None:
    synthesis = {
        "leading_diagnosis": "Acute MI",
        "confidence_band": "high",
        "body_markdown": "Most likely: Acute MI...",
        "research_demo_disclaimer": "Research demonstration only.",
    }
    rendered = load_prompt(
        "safety_reviewer/system",
        version=1,
        case_summary="55M chest pain",
        synthesis_output_json=json.dumps(synthesis),
        reviewed_by="pending",
    )
    text = rendered.text.lower()
    assert "prescription_leak_detected" in rendered.text
    assert "phi_detected" in rendered.text
    assert "disclaimer_present" in rendered.text
    assert "citation_completeness" in rendered.text
    # The three-way verdict is named explicitly
    assert "approve" in text
    assert "revise" in text
    assert "refuse" in text
    # The synthesis is embedded for the reviewer to audit
    assert "Acute MI" in rendered.text
    # Pending-review cue is surfaced
    assert "pending" in rendered.text
