"""CaseState — single source of truth per diagnostic session.

Persisted as ``cases/{case_id}`` in Firestore. Heavy fields (full retrieved chunks, raw
user messages, full agent outputs) spill to subcollections so this document stays under
Firestore's 1 MiB limit. See KICKOFF_PLAN.md §6 for the persistence contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from tongue_doctor.schemas.attachment import AttachmentRef
from tongue_doctor.schemas.differential import Differential


class CaseStatus(StrEnum):
    GATHERING = "gathering"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ESCALATED = "escalated"
    OUT_OF_SCOPE = "out_of_scope"
    ABANDONED = "abandoned"


class ConfidenceBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Fact(BaseModel):
    """A discrete known fact about the case.

    ``category`` is one of: ``history`` | ``exam`` | ``lab`` | ``imaging`` | ``medication`` |
    ``social`` | ``family`` | ``ros``.

    ``source`` is one of: ``user`` | ``attachment:<id>`` | ``retrieval`` | ``template``.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    category: str = "history"
    source: str = "user"
    source_attachment_id: str | None = None
    surfaced_at_turn: int
    confidence: float = 1.0


class RedFlag(BaseModel):
    """A red-flag finding requiring escalation or special handling."""

    model_config = ConfigDict(extra="forbid")

    name: str
    severity: str = "high"
    rationale: str
    surfaced_at_turn: int


class ResearchPrescription(BaseModel):
    """Internal-only prescription. NEVER surfaced to the user.

    Any substring of any string field that appears in :class:`UserFacingOutput`.body raises
    :class:`PrescriptionLeakError` from :mod:`tongue_doctor.safety.prescription_leak_detector`.
    See SAFETY_INVARIANTS.md I-3.
    """

    model_config = ConfigDict(extra="forbid")

    drug_class: list[str] = Field(default_factory=list)
    drug_name: str
    dose: str
    duration: str
    rationale: str
    contraindications_considered: list[str] = Field(default_factory=list)
    interactions_considered: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CaseState(BaseModel):
    """Single source of truth per diagnostic session."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    schema_version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: CaseStatus = CaseStatus.GATHERING
    turn_count: int = 0
    iteration_count: int = 0
    messages_summary: str = ""
    known_facts: list[Fact] = Field(default_factory=list)
    attachments: list[AttachmentRef] = Field(default_factory=list)
    differential: list[Differential] = Field(default_factory=list)
    must_not_miss_considered: list[str] = Field(default_factory=list)
    red_flags_detected: list[RedFlag] = Field(default_factory=list)
    retrieved_knowledge_summary: str = ""
    research_prescription: ResearchPrescription | None = None
    confidence_band: ConfidenceBand = ConfidenceBand.LOW
    disclaimer_required: bool = True
