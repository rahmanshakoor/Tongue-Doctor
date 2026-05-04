"""Critic agent: looks for genuine reasoning errors in the Reasoner's trace.

Replacement for the old :class:`DevilsAdvocateAgent`. Output is structured
markdown prose with named section headers (Verdict / Where I agree with the
Defender / Missed findings / Biases observed / Live alternatives / Tests
that would resolve / Bottom line) — NOT JSON. The agent is explicitly told
that *concession is the strongest output when warranted* and that
manufactured doubt erodes its credibility.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tongue_doctor.agents._runtime import call_text, usage_metadata
from tongue_doctor.agents.base import AgentResult
from tongue_doctor.models.base import LLMClient
from tongue_doctor.schemas import CaseState


class CriticAgent:
    """Objective error-finder over the Reasoner's trace.

    Reads the Reasoner trace, the MNM sweep, the retrieved evidence, and (in
    rounds 2+) the prior rounds plus the current Defender output. Produces
    free-form markdown prose. Empty / "no material errors" output is allowed
    and encouraged when warranted.
    """

    name: str = "critic"
    model_assignment_key: str = "critic"
    prompt_name: str = "critic/system"
    prompt_version: int = 1

    def __init__(self, client: LLMClient, *, prompts_dir: Path | None = None) -> None:
        self.client = client
        self.prompts_dir = prompts_dir

    async def run(self, case_state: CaseState, **kwargs: Any) -> AgentResult:
        case_summary = kwargs["case_summary"]
        reasoner_trace = kwargs["reasoner_trace"]
        template = kwargs["template"]
        retrieved_chunks = kwargs.get("retrieved_chunks", [])
        mnm_sweep = kwargs.get("mnm_sweep")
        round_num = int(kwargs.get("round", 1))
        prior_rounds = kwargs.get("prior_rounds", [])
        current_defender = kwargs.get("current_defender", "")
        on_chunk = kwargs.get("on_chunk")

        text, response, latency = await call_text(
            self.client,
            prompt_name=self.prompt_name,
            prompt_version=self.prompt_version,
            prompt_kwargs={
                "case_summary": case_summary,
                "reasoner_trace": reasoner_trace,
                "template": template,
                "retrieved_chunks": retrieved_chunks,
                "mnm_sweep": mnm_sweep,
                "round": round_num,
                "prior_rounds": prior_rounds,
                "current_defender": current_defender,
            },
            prompts_dir=self.prompts_dir,
            on_chunk=on_chunk,
        )

        return AgentResult(
            output=text,
            latency_ms=latency,
            metadata=usage_metadata(response),
        )
