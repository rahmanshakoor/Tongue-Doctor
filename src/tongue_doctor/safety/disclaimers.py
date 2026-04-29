"""Disclaimer registry and injection helpers.

English-only for now (kickoff Decision L). Arabic translations land when tester needs
require, after counsel review of equivalence.
"""

from __future__ import annotations

from enum import StrEnum

from tongue_doctor.schemas import OutputKind, UserFacingOutput


class DisclaimerKind(StrEnum):
    RESEARCH_DEMO = "research_demo"
    MULTIMODAL = "multimodal"
    SCOPE_REFUSAL = "scope_refusal"
    ED_ROUTING = "ed_routing"


DISCLAIMERS: dict[DisclaimerKind, str] = {
    DisclaimerKind.RESEARCH_DEMO: (
        "This is a research demonstration of clinical reasoning. It is not a medical "
        "device, not clinically validated, and not a substitute for a qualified physician. "
        "Do not use this output to make medical decisions. If you are experiencing a "
        "medical emergency, contact emergency services."
    ),
    DisclaimerKind.MULTIMODAL: (
        "Findings were extracted by AI from the file(s) you uploaded. Verify with a "
        "clinician before relying on them."
    ),
    DisclaimerKind.SCOPE_REFUSAL: (
        "This complaint is outside the scope of this research demonstration. Please "
        "consult a qualified physician."
    ),
    DisclaimerKind.ED_ROUTING: (
        "Your description suggests an acute or potentially serious situation. Please "
        "contact emergency services or go to the nearest emergency department immediately. "
        "Do not wait for further information from this system."
    ),
}


def get_disclaimer(kind: DisclaimerKind) -> str:
    return DISCLAIMERS[kind]


def inject_disclaimer(output: UserFacingOutput, kind: DisclaimerKind) -> UserFacingOutput:
    """Return a new :class:`UserFacingOutput` with the named disclaimer set.

    Idempotent — calling twice with the same kind yields the same result.
    """
    return output.model_copy(update={"disclaimer": DISCLAIMERS[kind]})


def disclaimer_for_output_kind(kind: OutputKind, multimodal: bool = False) -> str:
    """Map an :class:`OutputKind` to a default disclaimer string.

    Escalation → ED routing. Refusal → scope refusal. Everything else → research demo,
    optionally appended with the multimodal qualifier when findings were AI-extracted.
    """
    if kind == OutputKind.ESCALATION:
        return DISCLAIMERS[DisclaimerKind.ED_ROUTING]
    if kind == OutputKind.REFUSAL:
        return DISCLAIMERS[DisclaimerKind.SCOPE_REFUSAL]
    base = DISCLAIMERS[DisclaimerKind.RESEARCH_DEMO]
    if multimodal:
        return f"{base} {DISCLAIMERS[DisclaimerKind.MULTIMODAL]}"
    return base
