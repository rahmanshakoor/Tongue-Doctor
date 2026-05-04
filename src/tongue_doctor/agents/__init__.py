"""Agent implementations.

Phase 1 active loop (convergence-style review):

- :class:`RouterAgent` — chief complaint → primary + ancillary template slugs.
- :class:`ReasonerAgent` — Stern's 9-step procedure (initial markdown trace).
- :class:`DefenderAgent` — honest steel-manner of the leading hypothesis (markdown prose).
- :class:`CriticAgent` — objective error-finder over the Reasoner's trace (markdown prose).
- :class:`ConvergenceCheckerAgent` — per-round adjudicator: continue or hand to Judge.
- :class:`MustNotMissSweeperAgent` — audits the must-not-miss list.
- :class:`JudgeAgent` — weighs the dialectic transcripts + MNM and issues the final verdict.
- :class:`SynthesizerAgent` — pure renderer of the Judge's verdict.
- :class:`SafetyReviewerAgent` — post-hoc safety audit (approve / revise / refuse).

The previous ``ProsecutorAgent`` and ``DevilsAdvocateAgent`` (courtroom layout
with adversarial JSON outputs) were retired 2026-05-02 — they produced
performative debate rather than honest review, and their forced-JSON outputs
were prone to repetition / degenerate-generation collapse. The Defender +
Critic pair replaces them with structured-prose review and explicit
permission-to-concede, plus a convergence checker that stops the loop when
no new ground is being broken. See :mod:`tongue_doctor.orchestrator.loop` for
the new pipeline.

Multimodal handler and Research Prescriber land in Phases 2 / 3.
"""

from tongue_doctor.agents.base import Agent, AgentResult, StateMutation
from tongue_doctor.agents.convergence_checker import ConvergenceCheckerAgent
from tongue_doctor.agents.critic import CriticAgent
from tongue_doctor.agents.defender import DefenderAgent
from tongue_doctor.agents.judge import JudgeAgent
from tongue_doctor.agents.must_not_miss_sweeper import MustNotMissSweeperAgent
from tongue_doctor.agents.reasoner import ReasonerAgent
from tongue_doctor.agents.router import RouterAgent
from tongue_doctor.agents.safety_reviewer import SafetyReviewerAgent
from tongue_doctor.agents.synthesizer import SynthesizerAgent

__all__ = [
    "Agent",
    "AgentResult",
    "ConvergenceCheckerAgent",
    "CriticAgent",
    "DefenderAgent",
    "JudgeAgent",
    "MustNotMissSweeperAgent",
    "ReasonerAgent",
    "RouterAgent",
    "SafetyReviewerAgent",
    "StateMutation",
    "SynthesizerAgent",
]
