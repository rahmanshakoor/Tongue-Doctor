"""FastAPI dependency providers (cached, process-singleton).

The DiagnosticLoop, BM25Index, and CaseManager are constructed once at app startup
and injected into request handlers via ``Depends(...)``. The functions here also
serve as override seams for tests via ``app.dependency_overrides``.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException

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
from tongue_doctor.orchestrator import CaseManager, DiagnosticLoop, LoopAgents
from tongue_doctor.retrieval.index import BM25Index
from tongue_doctor.settings import Settings, get_settings


@lru_cache(maxsize=1)
def get_case_manager() -> CaseManager:
    """API CaseManager backed by ``<repo>/.cases`` so state survives server restarts."""

    settings = get_settings()
    return CaseManager(persist_dir=settings.repo_root / ".cases")


@lru_cache(maxsize=1)
def get_bm25_index() -> BM25Index:
    """Load the BM25 index lazily on first access. Pickle files must already exist."""

    return BM25Index()


@lru_cache(maxsize=1)
def get_diagnostic_loop() -> DiagnosticLoop:
    settings: Settings = get_settings()
    bm25 = get_bm25_index()
    if not bm25.sources:
        # Surface a clear error to the caller before the loop tries to retrieve.
        raise HTTPException(
            status_code=503,
            detail=(
                "BM25 indices are not built. Run `make build-bm25-index` and restart the API server."
            ),
        )
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
    return DiagnosticLoop(
        agents=agents,
        case_manager=get_case_manager(),
        bm25_index=bm25,
        settings=settings,
    )


def reset_dependencies() -> None:
    """Clear cached singletons. Used by tests via ``app.dependency_overrides``."""

    get_case_manager.cache_clear()
    get_bm25_index.cache_clear()
    get_diagnostic_loop.cache_clear()


__all__ = [
    "get_bm25_index",
    "get_case_manager",
    "get_diagnostic_loop",
    "reset_dependencies",
]
