"""Judge agent: weighs the dialectic + MNM audit and issues the final verdict."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tongue_doctor.agents._runtime import call_structured, usage_metadata
from tongue_doctor.agents.base import AgentResult
from tongue_doctor.agents.schemas import JudgeVerdict
from tongue_doctor.models.base import LLMClient
from tongue_doctor.schemas import CaseState


class JudgeAgent:
    """Sole decider of the final clinical commitment.

    Reads the entire dialectic transcript (Prosecutor and DA arguments per round)
    plus the Reasoner's initial trace and the Must-Not-Miss audit, then issues
    a single :class:`JudgeVerdict` that downstream agents render verbatim. The
    Judge — and only the Judge — picks the final leading diagnosis, the
    confidence band, the recommended workup, the active / excluded alternatives,
    citations, and the closing statement.
    """

    name: str = "judge"
    model_assignment_key: str = "judge"
    prompt_name: str = "judge/system"
    prompt_version: int = 1

    def __init__(self, client: LLMClient, *, prompts_dir: Path | None = None) -> None:
        self.client = client
        self.prompts_dir = prompts_dir

    async def run(self, case_state: CaseState, **kwargs: Any) -> AgentResult:
        case_summary = kwargs["case_summary"]
        reasoner_trace = kwargs["reasoner_trace"]
        template = kwargs["template"]
        retrieved_chunks = kwargs.get("retrieved_chunks", [])
        # New convergence-loop inputs (replacing prosecutor_args / da_args):
        rounds = kwargs["rounds"]
        converged = bool(kwargs.get("converged", False))
        mnm_sweep = kwargs["mnm_sweep"]
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
                "rounds": rounds,
                "converged": converged,
                "mnm_sweep": mnm_sweep,
            },
            response_model=JudgeVerdict,
            prompts_dir=self.prompts_dir,
            on_chunk=on_chunk,
        )
        assert isinstance(parsed, JudgeVerdict)

        return AgentResult(
            output=parsed,
            latency_ms=latency,
            metadata=usage_metadata(response),
        )
