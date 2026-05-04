"""Safety Reviewer agent: post-hoc audit of the synthesizer output."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tongue_doctor.agents._runtime import call_structured, usage_metadata
from tongue_doctor.agents.base import AgentResult
from tongue_doctor.agents.schemas import SafetyVerdict, SynthesisOutput
from tongue_doctor.models.base import LLMClient
from tongue_doctor.schemas import CaseState


class SafetyReviewerAgent:
    """Audits the Synthesizer's output and returns approve / revise / refuse."""

    name: str = "safety_reviewer"
    model_assignment_key: str = "safety_reviewer"
    prompt_name: str = "safety_reviewer/system"
    prompt_version: int = 1

    def __init__(self, client: LLMClient, *, prompts_dir: Path | None = None) -> None:
        self.client = client
        self.prompts_dir = prompts_dir

    async def run(self, case_state: CaseState, **kwargs: Any) -> AgentResult:
        case_summary = kwargs["case_summary"]
        synthesis: SynthesisOutput = kwargs["synthesis_output"]
        reviewed_by = kwargs.get("reviewed_by", "pending")
        on_chunk = kwargs.get("on_chunk")

        parsed, response, latency = await call_structured(
            self.client,
            prompt_name=self.prompt_name,
            prompt_version=self.prompt_version,
            prompt_kwargs={
                "case_summary": case_summary,
                "synthesis_output_json": synthesis.model_dump_json(indent=2),
                "reviewed_by": reviewed_by,
            },
            response_model=SafetyVerdict,
            prompts_dir=self.prompts_dir,
            on_chunk=on_chunk,
        )
        assert isinstance(parsed, SafetyVerdict)

        return AgentResult(
            output=parsed,
            latency_ms=latency,
            metadata=usage_metadata(response),
        )
