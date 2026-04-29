"""Scope rules.

Phase 0 ships a placeholder rule that escalates obvious acute / severe presentations
to the ED and otherwise reports in-scope. The real classifier — an LLM-backed Router
— lands in Phase 1 (per ``KICKOFF_PLAN.md`` §1).

The scope decision is a hard short-circuit in the diagnostic loop: an ``ESCALATE_TO_ED``
or ``OUT_OF_SCOPE`` result skips the rest of the loop entirely and ships an escalation
or refusal message with the appropriate disclaimer.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ScopeDecision(StrEnum):
    IN_SCOPE = "in_scope"
    OUT_OF_SCOPE = "out_of_scope"
    ESCALATE_TO_ED = "escalate_to_ed"


class ScopeRationale(BaseModel):
    """Why a particular scope decision was reached."""

    model_config = ConfigDict(extra="forbid")

    decision: ScopeDecision
    reason: str
    matched_rule: str | None = None


def is_in_scope(
    complaint: str,
    severity: str = "moderate",
    onset_hours: float | None = None,
) -> ScopeRationale:
    """Placeholder rule. Refuses acute / severe presentations.

    Per kickoff Decisions Log row 19: refuse all acute-onset (< 24h) and route to ED.
    Phase 1 replaces this with an LLM-backed Router that also catches non-internal-medicine
    scope (pediatric / OB / psych / surgery).
    """
    if onset_hours is not None and onset_hours < 24:
        return ScopeRationale(
            decision=ScopeDecision.ESCALATE_TO_ED,
            reason=f"Onset {onset_hours}h is below the 24h threshold for this research demo.",
            matched_rule="acute_onset_lt_24h",
        )
    if severity in {"severe", "critical"}:
        return ScopeRationale(
            decision=ScopeDecision.ESCALATE_TO_ED,
            reason=f"Severity {severity!r} requires emergency evaluation.",
            matched_rule="severity_severe_or_critical",
        )
    return ScopeRationale(
        decision=ScopeDecision.IN_SCOPE,
        reason=f"Phase 0 placeholder for {complaint!r} — no LLM-backed scope classifier yet.",
        matched_rule="phase0_default",
    )
