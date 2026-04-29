"""Schema round-trips and the schema-level prescriber-isolation guard."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tongue_doctor.schemas import (
    AttachmentRef,
    AttachmentStatus,
    CaseState,
    CaseStatus,
    Citation,
    ConfidenceBand,
    Modality,
    OutputKind,
    UserFacingOutput,
)


def test_case_state_round_trips() -> None:
    state = CaseState(case_id="abc-123")
    raw = state.model_dump_json()
    restored = CaseState.model_validate_json(raw)
    assert restored.case_id == "abc-123"
    assert restored.status == CaseStatus.GATHERING
    assert restored.confidence_band == ConfidenceBand.LOW
    assert restored.disclaimer_required is True


def test_case_state_with_attachment_round_trips() -> None:
    state = CaseState(
        case_id="abc",
        attachments=[
            AttachmentRef(
                attachment_id="att1",
                modality=Modality.ECG,
                status=AttachmentStatus.PROCESSED,
                received_at_turn=1,
            )
        ],
    )
    raw = state.model_dump_json()
    restored = CaseState.model_validate_json(raw)
    assert restored.attachments[0].modality == Modality.ECG
    assert restored.attachments[0].status == AttachmentStatus.PROCESSED


def test_user_facing_output_forbids_extra_fields() -> None:
    """Schema-level guard for kickoff §J / SAFETY_INVARIANTS.md I-3.

    A future refactor cannot silently add a ``prescription`` field to
    :class:`UserFacingOutput` because ``extra="forbid"`` rejects unknown keys.
    """
    with pytest.raises(ValidationError):
        UserFacingOutput.model_validate(
            {
                "kind": "commitment",
                "body": "...",
                "disclaimer": "...",
                "prescription": "amoxicillin 500mg",
            }
        )


def test_user_facing_output_minimum_required_fields() -> None:
    out = UserFacingOutput(
        kind=OutputKind.COMMITMENT,
        body="The most likely cause is X.",
        disclaimer="Research demo only.",
    )
    assert out.citations == []


def test_user_facing_output_with_citation() -> None:
    out = UserFacingOutput(
        kind=OutputKind.COMMITMENT,
        body="...",
        disclaimer="...",
        citations=[
            Citation(
                label="[1]",
                source="UpToDate",
                citation="https://www.uptodate.com/article/...",
                authority_tier=1,
            )
        ],
    )
    assert out.citations[0].authority_tier == 1
    assert out.citations[0].source == "UpToDate"


def test_user_facing_output_authority_tier_is_constrained() -> None:
    """Citation authority_tier must be 1, 2, or 3."""
    with pytest.raises(ValidationError):
        Citation(label="[1]", source="x", citation="y", authority_tier=4)  # type: ignore[arg-type]
