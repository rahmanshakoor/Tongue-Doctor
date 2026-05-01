"""Tests for the Stern-faithful template schema.

Covers: role-tagged differential, computed must_not_miss, ``extra="forbid"``,
algorithm target_step validation, treatment-class deduplication.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from tongue_doctor.templates import (
    AlgorithmAction,
    AlgorithmBranch,
    AlgorithmStep,
    DecisionRule,
    DiagnosisHypothesis,
    HypothesisRole,
    Template,
    TestCharacteristic,
    load_template,
)


def _minimal_template_dict() -> dict[str, object]:
    """A reduced fixture mirroring what the extractor will emit for a chapter."""

    return {
        "complaint": "chest_pain",
        "chapter_number": 9,
        "chapter_title": "Chest Pain",
        "framework_type": "anatomical",
        "framework_categories": ["Cardiac", "Pulmonary", "Vascular", "GI", "MSK"],
        "pivotal_points": [
            "duration of symptoms (acute vs. chronic)",
            "vital signs",
            "presence of CHD risk factors",
        ],
        "decision_rules": [
            {
                "name": "HEART Score",
                "purpose": "Risk-stratify ED chest pain",
                "thresholds": ["0-3 low", "4-6 moderate", "7+ high"],
                "citation": "Stern p.169",
            }
        ],
        "differential": [
            {
                "name": "Stable angina",
                "role": "leading",
                "icd10": ["I20.9"],
                "pivotal_features_supporting": ["exertional", "relieved by rest"],
                "evidence_based_diagnosis": [
                    {
                        "test_name": "ECG stress test",
                        "sensitivity": 0.68,
                        "specificity": 0.77,
                        "lr_positive": 2.96,
                        "lr_negative": 0.41,
                        "citation": "Stern p.171",
                    }
                ],
                "treatment_classes": ["antiplatelet", "statin", "beta-blocker"],
                "textbook_presentation": (
                    "Substernal pressure with exertion, relieved within minutes by rest."
                ),
            },
            {
                "name": "Acute MI",
                "role": "active_must_not_miss",
                "icd10": ["I21.0", "I21.4"],
                "fingerprint_findings": ["ST elevation > 1mm in 2 contiguous leads"],
                "evidence_based_diagnosis": [
                    {
                        "test_name": "Troponin",
                        "sensitivity": 0.95,
                        "specificity": 0.96,
                        "citation": "Stern p.172",
                    }
                ],
                "treatment_classes": ["antiplatelet", "anticoagulant"],
                "textbook_presentation": "Acute substernal pressure, often with diaphoresis.",
            },
            {
                "name": "Aortic dissection",
                "role": "active_must_not_miss",
                "fingerprint_findings": ["BP differential between arms"],
                "treatment_classes": ["beta-blocker"],
                "textbook_presentation": "Tearing pain radiating to back; pulse deficit.",
            },
            {
                "name": "GERD",
                "role": "active_most_common",
                "icd10": ["K21.9"],
                "treatment_classes": ["proton pump inhibitor"],
                "textbook_presentation": "Burning retrosternal pain after meals.",
            },
            {
                "name": "Costochondritis",
                "role": "other",
                "treatment_classes": ["NSAID"],
                "textbook_presentation": "Reproducible chest-wall tenderness.",
            },
        ],
        "algorithm": [
            {
                "step_num": 1,
                "description": "Acute or chronic onset?",
                "rationale": "Acute presentations require ED triage.",
                "branches": [
                    {"condition": "Acute", "action": "next_step", "target_step": 2},
                    {"condition": "Chronic", "action": "next_step", "target_step": 5},
                ],
                "derived_from_figure": "Stern Fig 9-1",
            },
            {
                "step_num": 2,
                "description": "ECG meets STEMI criteria?",
                "branches": [
                    {
                        "condition": "Yes",
                        "action": "escalate",
                        "escalation_reason": "STEMI activation",
                    },
                    {"condition": "No", "action": "next_step", "target_step": 3},
                ],
                "derived_from_figure": "Stern Fig 9-2",
            },
            {
                "step_num": 3,
                "description": "Order troponin",
                "branches": [
                    {
                        "condition": "Positive",
                        "action": "confirm",
                        "target_diagnosis": "Acute MI",
                    },
                    {"condition": "Negative", "action": "next_step", "target_step": 4},
                ],
            },
            {
                "step_num": 4,
                "description": "Reassess differential with negative troponin",
                "branches": [
                    {"condition": "default", "action": "reassess", "target_step": 1},
                ],
            },
            {
                "step_num": 5,
                "description": "Apply HEART Score",
                "branches": [
                    {
                        "condition": "Score >= 7",
                        "action": "order_test",
                        "test_to_order": "Coronary angiography",
                    }
                ],
            },
        ],
        "source_pages": [164, 185],
        "reviewed_by": "pending",
    }


def test_minimal_template_round_trips() -> None:
    raw = _minimal_template_dict()
    t = Template.model_validate(raw)
    serialized = t.model_dump()
    # Round-trip preserves all explicit fields.
    assert serialized["complaint"] == "chest_pain"
    assert serialized["chapter_number"] == 9
    assert serialized["framework_type"] == "anatomical"
    # Computed fields surface in the dump.
    assert serialized["must_not_miss"] == ["Acute MI", "Aortic dissection"]
    assert serialized["leading_hypotheses"] == ["Stable angina"]
    # Treatment classes are deduplicated across diagnoses, preserving first-seen order.
    assert serialized["educational_treatment_classes"] == [
        "antiplatelet",
        "statin",
        "beta-blocker",
        "anticoagulant",
        "proton pump inhibitor",
        "NSAID",
    ]


def test_must_not_miss_filters_by_role() -> None:
    raw = _minimal_template_dict()
    t = Template.model_validate(raw)
    # Computed property reflects role tagging, not source order.
    assert set(t.must_not_miss) == {"Acute MI", "Aortic dissection"}
    # GERD (most common), Stable angina (leading), Costochondritis (other) are NOT here.
    for excluded in ("Stable angina", "GERD", "Costochondritis"):
        assert excluded not in t.must_not_miss


def test_extra_forbid_rejects_unknown_keys() -> None:
    raw = _minimal_template_dict()
    raw["extra_unknown_field"] = "should fail"
    with pytest.raises(ValidationError):
        Template.model_validate(raw)


def test_algorithm_validator_rejects_dangling_target_step() -> None:
    raw = _minimal_template_dict()
    # Point step 1's "Acute" branch at a non-existent step.
    raw["algorithm"][0]["branches"][0]["target_step"] = 99
    with pytest.raises(ValidationError) as exc_info:
        Template.model_validate(raw)
    assert "target_step=99" in str(exc_info.value)


def test_algorithm_validator_accepts_valid_targets() -> None:
    raw = _minimal_template_dict()
    Template.model_validate(raw)  # baseline must pass


def test_yaml_round_trip() -> None:
    raw = _minimal_template_dict()
    yaml_text = yaml.safe_dump(raw, sort_keys=False)
    parsed = yaml.safe_load(yaml_text)
    assert isinstance(parsed, dict)
    t = Template.model_validate(parsed)
    assert t.complaint == "chest_pain"
    assert len(t.algorithm) == 5


def test_load_template_finds_file(tmp_path: object) -> None:
    """Loader resolves a YAML by complaint name and validates it."""
    from pathlib import Path

    tmp_path = Path(str(tmp_path))  # type: ignore[arg-type]
    raw = _minimal_template_dict()
    target = tmp_path / "chest_pain.yaml"
    target.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    t = load_template("chest_pain", data_dir=tmp_path)
    assert t.complaint == "chest_pain"
    assert t.must_not_miss == ["Acute MI", "Aortic dissection"]


def test_constructable_from_python_objects() -> None:
    """A template assembled in Python (not from YAML) validates the same way."""

    t = Template(
        complaint="abdominal_pain",
        chapter_number=3,
        chapter_title="Abdominal Pain",
        framework_type="anatomical",
        differential=[
            DiagnosisHypothesis(
                name="Appendicitis",
                role=HypothesisRole.ACTIVE_MUST_NOT_MISS,
                evidence_based_diagnosis=[
                    TestCharacteristic(
                        test_name="CT abdomen",
                        sensitivity=0.94,
                        specificity=0.95,
                        citation="Stern p.55",
                    )
                ],
            ),
        ],
        decision_rules=[DecisionRule(name="Alvarado", purpose="Acute appendicitis")],
        algorithm=[
            AlgorithmStep(
                step_num=1,
                description="RLQ tenderness?",
                branches=[
                    AlgorithmBranch(
                        condition="Yes",
                        action=AlgorithmAction.ORDER_TEST,
                        test_to_order="CT abdomen",
                    )
                ],
            )
        ],
        source_pages=(40, 67),
    )
    assert t.must_not_miss == ["Appendicitis"]
