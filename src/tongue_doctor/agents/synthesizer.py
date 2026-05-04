"""Synthesizer agent: composes the final user-facing commitment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tongue_doctor.agents._runtime import call_structured, usage_metadata
from tongue_doctor.agents.base import AgentResult
from tongue_doctor.agents.schemas import SynthesisOutput
from tongue_doctor.models.base import LLMClient
from tongue_doctor.schemas import CaseState


class SynthesizerAgent:
    """Takes Reasoner trace + DA critique + MNM sweep and emits the final commitment."""

    name: str = "synthesizer"
    model_assignment_key: str = "synthesizer"
    prompt_name: str = "synthesizer/system"
    prompt_version: int = 1

    def __init__(self, client: LLMClient, *, prompts_dir: Path | None = None) -> None:
        self.client = client
        self.prompts_dir = prompts_dir

    async def run(self, case_state: CaseState, **kwargs: Any) -> AgentResult:
        # Pure renderer: takes the Judge's structured verdict and emits the
        # user-facing markdown body, the disclaimer, and citations.
        judge_verdict = kwargs["judge_verdict"]
        reviewed_by = kwargs.get("reviewed_by", "pending")
        on_chunk = kwargs.get("on_chunk")

        # Serialize the Judge's verdict for the prompt — the renderer reads the JSON
        # rather than receiving 14 individual kwargs the prompt would have to render.
        judge_verdict_json = (
            judge_verdict.model_dump_json(indent=2)
            if hasattr(judge_verdict, "model_dump_json")
            else str(judge_verdict)
        )

        parsed, response, latency = await call_structured(
            self.client,
            prompt_name=self.prompt_name,
            prompt_version=self.prompt_version,
            prompt_kwargs={
                "judge_verdict_json": judge_verdict_json,
                "reviewed_by": reviewed_by,
            },
            response_model=SynthesisOutput,
            prompts_dir=self.prompts_dir,
            on_chunk=on_chunk,
        )
        assert isinstance(parsed, SynthesisOutput)

        return AgentResult(
            output=parsed,
            latency_ms=latency,
            metadata=usage_metadata(response),
        )
