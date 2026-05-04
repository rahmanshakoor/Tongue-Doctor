"""Router agent: chief complaint → template slug."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tongue_doctor.agents._runtime import call_structured, template_catalog, usage_metadata
from tongue_doctor.agents.base import AgentResult, StateMutation
from tongue_doctor.agents.schemas import RouterOutput
from tongue_doctor.models.base import LLMClient
from tongue_doctor.schemas import CaseState


class RouterAgent:
    """Maps a free-text patient message onto one of the 31 Stern complaint templates."""

    name: str = "router"
    model_assignment_key: str = "router"
    prompt_name: str = "router/system"
    prompt_version: int = 1

    def __init__(
        self,
        client: LLMClient,
        *,
        prompts_dir: Path | None = None,
        templates_dir: Path | None = None,
    ) -> None:
        self.client = client
        self.prompts_dir = prompts_dir
        self._catalog = template_catalog(templates_dir)

    @property
    def catalog(self) -> list[dict[str, Any]]:
        return self._catalog

    async def run(self, case_state: CaseState, **kwargs: Any) -> AgentResult:
        user_message = kwargs.get("user_message", "")
        if not user_message:
            raise ValueError("RouterAgent.run requires user_message kwarg")
        on_chunk = kwargs.get("on_chunk")

        parsed, response, latency = await call_structured(
            self.client,
            prompt_name=self.prompt_name,
            prompt_version=self.prompt_version,
            prompt_kwargs={
                "user_message": user_message,
                "template_catalog": self._catalog,
            },
            response_model=RouterOutput,
            prompts_dir=self.prompts_dir,
            on_chunk=on_chunk,
        )
        assert isinstance(parsed, RouterOutput)

        return AgentResult(
            output=parsed,
            state_mutations=[
                StateMutation(
                    op="set_template_slug",
                    payload={"slug": parsed.template_slug},
                ),
            ],
            latency_ms=latency,
            metadata=usage_metadata(response),
        )
