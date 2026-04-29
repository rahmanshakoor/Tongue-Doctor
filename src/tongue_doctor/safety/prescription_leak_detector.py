"""Prescription leak detector.

Hard invariant (kickoff §J / SAFETY_INVARIANTS.md I-3): prescriptive content from
:class:`ResearchPrescription` must never appear in :class:`UserFacingOutput`.body.
This module is the runtime backstop. The schema-level guard (``UserFacingOutput`` with
``extra="forbid"`` and no ``prescription`` field) is the compile-time backstop. Together
they make a prescription leak both impossible to add silently and detectable when an
agent's output text inadvertently echoes prescription details.

What counts as "prescriptive content":

- ``drug_name``
- ``dose``
- ``duration``
- ``drug_class`` items
- ``contraindications_considered`` items
- ``interactions_considered`` items

``rationale`` is intentionally **excluded** — clinical reasoning legitimately overlaps
between the prescriber's working notes and the user-facing differential explanation.
Including it would generate false positives that mask real leaks. See ADR-0003 family
of decisions if this scope changes.
"""

from __future__ import annotations

import re

from tongue_doctor.schemas import (
    CaseState,
    ResearchPrescription,
    UserFacingOutput,
)

_MIN_SUBSTRING_LEN = 4
"""Substrings shorter than this are skipped — common short tokens (mg, PO, q12h)
generate noise without indicating an actual leak path."""

_WS_NORMALIZE_RE = re.compile(r"\s+")


class PrescriptionLeakError(RuntimeError):
    """Raised when prescriptive content appears in user-facing output.

    The ``leaked_substrings`` attribute lists the offending strings (after whitespace
    normalisation, lowercased) so callers can log a redacted incident report.
    """

    def __init__(self, leaked_substrings: list[str]) -> None:
        super().__init__(
            f"Prescription leak: {len(leaked_substrings)} substring(s) "
            f"from research_prescription appear in user-facing body."
        )
        self.leaked_substrings = leaked_substrings


def _normalize(s: str) -> str:
    return _WS_NORMALIZE_RE.sub(" ", s.strip().lower())


def _candidate_substrings(prescription: ResearchPrescription) -> set[str]:
    """Return prescriptive strings worth checking, normalised for comparison."""
    raw_strings: list[str] = [
        prescription.drug_name,
        prescription.dose,
        prescription.duration,
        *prescription.drug_class,
        *prescription.contraindications_considered,
        *prescription.interactions_considered,
    ]
    out: set[str] = set()
    for s in raw_strings:
        if not s:
            continue
        normalized = _normalize(s)
        if len(normalized) >= _MIN_SUBSTRING_LEN:
            out.add(normalized)
    return out


def find_leaks(
    output: UserFacingOutput,
    prescription: ResearchPrescription | None,
) -> list[str]:
    """Return any prescriptive substring that appears in ``output.body``.

    Returns an empty list when there is no prescription to check or the body is empty.
    Comparison is whitespace-normalised and case-insensitive.
    """
    if prescription is None:
        return []
    body_norm = _normalize(output.body)
    if not body_norm:
        return []
    candidates = _candidate_substrings(prescription)
    return sorted(s for s in candidates if s in body_norm)


def assert_no_leak(output: UserFacingOutput, case_state: CaseState) -> None:
    """Raise :class:`PrescriptionLeakError` if ``output.body`` leaks prescriptive content.

    Call this at the synthesizer / safety-reviewer boundary, before any output ships.
    """
    leaks = find_leaks(output, case_state.research_prescription)
    if leaks:
        raise PrescriptionLeakError(leaks)


class TaintTracker:
    """Stateful wrapper for orchestrator code that registers a prescription once per
    case and asserts against multiple outputs over the case lifecycle.

    For Phase 0 the simpler stateless :func:`assert_no_leak` is sufficient; this class
    exists so Phase 1 has an extension point (per-iteration tracking, leak metrics).
    """

    def __init__(self, prescription: ResearchPrescription | None = None) -> None:
        self._prescription = prescription

    def register(self, prescription: ResearchPrescription) -> None:
        self._prescription = prescription

    def find_leaks(self, output: UserFacingOutput) -> list[str]:
        return find_leaks(output, self._prescription)

    def assert_no_leak(self, output: UserFacingOutput) -> None:
        leaks = self.find_leaks(output)
        if leaks:
            raise PrescriptionLeakError(leaks)
