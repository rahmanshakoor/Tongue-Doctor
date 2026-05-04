"""Integration test for the full diagnostic loop with mock LLMs.

Exercises the convergence-loop pipeline (Router → Reasoner → MNM (parallel) →
Defender ↔ Critic ↔ ConvergenceChecker → Judge → Synthesizer → Safety) with
canned per-agent responses. Asserts:

- Every agent fires exactly once for a single-round, immediately-converging case.
- Defender + Critic produce free-form markdown prose; their transcripts land on
  the trace verbatim.
- The convergence checker stops the loop when it returns ``converged: true``.
- The Synthesizer's output is projected onto the locked-down :class:`UserFacingOutput`.
- Safety verdict ``refuse`` produces a REFUSAL output.
- Multi-turn case state threading still works end-to-end.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tongue_doctor.agents import (
    ConvergenceCheckerAgent,
    CriticAgent,
    DefenderAgent,
    JudgeAgent,
    MustNotMissSweeperAgent,
    ReasonerAgent,
    RouterAgent,
    SafetyReviewerAgent,
    SynthesizerAgent,
)
from tongue_doctor.agents.schemas import (
    ConvergenceCheck,
    JudgeVerdict,
    MustNotMissEntry,
    MustNotMissSweep,
    RouterOutput,
    SafetyVerdict,
    SynthesisCitation,
    SynthesisOutput,
    WorkupItem,
)
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore
from tongue_doctor.knowledge.schema import AuthorityTier, Chunk
from tongue_doctor.models.base import LLMResponse, TokenUsage
from tongue_doctor.orchestrator import (
    CaseManager,
    DiagnosticLoop,
    LoopAgents,
)
from tongue_doctor.retrieval.bm25 import build_index, save_index
from tongue_doctor.retrieval.index import BM25Index
from tongue_doctor.schemas.output import OutputKind
from tongue_doctor.settings import get_settings


def _llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        model_id="gemini-3.1-pro-preview",
        finish_reason="stop",
    )


class _RecordingClient:
    name: str = "mock"
    model_id: str = "gemini-3.1-pro-preview"

    def __init__(self, response_text: str) -> None:
        self._text = response_text
        self.call_count = 0

    async def generate(
        self,
        messages: Any,
        *,
        system: str | None = None,
        tools: Any = None,
        response_schema: Any = None,
        thinking: Any = None,
    ) -> LLMResponse:
        self.call_count += 1
        return _llm_response(self._text)


@pytest.fixture
def bm25_index(tmp_path: Path) -> BM25Index:
    store = LocalCorpusStore(tmp_path / "knowledge")
    target_text = "Acute MI presents with crushing chest pain"
    pad = [
        ("p1", "Asthma is a chronic inflammatory airway disease"),
        ("p2", "Diabetes mellitus impacts glucose regulation"),
        ("p3", "Hypertension management requires lifestyle changes"),
    ]
    chunks = [
        Chunk(
            chunk_id="stern-target",
            source="stern",
            source_doc_id="ch9",
            title="Stern Ch. 9",
            section="Chest pain",
            source_location="p.169",
            text=target_text,
            token_count=8,
            citation="Stern Ch. 9 p.169",
            authority_tier=AuthorityTier.TEXTBOOK,
            url=None,
            license="test",
            ingested_at=datetime.now(UTC),
            metadata={},
        ),
        *(
            Chunk(
                chunk_id=cid,
                source="stern",
                source_doc_id="ch_other",
                title="Stern other",
                section="other",
                source_location="p.1",
                text=text,
                token_count=8,
                citation="Stern test",
                authority_tier=AuthorityTier.TEXTBOOK,
                url=None,
                license="test",
                ingested_at=datetime.now(UTC),
                metadata={},
            )
            for cid, text in pad
        ),
    ]
    store.write_chunks("stern", chunks)
    save_index(build_index("stern", store), store)
    return BM25Index(corpus_root=store.root, sources=["stern"])


_DEFENDER_FIXTURE = """## Defender — Round 1

### Position
I defend Acute MI with high confidence. The case shows crushing substernal chest pain
with classic risk factors and the must-not-miss list is closed.

### Evidence supporting the leading hypothesis
- Crushing substernal chest pain with diaphoresis (case)
- Stern p.169 — troponin LR+ 9.5 for NSTEMI

### Bottom line
Leading hypothesis is well-supported.
"""

_CRITIC_FIXTURE = """## Critic — Round 1

### Verdict on the leading hypothesis
I find no material errors in the Reasoner's trace. The leading hypothesis is well-supported,
the differential addresses the must-not-miss list, and the workup is adequate.

### Bottom line
No material concerns.
"""


def _make_agents() -> tuple[LoopAgents, dict[str, _RecordingClient]]:
    """Build the 9 agents wired to recording clients with canned responses.

    The Defender + Critic produce structured markdown prose; the convergence
    checker returns ``converged=true`` so the loop stops after round 1.
    """

    router_out = RouterOutput(
        template_slug="chest_pain",
        chapter_number=9,
        confidence=0.92,
        rationale="Crushing chest pain matches Ch. 9.",
        fallback_slug=None,
        requires_clarification=False,
    )
    convergence_out = ConvergenceCheck(
        converged=True,
        reason="Defender and Critic agree the leading dx is well-supported.",
        new_points_this_round=[],
    )
    mnm_out = MustNotMissSweep(
        sweep=[
            MustNotMissEntry(
                diagnosis="Acute MI",
                considered_in_trace=True,
                test_to_rule_out="High-sensitivity troponin",
                lr_negative=0.06,
                gap="Troponin not yet drawn",
            )
        ],
        gaps_identified=["Troponin not yet drawn"],
        requires_escalation=False,
        summary="One workup pending.",
    )
    synth_out = SynthesisOutput(
        body_markdown="**Most likely:** Acute MI...\n\nResearch demonstration only.",
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
    judge_out = JudgeVerdict(
        leading_diagnosis="Acute MI",
        confidence_band="moderate",
        verdict_rationale="Defender's case for MI dominates; Critic raised no case-supported alternatives.",
        defender_strengths=["specific case findings cited"],
        defender_weaknesses=[],
        critic_strengths=["honest concession when warranted"],
        critic_weaknesses=[],
        active_alternatives=[],
        excluded_alternatives=[],
        recommended_workup=[
            WorkupItem(
                step="Order ECG and high-sensitivity troponin",
                rationale="Troponin LR- 0.06 to exclude MI.",
                lr_plus_or_minus="LR- 0.06",
                citation="Stern p.169",
            )
        ],
        red_flags_to_monitor=["Hypotension"],
        educational_treatment_classes=["antiplatelet"],
        citations=[
            SynthesisCitation(
                label="Stern Ch. 9",
                source="stern",
                citation="p.169",
                authority_tier=3,
            )
        ],
        closing_statement="After review, Acute MI is the leading diagnosis with moderate confidence.",
        rounds_held=1,
    )
    safety_out = SafetyVerdict(
        verdict="approve",
        prescription_leak_detected=False,
        phi_detected=False,
        disclaimer_present=True,
        citation_completeness="partial",
        summary="No leaks; disclaimer present.",
    )

    clients = {
        "router": _RecordingClient(router_out.model_dump_json()),
        "reasoner": _RecordingClient("# Step 6 — Ranked Differential\n- Leading Hypothesis: Acute MI"),
        "defender": _RecordingClient(_DEFENDER_FIXTURE),
        "critic": _RecordingClient(_CRITIC_FIXTURE),
        "convergence_checker": _RecordingClient(convergence_out.model_dump_json()),
        "must_not_miss_sweeper": _RecordingClient(mnm_out.model_dump_json()),
        "judge": _RecordingClient(judge_out.model_dump_json()),
        "synthesizer": _RecordingClient(synth_out.model_dump_json()),
        "safety_reviewer": _RecordingClient(safety_out.model_dump_json()),
    }

    agents = LoopAgents(
        router=RouterAgent(clients["router"]),  # type: ignore[arg-type]
        reasoner=ReasonerAgent(clients["reasoner"]),  # type: ignore[arg-type]
        defender=DefenderAgent(clients["defender"]),  # type: ignore[arg-type]
        critic=CriticAgent(clients["critic"]),  # type: ignore[arg-type]
        convergence_checker=ConvergenceCheckerAgent(clients["convergence_checker"]),  # type: ignore[arg-type]
        must_not_miss_sweeper=MustNotMissSweeperAgent(clients["must_not_miss_sweeper"]),  # type: ignore[arg-type]
        judge=JudgeAgent(clients["judge"]),  # type: ignore[arg-type]
        synthesizer=SynthesizerAgent(clients["synthesizer"]),  # type: ignore[arg-type]
        safety_reviewer=SafetyReviewerAgent(clients["safety_reviewer"]),  # type: ignore[arg-type]
    )
    return agents, clients


@pytest.mark.asyncio
async def test_loop_full_pipeline(bm25_index: BM25Index) -> None:
    agents, clients = _make_agents()
    case_manager = CaseManager()
    settings = get_settings()
    loop = DiagnosticLoop(
        agents=agents,
        case_manager=case_manager,
        bm25_index=bm25_index,
        settings=settings,
        retrieval_top_k=3,
        max_rounds=2,
    )

    result = await loop.handle_message("case-1", "55M crushing chest pain radiating to left arm")

    # Every primary agent fired exactly once for a single-round converging case.
    # The convergence checker fires only when round_num < max_rounds (so on round 1
    # of a max_rounds=2 run it fires once and returns converged=true; the loop stops).
    expected_single_call = {
        "router",
        "reasoner",
        "defender",
        "critic",
        "convergence_checker",
        "must_not_miss_sweeper",
        "judge",
        "synthesizer",
        "safety_reviewer",
    }
    for name in expected_single_call:
        assert clients[name].call_count == 1, (
            f"agent {name} fired {clients[name].call_count} times (expected 1)"
        )

    # Trace contents
    assert result.case_id == "case-1"
    assert result.trace.template_slug == "chest_pain"
    assert result.trace.chapter_number == 9
    assert result.trace.reasoner_trace.startswith("# Step 6")
    assert result.trace.judge_verdict is not None
    assert result.trace.judge_verdict.leading_diagnosis == "Acute MI"
    assert result.trace.safety.verdict == "approve"
    assert result.trace.converged is True
    assert len(result.trace.dialectic_rounds) == 1
    round1 = result.trace.dialectic_rounds[0]
    assert "I defend Acute MI" in round1.defender_markdown
    assert "no material errors" in round1.critic_markdown
    assert round1.convergence_check is not None
    assert round1.convergence_check.converged is True
    assert len(result.trace.retrieved_chunks) >= 1

    # User-facing output is the locked-down COMMITMENT shape.
    assert result.user_facing.kind == OutputKind.COMMITMENT
    assert "Acute MI" in result.user_facing.body
    assert "Research demonstration" in result.user_facing.disclaimer
    assert len(result.user_facing.citations) == 1
    assert result.user_facing.citations[0].source == "stern"

    # Timings populated
    assert result.trace.timings.total_ms > 0
    assert result.duration_ms > 0


@pytest.mark.asyncio
async def test_loop_safety_refusal_overrides_synthesis(bm25_index: BM25Index) -> None:
    """A ``refuse`` verdict produces a REFUSAL UserFacingOutput, not the synthesis body."""

    agents, clients = _make_agents()
    refusal = SafetyVerdict(
        verdict="refuse",
        refusal_reason="Detected specific drug + dose in synthesis body.",
        prescription_leak_detected=True,
    )
    clients["safety_reviewer"] = _RecordingClient(refusal.model_dump_json())
    agents.safety_reviewer = SafetyReviewerAgent(clients["safety_reviewer"])  # type: ignore[arg-type]

    loop = DiagnosticLoop(
        agents=agents,
        case_manager=CaseManager(),
        bm25_index=bm25_index,
        settings=get_settings(),
        retrieval_top_k=3,
        max_rounds=2,
    )
    result = await loop.handle_message("case-2", "55M chest pain")

    assert result.user_facing.kind == OutputKind.REFUSAL
    assert "drug" in result.user_facing.body.lower()
    assert result.trace.safety.prescription_leak_detected is True


@pytest.mark.asyncio
async def test_loop_persists_state(bm25_index: BM25Index) -> None:
    agents, _clients = _make_agents()
    case_manager = CaseManager()
    loop = DiagnosticLoop(
        agents=agents,
        case_manager=case_manager,
        bm25_index=bm25_index,
        settings=get_settings(),
        retrieval_top_k=3,
        max_rounds=2,
    )
    await loop.handle_message("case-3", "55M chest pain")
    state = await case_manager.get("case-3")
    assert state.turn_count == 1
    assert "Acute MI" in state.messages_summary


@pytest.mark.asyncio
async def test_reasoner_sees_user_message_on_turn_one(bm25_index: BM25Index) -> None:
    """The Reasoner's case_state must carry the user's message on turn 1.

    Regression for a bug where the orchestrator passed the unmodified case_state
    to the Reasoner before _apply_turn updated messages_summary, so the Reasoner
    rendered ``(empty — first iteration on this chief complaint)``.
    """

    agents, _clients = _make_agents()
    case_manager = CaseManager()
    loop = DiagnosticLoop(
        agents=agents,
        case_manager=case_manager,
        bm25_index=bm25_index,
        settings=get_settings(),
        retrieval_top_k=3,
        max_rounds=2,
    )
    captured: dict[str, Any] = {}
    original = agents.reasoner.run

    async def _spy(case_state: Any, **kwargs: Any) -> Any:
        captured["case_state"] = case_state
        return await original(case_state, **kwargs)

    agents.reasoner.run = _spy  # type: ignore[method-assign]
    await loop.handle_message("case-r1", "55M crushing chest pain radiating to left arm")
    assert "55M crushing chest pain" in captured["case_state"].messages_summary


@pytest.mark.asyncio
async def test_loop_merges_ancillary_chapters_into_differential(bm25_index: BM25Index) -> None:
    """When the Router emits ancillaries, the Reasoner sees a merged template
    whose differential includes diagnoses from multiple chapters."""

    agents, clients = _make_agents()

    multi = RouterOutput(
        template_slug="chest_pain",
        chapter_number=9,
        confidence=0.55,
        rationale="Multi-system case spanning chest, headache, abdominal symptoms.",
        ancillary_template_slugs=["headache", "abdominal_pain"],
        fallback_slug=None,
        requires_clarification=False,
    )
    clients["router"] = _RecordingClient(multi.model_dump_json())
    agents.router = RouterAgent(clients["router"])  # type: ignore[arg-type]

    captured: dict[str, Any] = {}
    original = agents.reasoner.run

    async def _spy(case_state: Any, **kwargs: Any) -> Any:
        captured["template"] = kwargs.get("template")
        return await original(case_state, **kwargs)

    agents.reasoner.run = _spy  # type: ignore[method-assign]

    loop = DiagnosticLoop(
        agents=agents,
        case_manager=CaseManager(),
        bm25_index=bm25_index,
        settings=get_settings(),
        retrieval_top_k=3,
        max_rounds=2,
    )
    result = await loop.handle_message("case-multi-chapter", "headache + chest pain + bloating")

    assert result.trace.template_slug == "chest_pain"
    assert result.trace.ancillary_template_slugs == ["headache", "abdominal_pain"]

    merged_template = captured["template"]
    diff_names = {d.name.lower() for d in merged_template.differential}
    assert any("mi" in n or "infarction" in n for n in diff_names)
    tagged = [d for d in merged_template.differential if "from Ch." in d.notes]
    assert len(tagged) >= 1


@pytest.mark.asyncio
async def test_loop_skips_unknown_ancillary_slugs(bm25_index: BM25Index) -> None:
    """Router hallucinated slug → loop skips it, doesn't crash."""

    agents, clients = _make_agents()
    bad = RouterOutput(
        template_slug="chest_pain",
        chapter_number=9,
        confidence=0.7,
        rationale="x",
        ancillary_template_slugs=["headache", "this_is_not_a_real_chapter"],
    )
    clients["router"] = _RecordingClient(bad.model_dump_json())
    agents.router = RouterAgent(clients["router"])  # type: ignore[arg-type]

    loop = DiagnosticLoop(
        agents=agents,
        case_manager=CaseManager(),
        bm25_index=bm25_index,
        settings=get_settings(),
        retrieval_top_k=3,
        max_rounds=2,
    )
    result = await loop.handle_message("case-bad-slug", "55M chest pain + headache")
    assert result.trace.ancillary_template_slugs == ["headache"]


@pytest.mark.asyncio
async def test_loop_threads_prior_findings_on_followup(bm25_index: BM25Index) -> None:
    """Second call with the same case_id sees prior findings + cumulative summary."""

    agents, _clients = _make_agents()
    case_manager = CaseManager()
    loop = DiagnosticLoop(
        agents=agents,
        case_manager=case_manager,
        bm25_index=bm25_index,
        settings=get_settings(),
        retrieval_top_k=3,
        max_rounds=2,
    )
    # Turn 1
    await loop.handle_message("case-multi", "55M crushing chest pain")
    state_after_1 = await case_manager.get("case-multi")
    assert state_after_1.turn_count == 1
    assert any(
        "Turn 1 Judge leading dx: Acute MI" in f for f in state_after_1.prior_findings
    )
    assert "Turn 1 user message" in state_after_1.messages_summary
    assert "Turn 1 Judge verdict" in state_after_1.messages_summary

    reasoner_kwargs: dict[str, Any] = {}
    original_reasoner_run = agents.reasoner.run

    async def _spy_reasoner(case_state: Any, **kwargs: Any) -> Any:
        reasoner_kwargs.update(kwargs)
        return await original_reasoner_run(case_state, **kwargs)

    judge_kwargs: dict[str, Any] = {}
    original_judge_run = agents.judge.run

    async def _spy_judge(case_state: Any, **kwargs: Any) -> Any:
        judge_kwargs.update(kwargs)
        return await original_judge_run(case_state, **kwargs)

    agents.reasoner.run = _spy_reasoner  # type: ignore[method-assign]
    agents.judge.run = _spy_judge  # type: ignore[method-assign]

    # Turn 2 — new info
    await loop.handle_message(
        "case-multi",
        "Troponin came back at 0.8 ng/mL. ECG shows ST elevation in V1-V4.",
    )
    state_after_2 = await case_manager.get("case-multi")
    assert state_after_2.turn_count == 2
    assert len(state_after_2.prior_findings) >= 6  # 3 lines x 2 turns

    assert reasoner_kwargs["iteration"] == 2
    prior = reasoner_kwargs["previous_findings"]
    assert any("Turn 1 Judge leading dx: Acute MI" in f for f in prior)

    # The Judge's case_summary now includes both turns (cumulative summary
    # threaded through every agent in the loop).
    cumulative = judge_kwargs["case_summary"]
    assert "55M crushing chest pain" in cumulative
    assert "ST elevation" in cumulative
    assert "Turn 1 Judge verdict" in cumulative


@pytest.mark.asyncio
async def test_loop_continues_when_convergence_check_says_continue(bm25_index: BM25Index) -> None:
    """When ``ConvergenceCheck.converged=False``, the loop runs another round
    (up to max_rounds). The Defender / Critic each fire ``max_rounds`` times.
    """

    agents, clients = _make_agents()
    not_yet = ConvergenceCheck(
        converged=False,
        reason="Critic raised a new point the Defender has not addressed.",
        new_points_this_round=["Aortic dissection workup not yet ordered"],
    )
    clients["convergence_checker"] = _RecordingClient(not_yet.model_dump_json())
    agents.convergence_checker = ConvergenceCheckerAgent(clients["convergence_checker"])  # type: ignore[arg-type]

    loop = DiagnosticLoop(
        agents=agents,
        case_manager=CaseManager(),
        bm25_index=bm25_index,
        settings=get_settings(),
        retrieval_top_k=3,
        max_rounds=3,
    )
    result = await loop.handle_message("case-noconverge", "55M chest pain")

    # 3 rounds * (Defender + Critic) plus 2 convergence checks (no check on the
    # final round - we don't ask "should we continue?" when there's nothing
    # left to do).
    assert clients["defender"].call_count == 3
    assert clients["critic"].call_count == 3
    assert clients["convergence_checker"].call_count == 2
    assert len(result.trace.dialectic_rounds) == 3
    assert result.trace.converged is False
