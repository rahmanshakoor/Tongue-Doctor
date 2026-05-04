"""Tests for ``DiagnosticLoop.stream_message`` — the event-stream API the chat
CLI consumes.

These tests use the same canned-response fixture machinery as ``test_loop_smoke``
but assert the *shape* of the emitted ``LoopEvent`` sequence rather than the
final result. We also sanity-check that ``handle_message`` (now implemented as a
thin drain over ``stream_message``) still produces the same final payload.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from tongue_doctor.models.base import LLMResponse, StreamChunk, TokenUsage
from tongue_doctor.orchestrator import (
    CaseManager,
    DiagnosticLoop,
)
from tongue_doctor.orchestrator.types import (
    AgentChunk,
    AgentDone,
    Final,
    PhaseStarted,
    RetrievalDone,
)
from tongue_doctor.retrieval.index import BM25Index
from tongue_doctor.settings import get_settings

from .test_loop_smoke import _make_agents, bm25_index  # noqa: F401


def _build_loop(bm25: BM25Index) -> DiagnosticLoop:
    agents, _ = _make_agents()
    return DiagnosticLoop(
        agents=agents,
        case_manager=CaseManager(),
        bm25_index=bm25,
        settings=get_settings(),
        retrieval_top_k=3,
        max_rounds=2,
    )


@pytest.mark.asyncio
async def test_stream_message_emits_expected_phases(bm25_index: BM25Index) -> None:  # noqa: F811
    """The phase-started events fire in pipeline order with one Final at the end."""

    loop = _build_loop(bm25_index)
    phases_started: list[str] = []
    phases_done: list[str] = []
    saw_retrieval = False
    saw_final = False

    async for ev in loop.stream_message("case-stream-1", "55M crushing chest pain"):
        if isinstance(ev, PhaseStarted):
            phases_started.append(ev.phase)
        elif isinstance(ev, AgentDone):
            phases_done.append(ev.phase)
        elif isinstance(ev, RetrievalDone):
            saw_retrieval = True
        elif isinstance(ev, Final):
            saw_final = True
            assert ev.result.user_facing.body  # body populated

    # Pipeline order — router → reasoner → defender → MNM (between defender + critic
    # of round 1) → critic → convergence check → judge → synthesizer → safety. The
    # convergence check fires when ``round_num < max_rounds``; the smoke fixture's
    # ConvergenceCheck returns ``converged=True`` so the loop stops after round 1.
    expected_order = [
        "router",
        "reasoner",
        "round_1_defender",
        "must_not_miss",
        "round_1_critic",
        "round_1_convergence",
        "judge",
        "synthesizer",
        "safety",
    ]
    assert phases_started == expected_order
    assert phases_done == expected_order
    assert saw_retrieval, "retrieval_done event was not emitted"
    assert saw_final, "final event was not emitted"


@pytest.mark.asyncio
async def test_handle_message_drains_stream(bm25_index: BM25Index) -> None:  # noqa: F811
    """``handle_message`` must return the same payload as the Final event."""

    loop = _build_loop(bm25_index)
    final_via_stream = None
    async for ev in loop.stream_message("case-stream-2", "55M chest pain"):
        if isinstance(ev, Final):
            final_via_stream = ev.result

    # Use a fresh loop / case_manager so persistence doesn't bleed turn counts.
    loop2 = _build_loop(bm25_index)
    via_handle = await loop2.handle_message("case-stream-3", "55M chest pain")

    assert final_via_stream is not None
    # Same shape — turn counts may differ because case_ids differ, but the user-facing
    # body / clinical fields come from identical canned outputs.
    assert via_handle.user_facing.kind == final_via_stream.user_facing.kind
    assert via_handle.trace.judge_verdict.leading_diagnosis == (
        final_via_stream.trace.judge_verdict.leading_diagnosis
    )


# --- Streaming-aware client: yields chunks then a final aggregated response ---


class _StreamingClient:
    """Recording client that exposes both ``generate`` and ``generate_stream``."""

    name: str = "stream-mock"
    model_id: str = "gemini-3.1-pro-preview"

    def __init__(self, response_text: str, *, deltas: Sequence[str] | None = None) -> None:
        self._text = response_text
        # If no explicit deltas given, slice the response into 4 roughly-equal pieces
        # so we exercise multi-chunk streaming.
        if deltas is None:
            n = max(4, len(response_text) // 50)
            step = max(1, len(response_text) // n)
            deltas = [
                response_text[i : i + step] for i in range(0, len(response_text), step)
            ]
        self._deltas: list[str] = list(deltas)
        self.generate_calls = 0
        self.generate_stream_calls = 0

    async def generate(
        self,
        messages: Any,
        *,
        system: str | None = None,
        tools: Any = None,
        response_schema: Any = None,
        thinking: Any = None,
    ) -> LLMResponse:
        self.generate_calls += 1
        return LLMResponse(
            text=self._text,
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            model_id=self.model_id,
            finish_reason="stop",
        )

    async def generate_stream(
        self,
        messages: Any,
        *,
        system: str | None = None,
        tools: Any = None,
        response_schema: Any = None,
        thinking: Any = None,
    ) -> AsyncIterator[StreamChunk]:
        self.generate_stream_calls += 1
        for delta in self._deltas:
            yield StreamChunk(delta=delta)
        yield StreamChunk(
            delta="",
            response=LLMResponse(
                text=self._text,
                usage=TokenUsage(input_tokens=10, output_tokens=5),
                model_id=self.model_id,
                finish_reason="stop",
            ),
        )


@pytest.mark.asyncio
async def test_stream_message_emits_chunks_when_client_streams(
    bm25_index: BM25Index,  # noqa: F811
) -> None:
    """When a client implements ``generate_stream``, AgentChunk events are emitted
    for each delta and the reconstructed text matches the canned response."""

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
        MustNotMissSweep,
        RouterOutput,
        SafetyVerdict,
        SynthesisCitation,
        SynthesisOutput,
        WorkupItem,
    )
    from tongue_doctor.orchestrator import LoopAgents

    router_out = RouterOutput(
        template_slug="chest_pain",
        chapter_number=9,
        confidence=0.9,
        rationale="ok",
    )
    convergence_out = ConvergenceCheck(
        converged=True,
        reason="Both agree the leading dx is well-supported.",
        new_points_this_round=[],
    )
    mnm_out = MustNotMissSweep(summary="ok")
    judge_out = JudgeVerdict(
        leading_diagnosis="Acute MI",
        confidence_band="moderate",
        verdict_rationale="ok",
        closing_statement="ok",
        citations=[
            SynthesisCitation(label="x", source="stern", citation="p.169", authority_tier=3)
        ],
        recommended_workup=[WorkupItem(step="ECG", rationale="ok")],
    )
    synth_out = SynthesisOutput(
        body_markdown="**Most likely:** Acute MI",
        research_demo_disclaimer="Research demo only.",
    )
    safety_out = SafetyVerdict(verdict="approve", disclaimer_present=True)

    reasoner_text = "# Step 6 — Ranked Differential\n- Leading: Acute MI"
    # Hand-tune Reasoner deltas so we can assert reconstruction precisely.
    reasoner_deltas = ["# Step 6 — Ranked ", "Differential\n- Leading", ": Acute MI"]
    defender_text = "## Defender — Round 1\n### Bottom line\nLeading hypothesis well-supported."
    critic_text = "## Critic — Round 1\n### Bottom line\nNo material concerns."
    streaming_clients = {
        "router": _StreamingClient(router_out.model_dump_json()),
        "reasoner": _StreamingClient(reasoner_text, deltas=reasoner_deltas),
        "defender": _StreamingClient(defender_text),
        "critic": _StreamingClient(critic_text),
        "convergence_checker": _StreamingClient(convergence_out.model_dump_json()),
        "must_not_miss_sweeper": _StreamingClient(mnm_out.model_dump_json()),
        "judge": _StreamingClient(judge_out.model_dump_json()),
        "synthesizer": _StreamingClient(synth_out.model_dump_json()),
        "safety_reviewer": _StreamingClient(safety_out.model_dump_json()),
    }
    agents = LoopAgents(
        router=RouterAgent(streaming_clients["router"]),  # type: ignore[arg-type]
        reasoner=ReasonerAgent(streaming_clients["reasoner"]),  # type: ignore[arg-type]
        defender=DefenderAgent(streaming_clients["defender"]),  # type: ignore[arg-type]
        critic=CriticAgent(streaming_clients["critic"]),  # type: ignore[arg-type]
        convergence_checker=ConvergenceCheckerAgent(  # type: ignore[arg-type]
            streaming_clients["convergence_checker"]
        ),
        must_not_miss_sweeper=MustNotMissSweeperAgent(  # type: ignore[arg-type]
            streaming_clients["must_not_miss_sweeper"]
        ),
        judge=JudgeAgent(streaming_clients["judge"]),  # type: ignore[arg-type]
        synthesizer=SynthesizerAgent(streaming_clients["synthesizer"]),  # type: ignore[arg-type]
        safety_reviewer=SafetyReviewerAgent(streaming_clients["safety_reviewer"]),  # type: ignore[arg-type]
    )
    loop = DiagnosticLoop(
        agents=agents,
        case_manager=CaseManager(),
        bm25_index=bm25_index,
        settings=get_settings(),
        retrieval_top_k=3,
        max_rounds=2,
    )

    chunks_by_phase: dict[str, list[str]] = {}
    final_received = False
    async for ev in loop.stream_message("case-stream-chunks", "55M chest pain"):
        if isinstance(ev, AgentChunk):
            chunks_by_phase.setdefault(ev.phase, []).append(ev.delta)
        elif isinstance(ev, Final):
            final_received = True

    assert final_received

    # Reasoner's deltas were forwarded as separate AgentChunk events — and they
    # reconstruct the canned text exactly.
    assert "reasoner" in chunks_by_phase, "expected at least one Reasoner chunk"
    assert "".join(chunks_by_phase["reasoner"]) == reasoner_text
    assert len(chunks_by_phase["reasoner"]) == len(reasoner_deltas)

    # Every streamable agent used generate_stream (not generate). The MNM Sweeper
    # is intentionally exempt — it runs in parallel with the convergence loop, so
    # live streaming would interleave with the Defender/Critic panels and confuse
    # the chat UI. It falls back to the non-streaming path on purpose.
    streaming_agents = {
        name for name in streaming_clients if name != "must_not_miss_sweeper"
    }
    for name in streaming_agents:
        client = streaming_clients[name]
        assert client.generate_stream_calls >= 1, (
            f"{name} should have streamed but did not; generate_stream_calls=0"
        )
        assert client.generate_calls == 0, (
            f"{name} fell back to non-streaming generate() despite supporting stream"
        )
    mnm = streaming_clients["must_not_miss_sweeper"]
    assert mnm.generate_calls == 1, "MNM should fall back to generate() (no on_chunk)"
    assert mnm.generate_stream_calls == 0
