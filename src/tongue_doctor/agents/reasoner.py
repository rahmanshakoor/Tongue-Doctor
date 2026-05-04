"""Reasoner agent: Stern's 9-step diagnostic procedure (markdown trace).

Output is the structured markdown trace defined in ``prompts/reasoner/system_v1.j2``
— named section headers, Stern vocabulary. Downstream agents (Devil's Advocate,
Must-Not-Miss Sweeper, Synthesizer) read it as a string.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tongue_doctor.agents._runtime import call_text, usage_metadata
from tongue_doctor.agents.base import AgentResult
from tongue_doctor.models.base import LLMClient
from tongue_doctor.schemas import CaseState


class ReasonerAgent:
    """Runs the 9-step procedure against a loaded Stern template + retrieved evidence."""

    name: str = "reasoner"
    model_assignment_key: str = "reasoner"
    prompt_name: str = "reasoner/system"
    prompt_version: int = 1

    def __init__(self, client: LLMClient, *, prompts_dir: Path | None = None) -> None:
        self.client = client
        self.prompts_dir = prompts_dir

    async def run(self, case_state: CaseState, **kwargs: Any) -> AgentResult:
        template = kwargs["template"]
        previous_findings = kwargs.get("previous_findings", [])
        iteration = kwargs.get("iteration", 1)
        # Critiques from the Devil's Advocate / Must-Not-Miss Sweeper for the
        # **same turn** — populated only on the rerank pass. Empty list keeps
        # the prompt's ``{% if critiques_to_address %}`` guard quiet.
        critiques_to_address = kwargs.get("critiques_to_address", [])
        on_chunk = kwargs.get("on_chunk")

        text, response, latency = await call_text(
            self.client,
            prompt_name=self.prompt_name,
            prompt_version=self.prompt_version,
            prompt_kwargs={
                "template": template,
                "case_state": case_state,
                "iteration": iteration,
                "previous_findings": previous_findings,
                "critiques_to_address": critiques_to_address,
            },
            prompts_dir=self.prompts_dir,
            on_chunk=on_chunk,
        )

        return AgentResult(
            output=text,
            latency_ms=latency,
            metadata=usage_metadata(response),
        )
