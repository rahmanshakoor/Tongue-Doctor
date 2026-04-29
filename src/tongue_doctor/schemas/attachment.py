"""Attachment schemas.

``Attachment`` is the full record (lives in ``attachments_meta`` Firestore collection).
``AttachmentRef`` is the compact reference embedded in :class:`CaseState`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Modality(StrEnum):
    UNKNOWN = "unknown"
    ECG = "ecg"
    LAB_IMAGE = "lab_image"
    LAB_PDF = "lab_pdf"
    DOCUMENT = "document"
    CXR = "cxr"
    SKIN = "skin"
    ADVANCED_IMAGING = "advanced_imaging"


class AttachmentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    DECLINED = "declined"


class Attachment(BaseModel):
    """Full attachment record. Persisted as ``attachments_meta/{attachment_id}``."""

    model_config = ConfigDict(extra="forbid")

    attachment_id: str
    case_id: str
    gcs_path: str
    mime: str
    modality: Modality = Modality.UNKNOWN
    status: AttachmentStatus = AttachmentStatus.PENDING
    received_at_turn: int
    extracted_findings: dict[str, Any] | None = None
    declination_reason: str | None = None
    disclaimer_required: bool = True
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AttachmentRef(BaseModel):
    """Compact attachment reference embedded in :class:`CaseState`.attachments."""

    model_config = ConfigDict(extra="forbid")

    attachment_id: str
    modality: Modality
    status: AttachmentStatus
    received_at_turn: int
