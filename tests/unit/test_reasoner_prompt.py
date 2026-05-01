"""Snapshot test for the Reasoner system prompt (v1).

Renders the prompt against a minimal fixture template + case_state and asserts
on stable structural anchors. We don't byte-compare the whole rendered output
because Jinja whitespace and timestamps drift; we anchor on the section headers
and the Stern-derived vocabulary that downstream agents depend on.
"""

from __future__ import annotations

from tongue_doctor.prompts.loader import load_prompt
from tongue_doctor.templates import (
    AlgorithmAction,
    AlgorithmBranch,
    AlgorithmStep,
    DecisionRule,
    DiagnosisHypothesis,
    HypothesisRole,
    Template,
    TestCharacteristic,
)

EXPECTED_HEADERS = [
    "# Step 1 — Problem List",
    "# Step 2 — Framing",
    "# Step 3 — Organized Differential",
    "# Step 4 — Pivotal Points",
    "# Step 5 — Findings That Support / Refute Each Candidate",
    "# Step 6 — Ranked Differential",
    "# Step 7 — Test Plan",
    "# Step 8 — Re-rank After New Data",
    "# Step 9 — New Hypotheses (if any)",
    "# Bias Audit",
    "# Decision",
]

# Case-insensitive vocabulary check — Stern uses mixed capitalization
# (bucket names are Title Case, biases are sentence case, etc.).
STERN_VOCABULARY = [
    "leading hypothesis",
    "active alternative — most common",
    "active alternative — must not miss",
    "other hypotheses",
    "excluded hypotheses",
    "premature closure",
    "anchoring",
    "confirmation bias",
    "availability bias",
    "base-rate neglect",
    "fingerprint findings",
    "pivotal point",
    "treatment threshold",
    "test threshold",
    "posttest odds = pretest odds × lr",  # noqa: RUF001
    "system 1",
    "system 2",
    "research-demo disclaimer",
]


def _fixture_template() -> Template:
    return Template(
        complaint="chest_pain",
        chapter_number=9,
        chapter_title="Chest Pain",
        framework_type="anatomical",
        framework_categories=["Cardiac", "Pulmonary", "Vascular", "GI", "MSK"],
        pivotal_points=[
            "duration of symptoms",
            "vital signs",
            "presence of CHD risk factors",
        ],
        decision_rules=[
            DecisionRule(name="HEART Score", purpose="Risk-stratify ED chest pain")
        ],
        differential=[
            DiagnosisHypothesis(
                name="Stable angina",
                role=HypothesisRole.LEADING,
                evidence_based_diagnosis=[
                    TestCharacteristic(
                        test_name="ECG stress test",
                        sensitivity=0.68,
                        specificity=0.77,
                    )
                ],
            ),
            DiagnosisHypothesis(
                name="Acute MI",
                role=HypothesisRole.ACTIVE_MUST_NOT_MISS,
            ),
            DiagnosisHypothesis(
                name="Aortic dissection",
                role=HypothesisRole.ACTIVE_MUST_NOT_MISS,
            ),
        ],
        algorithm=[
            AlgorithmStep(
                step_num=1,
                description="Acute or chronic onset?",
                branches=[
                    AlgorithmBranch(
                        condition="Acute",
                        action=AlgorithmAction.ESCALATE,
                        escalation_reason="ED triage",
                    )
                ],
            )
        ],
        source_pages=(164, 185),
    )


def test_reasoner_prompt_renders_with_minimal_context() -> None:
    template = _fixture_template()
    case_state = {"messages_summary": "62yo M, exertional chest pressure"}
    rendered = load_prompt(
        "reasoner/system",
        version=1,
        template=template,
        case_state=case_state,
        iteration=1,
        previous_findings=[],
    )
    assert rendered.metadata.name == "reasoner_system"
    assert rendered.metadata.version == 1
    assert rendered.text  # non-empty


def test_reasoner_prompt_includes_all_step_headers() -> None:
    template = _fixture_template()
    rendered = load_prompt(
        "reasoner/system",
        version=1,
        template=template,
        case_state={"messages_summary": ""},
        iteration=1,
        previous_findings=[],
    )
    for header in EXPECTED_HEADERS:
        assert header in rendered.text, f"missing section header: {header!r}"


def test_reasoner_prompt_includes_stern_vocabulary() -> None:
    template = _fixture_template()
    rendered = load_prompt(
        "reasoner/system",
        version=1,
        template=template,
        case_state={"messages_summary": ""},
        iteration=1,
        previous_findings=[],
    )
    text_lower = rendered.text.lower()
    for term in STERN_VOCABULARY:
        assert term in text_lower, f"missing Stern vocabulary: {term!r}"


def test_reasoner_prompt_substitutes_template_metadata() -> None:
    template = _fixture_template()
    rendered = load_prompt(
        "reasoner/system",
        version=1,
        template=template,
        case_state={"messages_summary": "x"},
        iteration=3,
        previous_findings=["found ST depression"],
    )
    assert "Iteration: 3" in rendered.text
    assert "chief complaint = chest_pain" in rendered.text
    assert "Chapter 9 — Chest Pain" in rendered.text
    assert "Source pages: 164-185" in rendered.text
    assert "HEART Score" in rendered.text
    assert "Acute MI" in rendered.text
    assert "Aortic dissection" in rendered.text
    assert "found ST depression" in rendered.text


def test_reasoner_prompt_handles_empty_previous_findings() -> None:
    template = _fixture_template()
    rendered = load_prompt(
        "reasoner/system",
        version=1,
        template=template,
        case_state={"messages_summary": ""},
        iteration=1,
        previous_findings=[],
    )
    assert "(none)" in rendered.text
