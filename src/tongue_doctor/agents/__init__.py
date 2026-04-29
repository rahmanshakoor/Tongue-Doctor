"""Agent implementations.

Phase 0 ships only :mod:`tongue_doctor.agents.base`. Concrete agents (Router, Reasoner,
Devil's Advocate, Must-Not-Miss Sweeper, Safety Reviewer, Synthesizer, Research
Prescriber) land in Phase 1 and Phase 3 per ``KICKOFF_PLAN.md`` §12.
"""

from tongue_doctor.agents.base import Agent, AgentResult, StateMutation

__all__ = ["Agent", "AgentResult", "StateMutation"]
