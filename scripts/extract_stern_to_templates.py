"""Vision-augmented per-chapter extraction of Stern complaint templates.

For each Stern complaint chapter (3-33), this script:

1. Reads the chapter's chunks from the local corpus (must run ``ingest_stern.py``
   first).
2. Detects ``Figure N-N`` and ``Table N-N`` captions in the text and resolves
   each to its rendered PDF page.
3. Renders those pages to PNG via pymupdf (transient by default, persisted to
   ``knowledge/_local/stern/_debug/`` only when ``--save-debug-images`` is set).
4. Sends one multimodal Claude request per chapter — chapter text + rendered
   figure pages — and forces a structured-output tool call matching
   :class:`Template`.
5. Validates the response and writes
   ``src/tongue_doctor/templates/data/<complaint>.yaml``.

Per the project posture, **diagrams are not persisted as runtime data** — they
inform extraction. The resulting template carries an ``algorithm[]`` field
distilled from the flowcharts plus a ``derived_from_figure`` provenance string.

Run::

    uv run python scripts/extract_stern_to_templates.py --chapter 9
    uv run python scripts/extract_stern_to_templates.py --all
    uv run python scripts/extract_stern_to_templates.py --chapter 9 \\
        --save-debug-images --model claude-sonnet-4-6
"""

from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import Iterable
from pathlib import Path

import fitz  # pymupdf
import typer
import yaml

from tongue_doctor.knowledge.ingest.base import default_root
from tongue_doctor.knowledge.ingest.sources.stern import DEFAULT_PDF_FILENAME
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore
from tongue_doctor.knowledge.schema import Chunk
from tongue_doctor.models.anthropic_direct import AnthropicDirectClient
from tongue_doctor.templates.schema import Template

DEFAULT_MODEL = "claude-opus-4-5"
DEFAULT_MAX_OUTPUT_TOKENS = 8192

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DATA_DIR = REPO_ROOT / "src" / "tongue_doctor" / "templates" / "data"
DEBUG_IMAGES_ROOT = REPO_ROOT / "knowledge" / "_local" / "stern" / "_debug"

_FIGURE_RE = re.compile(r"^Figure\s+(\d+-\d+)\.\s*(.*)$")
_TABLE_RE = re.compile(r"^Table\s+(\d+-\d+)\.\s*(.*)$")
_PAGE_RE = re.compile(r"p\.(\d+)$")

# Chapters 1 (Diagnostic Process) and 2 (Screening and Health Maintenance) are
# meta-chapters, not chief complaints — they don't get templates.
_TEMPLATE_CHAPTER_MIN = 3

SYSTEM_PROMPT = """\
You are extracting a structured per-complaint reasoning template from a chapter
of Stern, Cifu & Altkorn — *Symptoms to Diagnosis* (4th ed., 2020). The result
will populate the per-chapter knowledge base for a research demonstration of
clinical reasoning. Your output must be a single JSON object that conforms to
the supplied schema; do not return free text.

This is for internal research use. The template will be marked
``reviewed_by: "pending"`` regardless of what the model believes; do not change
that field.

Stern's per-chapter shape is highly consistent. Use these directives:

1. **Differential bucketing** — Stern's taxonomy is exact:
     - "Leading Hypothesis" → role = "leading"
     - "Active Alternative — Most Common" → role = "active_most_common"
     - "Active Alternative — Must Not Miss" → role = "active_must_not_miss"
     - "Other Alternative" / "Other Hypothesis" → role = "other"
   Walk every "Diagnostic Hypotheses" / "Differential Diagnosis" table and emit
   ONE ``DiagnosisHypothesis`` entry per row. Multiple cases per chapter (e.g.,
   acute vs. chronic) merge into a single union of diagnoses; if a diagnosis is
   "Must Not Miss" in any case, that role wins.

2. **Per-diagnosis fields** — populate from Stern's "Disease Highlights",
   "Evidence-Based Diagnosis", and "Treatment" subsections:
     - ``textbook_presentation``: a one- to three-sentence paraphrase of the
       Disease Highlights opening.
     - ``disease_highlights``: bullet list of the lettered A-Z items.
     - ``evidence_based_diagnosis``: one ``TestCharacteristic`` per concrete
       test mentioned, with sensitivity / specificity / LR+ / LR- when the text
       gives them. Cite "Stern p.<page>" in each entry.
     - ``treatment_classes``: educational drug *classes* only (e.g.,
       "antiplatelet", "statin", "proton pump inhibitor"). Never specific
       drugs, doses, durations, or "take X" text. Never write a prescription.
     - ``fingerprint_findings``: items Stern marks "FP" or describes as very
       specific to the diagnosis.

3. **Algorithm** — read the diagnostic-algorithm flowchart figures provided as
   images (Figure N-1, N-2, etc.) and emit a flat ordered ``algorithm`` of
   ``AlgorithmStep`` entries. Each step:
     - is 1-indexed in ``step_num`` order;
     - has a clear ``description``;
     - has ``branches`` covering the meaningful conditions at that decision
       point. Use these actions: "next_step" (target_step required),
       "order_test" (test_to_order), "confirm" (target_diagnosis), "exclude"
       (target_diagnosis), "escalate" (escalation_reason), "treat_empiric",
       "reassess" (target_step optional).
     - sets ``derived_from_figure`` to ``"Stern Fig N-N"`` — the figure ID, not
       the page number.
   When the flowchart and the chapter prose disagree, prefer the prose and
   note the discrepancy in ``rationale`` or ``notes``.

4. **Pivotal points** — extract from Stern's "Constructing a Differential
   Diagnosis" / "Ranking the Differential Diagnosis" prose, verbatim where
   possible. Each pivotal point is a single short string.

5. **Framework type** — choose the closest match to how Stern organizes the
   chapter:
     - "anatomical" (e.g., chest pain by anatomic origin)
     - "temporal" (e.g., abdominal pain by time course)
     - "physiologic" (e.g., dyspnea by mechanism)
     - "categorical" (e.g., diarrhea by infectious vs. non-infectious)
     - "primary_vs_secondary" (e.g., headache)
     - "mechanistic" (e.g., back pain by mechanism)

6. **Decision rules** — capture HEART, POUNDing, Wells, Centor, etc., with
   their thresholds when given.

7. **Citations** — every ``TestCharacteristic.citation`` and
   ``DecisionRule.citation`` must reference a Stern page (e.g., "Stern p.171").
   Use the page numbers visible in the chapter text.

8. **No prescriptions** — under any circumstance, never include drug names,
   doses, regimens, or anything an end user could mistake for a prescription.
   ``treatment_classes`` is a flat list of class names only.

The user message that follows contains the chapter text plus the rendered
images of every detected figure and table page. Each image is preceded by a
text label of the form ``"Figure 9-1: Diagnostic approach to chronic chest
pain (PDF page 167)"``. Use the labels to disambiguate.
"""


def _page_from_location(loc: str | None) -> int | None:
    if not loc:
        return None
    m = _PAGE_RE.match(loc)
    return int(m.group(1)) if m else None


def _slug_from_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or "complaint"


def load_chapter_chunks(store: LocalCorpusStore, ch_num: int) -> list[Chunk]:
    """Read all Stern chunks for a given chapter, ordered by page."""

    out = [c for c in store.read_chunks("stern") if c.metadata.get("chapter_num") == ch_num]
    out.sort(key=lambda c: (_page_from_location(c.source_location) or 0))
    return out


def detect_figures_and_tables(chunks: Iterable[Chunk]) -> list[dict[str, object]]:
    """Walk the chapter text for ``Figure N-N`` / ``Table N-N`` caption lines.

    Each detection records the kind, id, caption text, and the PDF page the
    caption appears on. Duplicates (same kind + id) are kept once.
    """

    detected: list[dict[str, object]] = []
    for chunk in chunks:
        page = _page_from_location(chunk.source_location)
        for raw_line in chunk.text.split("\n"):
            line = raw_line.strip()
            for kind, pattern in (("figure", _FIGURE_RE), ("table", _TABLE_RE)):
                m = pattern.match(line)
                if m:
                    detected.append(
                        {
                            "kind": kind,
                            "id": m.group(1),
                            "caption": m.group(2).strip(),
                            "page": page,
                        }
                    )
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, object]] = []
    for d in detected:
        key = (str(d["kind"]), str(d["id"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    return unique


def render_page_png(pdf_path: Path, page_num: int, scale: float = 2.0) -> bytes:
    """1-indexed page → PNG bytes (default ~144 DPI; 200 DPI at scale=2.7)."""

    with fitz.open(pdf_path) as doc:
        page = doc.load_page(page_num - 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        return bytes(pix.tobytes("png"))


def assemble_chapter_text(chunks: list[Chunk]) -> str:
    """Concatenate chapter chunks in page order with light page separators."""

    pieces: list[str] = []
    last_page: int | None = None
    for c in chunks:
        page = _page_from_location(c.source_location)
        if page != last_page:
            pieces.append(f"\n\n--- p.{page} ---\n")
            last_page = page
        pieces.append(c.text)
    return "\n".join(p for p in pieces if p).strip()


async def extract_chapter(
    *,
    chapter_chunks: list[Chunk],
    chapter_num: int,
    chapter_title: str,
    page_start: int,
    page_end: int,
    pdf_path: Path,
    figures: list[dict[str, object]],
    model_id: str,
    max_output_tokens: int,
    save_debug_images: bool,
) -> Template:
    """Run the multimodal extraction call and validate the result."""

    images: list[bytes] = []
    captions: list[str] = []
    for fig in figures:
        page = fig.get("page")
        if not isinstance(page, int):
            continue
        png = render_page_png(pdf_path, page)
        images.append(png)
        kind = str(fig["kind"]).title()
        captions.append(
            f"{kind} {fig['id']}: {fig.get('caption') or '(no caption)'} "
            f"(PDF page {page})"
        )
        if save_debug_images:
            debug_dir = DEBUG_IMAGES_ROOT / f"ch{chapter_num:02d}"
            debug_dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^a-zA-Z0-9-]+", "_", str(fig["id"]))
            (debug_dir / f"{fig['kind']}_{slug}.png").write_bytes(png)

    chapter_text = assemble_chapter_text(chapter_chunks)

    user_text = (
        f"# Stern Chapter {chapter_num}: {chapter_title}\n"
        f"Source pages: {page_start}-{page_end}\n\n"
        "## Chapter text (full body, page-tagged)\n\n"
        f"{chapter_text}\n\n"
        f"## Detected figures and tables ({len(captions)} images attached after this text)\n\n"
        + "\n".join(f"- {cap}" for cap in captions)
        + "\n\nNow emit one JSON object matching the schema."
    )

    schema = Template.model_json_schema(mode="validation")

    client = AnthropicDirectClient(
        model_id=model_id,
        max_output_tokens=max_output_tokens,
    )
    response = await client.generate_multimodal(
        text=user_text,
        images=images,
        image_captions=captions,
        system=SYSTEM_PROMPT,
        response_schema=schema,
    )

    if not response.tool_calls:
        raise RuntimeError(
            f"Chapter {chapter_num}: model returned no tool call. "
            f"Finish reason: {response.finish_reason}. "
            f"Stop text: {response.text[:300]!r}"
        )
    tool_args: dict[str, object] = dict(response.tool_calls[0].arguments)

    tool_args["chapter_number"] = chapter_num
    tool_args["chapter_title"] = chapter_title
    tool_args["source_pages"] = [page_start, page_end]
    tool_args["reviewed_by"] = "pending"
    tool_args.setdefault("complaint", _slug_from_title(chapter_title))

    template = Template.model_validate(tool_args)
    typer.echo(
        f"  [ch.{chapter_num}] tokens in/out: "
        f"{response.usage.input_tokens}/{response.usage.output_tokens}; "
        f"differential={len(template.differential)}, algorithm={len(template.algorithm)}, "
        f"must_not_miss={len(template.must_not_miss)}"
    )
    return template


def write_template_yaml(template: Template) -> Path:
    """Serialize a Template to YAML, omitting computed-field projections."""

    TEMPLATES_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMPLATES_DATA_DIR / f"{template.complaint}.yaml"
    data = template.model_dump(
        exclude={"must_not_miss", "leading_hypotheses", "educational_treatment_classes"},
        mode="json",
    )
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def discover_chapters(store: LocalCorpusStore) -> list[tuple[int, str, int, int]]:
    """Return ``[(ch_num, title, page_start, page_end), ...]`` for ch.3-33."""

    seen: dict[int, tuple[str, int, int]] = {}
    for c in store.read_chunks("stern"):
        ch = c.metadata.get("chapter_num")
        if not isinstance(ch, int) or ch < _TEMPLATE_CHAPTER_MIN:
            continue
        title = str(c.metadata.get("chapter_title") or "")
        ps_raw = c.metadata.get("page_start")
        pe_raw = c.metadata.get("page_end")
        ps = int(ps_raw) if isinstance(ps_raw, int) else 0
        pe = int(pe_raw) if isinstance(pe_raw, int) else 0
        seen[ch] = (title, ps, pe)
    return [(ch, t, ps, pe) for ch, (t, ps, pe) in sorted(seen.items())]


async def _run(
    chapter: int | None,
    run_all: bool,
    save_debug_images: bool,
    model: str,
    max_output_tokens: int,
) -> int:
    store = LocalCorpusStore(default_root())
    pdf_path = default_root() / "stern" / "raw" / DEFAULT_PDF_FILENAME
    if not pdf_path.is_file():
        typer.secho(f"Stern PDF not found at {pdf_path}", fg="red")
        return 1

    chapters_meta = discover_chapters(store)
    if not chapters_meta:
        typer.secho(
            "No Stern chapters found in the corpus. Run scripts/ingest_stern.py first.",
            fg="red",
        )
        return 1

    if run_all:
        targets = chapters_meta
    else:
        if chapter is None:
            typer.secho("Pass --chapter N or --all", fg="red")
            return 2
        targets = [m for m in chapters_meta if m[0] == chapter]
        if not targets:
            typer.secho(
                f"Chapter {chapter} not found among ingested chapters "
                f"({[m[0] for m in chapters_meta]}).",
                fg="red",
            )
            return 1

    typer.echo(
        f"[stern] extracting {len(targets)} chapter(s) with model={model}, "
        f"save_debug_images={save_debug_images}"
    )

    failures: list[tuple[int, str]] = []
    for ch_num, title, page_start, page_end in targets:
        chapter_chunks = load_chapter_chunks(store, ch_num)
        if not chapter_chunks:
            typer.echo(f"  [ch.{ch_num}] no chunks; skipping")
            continue
        figures = detect_figures_and_tables(chapter_chunks)
        typer.echo(
            f"[ch.{ch_num}: {title}] pp.{page_start}-{page_end}, "
            f"{len(chapter_chunks)} chunks, {len(figures)} fig/tab"
        )
        try:
            template = await extract_chapter(
                chapter_chunks=chapter_chunks,
                chapter_num=ch_num,
                chapter_title=title,
                page_start=page_start,
                page_end=page_end,
                pdf_path=pdf_path,
                figures=figures,
                model_id=model,
                max_output_tokens=max_output_tokens,
                save_debug_images=save_debug_images,
            )
            path = write_template_yaml(template)
            typer.echo(f"  [ch.{ch_num}] wrote {path.relative_to(REPO_ROOT)}")
        except Exception as exc:
            typer.secho(f"  [ch.{ch_num}] FAILED: {exc}", fg="red")
            failures.append((ch_num, str(exc)))

    if failures:
        typer.secho(f"\n{len(failures)} chapter(s) failed:", fg="red")
        for ch, err in failures:
            typer.echo(f"  ch.{ch}: {err[:200]}")
        return 1
    typer.echo(f"\nDone. {len(targets)} template(s) extracted.")
    return 0


app = typer.Typer(
    add_completion=False,
    help="Vision-augmented per-chapter Stern template extractor.",
)


@app.command()
def run(
    chapter: int = typer.Option(
        9, help="Chapter number to extract (default 9 = Chest Pain)."
    ),
    all_chapters: bool = typer.Option(
        False, "--all", help="Extract all chief-complaint chapters (3-33)."
    ),
    save_debug_images: bool = typer.Option(
        False,
        "--save-debug-images",
        help=(
            "Persist rendered figure pages under "
            "knowledge/_local/stern/_debug/ for spot-checking."
        ),
    ),
    model: str = typer.Option(
        DEFAULT_MODEL,
        help="Anthropic model id (default: Opus). Try claude-sonnet-4-5 for cheap.",
    ),
    max_output_tokens: int = typer.Option(
        DEFAULT_MAX_OUTPUT_TOKENS,
        help="Max output tokens; raise if the model truncates large templates.",
    ),
) -> None:
    code = asyncio.run(
        _run(
            chapter=None if all_chapters else chapter,
            run_all=all_chapters,
            save_debug_images=save_debug_images,
            model=model,
            max_output_tokens=max_output_tokens,
        )
    )
    raise typer.Exit(code=code)


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
