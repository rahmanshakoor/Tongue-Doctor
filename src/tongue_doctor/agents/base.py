"""Agent protocol.

All concrete agents (Router, Reasoner, Devil's Advocate, ...) satisfy this protocol
structurally. The orchestrator depends on the protocol — model swaps and prompt swaps
are config changes, not orchestrator changes.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from tongue_doctor.schemas import CaseState


class StateMutation(BaseModel):
    """A pending mutation an agent wants applied to the :class:`CaseState`.

    The orchestrator applies mutations inside a Firestore transaction via
    :meth:`CaseManager.update`. Agents never write to Firestore directly; this preserves
    the retry-on-contention semantics that the mutator pattern relies on.

    ``op`` is one of the documented operations
    (``append_known_fact``, ``set_status``, ``add_differential``, ``add_red_flag``, ...).
    ``payload`` is the operation-specific data (typed in the orchestrator dispatch).
    """

    model_config = ConfigDict(extra="forbid")

    op: str
    payload: dict[str, Any]


class AgentResult(BaseModel):
    """Output of one agent invocation."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    output: Any = None
    state_mutations: list[StateMutation] = Field(default_factory=list)
    retrieval_calls: int = 0
    tool_calls: int = 0
    latency_ms: int = 0
    cost_estimate_usd: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Agent(Protocol):
    """A unit of work invoked by the diagnostic loop.

    ``model_assignment_key`` is resolved by :func:`tongue_doctor.models.get_client`.
    ``prompt_name`` is the dotted-path resolved by
    :func:`tongue_doctor.prompts.load_prompt` together with the version pinned in
    ``config/default.yaml`` ``prompts:``.
    """

    name: str
    model_assignment_key: str
    prompt_name: str

    async def run(self, case_state: CaseState, **kwargs: Any) -> AgentResult: ...
