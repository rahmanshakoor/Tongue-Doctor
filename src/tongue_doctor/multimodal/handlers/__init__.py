"""Multimodal handler registry.

Adding a new modality is two steps: implement a Handler in this package, then call
:func:`register_handler`. The Processor dispatches by detected :class:`Modality`. This
plug-in surface is the v2 scaling answer — no orchestrator changes when a new handler
lands. See ``KICKOFF_PLAN.md`` §7 "Handler Interface".
"""

from __future__ import annotations

from typing import Any

from tongue_doctor.schemas import Modality

_HANDLERS: dict[Modality, Any] = {}


def register_handler(modality: Modality, handler: Any) -> None:
    """Register a handler for a specific modality.

    Last registration wins. Handlers must satisfy the (Phase 2) ``MultimodalHandler``
    protocol — a typed protocol arrives with the first concrete handler.
    """
    _HANDLERS[modality] = handler


def get_handler(modality: Modality) -> Any | None:
    return _HANDLERS.get(modality)


def list_modalities() -> list[Modality]:
    return list(_HANDLERS.keys())


__all__ = ["get_handler", "list_modalities", "register_handler"]
