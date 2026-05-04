"""Request / response schemas for the agent-loop HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tongue_doctor.orchestrator.types import LoopRunResult
from tongue_doctor.schemas.output import UserFacingOutput


class RunCaseRequest(BaseModel):
    """Body for POST ``/api/cases/run``."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., description="Free-text case description / chief complaint.")
    case_id: str | None = Field(
        default=None,
        description="Optional client-supplied id. Server generates a UUID when absent.",
    )
    bm25_corpora: list[str] | None = Field(
        default=None,
        description="Restrict BM25 retrieval to these source names. Default: all 7.",
    )
    top_k: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Top-K chunks to retrieve.",
    )


class RunCaseResponse(BaseModel):
    """Response for POST ``/api/cases/run`` — the full LoopRunResult."""

    model_config = ConfigDict(extra="forbid")

    result: LoopRunResult


class TemplateCatalogEntry(BaseModel):
    """One row in the template catalog returned by GET ``/api/templates``."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    chapter_number: int
    chapter_title: str
    framework_type: str
    must_not_miss_count: int
    differential_count: int
    algorithm_step_count: int


class TemplateCatalogResponse(BaseModel):
    """Response for GET ``/api/templates``."""

    model_config = ConfigDict(extra="forbid")

    count: int
    templates: list[TemplateCatalogEntry]


class CaseStateSummary(BaseModel):
    """Slim view for GET ``/api/cases/{case_id}`` — does not return private state."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    turn_count: int
    last_summary_excerpt: str
    last_user_facing: UserFacingOutput | None = None


class HealthStatus(BaseModel):
    """Response for GET ``/api/health``."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    bm25_loaded: bool
    bm25_sources: list[str]
    version: str
    detail: str = ""
