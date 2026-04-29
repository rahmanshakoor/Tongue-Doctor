"""Prescription leak detector — the hard invariant from kickoff §J.

This test file is non-negotiable. It pins the runtime behaviour of the leak guard
that must survive every refactor, prompt change, and model swap. See
``docs/SAFETY_INVARIANTS.md`` I-3.
"""

from __future__ import annotations

import pytest

from tongue_doctor.safety.prescription_leak_detector import (
    PrescriptionLeakError,
    TaintTracker,
    assert_no_leak,
    find_leaks,
)
from tongue_doctor.schemas import (
    CaseState,
    OutputKind,
    ResearchPrescription,
    UserFacingOutput,
)

DEFAULT_DISCLAIMER = "Research demo only."


def make_prescription() -> ResearchPrescription:
    return ResearchPrescription(
        drug_class=["beta-lactam antibiotic"],
        drug_name="amoxicillin-clavulanate",
        dose="875 mg PO q12h",
        duration="10 days",
        rationale="streptococcal pharyngitis",
        contraindications_considered=["penicillin allergy"],
        interactions_considered=["warfarin INR elevation"],
    )


def make_case_state(prescription: ResearchPrescription | None) -> CaseState:
    return CaseState(case_id="case-1", research_prescription=prescription)


def output_with_body(body: str) -> UserFacingOutput:
    return UserFacingOutput(
        kind=OutputKind.COMMITMENT,
        body=body,
        disclaimer=DEFAULT_DISCLAIMER,
    )


def test_drug_name_in_body_is_a_leak() -> None:
    cs = make_case_state(make_prescription())
    out = output_with_body("Take amoxicillin-clavulanate twice daily.")
    with pytest.raises(PrescriptionLeakError) as exc:
        assert_no_leak(out, cs)
    assert "amoxicillin-clavulanate" in exc.value.leaked_substrings


def test_dose_in_body_is_a_leak() -> None:
    cs = make_case_state(make_prescription())
    out = output_with_body(
        "The recommended schedule is 875 mg PO q12h, please follow your doctor's advice."
    )
    with pytest.raises(PrescriptionLeakError):
        assert_no_leak(out, cs)


def test_contraindication_in_body_is_a_leak() -> None:
    cs = make_case_state(make_prescription())
    out = output_with_body("Patients with penicillin allergy should be careful.")
    with pytest.raises(PrescriptionLeakError):
        assert_no_leak(out, cs)


def test_drug_class_in_body_is_a_leak() -> None:
    cs = make_case_state(make_prescription())
    out = output_with_body("This belongs to the beta-lactam antibiotic family.")
    with pytest.raises(PrescriptionLeakError):
        assert_no_leak(out, cs)


def test_interaction_in_body_is_a_leak() -> None:
    cs = make_case_state(make_prescription())
    out = output_with_body("Note: warfarin INR elevation can occur.")
    with pytest.raises(PrescriptionLeakError):
        assert_no_leak(out, cs)


def test_normalized_whitespace_match() -> None:
    cs = make_case_state(make_prescription())
    out = output_with_body("875  mg   PO\tq12h is the schedule.")
    with pytest.raises(PrescriptionLeakError):
        assert_no_leak(out, cs)


def test_case_insensitive_match() -> None:
    cs = make_case_state(make_prescription())
    out = output_with_body("AMOXICILLIN-CLAVULANATE is one option.")
    with pytest.raises(PrescriptionLeakError):
        assert_no_leak(out, cs)


def test_no_leak_when_body_is_unrelated() -> None:
    cs = make_case_state(make_prescription())
    out = output_with_body("Discuss treatment options with your physician.")
    assert_no_leak(out, cs)


def test_no_leak_when_no_prescription() -> None:
    cs = make_case_state(prescription=None)
    out = output_with_body("Take amoxicillin-clavulanate.")
    assert_no_leak(out, cs)
    assert find_leaks(out, None) == []


def test_no_leak_when_body_is_empty() -> None:
    cs = make_case_state(make_prescription())
    out = output_with_body("")
    assert_no_leak(out, cs)


def test_rationale_intentionally_not_checked() -> None:
    """Rationale prose is intentionally excluded.

    Pins the design choice: rationale legitimately overlaps between prescriber notes and
    the user-facing differential explanation. Including it would generate false positives
    that mask real leaks. A future change to include rationale is a deliberate one and
    should update this test.
    """
    cs = make_case_state(make_prescription())
    out = output_with_body("Consider streptococcal pharyngitis as the leading cause.")
    assert_no_leak(out, cs)


def test_short_substrings_below_min_length_are_skipped() -> None:
    """``mg`` alone is too short to be treated as prescriptive content."""
    rx = ResearchPrescription(
        drug_class=[],
        drug_name="X",
        dose="mg",
        duration="1d",
        rationale="...",
    )
    cs = make_case_state(rx)
    out = output_with_body("The plan calls for 1 mg once daily of an unrelated medication.")
    assert_no_leak(out, cs)


def test_taint_tracker_register_and_assert() -> None:
    tracker = TaintTracker()
    tracker.register(make_prescription())
    out = output_with_body("Take amoxicillin-clavulanate.")
    with pytest.raises(PrescriptionLeakError):
        tracker.assert_no_leak(out)


def test_taint_tracker_no_prescription_no_leak() -> None:
    tracker = TaintTracker()
    out = output_with_body("Take amoxicillin-clavulanate.")
    tracker.assert_no_leak(out)
    assert tracker.find_leaks(out) == []
