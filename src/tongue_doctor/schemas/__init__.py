"""Pydantic schemas — the typed surface every agent and the orchestrator pass around.

CaseState is the single source of truth per session (persisted in Firestore).
UserFacingOutput is the strict surface that ships to the user — see SAFETY_INVARIANTS.md I-3
for why this model has no ``prescription`` field and uses ``extra="forbid"``.
"""

from tongue_doctor.schemas.attachment import (
    Attachment,
    AttachmentRef,
    AttachmentStatus,
    Modality,
)
from tongue_doctor.schemas.case_state import (
    CaseState,
    CaseStatus,
    ConfidenceBand,
    Fact,
    RedFlag,
    ResearchPrescription,
)
from tongue_doctor.schemas.differential import (
    Differential,
    Evidence,
)
from tongue_doctor.schemas.output import (
    Citation,
    OutputKind,
    UserFacingOutput,
)
from tongue_doctor.schemas.retrieval import (
    AuthorityTier,
    RetrievalResult,
)

__all__ = [
    "Attachment",
    "AttachmentRef",
    "AttachmentStatus",
    "AuthorityTier",
    "CaseState",
    "CaseStatus",
    "Citation",
    "ConfidenceBand",
    "Differential",
    "Evidence",
    "Fact",
    "Modality",
    "OutputKind",
    "RedFlag",
    "ResearchPrescription",
    "RetrievalResult",
    "UserFacingOutput",
]
