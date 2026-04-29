"""Safety guards: disclaimers, scope rules, prescription leak detector.

The prescription leak detector is the only Phase 0 invariant fully enforced + tested.
See ``docs/SAFETY_INVARIANTS.md`` I-3 for the rationale.
"""

from tongue_doctor.safety.disclaimers import (
    DISCLAIMERS,
    DisclaimerKind,
    disclaimer_for_output_kind,
    get_disclaimer,
    inject_disclaimer,
)
from tongue_doctor.safety.prescription_leak_detector import (
    PrescriptionLeakError,
    TaintTracker,
    assert_no_leak,
    find_leaks,
)
from tongue_doctor.safety.scope import ScopeDecision, ScopeRationale, is_in_scope

__all__ = [
    "DISCLAIMERS",
    "DisclaimerKind",
    "PrescriptionLeakError",
    "ScopeDecision",
    "ScopeRationale",
    "TaintTracker",
    "assert_no_leak",
    "disclaimer_for_output_kind",
    "find_leaks",
    "get_disclaimer",
    "inject_disclaimer",
    "is_in_scope",
]
