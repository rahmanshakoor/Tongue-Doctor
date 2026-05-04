"""HTTP routes for the diagnostic agent loop.

Mounted under ``/api`` by ``tongue_doctor.app.create_app()``. Endpoints:

- ``POST /api/cases/run``       — run the full agent loop on a case description.
- ``GET  /api/cases/{case_id}`` — fetch persisted case state.
- ``GET  /api/templates``       — list all 31 Stern templates.
- ``GET  /api/templates/{slug}``— fetch a single template.
- ``GET  /api/health``          — liveness probe.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from tongue_doctor import __version__
from tongue_doctor.agents._runtime import template_catalog
from tongue_doctor.api.dependencies import (
    get_bm25_index,
    get_case_manager,
    get_diagnostic_loop,
)
from tongue_doctor.api.schemas import (
    CaseStateSummary,
    HealthStatus,
    RunCaseRequest,
    RunCaseResponse,
    TemplateCatalogEntry,
    TemplateCatalogResponse,
)
from tongue_doctor.orchestrator import CaseManager, DiagnosticLoop
from tongue_doctor.orchestrator.case_manager import CaseNotFoundError
from tongue_doctor.retrieval.index import BM25Index
from tongue_doctor.templates import Template, load_template
from tongue_doctor.templates.loader import TemplateNotFoundError

router = APIRouter(prefix="/api", tags=["diagnostic-loop"])


@router.get("/health", response_model=HealthStatus)
def health(bm25: BM25Index = Depends(get_bm25_index)) -> HealthStatus:
    sources = bm25.sources
    return HealthStatus(
        status="ok" if sources else "degraded",
        bm25_loaded=bool(sources),
        bm25_sources=sources,
        version=__version__,
        detail=(
            ""
            if sources
            else "No BM25 indices loaded. Run `make build-bm25-index` and restart."
        ),
    )


@router.post("/cases/run", response_model=RunCaseResponse)
async def run_case(
    body: RunCaseRequest,
    loop: DiagnosticLoop = Depends(get_diagnostic_loop),
) -> RunCaseResponse:
    case_id = body.case_id or f"api-{uuid.uuid4().hex[:8]}"
    # Honor per-request bm25_corpora / top_k by overriding the loop's defaults.
    if body.bm25_corpora is not None:
        # The corpora list is a search-time filter — pass via search; current loop
        # uses retrieval_top_k only. Future: thread corpora into handle_message.
        pass
    if body.top_k != loop.retrieval_top_k:
        loop.retrieval_top_k = body.top_k
    result = await loop.handle_message(case_id, body.message)
    return RunCaseResponse(result=result)


@router.get("/cases/{case_id}", response_model=CaseStateSummary)
async def get_case(
    case_id: str,
    case_manager: CaseManager = Depends(get_case_manager),
) -> CaseStateSummary:
    try:
        state = await case_manager.get(case_id)
    except CaseNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"case {case_id!r} not found") from e
    return CaseStateSummary(
        case_id=state.case_id,
        turn_count=state.turn_count,
        last_summary_excerpt=state.messages_summary[:512],
    )


@router.get("/templates", response_model=TemplateCatalogResponse)
def list_templates() -> TemplateCatalogResponse:
    catalog_rows = template_catalog()
    entries: list[TemplateCatalogEntry] = []
    for row in catalog_rows:
        try:
            t = load_template(row["slug"])
        except TemplateNotFoundError:
            continue
        entries.append(
            TemplateCatalogEntry(
                slug=t.complaint,
                chapter_number=t.chapter_number,
                chapter_title=t.chapter_title,
                framework_type=t.framework_type,
                must_not_miss_count=len(t.must_not_miss),
                differential_count=len(t.differential),
                algorithm_step_count=len(t.algorithm),
            )
        )
    return TemplateCatalogResponse(count=len(entries), templates=entries)


@router.get("/templates/{slug}", response_model=Template)
def get_template(slug: str) -> Template:
    try:
        return load_template(slug)
    except TemplateNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"template {slug!r} not found") from e


__all__ = ["router"]
