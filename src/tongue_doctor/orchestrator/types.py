"""Orchestrator return types.

The :class:`LoopRunResult` is what :meth:`DiagnosticLoop.handle_message` returns:
the locked-down :class:`UserFacingOutput` *plus* the full agent trace so the API /
CLI can render the intermediate steps. Persisting :class:`UserFacingOutput`
unchanged preserves the SAFETY_INVARIANTS.md I-3 contract.

The ``LoopEvent`` family is for the chat-mode CLI (and any future SSE / WebSocket
frontend): :meth:`DiagnosticLoop.stream_message` is an async generator that emits
these events in pipeline order so the UI can render each agent's output as it
arrives. ``handle_message`` is implemented on top of the stream — it just drains
the generator and returns the terminal :class:`Final` event's payload.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tongue_doctor.agents.schemas import (
    DialecticRound,
    JudgeVerdict,
    MustNotMissSweep,
    RouterOutput,
    SafetyVerdict,
    SynthesisOutput,
)
from tongue_doctor.retrieval.index import ScoredChunk
from tongue_doctor.schemas.output import UserFacingOutput


class AgentTimings(BaseModel):
    """Per-agent latency in milliseconds."""

    model_config = ConfigDict(extra="forbid")

    router_ms: int = 0
    retrieval_ms: int = 0
    reasoner_ms: int = 0
    reasoner_rerank_ms: int = 0  # reserved
    prosecutor_ms: int = 0  # cumulative across dialectic rounds
    devils_advocate_ms: int = 0  # cumulative across dialectic rounds
    dialectic_total_ms: int = 0  # wall time for all rounds (Pros+DA sequential per round)
    must_not_miss_ms: int = 0
    judge_ms: int = 0
    synthesizer_ms: int = 0
    safety_reviewer_ms: int = 0
    total_ms: int = 0


class AgentTrace(BaseModel):
    """The intermediate outputs of every agent in one diagnostic loop run."""

    model_config = ConfigDict(extra="forbid")

    template_slug: str
    chapter_number: int
    ancillary_template_slugs: list[str] = Field(default_factory=list)
    router: RouterOutput
    retrieved_chunks: list[ScoredChunk] = Field(default_factory=list)
    reasoner_trace: str
    # Reserved for a future Reasoner re-rank pass; unused under the current layout.
    reasoner_initial_trace: str = ""
    reasoner_reranked: bool = False
    critiques_addressed: list[str] = Field(default_factory=list)
    # Defender ↔ Critic convergence-loop transcripts (one entry per round). Each
    # round carries the two prose transcripts plus the per-round
    # ``ConvergenceCheck`` verdict. The list length tells the caller how many
    # rounds were needed; ``converged`` says whether the loop stopped via
    # convergence (True) or hit ``max_rounds`` (False).
    dialectic_rounds: list[DialecticRound] = Field(default_factory=list)
    converged: bool = False
    must_not_miss: MustNotMissSweep
    judge_verdict: JudgeVerdict | None = None
    synthesis: SynthesisOutput
    safety: SafetyVerdict
    timings: AgentTimings = Field(default_factory=AgentTimings)


class LoopRunResult(BaseModel):
    """The diagnostic loop's full output: user-facing slice + structural trace."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    duration_ms: int
    user_facing: UserFacingOutput
    trace: AgentTrace


# --- Streaming event types (for chat-mode CLI / future SSE frontend) ---


# Slugs identify which agent / phase a streaming event belongs to. They double as
# stable anchors the chat CLI uses to look up panel titles, colors, and which
# parsed-output renderer to invoke when the agent finishes.
PhaseName = Literal[
    "router",
    "retrieval",
    "reasoner",
    "must_not_miss",
    "judge",
    "synthesizer",
    "safety",
]


class PhaseStarted(BaseModel):
    """Emitted before each non-dialectic agent (and once per dialectic role per round) starts."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["phase_started"] = "phase_started"
    phase: str  # PhaseName values plus "round_{N}_prosecutor" / "round_{N}_devils_advocate"
    label: str  # human title, e.g. "Devil's Advocate (Round 2)"
    round: int = 0  # 0 for non-dialectic phases


class AgentChunk(BaseModel):
    """A streamed text delta from the currently-running agent.

    For free-text agents (Reasoner) the delta is prose. For structured agents the
    delta is raw JSON tokens — that's what the model emits when ``response_schema``
    is set. The chat CLI surfaces both kinds verbatim under each agent's panel.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["agent_chunk"] = "agent_chunk"
    phase: str
    delta: str


class AgentDone(BaseModel):
    """Emitted after each agent's call completes successfully.

    ``summary`` is a short human-readable view of the parsed output suitable for
    a panel footer. The full structured payload lives on the eventual
    :class:`AgentTrace`; the streamed event keeps the chat CLI lightweight.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["agent_done"] = "agent_done"
    phase: str
    label: str
    summary: str
    latency_ms: int
    round: int = 0


class RetrievalDone(BaseModel):
    """Emitted after BM25 retrieval — there is no ``AgentChunk`` for retrieval since
    BM25 is synchronous and finishes in milliseconds."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["retrieval_done"] = "retrieval_done"
    chunk_count: int
    top_sources: list[str] = Field(default_factory=list)
    latency_ms: int


class Final(BaseModel):
    """Terminal event with the same payload as :class:`LoopRunResult`."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["final"] = "final"
    result: LoopRunResult


LoopEvent = PhaseStarted | AgentChunk | AgentDone | RetrievalDone | Final


__all__ = [
    "AgentChunk",
    "AgentDone",
    "AgentTimings",
    "AgentTrace",
    "Final",
    "LoopEvent",
    "LoopRunResult",
    "PhaseName",
    "PhaseStarted",
    "RetrievalDone",
]
