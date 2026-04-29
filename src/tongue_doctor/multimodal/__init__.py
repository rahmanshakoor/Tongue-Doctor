"""Multimodal pipeline.

Phase 0 ships an empty package. The processor + per-modality handlers land in Phase 2
(ECG first), then Phase 6 (lab image / lab PDF / document / CXR / skin). See
``KICKOFF_PLAN.md`` §7.
"""
