"""Diagnostic loop.

Phase 0 — skeleton; :meth:`DiagnosticLoop.handle_message` raises
:class:`NotImplementedError`. Phase 1 wires the loop body around the
:class:`tongue_doctor.agents.base.Agent` protocol.

The loop's invariants (per ``KICKOFF_PLAN.md`` §1 and ``SAFETY_INVARIANTS.md``):

- Iteration count is bounded by ``settings.loop.max_iterations``.
- Status transitions to ``committed`` only after a must-not-miss audit passes.
- Research Prescriber output flows to ``case_state.research_prescription`` only,
  never to the user-facing output (taint-tracker enforces).
- Every output has a disclaimer; multimodal-derived outputs add the multimodal disclaimer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tongue_doctor.agents.base import Agent
from tongue_doctor.orchestrator.case_manager import CaseManager
from tongue_doctor.schemas import UserFacingOutput
from tongue_doctor.settings import Settings


class DiagnosticLoop:
    """Gather → hypothesize → retrieve → critique → audit → commit-or-iterate."""

    def __init__(
        self,
        *,
        agents: dict[str, Agent],
        case_manager: CaseManager,
        settings: Settings,
    ) -> None:
        self.agents = agents
        self.case_manager = case_manager
        self.settings = settings

    async def handle_message(
        self,
        case_id: str,
        message: str,
        attachments: Sequence[Any] | None = None,
    ) -> UserFacingOutput:
        """Process one user turn. Returns the :class:`UserFacingOutput` to ship.

        Phase 1 sequence:

        1. Router scope check (:meth:`Router.run`) — short-circuit on out_of_scope or escalate.
        2. Multimodal processing (Phase 2 onwards) — pull findings into known_facts.
        3. Inner reasoning loop (bounded by ``settings.loop.max_iterations``):

           - :meth:`Reasoner.run` — produce or refine differential.
           - :meth:`Retriever.query` calls as needed.
           - :meth:`DevilsAdvocate.run` on commit-readiness.
           - :meth:`MustNotMissSweeper.run` before committing.

        4. Phase 3 — :meth:`ResearchPrescriber.run` populates ``research_prescription``;
           taint-tracker registers the substring set.
        5. :meth:`SafetyReviewer.run` audits the candidate output.
        6. :meth:`Synthesizer.run` formats the final user-facing message; leak detector
           runs on the result before return.
        """
        raise NotImplementedError(
            "DiagnosticLoop.handle_message is implemented in Phase 1. "
            "See KICKOFF_PLAN.md §1 for the loop body and §10 for the trace shape."
        )
