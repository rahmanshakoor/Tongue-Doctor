"""Firestore-backed CaseState CRUD.

Phase 0 — class skeleton; methods raise :class:`NotImplementedError`. Phase 1 wires
``google-cloud-firestore`` and the transaction-and-mutator pattern.

**Mutator pattern.** Every update goes through :meth:`CaseManager.update` with a pure
``CaseState -> CaseState`` function. The Firestore transaction retries the mutator on
contention; side effects inside the mutator break that contract. Agents return
:class:`StateMutation` objects which the orchestrator translates into mutator functions.
See ``KICKOFF_PLAN.md`` §6.
"""

from __future__ import annotations

from collections.abc import Callable

from tongue_doctor.schemas import CaseState

CaseMutator = Callable[[CaseState], CaseState]


class CaseNotFoundError(KeyError):
    """Raised when ``get`` or ``update`` is called for an unknown ``case_id``."""


class CaseManager:
    """Firestore CRUD for :class:`CaseState`.

    Phase 1 wires:

    - :class:`google.cloud.firestore.AsyncClient` (with emulator host when set).
    - Document path: ``cases/{case_id}``.
    - Subcollections: ``cases/{case_id}/turns``, ``cases/{case_id}/iterations``,
      ``cases/{case_id}/audit``.
    - Transaction-and-mutator semantics for ``update``.
    """

    def __init__(self, *, project: str = "", emulator_host: str = "") -> None:
        self.project = project
        self.emulator_host = emulator_host

    async def create(self, case_id: str) -> CaseState:
        raise NotImplementedError(
            "CaseManager.create lands in Phase 1 (Firestore async client + initial CaseState)."
        )

    async def get(self, case_id: str) -> CaseState:
        raise NotImplementedError(
            "CaseManager.get lands in Phase 1. Raise CaseNotFoundError when document missing."
        )

    async def update(self, case_id: str, mutator: CaseMutator) -> CaseState:
        """Apply ``mutator`` to the current state inside a Firestore transaction.

        The mutator must be a pure function — it may be retried automatically.
        """
        raise NotImplementedError(
            "CaseManager.update lands in Phase 1. Use Firestore transactions; retry on aborted."
        )

    async def compact_case_state(self, case_id: str) -> None:
        """Spill heavy fields out of the parent document to keep it < 1 MiB.

        Per ``KICKOFF_PLAN.md`` §6: retrieved_knowledge_summary stays compact in the parent;
        full chunks move to the ``iterations`` subcollection. Long agent outputs move to
        case-scoped subcollections referenced by ID.
        """
        raise NotImplementedError("CaseManager.compact_case_state lands in Phase 1.")
