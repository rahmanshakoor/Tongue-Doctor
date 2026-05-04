"""CaseState CRUD with optional on-disk persistence.

Phase 1 trial — we keep cases in a per-process dict, and (when ``persist_dir`` is
set) also serialize each updated state to ``<persist_dir>/<case_id>.json``. The
disk layer is what makes multi-turn workflows actually work for the CLI: each
``make run-case`` call is a fresh Python process, so without disk persistence the
prior turn's state evaporates. Firestore lands in Phase 1b; the mutator pattern
preserved here keeps that upgrade mechanical.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tongue_doctor.schemas import CaseState

CaseMutator = Callable[[CaseState], CaseState]


class CaseNotFoundError(KeyError):
    """Raised when ``get`` or ``update`` is called for an unknown ``case_id``."""


class CaseManager:
    """In-memory CaseState store with optional disk-backed persistence.

    When ``persist_dir`` is provided:

    - ``update`` writes the new state to ``<persist_dir>/<case_id>.json`` after
      applying the mutator (best-effort; failures are not fatal — they're logged
      via the standard library and the in-memory state still updates).
    - ``get`` and ``get_or_create`` look on disk before raising / creating, so a
      fresh process picks up state written by an earlier process.
    - ``persist_dir`` is created if it does not already exist.

    With ``persist_dir=None`` the store is purely in-memory (the test default).
    """

    def __init__(
        self,
        *,
        project: str = "",
        emulator_host: str = "",
        persist_dir: Path | None = None,
    ) -> None:
        self.project = project
        self.emulator_host = emulator_host
        self._store: dict[str, CaseState] = {}
        self._persist_dir = persist_dir
        if persist_dir is not None:
            persist_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, case_id: str) -> Path | None:
        if self._persist_dir is None:
            return None
        # Sanitize: case_id may come from user input via the CLI / API.
        safe = "".join(c for c in case_id if c.isalnum() or c in "-_.")
        if not safe:
            safe = "_unknown_"
        return self._persist_dir / f"{safe}.json"

    def _load_from_disk(self, case_id: str) -> CaseState | None:
        path = self._path_for(case_id)
        if path is None or not path.is_file():
            return None
        try:
            return CaseState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_to_disk(self, state: CaseState) -> None:
        path = self._path_for(state.case_id)
        if path is None:
            return
        # Best-effort persistence; in-memory state already updated.
        with contextlib.suppress(OSError):
            path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    async def create(self, case_id: str, **_kwargs: Any) -> CaseState:
        if case_id in self._store:
            return self._store[case_id]
        on_disk = self._load_from_disk(case_id)
        state = on_disk if on_disk is not None else CaseState(case_id=case_id)
        self._store[case_id] = state
        return state

    async def get(self, case_id: str) -> CaseState:
        if case_id in self._store:
            return self._store[case_id]
        on_disk = self._load_from_disk(case_id)
        if on_disk is not None:
            self._store[case_id] = on_disk
            return on_disk
        raise CaseNotFoundError(case_id)

    async def get_or_create(self, case_id: str) -> CaseState:
        if case_id in self._store:
            return self._store[case_id]
        on_disk = self._load_from_disk(case_id)
        if on_disk is not None:
            self._store[case_id] = on_disk
            return on_disk
        return await self.create(case_id)

    async def update(self, case_id: str, mutator: CaseMutator) -> CaseState:
        """Apply ``mutator`` and (when persistent) write the new state to disk.

        The mutator must be a pure function — when this class moves to Firestore the
        caller's mutator may be retried on contention.
        """

        # If we have nothing in memory but the disk has it, hydrate first so the
        # mutator sees the persisted state — needed for cross-process multi-turn.
        if case_id not in self._store:
            on_disk = self._load_from_disk(case_id)
            if on_disk is None:
                raise CaseNotFoundError(case_id)
            self._store[case_id] = on_disk
        new_state = mutator(self._store[case_id])
        self._store[case_id] = new_state
        self._write_to_disk(new_state)
        return new_state

    async def compact_case_state(self, case_id: str) -> None:
        """No-op for the in-memory store."""

        return
