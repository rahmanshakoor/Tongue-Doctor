"""Interactive chat REPL for the courtroom diagnostic loop.

Modeled on Claude Code's CLI: you type the initial case info, the agents discuss
in real time (their writing streams to your terminal as it happens), the loop
returns a verdict, you type a follow-up, and the conversation continues with the
case state persisted across turns.

::

    make chat
    make chat CASE_ID=chest-pain-1
    make chat NO_PERSIST=1

    # or directly:
    uv run python -m scripts.chat
    uv run python -m scripts.chat --case-id existing-case
    uv run python -m scripts.chat --no-persist

While in the chat:

    /quit, /exit, q       end the session
    /new                  start a fresh case (new case_id)
    /case <id>            switch to / resume a different case_id
    /verbose              toggle full agent trace dump after each turn
    /help                 show this list

Pasted multi-line input is preserved as-is (bracketed-paste aware) — only a
real Enter keystroke submits, so paste a long case history and review before
sending. Up / Down arrows recall prior messages in this session.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import uuid
from pathlib import Path

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from tongue_doctor.orchestrator import DiagnosticLoop, LoopRunResult
from tongue_doctor.orchestrator.types import (
    AgentChunk,
    AgentDone,
    Final,
    PhaseStarted,
    RetrievalDone,
)
from tongue_doctor.settings import REPO_ROOT

from .run_case import _build_loop, _render_full_trace  # build the loop with the same agents

DEFAULT_CASE_STORE = REPO_ROOT / ".cases"

app = typer.Typer(
    add_completion=False,
    help="Interactive chat REPL — type case info, watch the agents argue live.",
)


# Mapping from phase slug → (icon, color) for the live panels.
PHASE_STYLE: dict[str, tuple[str, str]] = {
    "router": ("🧭", "cyan"),
    "reasoner": ("🧑‍⚕️", "blue"),
    "must_not_miss": ("🩺", "yellow"),
    "judge": ("⚖️", "magenta"),
    "synthesizer": ("✍️", "white"),
    "safety": ("🛡️", "green"),
}
DIALECTIC_STYLE: dict[str, tuple[str, str]] = {
    "prosecutor": ("⚔️", "red"),
    "devils_advocate": ("😈", "yellow"),
}


def _phase_style(phase: str) -> tuple[str, str]:
    """Resolve a phase slug to ``(icon, color)``.

    Round-tagged dialectic phases (``round_2_prosecutor``, ``round_3_devils_advocate``)
    fall back to the dialectic icons.
    """

    if phase in PHASE_STYLE:
        return PHASE_STYLE[phase]
    if phase.endswith("_prosecutor"):
        return DIALECTIC_STYLE["prosecutor"]
    if phase.endswith("_devils_advocate"):
        return DIALECTIC_STYLE["devils_advocate"]
    return ("•", "white")


def _print_banner(console: Console, case_id: str, persist_dir: Path | None) -> None:
    head = Text.assemble(
        ("Tongue-Doctor chat — research demo. Not a clinical tool.\n", "bold"),
        ("Type case details, send, and watch the agents argue in real time.\n", "dim"),
        ("Slash commands: /quit /new /case <id> /verbose /help\n", "dim"),
    )
    console.print(Panel(head, title="🩺 chat mode", border_style="cyan"))
    persist_note = (
        f"Persistence: {persist_dir}/{case_id}.json"
        if persist_dir is not None
        else "Persistence: off (in-memory only)"
    )
    console.print(f"[dim]case_id={case_id} | {persist_note}[/dim]")


def _print_phase_header(console: Console, ev: PhaseStarted) -> None:
    icon, color = _phase_style(ev.phase)
    console.print()
    console.print(Rule(f"{icon} {ev.label}", style=color, align="left"))


def _print_chunk(delta: str) -> None:
    """Stream a token delta to stdout without rich coloring.

    We avoid ``console.print`` here because rich would buffer / re-flow the line
    breaks; the agents' output (especially Reasoner markdown and Judge JSON) is
    most readable when the deltas appear character-for-character as they arrive.
    """

    sys.stdout.write(delta)
    sys.stdout.flush()


def _print_agent_done(console: Console, ev: AgentDone) -> None:
    icon, color = _phase_style(ev.phase)
    # Make sure we end the streamed body on its own line before the footer.
    if not _LAST_LINE_ENDED.get("flag", True):
        sys.stdout.write("\n")
        sys.stdout.flush()
    summary = ev.summary.strip() or "(no summary)"
    console.print(
        f"[{color}]{icon} {ev.label}[/{color}] [dim]→ {summary}  ({ev.latency_ms} ms)[/dim]"
    )
    _LAST_LINE_ENDED["flag"] = True


def _print_retrieval_done(console: Console, ev: RetrievalDone) -> None:
    sources = ", ".join(ev.top_sources) if ev.top_sources else "(no sources)"
    console.print()
    console.print(Rule("📚 Retrieval", style="dim", align="left"))
    console.print(
        f"[dim]{ev.chunk_count} chunks indexed (top sources: {sources}) — {ev.latency_ms} ms[/dim]"
    )


def _print_final(console: Console, result: LoopRunResult, *, verbose: bool) -> None:
    console.print()
    console.print(Rule("Final answer", style="bold green", align="left"))
    console.print(Markdown(result.user_facing.body))
    if result.user_facing.citations:
        console.print()
        console.print("[bold]Citations[/bold]")
        for c in result.user_facing.citations:
            console.print(
                f"  • {c.label} [dim]({c.source}, tier {c.authority_tier})[/dim] — {c.citation}"
            )
    console.print()
    console.print(f"[dim italic]{result.user_facing.disclaimer}[/dim italic]")
    console.print(f"[dim]Total wall time: {result.duration_ms} ms[/dim]")

    if verbose:
        console.print()
        console.print(Rule("Agent trace (verbose)", style="dim"))
        for line in _render_full_trace(result):
            console.print(line)


# Tracks whether the streaming output ended with a newline. Some agents stream
# JSON without a trailing newline; without this we'd glue the footer onto the
# last token. The dict-of-bool dance gives mutability inside helpers.
_LAST_LINE_ENDED: dict[str, bool] = {"flag": True}


async def _drive_turn(
    loop: DiagnosticLoop,
    console: Console,
    case_id: str,
    message: str,
    *,
    verbose: bool,
) -> LoopRunResult:
    """Drive one turn through ``stream_message`` and render every event live."""

    final_result: LoopRunResult | None = None
    async for event in loop.stream_message(case_id, message):
        if isinstance(event, PhaseStarted):
            _print_phase_header(console, event)
            _LAST_LINE_ENDED["flag"] = True
        elif isinstance(event, AgentChunk):
            _print_chunk(event.delta)
            # Track whether the most recent character was a newline so the
            # AgentDone footer prints on a fresh line.
            _LAST_LINE_ENDED["flag"] = event.delta.endswith("\n")
        elif isinstance(event, RetrievalDone):
            _print_retrieval_done(console, event)
        elif isinstance(event, AgentDone):
            _print_agent_done(console, event)
        elif isinstance(event, Final):
            final_result = event.result
            _print_final(console, event.result, verbose=verbose)
        else:  # pragma: no cover — exhaustive union
            console.print(f"[red]unknown event: {event!r}[/red]")
    if final_result is None:
        raise RuntimeError("stream_message ended without a Final event")
    return final_result


def _drain_stdin() -> None:
    """Discard keystrokes the user typed while the previous turn was streaming.

    A turn can take 60-180 s. Anything the user types during that window — out of
    curiosity, impatience, or accident — gets queued into the terminal's input
    buffer. Without draining, ``console.input`` would feed those buffered
    characters straight into the next prompt: a stray Enter alone is enough to
    kick off another loop with whatever fragment was queued. The fix is platform-
    specific because POSIX and Windows expose different APIs for the TTY input
    buffer; both are best-effort and silently no-op on non-TTY (piped) stdin.
    """

    if not sys.stdin.isatty():
        return  # piped / scripted input — don't discard the script's bytes
    if sys.platform == "win32":
        try:
            import msvcrt  # type: ignore[import-not-found]

            while msvcrt.kbhit():
                msvcrt.getch()
        except ImportError:
            return
        return
    try:
        import termios

        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except (OSError, ImportError):
        return


# Lazily-initialized prompt_toolkit session — gives us native bracketed-paste
# handling (multi-line paste accumulates in the buffer instead of submitting on
# the first embedded ``\n``), in-session history (Up/Down recalls prior
# messages), and proper Ctrl-C/Ctrl-D semantics. We hold one session for the
# life of the REPL so history persists across turns.
_INPUT_SESSION: PromptSession[str] | None = None


def _get_input_session() -> PromptSession[str]:
    global _INPUT_SESSION
    if _INPUT_SESSION is None:
        # The Unicode chevron is the literal prompt indicator we want users to
        # see; ruff's "ambiguous character" lint doesn't apply to deliberate UI.
        prompt_indicator = "\N{HEAVY RIGHT-POINTING ANGLE QUOTATION MARK ORNAMENT} "
        _INPUT_SESSION = PromptSession[str](
            message=FormattedText([("ansicyan bold", prompt_indicator)]),
            multiline=False,  # one-line conceptually; paste with newlines still works via bracketed paste
            enable_history_search=True,
            mouse_support=False,
        )
    return _INPUT_SESSION


def _print_rule(console: Console) -> None:
    """Draw a single full-width separator that frames the input area.

    Rendered ourselves rather than via ``rich.rule.Rule`` so the line is plain
    ASCII / box-drawing characters with no embedded title — matches the
    Claude Code input frame look.
    """

    width = max(1, console.size.width)
    console.print("[dim]" + ("─" * width) + "[/dim]", highlight=False)


async def _read_message(console: Console) -> str:
    """Read one user message via a framed prompt with bracketed-paste support.

    Uses prompt_toolkit's async API (``prompt_async``) because the chat REPL
    already runs inside ``asyncio.run(_chat_loop(...))`` — the synchronous
    ``prompt()`` would try to spin up a second event loop and fail with
    ``RuntimeError: asyncio.run() cannot be called from a running event loop``.

    The visual: a horizontal rule above and below the prompt line, with a
    chevron prompt indicator. Bracketed paste mode (handled by prompt_toolkit)
    means pasting multi-line text doesn't submit on the first embedded newline
    — only a real Enter keystroke submits, so you can paste a long case
    history and review it before sending.

    A buffered-stdin drain (see :func:`_drain_stdin`) runs first so any keys
    hit during the prior turn's streaming don't leak into this prompt.
    """

    _drain_stdin()
    console.print()
    _print_rule(console)
    session = _get_input_session()
    try:
        text = await session.prompt_async()
    except EOFError:
        # Ctrl-D on an empty buffer.
        return "/quit"
    except KeyboardInterrupt:
        # Ctrl-C clears the prompt — return empty so the REPL re-prompts.
        return ""
    finally:
        _print_rule(console)
    return text


def _print_help(console: Console) -> None:
    console.print(
        Panel(
            Text.assemble(
                ("/quit, /exit, q   ", "bold"),
                ("end the session\n", ""),
                ("/new              ", "bold"),
                ("start a fresh case (new case_id)\n", ""),
                ("/case <id>        ", "bold"),
                ("switch to / resume a different case_id\n", ""),
                ("/verbose          ", "bold"),
                ("toggle full agent trace dump after each turn\n", ""),
                ("/help             ", "bold"),
                ("show this help\n", ""),
                ("\n", ""),
                ("Multi-line input: ", "dim"),
                ("paste with newlines as normal — only your real Enter submits.\n", "dim"),
                ("History: ", "dim"),
                ("Up / Down arrows recall prior messages in this session.\n", "dim"),
            ),
            title="commands",
            border_style="dim",
        )
    )


async def _chat_loop(
    *,
    initial_case_id: str,
    persist_dir: Path | None,
    top_k: int,
    verbose_initial: bool,
) -> None:
    console = Console()
    loop = _build_loop(retrieval_top_k=top_k, persist_dir=persist_dir)
    case_id = initial_case_id
    verbose = verbose_initial

    _print_banner(console, case_id, persist_dir)

    while True:
        message = await _read_message(console)
        cmd = message.strip().lower()
        if cmd in {"/quit", "/exit", "q", ""}:
            if cmd == "":
                continue
            console.print("[dim]bye.[/dim]")
            return
        if cmd == "/help":
            _print_help(console)
            continue
        if cmd == "/new":
            case_id = f"chat-{uuid.uuid4().hex[:8]}"
            console.print(f"[dim]new case → {case_id}[/dim]")
            continue
        if cmd.startswith("/case"):
            parts = message.strip().split(maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                console.print("[red]usage: /case <id>[/red]")
                continue
            case_id = parts[1].strip()
            console.print(f"[dim]switched to case {case_id}[/dim]")
            continue
        if cmd == "/verbose":
            verbose = not verbose
            console.print(f"[dim]verbose: {'on' if verbose else 'off'}[/dim]")
            continue
        if message.strip().startswith("/"):
            console.print(f"[red]unknown command: {message.strip()}[/red]")
            console.print("[dim]type /help for the list[/dim]")
            continue

        try:
            await _drive_turn(loop, console, case_id, message, verbose=verbose)
        except KeyboardInterrupt:
            console.print("\n[dim]turn interrupted.[/dim]")
        except Exception as exc:
            # Show the error but keep the REPL alive — a single bad turn shouldn't
            # force the user to restart and lose their case context.
            console.print(f"\n[red]turn failed: {exc!r}[/red]")
            console.print("[dim]you can keep typing — case state is unchanged for this turn.[/dim]")


@app.command()
def chat(
    case_id: str | None = typer.Option(
        None,
        "--case-id",
        help="Resume an existing case from .cases/<id>.json. Omit for a fresh chat.",
    ),
    persist_dir: Path | None = typer.Option(
        None,
        "--persist-dir",
        help="Directory for case state (default: <repo>/.cases). Use --no-persist for in-memory.",
    ),
    no_persist: bool = typer.Option(
        False,
        "--no-persist",
        help="Disable disk persistence; case state evaporates when the chat exits.",
    ),
    top_k: int = typer.Option(25, "--top-k", help="Top-K BM25 chunks to retrieve per turn."),
    verbose: bool = typer.Option(
        False, "--verbose", help="Print the full agent trace after every turn."
    ),
) -> None:
    """Start an interactive chat with the diagnostic loop."""

    # Surface rate-limit / retry messages from the Gemini client to the user.
    # Without this they go to the default last-resort handler with no formatting,
    # which interleaves badly with the rich panels. Format keeps it short so the
    # warnings don't visually overpower the agents' streamed output.
    logging.basicConfig(
        level=logging.WARNING,
        format="\033[33m⚠ %(message)s\033[0m",  # yellow ANSI, no logger name / timestamp
        stream=sys.stderr,
    )

    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        typer.echo(
            "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set. "
            "Set it in your shell or .env before starting the chat.",
            err=True,
        )
        raise typer.Exit(code=1)

    cid = case_id or f"chat-{uuid.uuid4().hex[:8]}"
    resolved_persist: Path | None = None if no_persist else (persist_dir or DEFAULT_CASE_STORE)

    # Ctrl-C at the prompt should exit cleanly without dumping a traceback.
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(
            _chat_loop(
                initial_case_id=cid,
                persist_dir=resolved_persist,
                top_k=top_k,
                verbose_initial=verbose,
            )
        )


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
