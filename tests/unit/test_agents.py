"""Unit tests for the 6 concrete agent classes.

Each agent is exercised against a mocked :class:`LLMClient` that returns canned
:class:`LLMResponse` objects. We verify:

- the agent satisfies the :class:`Agent` protocol structurally,
- ``run()`` emits an :class:`AgentResult` with the expected ``output`` type,
- the prompt is rendered (no template variables are missing) and forwarded.
"""

from __future__ import annotations

from typing import Any

import pytest

from tongue_doctor.agents import (
    Agent,
    CriticAgent,
    DefenderAgent,
    MustNotMissSweeperAgent,
    ReasonerAgent,
    RouterAgent,
    SafetyReviewerAgent,
    SynthesizerAgent,
)
from tongue_doctor.agents.schemas import (
    JudgeVerdict,
    MustNotMissEntry,
    MustNotMissSweep,
    RouterOutput,
    SafetyVerdict,
    SynthesisCitation,
    SynthesisOutput,
    WorkupItem,
)
from tongue_doctor.models.base import (
    FinishReason,
    LLMResponse,
    TokenUsage,
)
from tongue_doctor.schemas import CaseState
from tongue_doctor.templates.loader import load_template


def _empty_state() -> CaseState:
    return CaseState(case_id="case-1")


def _llm_response(text: str = "", finish_reason: FinishReason = "stop") -> LLMResponse:
    return LLMResponse(
        text=text,
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        model_id="gemini-3.1-pro-preview",
        finish_reason=finish_reason,
    )


class _MockClient:
    """Minimal LLMClient mock that returns a canned response and records the call."""

    name: str = "mock"
    model_id: str = "gemini-3.1-pro-preview"

    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.last_call: dict[str, Any] | None = None

    async def generate(
        self,
        messages: Any,
        *,
        system: str | None = None,
        tools: Any = None,
        response_schema: Any = None,
        thinking: Any = None,
    ) -> LLMResponse:
        self.last_call = {
            "messages": list(messages),
            "system": system,
            "tools": tools,
            "response_schema": response_schema,
            "thinking": thinking,
        }
        return self._response


# --- Protocol conformance ---


@pytest.mark.parametrize(
    "agent_factory",
    [
        lambda c: RouterAgent(c),
        lambda c: ReasonerAgent(c),
        lambda c: DefenderAgent(c),
        lambda c: CriticAgent(c),
        lambda c: MustNotMissSweeperAgent(c),
        lambda c: SynthesizerAgent(c),
        lambda c: SafetyReviewerAgent(c),
    ],
)
def test_each_agent_implements_protocol(agent_factory: Any) -> None:
    client = _MockClient(_llm_response())
    agent = agent_factory(client)
    assert isinstance(agent, Agent)
    assert agent.name
    assert agent.model_assignment_key
    assert agent.prompt_name


# --- Router ---


@pytest.mark.asyncio
async def test_router_run_returns_typed_output() -> None:
    output = RouterOutput(
        template_slug="chest_pain",
        chapter_number=9,
        confidence=0.92,
        rationale="Chief complaint matches Ch. 9 — Chest Pain.",
        fallback_slug=None,
        requires_clarification=False,
    )
    client = _MockClient(_llm_response(text=output.model_dump_json()))
    agent = RouterAgent(client)

    result = await agent.run(_empty_state(), user_message="55M crushing chest pain")
    assert isinstance(result.output, RouterOutput)
    assert result.output.template_slug == "chest_pain"
    assert result.state_mutations[0].op == "set_template_slug"
    assert result.state_mutations[0].payload == {"slug": "chest_pain"}
    assert result.metadata["model_id"] == "gemini-3.1-pro-preview"
    assert client.last_call is not None
    assert client.last_call["response_schema"] is not None


@pytest.mark.asyncio
async def test_router_requires_user_message() -> None:
    client = _MockClient(_llm_response())
    agent = RouterAgent(client)
    with pytest.raises(ValueError, match="user_message"):
        await agent.run(_empty_state())


def test_router_catalog_lists_31_templates() -> None:
    client = _MockClient(_llm_response())
    agent = RouterAgent(client)
    catalog = agent.catalog
    assert len(catalog) == 31
    slugs = {entry["slug"] for entry in catalog}
    assert "chest_pain" in slugs
    assert "abdominal_pain" in slugs
    for entry in catalog[:3]:
        assert isinstance(entry["chapter_number"], int)


# --- Reasoner ---


_REASONER_TRACE_FIXTURE = """
# Step 1 — Problem List
- chest pain

# Step 6 — Ranked Differential
- Leading Hypothesis: Acute MI
"""


@pytest.mark.asyncio
async def test_reasoner_returns_markdown_trace() -> None:
    client = _MockClient(_llm_response(text=_REASONER_TRACE_FIXTURE))
    agent = ReasonerAgent(client)
    template = load_template("chest_pain")
    result = await agent.run(_empty_state(), template=template, iteration=1)
    assert isinstance(result.output, str)
    assert "Step 1" in result.output
    assert "Acute MI" in result.output
    # Reasoner does NOT pass response_schema — output is markdown.
    assert client.last_call is not None
    assert client.last_call["response_schema"] is None


# --- Defender + Critic (free-form markdown prose; replaces Prosecutor + DA) ---


_DEFENDER_FIXTURE = """## Defender — Round 1

### Position
I defend Acute MI with high confidence given crushing substernal pain and risk factors.

### Bottom line
Leading hypothesis is well-supported.
"""

_CRITIC_FIXTURE = """## Critic — Round 1

### Verdict on the leading hypothesis
I find no material errors in the Reasoner's trace. The leading hypothesis is well-supported.

### Bottom line
No material concerns.
"""


@pytest.mark.asyncio
async def test_defender_returns_markdown_prose() -> None:
    client = _MockClient(_llm_response(text=_DEFENDER_FIXTURE))
    agent = DefenderAgent(client)
    template = load_template("chest_pain")
    result = await agent.run(
        _empty_state(),
        case_summary="55M chest pain",
        reasoner_trace=_REASONER_TRACE_FIXTURE,
        template=template,
        retrieved_chunks=[],
        round=1,
        prior_rounds=[],
    )
    # Defender produces free-form markdown — no JSON parsing, no response_schema.
    assert isinstance(result.output, str)
    assert "Defender" in result.output
    assert client.last_call is not None
    assert client.last_call["response_schema"] is None


@pytest.mark.asyncio
async def test_critic_returns_markdown_prose_with_concession() -> None:
    client = _MockClient(_llm_response(text=_CRITIC_FIXTURE))
    agent = CriticAgent(client)
    template = load_template("chest_pain")
    result = await agent.run(
        _empty_state(),
        case_summary="55M chest pain",
        reasoner_trace=_REASONER_TRACE_FIXTURE,
        template=template,
        retrieved_chunks=[],
        round=1,
        prior_rounds=[],
        current_defender=_DEFENDER_FIXTURE,
    )
    assert isinstance(result.output, str)
    assert "Critic" in result.output
    assert "no material errors" in result.output
    assert client.last_call is not None
    assert client.last_call["response_schema"] is None


# --- Must-Not-Miss Sweeper ---


@pytest.mark.asyncio
async def test_must_not_miss_sweeper_returns_sweep() -> None:
    sweep_out = MustNotMissSweep(
        sweep=[
            MustNotMissEntry(
                diagnosis="Acute MI",
                considered_in_trace=True,
                test_to_rule_out="High-sensitivity troponin",
                lr_negative=0.06,
                test_result_in_case="not yet drawn",
                gap="Troponin not yet drawn",
            )
        ],
        gaps_identified=["Troponin not yet drawn"],
        requires_escalation=True,
        summary="One must-not-miss workup pending.",
    )
    client = _MockClient(_llm_response(text=sweep_out.model_dump_json()))
    agent = MustNotMissSweeperAgent(client)
    template = load_template("chest_pain")
    result = await agent.run(
        _empty_state(),
        case_summary="55M chest pain",
        reasoner_trace=_REASONER_TRACE_FIXTURE,
        template=template,
        retrieved_chunks=[],
    )
    assert isinstance(result.output, MustNotMissSweep)
    assert result.output.requires_escalation is True
    assert result.output.gaps_identified == ["Troponin not yet drawn"]


# --- Synthesizer ---


@pytest.mark.asyncio
async def test_synthesizer_returns_commitment() -> None:
    synth_out = SynthesisOutput(
        body_markdown="**Most likely:** Acute MI...\n\nResearch demo only.",
        research_demo_disclaimer="Research demonstration only. Not clinical advice.",
        citations=[
            SynthesisCitation(
                label="Stern Ch. 9",
                source="stern",
                citation="p.169",
                authority_tier=3,
            )
        ],
    )
    client = _MockClient(_llm_response(text=synth_out.model_dump_json()))
    agent = SynthesizerAgent(client)

    judge_verdict = JudgeVerdict(
        leading_diagnosis="Acute MI",
        confidence_band="moderate",
        verdict_rationale="x",
        recommended_workup=[
            WorkupItem(
                step="Order ECG and high-sensitivity troponin",
                rationale="Troponin LR- 0.06 to exclude MI.",
                lr_plus_or_minus="LR- 0.06",
                citation="Stern p.169",
            )
        ],
        active_alternatives=["Aortic dissection"],
        educational_treatment_classes=["antiplatelet", "statin"],
        citations=[
            SynthesisCitation(
                label="Stern Ch. 9",
                source="stern",
                citation="p.169",
                authority_tier=3,
            )
        ],
        closing_statement="Acute MI committed.",
        rounds_held=1,
    )
    result = await agent.run(
        _empty_state(),
        judge_verdict=judge_verdict,
        reviewed_by="pending",
    )
    assert isinstance(result.output, SynthesisOutput)
    assert "Research demo" in result.output.body_markdown


# --- Safety Reviewer ---


@pytest.mark.asyncio
async def test_safety_reviewer_returns_verdict() -> None:
    verdict = SafetyVerdict(
        verdict="approve",
        prescription_leak_detected=False,
        phi_detected=False,
        disclaimer_present=True,
        citation_completeness="partial",
        summary="No leaks; disclaimer present.",
    )
    client = _MockClient(_llm_response(text=verdict.model_dump_json()))
    agent = SafetyReviewerAgent(client)

    synth = SynthesisOutput(
        body_markdown="x. Research demonstration only.",
        research_demo_disclaimer="Research demonstration only.",
    )
    result = await agent.run(
        _empty_state(),
        case_summary="55M chest pain",
        synthesis_output=synth,
        reviewed_by="pending",
    )
    assert isinstance(result.output, SafetyVerdict)
    assert result.output.verdict == "approve"


# --- _runtime helpers exercised indirectly ---


@pytest.mark.asyncio
async def test_invalid_json_raises_helpful_error() -> None:
    """Bad JSON from the LLM should surface clearly, not crash silently."""

    client = _MockClient(_llm_response(text="not json at all"))
    agent = RouterAgent(client)
    with pytest.raises(ValueError, match="schema validation"):
        await agent.run(_empty_state(), user_message="hi")
