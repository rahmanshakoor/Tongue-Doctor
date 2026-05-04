"""HTTP API integration tests.

Uses FastAPI's ``TestClient`` with the DiagnosticLoop mocked via dependency
overrides. No real LLM calls are made.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from tongue_doctor.agents.schemas import (
    JudgeVerdict,
    MustNotMissSweep,
    RouterOutput,
    SafetyVerdict,
    SynthesisOutput,
)
from tongue_doctor.api import create_app
from tongue_doctor.api.dependencies import (
    get_bm25_index,
    get_case_manager,
    get_diagnostic_loop,
    reset_dependencies,
)
from tongue_doctor.orchestrator import (
    AgentTimings,
    AgentTrace,
    CaseManager,
    DiagnosticLoop,
    LoopRunResult,
)
from tongue_doctor.retrieval.index import BM25Index
from tongue_doctor.schemas.output import OutputKind, UserFacingOutput


@pytest.fixture
def fake_loop() -> Any:
    """A DiagnosticLoop stand-in whose ``handle_message`` returns a fixed result."""

    synth = SynthesisOutput(
        body_markdown="**Most likely:** Acute MI.\n\nResearch demonstration only.",
        research_demo_disclaimer="Research demonstration only.",
    )
    safety = SafetyVerdict(
        verdict="approve",
        disclaimer_present=True,
        citation_completeness="partial",
    )
    router_out = RouterOutput(
        template_slug="chest_pain",
        chapter_number=9,
        confidence=0.9,
        rationale="x",
    )
    judge = JudgeVerdict(
        leading_diagnosis="Acute MI",
        confidence_band="moderate",
        verdict_rationale="x",
        closing_statement="MI committed.",
        rounds_held=1,
    )

    result = LoopRunResult(
        case_id="api-test-1",
        duration_ms=42,
        user_facing=UserFacingOutput(
            kind=OutputKind.COMMITMENT,
            body=synth.body_markdown,
            disclaimer=synth.research_demo_disclaimer,
            citations=[],
        ),
        trace=AgentTrace(
            template_slug="chest_pain",
            chapter_number=9,
            router=router_out,
            retrieved_chunks=[],
            reasoner_trace="# Step 1\n- chest pain",
            dialectic_rounds=[],
            converged=True,
            must_not_miss=MustNotMissSweep(),
            judge_verdict=judge,
            synthesis=synth,
            safety=safety,
            timings=AgentTimings(total_ms=42),
        ),
    )

    loop = AsyncMock(spec=DiagnosticLoop)
    loop.handle_message = AsyncMock(return_value=result)
    loop.retrieval_top_k = 25
    return loop


@pytest.fixture
def fake_bm25() -> Any:
    bm = AsyncMock(spec=BM25Index)
    bm.sources = ["stern", "statpearls"]
    return bm


@pytest.fixture
def app(fake_loop: Any, fake_bm25: Any) -> Any:
    reset_dependencies()
    a = create_app()
    a.dependency_overrides[get_diagnostic_loop] = lambda: fake_loop
    a.dependency_overrides[get_case_manager] = lambda: CaseManager()
    a.dependency_overrides[get_bm25_index] = lambda: fake_bm25
    yield a
    a.dependency_overrides.clear()
    reset_dependencies()


@pytest.fixture
def client(app: Any) -> TestClient:
    return TestClient(app)


# --- /api/health ---


def test_health_returns_ok_when_bm25_loaded(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["bm25_loaded"] is True
    assert "stern" in body["bm25_sources"]


def test_health_returns_degraded_when_bm25_empty(app: Any, fake_loop: Any) -> None:
    empty_bm = AsyncMock(spec=BM25Index)
    empty_bm.sources = []
    app.dependency_overrides[get_bm25_index] = lambda: empty_bm
    c = TestClient(app)
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


# --- /api/templates ---


def test_templates_lists_all_31(client: TestClient) -> None:
    r = client.get("/api/templates")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 31
    slugs = {t["slug"] for t in body["templates"]}
    assert "chest_pain" in slugs
    assert "abdominal_pain" in slugs


def test_template_by_slug(client: TestClient) -> None:
    r = client.get("/api/templates/chest_pain")
    assert r.status_code == 200
    body = r.json()
    assert body["complaint"] == "chest_pain"
    assert body["chapter_number"] == 9
    assert isinstance(body["differential"], list)


def test_template_by_slug_unknown_returns_404(client: TestClient) -> None:
    r = client.get("/api/templates/nonexistent_complaint")
    assert r.status_code == 404


# --- /api/cases/run ---


def test_run_case_returns_full_trace(client: TestClient, fake_loop: Any) -> None:
    r = client.post(
        "/api/cases/run",
        json={"message": "55M crushing chest pain"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body
    res = body["result"]
    assert res["case_id"] == "api-test-1"
    assert res["user_facing"]["kind"] == "commitment"
    assert "Acute MI" in res["user_facing"]["body"]
    assert res["trace"]["template_slug"] == "chest_pain"
    assert res["trace"]["safety"]["verdict"] == "approve"
    fake_loop.handle_message.assert_awaited_once()


def test_run_case_with_top_k_override(client: TestClient, fake_loop: Any) -> None:
    r = client.post(
        "/api/cases/run",
        json={"message": "55M chest pain", "top_k": 10},
    )
    assert r.status_code == 200
    assert fake_loop.retrieval_top_k == 10


def test_run_case_rejects_extra_field(client: TestClient) -> None:
    r = client.post(
        "/api/cases/run",
        json={"message": "x", "evil_field": "leak"},
    )
    assert r.status_code == 422  # Pydantic extra="forbid"


# --- /api/cases/{case_id} ---


def test_get_case_returns_404_for_unknown(client: TestClient) -> None:
    r = client.get("/api/cases/unknown")
    assert r.status_code == 404
