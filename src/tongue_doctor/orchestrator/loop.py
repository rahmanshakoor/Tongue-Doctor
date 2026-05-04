"""Diagnostic loop with convergence-driven Defender ↔ Critic review.

Phase 1 pipeline (revised 2026-05-02 — replaced courtroom Prosecutor / DA with
honest peer-review-style Defender + Critic + ConvergenceChecker):

    Router → BM25 → Reasoner (initial) ─┬─ MNM Sweeper (parallel)
                                        └─ Convergence loop:
                                             Round N: Defender (prose)
                                                      → Critic (prose)
                                                      → ConvergenceChecker (JSON)
                                             repeat until converged or max_rounds
                                        → Judge (sole decider, reads prose transcripts + MNM)
        → Synthesizer (pure renderer) → Safety Reviewer

The Defender steel-mans the Reasoner's leading hypothesis honestly; the Critic
finds genuine errors. **Both are explicitly permitted (and encouraged) to
concede when warranted** — that's the structural fix for the "debate for
debate's sake" failure mode of the courtroom layout. Outputs are free-form
markdown prose with named section headers, NOT JSON, so neither agent is
forced to fill fields it has nothing to put in.

The convergence checker stops the loop when no new substantive points emerged
this round, or when both sides agree. Default ``max_rounds=3`` is a safety
cap; most clear cases converge in 1 round.

The Judge remains the sole decider of all clinical fields (leading_diagnosis,
confidence_band, workup, alternatives, citations, closing_statement). The
Synthesizer renders that verdict; it does not re-decide. This honors the
"no overlapping prompts" rule.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

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
from tongue_doctor.agents.base import AgentResult
from tongue_doctor.agents.schemas import (
    ConvergenceCheck,
    DialecticRound,
    JudgeVerdict,
    MustNotMissSweep,
    RouterOutput,
    SafetyVerdict,
    SynthesisOutput,
)
from tongue_doctor.orchestrator.case_manager import CaseManager
from tongue_doctor.orchestrator.types import (
    AgentChunk,
    AgentDone,
    AgentTimings,
    AgentTrace,
    Final,
    LoopEvent,
    LoopRunResult,
    PhaseStarted,
    RetrievalDone,
)
from tongue_doctor.retrieval.index import BM25Index
from tongue_doctor.schemas import CaseState
from tongue_doctor.schemas.output import Citation, OutputKind, UserFacingOutput
from tongue_doctor.settings import Settings
from tongue_doctor.templates import Template
from tongue_doctor.templates.loader import TemplateNotFoundError, load_template


@dataclass
class LoopAgents:
    """Bundle of the 9 agents the convergence-loop pipeline drives."""

    router: RouterAgent
    reasoner: ReasonerAgent
    defender: DefenderAgent
    critic: CriticAgent
    convergence_checker: ConvergenceCheckerAgent
    must_not_miss_sweeper: MustNotMissSweeperAgent
    judge: JudgeAgent
    synthesizer: SynthesizerAgent
    safety_reviewer: SafetyReviewerAgent


# Type alias for the run-coroutine factory passed to ``_stream_agent_run``: given
# an ``on_chunk`` callback, it returns the awaitable agent invocation.
RunCoroFactory = Callable[[Callable[[str], None]], Awaitable[AgentResult]]


class DiagnosticLoop:
    """Convergence-driven peer-review loop: Defender ↔ Critic until they agree, then Judge rules."""

    def __init__(
        self,
        *,
        agents: LoopAgents,
        case_manager: CaseManager,
        bm25_index: BM25Index,
        settings: Settings,
        retrieval_top_k: int = 25,
        max_rounds: int = 3,
    ) -> None:
        self.agents = agents
        self.case_manager = case_manager
        self.bm25_index = bm25_index
        self.settings = settings
        self.retrieval_top_k = retrieval_top_k
        # Hard cap on Defender ↔ Critic rounds. The convergence checker will
        # usually stop the loop earlier (after round 1 on clear cases). Setting
        # this to 1 disables iteration; 2-3 is the productive range.
        self.max_rounds = max(1, int(max_rounds))

    async def handle_message(self, case_id: str, message: str) -> LoopRunResult:
        """Run the agent loop end-to-end on one user message.

        Implemented on top of :meth:`stream_message` — it just drains the event
        stream and returns the terminal :class:`Final` payload. Callers that want
        to render intermediate progress (chat-mode CLI, future SSE) should iterate
        ``stream_message`` instead.
        """

        async for event in self.stream_message(case_id, message):
            if isinstance(event, Final):
                return event.result
        raise RuntimeError("stream_message terminated without emitting a Final event")

    async def stream_message(
        self, case_id: str, message: str
    ) -> AsyncIterator[LoopEvent]:
        """Drive the courtroom loop and emit :class:`LoopEvent`s as each agent runs.

        For agents whose underlying client supports streaming (currently only
        ``GeminiDirectClient``), text deltas are surfaced as :class:`AgentChunk`
        events as they arrive. The chat-mode CLI consumes these to render live
        per-agent panels; the API / ``run_case.py`` use :meth:`handle_message`
        which is a thin drain over this same stream.
        """

        t_total = time.perf_counter()
        case_state = await self.case_manager.get_or_create(case_id)
        timings = AgentTimings()

        # Build the cumulative summary up-front so every agent — Router included —
        # sees the same multi-turn context. Without this, follow-up turns where
        # the user types only labs / imaging / new findings would lose the
        # original chief complaint and the Router would refuse to commit (it
        # extracts the chief complaint from the message it sees, and on a
        # follow-up that message is just "Trop 0.8, ECG STEMI V1-V4" with no
        # presenting symptom). On turn 1, ``cumulative_summary == message`` so
        # behavior is unchanged.
        iteration = case_state.turn_count + 1
        cumulative_summary = _cumulative_summary(case_state, message)

        # 1. Router
        yield PhaseStarted(phase="router", label="Router", round=0)
        router_holder: list[Any] = []
        async for ev in _stream_agent_run(
            phase="router",
            label="Router",
            round_num=0,
            run_coro_factory=lambda cb: self.agents.router.run(
                case_state, user_message=cumulative_summary, on_chunk=cb
            ),
            summarizer=lambda out: _summarize_router(out),
            result_holder=router_holder,
        ):
            yield ev
            if isinstance(ev, AgentDone):
                timings.router_ms = ev.latency_ms
        router_out = router_holder[0]
        assert isinstance(router_out, RouterOutput)

        # Load the chosen template (router always emits one even on clarification),
        # plus any ancillary chapters the router flagged for multi-system cases.
        primary_template = load_template(router_out.template_slug)
        ancillary_templates: list[Template] = []
        loaded_ancillary_slugs: list[str] = []
        for slug in router_out.ancillary_template_slugs:
            if slug == router_out.template_slug:
                continue  # router shouldn't repeat the primary, but be defensive
            try:
                ancillary_templates.append(load_template(slug))
                loaded_ancillary_slugs.append(slug)
            except TemplateNotFoundError:
                # Router hallucinated a slug — skip it rather than fail the loop.
                continue
        template = _merge_templates(primary_template, ancillary_templates)

        # 2. Retrieval (BM25, single pass)
        t = time.perf_counter()
        retrieval_query = f"{message} {router_out.template_slug.replace('_', ' ')}"
        retrieved = self.bm25_index.search(retrieval_query, top_k=self.retrieval_top_k)
        timings.retrieval_ms = int((time.perf_counter() - t) * 1000)
        top_sources: list[str] = []
        seen_sources: set[str] = set()
        for hit in retrieved[:5]:
            src = hit.chunk.source
            if src not in seen_sources:
                seen_sources.add(src)
                top_sources.append(src)
        yield RetrievalDone(
            chunk_count=len(retrieved),
            top_sources=top_sources,
            latency_ms=timings.retrieval_ms,
        )

        # 3. Reasoner — pass prior turn context AND the current message via a synthetic
        # case_state whose messages_summary holds the cumulative summary. The Reasoner
        # prompt renders ``{{ case_state.messages_summary }}`` directly; if we passed
        # the unmodified case_state, the Reasoner would not see the user's message on
        # turn 1 (messages_summary is only updated by ``_apply_turn`` after all agents
        # finish). ``cumulative_summary`` and ``iteration`` were already computed
        # before the Router so every agent in the loop reasons against the same
        # multi-turn context.
        case_state_for_reasoner = case_state.model_copy(
            update={"messages_summary": cumulative_summary}
        )
        yield PhaseStarted(phase="reasoner", label="Reasoner", round=0)
        reasoner_holder: list[Any] = []
        async for ev in _stream_agent_run(
            phase="reasoner",
            label="Reasoner",
            round_num=0,
            run_coro_factory=lambda cb: self.agents.reasoner.run(
                case_state_for_reasoner,
                template=template,
                iteration=iteration,
                previous_findings=list(case_state.prior_findings),
                on_chunk=cb,
            ),
            summarizer=lambda out: _summarize_reasoner(str(out or "")),
            result_holder=reasoner_holder,
        ):
            yield ev
            if isinstance(ev, AgentDone):
                timings.reasoner_ms = ev.latency_ms
        reasoner_trace = str(reasoner_holder[0] or "")

        # 4. MNM Sweeper. We kick it off in parallel with the convergence loop
        # so the loop's first round can start immediately, then await MNM before
        # the Critic of round 1 (whose prompt reads the MNM gaps). MNM typically
        # finishes faster than a single Defender turn, so the parallelism is
        # essentially free.
        mnm_task = asyncio.create_task(
            self.agents.must_not_miss_sweeper.run(
                case_state,
                case_summary=cumulative_summary,
                reasoner_trace=reasoner_trace,
                template=template,
                retrieved_chunks=retrieved,
            )
        )

        # 5. Convergence loop: Defender ↔ Critic ↔ ConvergenceChecker.
        # Each round: Defender produces a structured-prose defense, then Critic
        # produces a structured-prose critique, then the convergence checker
        # decides whether to continue. We stop on convergence or after
        # ``max_rounds`` rounds (hard cap; default 3). Both Defender and Critic
        # are explicitly permitted to concede when warranted — that's the
        # structural fix for the "debate for debate's sake" pathology of the
        # courtroom layout this replaces.
        rounds: list[DialecticRound] = []
        dialectic_t0 = time.perf_counter()
        defender_total_ms = 0
        critic_total_ms = 0
        convergence_total_ms = 0
        mnm_out: MustNotMissSweep | None = None  # populated before round 1's critic
        converged = False
        for round_num in range(1, self.max_rounds + 1):
            # --- Defender ---
            d_phase = f"round_{round_num}_defender"
            d_label = f"Defender (Round {round_num})"
            yield PhaseStarted(phase=d_phase, label=d_label, round=round_num)
            d_holder: list[Any] = []
            async for ev in _stream_agent_run(
                phase=d_phase,
                label=d_label,
                round_num=round_num,
                run_coro_factory=_defender_factory(
                    self.agents.defender,
                    case_state,
                    cumulative_summary,
                    reasoner_trace,
                    template,
                    retrieved,
                    mnm_out,
                    round_num,
                    _serializable_prior_rounds(rounds),
                ),
                summarizer=_summarize_prose,
                result_holder=d_holder,
            ):
                yield ev
                if isinstance(ev, AgentDone):
                    defender_total_ms += ev.latency_ms
            defender_text = str(d_holder[0] or "")

            # --- Wait for MNM before the Critic (only first round) ---
            if mnm_out is None:
                yield PhaseStarted(phase="must_not_miss", label="Must-Not-Miss Sweeper", round=0)
                mnm_result = await mnm_task
                timings.must_not_miss_ms = mnm_result.latency_ms
                mnm_out = mnm_result.output
                assert isinstance(mnm_out, MustNotMissSweep)
                yield AgentDone(
                    phase="must_not_miss",
                    label="Must-Not-Miss Sweeper",
                    summary=_summarize_mnm(mnm_out),
                    latency_ms=timings.must_not_miss_ms,
                )

            # --- Critic ---
            c_phase = f"round_{round_num}_critic"
            c_label = f"Critic (Round {round_num})"
            yield PhaseStarted(phase=c_phase, label=c_label, round=round_num)
            c_holder: list[Any] = []
            async for ev in _stream_agent_run(
                phase=c_phase,
                label=c_label,
                round_num=round_num,
                run_coro_factory=_critic_factory(
                    self.agents.critic,
                    case_state,
                    cumulative_summary,
                    reasoner_trace,
                    template,
                    retrieved,
                    mnm_out,
                    round_num,
                    _serializable_prior_rounds(rounds),
                    defender_text,
                ),
                summarizer=_summarize_prose,
                result_holder=c_holder,
            ):
                yield ev
                if isinstance(ev, AgentDone):
                    critic_total_ms += ev.latency_ms
            critic_text = str(c_holder[0] or "")

            # --- Convergence check ---
            check: ConvergenceCheck | None = None
            if round_num < self.max_rounds:
                cc_phase = f"round_{round_num}_convergence"
                cc_label = f"Convergence Check (Round {round_num})"
                yield PhaseStarted(phase=cc_phase, label=cc_label, round=round_num)
                cc_holder: list[Any] = []
                # Bound copies for the closure so each iteration captures its own
                # round_num / prior_rounds / texts (lambdas in loops would alias).
                cc_factory = _convergence_checker_factory(
                    self.agents.convergence_checker,
                    case_state,
                    round_num=round_num,
                    prior_rounds=_serializable_prior_rounds(rounds),
                    current_defender=defender_text,
                    current_critic=critic_text,
                )
                async for ev in _stream_agent_run(
                    phase=cc_phase,
                    label=cc_label,
                    round_num=round_num,
                    run_coro_factory=cc_factory,
                    summarizer=_summarize_convergence,
                    result_holder=cc_holder,
                ):
                    yield ev
                    if isinstance(ev, AgentDone):
                        convergence_total_ms += ev.latency_ms
                check = cc_holder[0]
                assert isinstance(check, ConvergenceCheck)

            rounds.append(
                DialecticRound(
                    round=round_num,
                    defender_markdown=defender_text,
                    critic_markdown=critic_text,
                    convergence_check=check,
                )
            )

            if check is not None and check.converged:
                converged = True
                break

        # If the loop exhausted max_rounds without converging, that's fine —
        # the Judge will see the full transcript and rule on it.
        timings.prosecutor_ms = defender_total_ms  # legacy field repurposed for Defender
        timings.devils_advocate_ms = critic_total_ms  # legacy field repurposed for Critic
        timings.dialectic_total_ms = int((time.perf_counter() - dialectic_t0) * 1000)
        # Defensive: if max_rounds is exhausted without convergence and MNM was
        # somehow still pending (shouldn't happen — round 1 awaits it), drain.
        if mnm_out is None:
            mnm_result = await mnm_task
            mnm_out = mnm_result.output
            timings.must_not_miss_ms = mnm_result.latency_ms
            assert isinstance(mnm_out, MustNotMissSweep)

        # 6. Judge — sole decider. Reads Reasoner trace + Defender/Critic prose
        # transcripts + MNM. The Judge prompt is updated to consume markdown
        # rounds rather than the legacy ProsecutorArgument / DevilsAdvocateOutput
        # JSON args.
        yield PhaseStarted(phase="judge", label="Judge", round=0)
        judge_holder: list[Any] = []
        async for ev in _stream_agent_run(
            phase="judge",
            label="Judge",
            round_num=0,
            run_coro_factory=lambda cb: self.agents.judge.run(
                case_state,
                case_summary=cumulative_summary,
                reasoner_trace=reasoner_trace,
                template=template,
                retrieved_chunks=retrieved,
                rounds=list(rounds),
                converged=converged,
                mnm_sweep=mnm_out,
                on_chunk=cb,
            ),
            summarizer=_summarize_judge,
            result_holder=judge_holder,
        ):
            yield ev
            if isinstance(ev, AgentDone):
                timings.judge_ms = ev.latency_ms
        judge_verdict = judge_holder[0]
        assert isinstance(judge_verdict, JudgeVerdict)

        # 7. Synthesizer — pure renderer. Produces body_markdown + disclaimer + citations.
        yield PhaseStarted(phase="synthesizer", label="Synthesizer", round=0)
        synth_holder: list[Any] = []
        async for ev in _stream_agent_run(
            phase="synthesizer",
            label="Synthesizer",
            round_num=0,
            run_coro_factory=lambda cb: self.agents.synthesizer.run(
                case_state,
                judge_verdict=judge_verdict,
                reviewed_by=template.reviewed_by,
                on_chunk=cb,
            ),
            summarizer=_summarize_synth,
            result_holder=synth_holder,
        ):
            yield ev
            if isinstance(ev, AgentDone):
                timings.synthesizer_ms = ev.latency_ms
        synth_out = synth_holder[0]
        assert isinstance(synth_out, SynthesisOutput)

        # 8. Safety Reviewer
        yield PhaseStarted(phase="safety", label="Safety Reviewer", round=0)
        safety_holder: list[Any] = []
        async for ev in _stream_agent_run(
            phase="safety",
            label="Safety Reviewer",
            round_num=0,
            run_coro_factory=lambda cb: self.agents.safety_reviewer.run(
                case_state,
                # Use the cumulative summary, not just the latest user message:
                # the Safety Reviewer's PHI check compares the synthesis body
                # against what the user has told the system *across all turns*.
                # Passing only the follow-up message makes details from prior
                # turns (age, presenting complaint) look like hallucinated PHI
                # and trips a spurious refuse verdict.
                case_summary=cumulative_summary,
                synthesis_output=synth_out,
                reviewed_by=template.reviewed_by,
                on_chunk=cb,
            ),
            summarizer=_summarize_safety,
            result_holder=safety_holder,
        ):
            yield ev
            if isinstance(ev, AgentDone):
                timings.safety_reviewer_ms = ev.latency_ms
        safety_out = safety_holder[0]
        assert isinstance(safety_out, SafetyVerdict)

        # Build the user-facing output from synthesis + safety verdict.
        user_facing = _build_user_facing(synth_out, safety_out, judge_verdict)

        # Persist a small slice of derived state for /api/cases/{id} replay AND
        # for the next turn — prior_findings + appended messages_summary feed
        # the Reasoner / DA / MNM / Synthesizer on the follow-up call. We use
        # the Judge's verdict (not the Synthesizer's render) because the Judge
        # owns the clinical fields.
        await self.case_manager.update(case_id, _apply_turn(message, judge_verdict))

        timings.total_ms = int((time.perf_counter() - t_total) * 1000)

        # ``rounds`` was built up inside the convergence loop with prose
        # transcripts and per-round convergence checks — pass it through to the
        # trace verbatim. The legacy AgentTrace.devils_advocate slot is set to
        # an empty placeholder for backward compatibility with downstream
        # consumers that haven't migrated; once those are gone it can be deleted.
        trace = AgentTrace(
            template_slug=router_out.template_slug,
            chapter_number=router_out.chapter_number,
            ancillary_template_slugs=loaded_ancillary_slugs,
            router=router_out,
            retrieved_chunks=list(retrieved),
            reasoner_trace=reasoner_trace,
            dialectic_rounds=rounds,
            converged=converged,
            must_not_miss=mnm_out,
            judge_verdict=judge_verdict,
            synthesis=synth_out,
            safety=safety_out,
            timings=timings,
        )
        result = LoopRunResult(
            case_id=case_id,
            duration_ms=timings.total_ms,
            user_facing=user_facing,
            trace=trace,
        )
        yield Final(result=result)


# --- Helpers ---


async def _stream_agent_run(
    *,
    phase: str,
    label: str,
    round_num: int,
    run_coro_factory: RunCoroFactory,
    summarizer: Callable[[Any], str],
    result_holder: list[Any],
) -> AsyncIterator[LoopEvent]:
    """Drive one agent invocation as a stream of :class:`LoopEvent`s.

    The agent runs as a background task; an :class:`asyncio.Queue` interleaves
    its streamed text deltas with a final ``done`` marker. Chunks are emitted
    as :class:`AgentChunk` events; on completion an :class:`AgentDone` is
    emitted and the agent's parsed output is appended to ``result_holder`` so
    the caller can read it after iteration finishes.
    """

    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def on_chunk(delta: str) -> None:
        # Sync callback — the runtime's _emit will schedule it. We can put
        # synchronously because Queue.put_nowait is thread-safe on a single-loop
        # asyncio queue.
        if delta:
            queue.put_nowait(("chunk", delta))

    async def runner() -> AgentResult:
        try:
            res = await run_coro_factory(on_chunk)
        except BaseException as exc:
            # Catch BaseException so a CancelledError still flows back to the
            # consumer — ``await task`` below will re-raise the original.
            queue.put_nowait(("error", exc))
            raise
        queue.put_nowait(("done", res))
        return res

    t0 = time.perf_counter()
    task = asyncio.create_task(runner())
    while True:
        kind, payload = await queue.get()
        if kind == "chunk":
            yield AgentChunk(phase=phase, delta=str(payload))
        elif kind == "done":
            assert isinstance(payload, AgentResult)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            result_holder.append(payload.output)
            yield AgentDone(
                phase=phase,
                label=label,
                summary=summarizer(payload.output),
                latency_ms=latency_ms,
                round=round_num,
            )
            await task  # propagate any post-emit cleanup / exceptions
            return
        elif kind == "error":
            await task  # surface the original exception with its traceback
            return  # unreachable — the await above raises


def _serializable_prior_rounds(rounds: list[DialecticRound]) -> list[dict[str, Any]]:
    """Project ``DialecticRound`` objects into plain dicts for prompt rendering.

    Jinja templates render ``{{ pr.round }}`` etc.; passing pydantic objects
    directly works, but plain dicts are cheaper to copy and don't drag the
    convergence_check object into the prompt body where we don't need it.
    """

    return [
        {
            "round": r.round,
            "defender_markdown": r.defender_markdown,
            "critic_markdown": r.critic_markdown,
        }
        for r in rounds
    ]


def _defender_factory(
    agent: DefenderAgent,
    case_state: CaseState,
    cumulative_summary: str,
    reasoner_trace: str,
    template: Template,
    retrieved: Any,
    mnm_sweep: MustNotMissSweep | None,
    round_num: int,
    prior_rounds: list[dict[str, Any]],
) -> RunCoroFactory:
    """Bind the Defender's per-round kwargs to a callback-accepting factory."""

    def _factory(cb: Callable[[str], None]) -> Awaitable[AgentResult]:
        return agent.run(
            case_state,
            case_summary=cumulative_summary,
            reasoner_trace=reasoner_trace,
            template=template,
            retrieved_chunks=retrieved,
            mnm_sweep=mnm_sweep,
            round=round_num,
            prior_rounds=prior_rounds,
            on_chunk=cb,
        )

    return _factory


def _critic_factory(
    agent: CriticAgent,
    case_state: CaseState,
    cumulative_summary: str,
    reasoner_trace: str,
    template: Template,
    retrieved: Any,
    mnm_sweep: MustNotMissSweep | None,
    round_num: int,
    prior_rounds: list[dict[str, Any]],
    current_defender: str,
) -> RunCoroFactory:
    """Bind the Critic's per-round kwargs to a callback-accepting factory."""

    def _factory(cb: Callable[[str], None]) -> Awaitable[AgentResult]:
        return agent.run(
            case_state,
            case_summary=cumulative_summary,
            reasoner_trace=reasoner_trace,
            template=template,
            retrieved_chunks=retrieved,
            mnm_sweep=mnm_sweep,
            round=round_num,
            prior_rounds=prior_rounds,
            current_defender=current_defender,
            on_chunk=cb,
        )

    return _factory


def _convergence_checker_factory(
    agent: ConvergenceCheckerAgent,
    case_state: CaseState,
    *,
    round_num: int,
    prior_rounds: list[dict[str, Any]],
    current_defender: str,
    current_critic: str,
) -> RunCoroFactory:
    """Bind the convergence checker's per-round kwargs to a factory."""

    def _factory(cb: Callable[[str], None]) -> Awaitable[AgentResult]:
        return agent.run(
            case_state,
            round=round_num,
            prior_rounds=prior_rounds,
            current_defender=current_defender,
            current_critic=current_critic,
            on_chunk=cb,
        )

    return _factory


# --- Per-agent summarizers (what the chat UI shows under each panel header) ---


def _summarize_router(router_out: RouterOutput) -> str:
    pieces = [
        f"{router_out.template_slug} (Ch. {router_out.chapter_number}, "
        f"confidence {router_out.confidence:.2f})"
    ]
    if router_out.ancillary_template_slugs:
        pieces.append("+ " + ", ".join(router_out.ancillary_template_slugs))
    if router_out.requires_clarification and router_out.clarification_question:
        pieces.append(f"clarification: {router_out.clarification_question}")
    return " | ".join(pieces)


def _summarize_reasoner(text: str) -> str:
    # Reasoner is free-form markdown; surface a short head so the panel footer
    # is informative but not overwhelming.
    snippet = text.strip().replace("\n", " ")[:240]
    return snippet + ("…" if len(text) > 240 else "")


def _summarize_prose(text: str) -> str:
    """Summarize a free-form prose agent output for the chat panel footer.

    Looks for a "Bottom line" section and surfaces it; falls back to the first
    non-blank line if no Bottom line is present (or if the agent forgot to
    use the section header).
    """

    if not text:
        return "(no output)"
    lines = text.splitlines()
    # Find a "Bottom line" header and grab the next non-blank line.
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("### bottom line") or line.strip().lower() == "bottom line":
            for follow in lines[i + 1 :]:
                follow_stripped = follow.strip()
                if follow_stripped and not follow_stripped.startswith("#"):
                    return follow_stripped[:200] + ("…" if len(follow_stripped) > 200 else "")
            break
    # Fallback: first non-blank, non-header line.
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:200] + ("…" if len(stripped) > 200 else "")
    return text.strip()[:200]


def _summarize_convergence(c: ConvergenceCheck) -> str:
    state = "converged" if c.converged else "continue"
    return f"{state}: {c.reason[:200]}"


def _summarize_mnm(mnm: MustNotMissSweep) -> str:
    flagged = sum(1 for e in mnm.sweep if e.gap)
    bits = [f"{len(mnm.sweep)} dx swept", f"{flagged} gap(s)"]
    if mnm.requires_escalation:
        bits.append("ESCALATE")
    return ", ".join(bits)


def _summarize_judge(j: JudgeVerdict) -> str:
    out = f"{j.leading_diagnosis} ({j.confidence_band})"
    if j.active_alternatives:
        out += f" | active: {', '.join(j.active_alternatives[:3])}"
    return out


def _summarize_synth(s: SynthesisOutput) -> str:
    head = s.body_markdown.strip().splitlines()[0] if s.body_markdown.strip() else ""
    return head[:200]


def _summarize_safety(s: SafetyVerdict) -> str:
    bits: list[str] = [str(s.verdict)]
    if s.required_fixes:
        bits.append(f"{len(s.required_fixes)} fix(es)")
    if s.refusal_reason:
        bits.append(f"refusal: {s.refusal_reason[:120]}")
    return ", ".join(bits)


def _build_user_facing(
    synth: SynthesisOutput,
    safety: object,
    judge_verdict: JudgeVerdict,
) -> UserFacingOutput:
    """Project the Synthesizer's render onto the locked-down :class:`UserFacingOutput`.

    Falls back to the Judge's ``citations`` if the Synthesizer dropped them
    (defensive — citations should always be present, but we don't want a
    rendering bug to silently strip authority-tier evidence).
    """

    # The Safety Reviewer is the gate: refuse → REFUSAL message; approve/revise → COMMITMENT.
    verdict = getattr(safety, "verdict", "approve")
    if verdict == "refuse":
        body = getattr(safety, "refusal_reason", "") or "Output refused by safety reviewer."
        return UserFacingOutput(
            kind=OutputKind.REFUSAL,
            body=body,
            disclaimer=synth.research_demo_disclaimer,
            citations=[],
        )

    body_md = synth.body_markdown
    if verdict == "revise":
        fixes = getattr(safety, "required_fixes", []) or []
        if fixes:
            body_md = (
                body_md.rstrip()
                + "\n\n**Safety review notes**\n"
                + "\n".join(f"- {fix}" for fix in fixes)
            )

    raw_citations = synth.citations or judge_verdict.citations
    citations = [
        Citation(
            label=c.label,
            source=c.source,
            citation=c.citation,
            authority_tier=c.authority_tier,
        )
        for c in raw_citations
    ]
    return UserFacingOutput(
        kind=OutputKind.COMMITMENT,
        body=body_md,
        disclaimer=synth.research_demo_disclaimer,
        citations=citations,
    )


def _merge_templates(primary: Template, additionals: list[Template]) -> Template:
    """Merge ancillary chapters into the primary template so the loop reasons
    across the union of relevant chapters instead of just one.

    What gets merged (deduplicated by name, primary first):
      - ``differential`` — diagnoses from ancillaries are tagged in their ``notes``
        with the source chapter for provenance. Computed ``must_not_miss`` and
        ``leading_hypotheses`` derive from the merged differential automatically.
      - ``pivotal_points`` — case-distinguishing descriptors.
      - ``decision_rules`` — named rules (HEART, POUNDing, Wells, etc.).

    What is *not* merged (chapter-specific):
      - ``algorithm`` — flowchart steps reference internal ``target_step`` numbers;
        merging would create dangling references. Primary's algorithm wins.
      - ``framework_type`` / ``framework_categories`` / ``source_pages`` /
        ``chapter_number`` / ``chapter_title`` / ``complaint`` — these belong to
        the primary chapter's identity.
    """

    if not additionals:
        return primary

    seen_dx = {d.name.lower() for d in primary.differential}
    extra_dx = []
    for t in additionals:
        for d in t.differential:
            key = d.name.lower()
            if key in seen_dx:
                continue
            seen_dx.add(key)
            chapter_tag = f"[from Ch. {t.chapter_number} — {t.chapter_title}]"
            new_notes = f"{d.notes} {chapter_tag}".strip() if d.notes else chapter_tag
            extra_dx.append(d.model_copy(update={"notes": new_notes}))

    merged_pivotal = list(primary.pivotal_points)
    seen_pp = {pp.lower() for pp in merged_pivotal}
    for t in additionals:
        for pp in t.pivotal_points:
            if pp.lower() in seen_pp:
                continue
            seen_pp.add(pp.lower())
            merged_pivotal.append(pp)

    seen_rules = {r.name.lower() for r in primary.decision_rules}
    extra_rules = []
    for t in additionals:
        for r in t.decision_rules:
            if r.name.lower() in seen_rules:
                continue
            seen_rules.add(r.name.lower())
            extra_rules.append(r)

    return primary.model_copy(
        update={
            "differential": [*primary.differential, *extra_dx],
            "pivotal_points": merged_pivotal,
            "decision_rules": [*primary.decision_rules, *extra_rules],
        }
    )


def _cumulative_summary(state: CaseState, latest_message: str) -> str:
    """Build the case summary handed to DA / MNM / Synthesizer on multi-turn cases.

    Turn 1 — just the user's message.
    Turn N — prior accumulated summary + the new message clearly delimited so the
    LLM can tell historical context apart from the latest input.
    """

    if not state.messages_summary:
        return latest_message
    return (
        state.messages_summary.strip()
        + f"\n\n--- Latest message (turn {state.turn_count + 1}) ---\n"
        + latest_message
    )


def _apply_turn(message: str, verdict: JudgeVerdict):  # type: ignore[no-untyped-def]
    """Return a CaseMutator that records this turn (user message + Judge's verdict).

    Per the no-overlap rule, clinical fields come from the Judge — not from
    the Synthesizer. The Synthesizer's render is for the user; the Judge's
    structured verdict is what subsequent turns reason against.
    """

    def _mutate(state: CaseState) -> CaseState:
        new_turn = state.turn_count + 1
        appended_summary = (
            f"\n\n--- Turn {new_turn} user message ---\n{message[:16384]}"
            f"\n\n--- Turn {new_turn} Judge verdict ---\n"
            f"Leading: {verdict.leading_diagnosis} (confidence={verdict.confidence_band})\n"
            f"Active alternatives: {', '.join(verdict.active_alternatives) or '(none)'}\n"
            f"Rationale: {verdict.verdict_rationale[:1024]}\n"
            f"Closing: {verdict.closing_statement[:1024]}"
        )
        new_findings = [
            *state.prior_findings,
            f"Turn {new_turn} Judge leading dx: {verdict.leading_diagnosis} "
            f"({verdict.confidence_band} confidence)",
            f"Turn {new_turn} active alternatives: "
            f"{'; '.join(verdict.active_alternatives) or '(none)'}",
            f"Turn {new_turn} workup proposed: "
            f"{'; '.join(w.step for w in verdict.recommended_workup) or '(none)'}",
        ]
        return state.model_copy(
            update={
                "messages_summary": (state.messages_summary or "") + appended_summary,
                "turn_count": new_turn,
                "prior_findings": new_findings,
            }
        )

    return _mutate


__all__ = [
    "DiagnosticLoop",
    "LoopAgents",
]
