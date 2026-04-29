"""User-facing output schema.

INVARIANT — kickoff §J / SAFETY_INVARIANTS.md I-3: this model has no ``prescription`` field
and uses ``extra="forbid"`` so a future refactor cannot silently re-add one. The runtime
backstop is :mod:`tongue_doctor.safety.prescription_leak_detector`, which checks any
substring of ``CaseState.research_prescription`` against ``UserFacingOutput.body``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OutputKind(StrEnum):
    QUESTION = "question"
    COMMITMENT = "commitment"
    ESCALATION = "escalation"
    REFUSAL = "refusal"


class Citation(BaseModel):
    """Citation attached to a user-facing output."""

    model_config = ConfigDict(extra="forbid")

    label: str
    source: str
    citation: str
    authority_tier: Literal[1, 2, 3]


class UserFacingOutput(BaseModel):
    """What the synthesizer ships and the safety reviewer audits.

    Exactly four fields are permitted. Adding any other field (notably ``prescription``)
    fails Pydantic validation thanks to ``extra="forbid"``. The schema is the first line
    of defense for the prescriber-isolation invariant.
    """

    model_config = ConfigDict(extra="forbid")

    kind: OutputKind
    body: str
    disclaimer: str
    citations: list[Citation] = Field(default_factory=list)
