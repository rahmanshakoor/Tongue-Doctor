"""Convergence checker: decides if the Defender ↔ Critic dialectic should stop.

Tiny JSON-output agent. Output schema is a small bool + short reason + bounded
list, so JSON forcing here doesn't risk the field-stuffing degeneration that
plagued the larger structured agents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tongue_doctor.agents._runtime import call_structured, usage_metadata
from tongue_doctor.agents.base import AgentResult
from tongue_doctor.agents.schemas import ConvergenceCheck
from tongue_doctor.models.base import LLMClient
from tongue_doctor.schemas import CaseState


class ConvergenceCheckerAgent:
    """Per-round adjudicator of whether the dialectic has converged."""

    name: str = "convergence_checker"
    model_assignment_key: str = "convergence_checker"
    prompt_name: str = "convergence_checker/system"
    prompt_version: int = 1

    def __init__(self, client: LLMClient, *, prompts_dir: Path | None = None) -> None:
        self.client = client
        self.prompts_dir = prompts_dir

    async def run(self, case_state: CaseState, **kwargs: Any) -> AgentResult:
        round_num = int(kwargs["round"])
        current_defender = kwargs["current_defender"]
        current_critic = kwargs["current_critic"]
        prior_rounds = kwargs.get("prior_rounds", [])
        on_chunk = kwargs.get("on_chunk")

        parsed, response, latency = await call_structured(
            self.client,
            prompt_name=self.prompt_name,
            prompt_version=self.prompt_version,
            prompt_kwargs={
                "round": round_num,
                "current_defender": current_defender,
                "current_critic": current_critic,
                "prior_rounds": prior_rounds,
            },
            response_model=ConvergenceCheck,
            prompts_dir=self.prompts_dir,
            on_chunk=on_chunk,
        )
        assert isinstance(parsed, ConvergenceCheck)

        return AgentResult(
            output=parsed,
            latency_ms=latency,
            metadata=usage_metadata(response),
        )
