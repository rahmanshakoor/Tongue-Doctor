"""End-to-end case runner CLI.

Drives the full diagnostic loop (Router → BM25 → Reasoner → DA + MNM → Synth → Safety)
on a free-text case description and prints either a markdown summary or the JSON trace.

Requires ``GEMINI_API_KEY`` in the environment (see ``.env.example``).

::

    uv run python scripts/run_case.py "55M crushing chest pain radiating to left arm"
    uv run python scripts/run_case.py "55M chest pain" --output json
    uv run python scripts/run_case.py "55M chest pain" --verbose
    uv run python scripts/run_case.py --from-file case.txt
    cat case.txt | uv run python scripts/run_case.py -
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import typer

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
from tongue_doctor.models import get_client
from tongue_doctor.orchestrator import (
    CaseManager,
    DiagnosticLoop,
    LoopAgents,
    LoopRunResult,
)
from tongue_doctor.retrieval.index import BM25Index
from tongue_doctor.settings import REPO_ROOT, get_settings

# Where the CLI persists case state across invocations. Each ``--case-id`` gets
# its own JSON file; on the next call we hydrate from disk so multi-turn works.
DEFAULT_CASE_STORE = REPO_ROOT / ".cases"

app = typer.Typer(add_completion=False, help="Run the full diagnostic agent loop on a case.")


def _build_loop(
    retrieval_top_k: int = 25,
    *,
    persist_dir: Path | None = None,
) -> DiagnosticLoop:
    """Construct the loop with all 6 agents wired to their configured LLM clients.

    ``persist_dir`` writes case state to disk after each turn so a follow-up CLI
    invocation reusing the same ``--case-id`` picks up where the prior turn left off.
    """

    settings = get_settings()
    agents = LoopAgents(
        router=RouterAgent(get_client("router")),
        reasoner=ReasonerAgent(get_client("reasoner")),
        defender=DefenderAgent(get_client("defender")),
        critic=CriticAgent(get_client("critic")),
        convergence_checker=ConvergenceCheckerAgent(get_client("convergence_checker")),
        must_not_miss_sweeper=MustNotMissSweeperAgent(get_client("must_not_miss_sweeper")),
        judge=JudgeAgent(get_client("judge")),
        synthesizer=SynthesizerAgent(get_client("synthesizer")),
        safety_reviewer=SafetyReviewerAgent(get_client("safety_reviewer")),
    )
    bm25 = BM25Index()
    if not bm25.sources:
        typer.echo(
            "No BM25 indices found under knowledge/_local/. "
            "Run `make build-bm25-index` first.",
            err=True,
        )
        raise typer.Exit(code=2)
    return DiagnosticLoop(
        agents=agents,
        case_manager=CaseManager(persist_dir=persist_dir),
        bm25_index=bm25,
        settings=settings,
        retrieval_top_k=retrieval_top_k,
    )


def _render_markdown(result: LoopRunResult, *, verbose: bool) -> str:
    """Format the run result as a human-readable markdown summary."""

    lines: list[str] = []
    lines.append(f"# Case {result.case_id}")
    lines.append("")
    lines.append(
        f"**Routed to:** `{result.trace.template_slug}` "
        f"(Ch. {result.trace.chapter_number}, confidence {result.trace.router.confidence:.2f})"
    )
    if result.trace.ancillary_template_slugs:
        lines.append(
            "**Also reasoning across:** "
            + ", ".join(f"`{s}`" for s in result.trace.ancillary_template_slugs)
        )
    lines.append(f"**Wall time:** {result.duration_ms} ms")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(result.user_facing.body)
    lines.append("")
    lines.append("---")
    lines.append("")
    if result.user_facing.citations:
        lines.append("**Citations**")
        for c in result.user_facing.citations:
            lines.append(f"- {c.label} ({c.source}, tier {c.authority_tier}) — {c.citation}")
    lines.append("")
    lines.append(f"_{result.user_facing.disclaimer}_")
    if verbose:
        lines.extend(_render_full_trace(result))
    return "\n".join(lines)


def _render_full_trace(result: LoopRunResult) -> list[str]:
    """Verbose section: every agent's structured output, in pipeline order.

    Sections (in pipeline order):
        Router → Retrieval → Reasoner → Devil's Advocate → Must-Not-Miss
        → Synthesis details → Safety verdict → Timings.
    """

    out: list[str] = []
    t = result.trace

    out.extend(["", "---", "", "# Full agent trace"])

    # --- Router ---
    out.extend(["", "## 1. Router"])
    out.append(f"- Primary: `{t.router.template_slug}` (Ch. {t.router.chapter_number}, "
               f"confidence {t.router.confidence:.2f})")
    if t.ancillary_template_slugs:
        out.append(
            "- Ancillary chapters merged into the differential: "
            + ", ".join(f"`{s}`" for s in t.ancillary_template_slugs)
        )
    out.append(f"- Rationale: {t.router.rationale}")
    if t.router.fallback_slug:
        out.append(f"- Fallback primary: `{t.router.fallback_slug}`")
    if t.router.requires_clarification:
        out.append(f"- ⚠ Clarification requested: {t.router.clarification_question}")

    # --- Retrieval ---
    out.extend(["", "## 2. Retrieval (top BM25 hits)"])
    if not t.retrieved_chunks:
        out.append("- _no chunks retrieved_")
    else:
        for hit in t.retrieved_chunks[:15]:
            chunk = hit.chunk
            snippet = chunk.text[:200].strip().replace("\n", " ")
            out.append(
                f"- rank {hit.rank} (score {hit.score:.2f}) "
                f"[{chunk.source} | tier {int(chunk.authority_tier)}] "
                f"{chunk.citation} — {chunk.source_location}"
            )
            if snippet:
                out.append(f"  > {snippet}{'…' if len(chunk.text) > 200 else ''}")
        if len(t.retrieved_chunks) > 15:
            out.append(f"- _… {len(t.retrieved_chunks) - 15} more not shown_")

    # --- Reasoner ---
    out.extend(["", "## 3. Reasoner (Stern 9-step trace)", "", t.reasoner_trace.strip()])

    # --- Defender ↔ Critic convergence transcripts ---
    out.extend(["", f"## 4. Defender ↔ Critic review (converged: {t.converged})"])
    if not t.dialectic_rounds:
        out.append("- _no review rounds were held_")
    for dr in t.dialectic_rounds:
        out.extend(["", f"### Round {dr.round}"])
        out.extend(["", "**Defender:**"])
        out.append(dr.defender_markdown)
        out.extend(["", "**Critic:**"])
        out.append(dr.critic_markdown)
        if dr.convergence_check is not None:
            cc = dr.convergence_check
            out.extend(
                [
                    "",
                    f"**Convergence:** {'converged' if cc.converged else 'continue'} "
                    f"— {cc.reason}",
                ]
            )
            if cc.new_points_this_round:
                for p in cc.new_points_this_round:
                    out.append(f"  - new point: {p}")

    # --- Must-Not-Miss ---
    mnm = t.must_not_miss
    out.extend(["", "## 5. Must-Not-Miss sweep"])
    out.append(f"- **Requires escalation:** {mnm.requires_escalation}")
    if mnm.sweep:
        for entry in mnm.sweep:
            mark = "✓" if entry.considered_in_trace and not entry.gap else "!"
            line = (
                f"- [{mark}] **{entry.diagnosis}** — test: "
                f"{entry.test_to_rule_out or '(unspecified)'}"
            )
            if entry.lr_negative is not None:
                line += f" (LR- {entry.lr_negative})"
            if entry.test_result_in_case:
                line += f" — case result: {entry.test_result_in_case}"
            if entry.gap:
                line += f" — **gap:** {entry.gap}"
            out.append(line)
    if mnm.gaps_identified:
        out.append("- **Gaps identified:**")
        for gap in mnm.gaps_identified:
            out.append(f"  - {gap}")
    if mnm.summary:
        out.append(f"- **Summary:** {mnm.summary}")

    # --- Judge verdict (sole decider) ---
    jv = t.judge_verdict
    out.extend(["", "## 6. Judge's verdict"])
    if jv is None:
        out.append("- _no verdict (degenerate run)_")
    else:
        out.append(f"- **Leading diagnosis:** {jv.leading_diagnosis} "
                   f"(confidence: {jv.confidence_band})")
        out.append(f"- **Verdict rationale:** {jv.verdict_rationale}")
        if jv.defender_strengths:
            out.append("- **Defender strengths accepted:**")
            for s in jv.defender_strengths:
                out.append(f"  - {s}")
        if jv.defender_weaknesses:
            out.append("- **Defender weaknesses (rejected):**")
            for s in jv.defender_weaknesses:
                out.append(f"  - {s}")
        if jv.critic_strengths:
            out.append("- **Critic strengths accepted:**")
            for s in jv.critic_strengths:
                out.append(f"  - {s}")
        if jv.critic_weaknesses:
            out.append("- **Critic weaknesses (rejected):**")
            for s in jv.critic_weaknesses:
                out.append(f"  - {s}")
        if jv.active_alternatives:
            out.append(f"- **Active alternatives:** {', '.join(jv.active_alternatives)}")
        if jv.excluded_alternatives:
            out.append("- **Excluded alternatives:**")
            for x in jv.excluded_alternatives:
                out.append(f"  - {x}")
        if jv.recommended_workup:
            out.append("- **Recommended workup (with rationale):**")
            for w in jv.recommended_workup:
                lr = f" — {w.lr_plus_or_minus}" if w.lr_plus_or_minus else ""
                cite = f" [{w.citation}]" if w.citation else ""
                out.append(f"  - **{w.step}** — {w.rationale}{lr}{cite}")
        if jv.red_flags_to_monitor:
            out.append("- **Red flags to monitor:**")
            for rf in jv.red_flags_to_monitor:
                out.append(f"  - {rf}")
        if jv.educational_treatment_classes:
            out.append(
                f"- **Educational treatment classes:** "
                f"{', '.join(jv.educational_treatment_classes)}"
            )
        out.append(f"- **Closing statement:** {jv.closing_statement}")
        out.append(f"- **Rounds held:** {jv.rounds_held}")

    # --- Safety verdict ---
    sv = t.safety
    out.extend(["", "## 7. Safety verdict"])
    out.append(f"- **Verdict:** {sv.verdict}")
    out.append(f"- **Disclaimer present:** {sv.disclaimer_present}")
    out.append(f"- **Prescription leak detected:** {sv.prescription_leak_detected}")
    out.append(f"- **PHI detected:** {sv.phi_detected}")
    out.append(f"- **Citation completeness:** {sv.citation_completeness}")
    if sv.refusal_reason:
        out.append(f"- **Refusal reason:** {sv.refusal_reason}")
    if sv.required_fixes:
        out.append("- **Required fixes:**")
        for fix in sv.required_fixes:
            out.append(f"  - {fix}")
    if sv.summary:
        out.append(f"- **Summary:** {sv.summary}")

    # --- Timings ---
    out.extend(["", "## 8. Timings (ms)"])
    timings = t.timings
    for label, value in (
        ("router", timings.router_ms),
        ("retrieval", timings.retrieval_ms),
        ("reasoner", timings.reasoner_ms),
        ("defender (cumulative)", timings.prosecutor_ms),
        ("critic (cumulative)", timings.devils_advocate_ms),
        ("dialectic wall-time", timings.dialectic_total_ms),
        ("must_not_miss", timings.must_not_miss_ms),
        ("judge", timings.judge_ms),
        ("synthesizer", timings.synthesizer_ms),
        ("safety_reviewer", timings.safety_reviewer_ms),
        ("**total**", timings.total_ms),
    ):
        out.append(f"- {label}: {value}")
    return out


def _resolve_message(message_arg: str | None, from_file: Path | None) -> str:
    """Pick the case description from --from-file > stdin (when arg is '-') > positional arg."""

    if from_file is not None:
        return from_file.read_text(encoding="utf-8").strip()
    if message_arg == "-":
        return sys.stdin.read().strip()
    if message_arg:
        return message_arg.strip()
    return ""


@app.command()
def run(
    message: str = typer.Argument(
        "",
        help=(
            "Free-text case description. Pass '-' to read from stdin. "
            "Omit when using --from-file."
        ),
    ),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        "-f",
        help="Read the case description from a text file (handles multi-line inputs cleanly).",
    ),
    case_id: str | None = typer.Option(
        None,
        "--case-id",
        help=(
            "Client-supplied case id. Reuse the same id on follow-up calls to thread "
            "prior context (state is persisted to .cases/<id>.json by default)."
        ),
    ),
    output: str = typer.Option("markdown", "--output", help="markdown or json"),
    verbose: bool = typer.Option(False, "--verbose", help="Include intermediate agent traces."),
    top_k: int = typer.Option(25, "--top-k", help="Top-K BM25 chunks to retrieve."),
    persist_dir: Path | None = typer.Option(
        None,
        "--persist-dir",
        help=(
            "Directory for cross-process case state. Defaults to <repo>/.cases. "
            "Use --no-persist (or set to /dev/null) for an ephemeral run."
        ),
    ),
    no_persist: bool = typer.Option(
        False,
        "--no-persist",
        help="Disable disk persistence; case state evaporates when the process exits.",
    ),
) -> None:
    if output not in {"markdown", "json"}:
        typer.echo(f"--output must be 'markdown' or 'json' (got {output!r})", err=True)
        raise typer.Exit(code=1)

    case_message = _resolve_message(message, from_file)
    if not case_message:
        typer.echo(
            "No case description supplied. Pass it as a positional argument, "
            "via --from-file <path>, or pipe it on stdin with '-'.",
            err=True,
        )
        raise typer.Exit(code=1)

    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        typer.echo(
            "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set. "
            "Set it in your shell or .env before running.",
            err=True,
        )
        raise typer.Exit(code=1)

    cid = case_id or f"cli-{uuid.uuid4().hex[:8]}"
    resolved_persist: Path | None = None if no_persist else (persist_dir or DEFAULT_CASE_STORE)
    loop = _build_loop(retrieval_top_k=top_k, persist_dir=resolved_persist)

    async def _go() -> LoopRunResult:
        return await loop.handle_message(cid, case_message)

    result = asyncio.run(_go())
    if output == "json":
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(_render_markdown(result, verbose=verbose))
        if resolved_persist is not None:
            typer.echo(
                f"\n_Case state saved to {resolved_persist / (cid + '.json')}._\n"
                f"_Reuse with:_ `make run-case CASE='<follow-up message>' "
                f"CASE_ID={cid}`",
                err=False,
            )


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__: list[Any] = []
