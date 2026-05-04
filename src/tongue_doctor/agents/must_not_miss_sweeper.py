"""Must-Not-Miss Sweeper agent: audits ACTIVE_MUST_NOT_MISS coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tongue_doctor.agents._runtime import call_structured, usage_metadata
from tongue_doctor.agents.base import AgentResult
from tongue_doctor.agents.schemas import MustNotMissSweep
from tongue_doctor.models.base import LLMClient
from tongue_doctor.schemas import CaseState


class MustNotMissSweeperAgent:
    """Walks every ``ACTIVE_MUST_NOT_MISS`` diagnosis and demands an explicit test rationale."""

    name: str = "must_not_miss_sweeper"
    model_assignment_key: str = "must_not_miss_sweeper"
    prompt_name: str = "must_not_miss_sweeper/system"
    prompt_version: int = 1

    def __init__(self, client: LLMClient, *, prompts_dir: Path | None = None) -> None:
        self.client = client
        self.prompts_dir = prompts_dir

    async def run(self, case_state: CaseState, **kwargs: Any) -> AgentResult:
        case_summary = kwargs["case_summary"]
        reasoner_trace = kwargs["reasoner_trace"]
        template = kwargs["template"]
        retrieved_chunks = kwargs.get("retrieved_chunks", [])
        on_chunk = kwargs.get("on_chunk")

        parsed, response, latency = await call_structured(
            self.client,
            prompt_name=self.prompt_name,
            prompt_version=self.prompt_version,
            prompt_kwargs={
                "case_summary": case_summary,
                "reasoner_trace": reasoner_trace,
                "template": template,
                "retrieved_chunks": retrieved_chunks,
            },
            response_model=MustNotMissSweep,
            prompts_dir=self.prompts_dir,
            on_chunk=on_chunk,
        )
        assert isinstance(parsed, MustNotMissSweep)

        return AgentResult(
            output=parsed,
            latency_ms=latency,
            metadata=usage_metadata(response),
        )
