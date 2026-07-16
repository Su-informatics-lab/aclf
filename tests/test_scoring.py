from __future__ import annotations

import math

import pytest

from schema import ACLFAssessment
from scoring import (
    compute_child_pugh,
    compute_clif_c_aclf_score,
    compute_clif_c_ad_score,
    compute_meld,
    compute_meld_na,
    score_aclf,
)
from tests.test_schema import valid_payload


def assessed(scores: dict[str, int | None]) -> ACLFAssessment:
    payload = valid_payload(scores)
    values = {
        "liver": {1: 2.0, 2: 8.0, 3: 13.0},
        "kidney": {1: 1.0, 2: 1.7, 3: 2.2},
        "coagulation": {1: 1.2, 2: 2.2, 3: 2.7},
    }
    for organ in payload["organs"]:
        if organ["organ"] in values and organ["clif_score"] is not None:
            organ["peak_value"] = values[organ["organ"]][organ["clif_score"]]
    return ACLFAssessment.model_validate(payload)


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ({}, "no_aclf"),
        ({"liver": 3}, "no_aclf"),
        ({"kidney": 3}, "1a"),
        ({"liver": 3, "kidney": 2}, "1b"),
        ({"liver": 3, "brain": 2}, "1b"),
        ({"liver": 3, "kidney": 3}, "2"),
        ({"liver": 3, "kidney": 3, "brain": 3}, "3a"),
        ({"liver": 3, "kidney": 3, "brain": 3, "coagulation": 3}, "3b"),
    ],
)
def test_all_grade_paths(scores, expected):
    assert score_aclf(assessed(scores))["aclf_grade"] == expected


def test_missing_organ_yields_indeterminate_not_normal():
    result = score_aclf(assessed({"respiration": None}))
    assert result["aclf_grade"] == "indeterminate"
    assert result["missing_organs"] == ["respiration"]


def test_known_three_failures_prove_aclf_with_bounded_grade():
    result = score_aclf(
        assessed(
            {
                "liver": 3,
                "kidney": 3,
                "coagulation": 3,
                "brain": None,
                "circulation": None,
                "respiration": None,
            }
        )
    )
    assert result["aclf_grade"] == "indeterminate"
    assert result["aclf_present"] is True
    assert result["aclf_grade_min"] == "3a"
    assert result["aclf_grade_max"] == "3b"
    assert result["n_organ_failures_min"] == 3
    assert result["n_organ_failures_max"] == 6


def test_single_non_kidney_failure_with_missing_kidney_is_presence_indeterminate():
    result = score_aclf(assessed({"liver": 3, "kidney": None}))
    assert result["aclf_present"] is None
    assert result["aclf_grade_min"] == "no_aclf"
    assert result["aclf_grade_max"] == "2"


def test_no_acute_decompensation_is_not_aclf_or_ad_score():
    assessment = assessed({"kidney": 3})
    assessment.has_acute_decompensation = False
    assessment.decompensation_type = []
    result = score_aclf(assessment)
    assert result["aclf_grade"] == "no_aclf"
    assert result["scoring_status"] == "not_eligible_no_acute_decompensation"
    assert result["clif_c_ad_score"] is None


def test_no_acute_decompensation_takes_precedence_over_missing_organs():
    assessment = assessed({"brain": None, "respiration": None})
    assessment.has_acute_decompensation = False
    assessment.decompensation_type = []
    result = score_aclf(assessment)
    assert result["aclf_grade"] == "no_aclf"
    assert result["scoring_status"] == "not_eligible_no_acute_decompensation"
    assert result["missing_organs"] == ["brain", "respiration"]


def test_clif_c_aclf_formula():
    expected = 10 * (0.33 * 12 + 0.04 * 60 + 0.63 * math.log(10) - 2)
    assert compute_clif_c_aclf_score(12, 60, 10) == round(expected, 1)


def test_clif_c_ad_formula():
    expected = 10 * (
        0.03 * 60
        + 0.66 * math.log(1.2)
        + 1.71 * math.log(1.4)
        + 0.88 * math.log(8)
        - 0.05 * 135
        + 8
    )
    assert compute_clif_c_ad_score(60, 1.2, 1.4, 8, 135) == round(expected, 1)


def test_log_inputs_must_be_positive():
    with pytest.raises(ValueError):
        compute_clif_c_ad_score(60, 0, 1.4, 8, 135)


def test_clif_scores_are_trimmed_to_published_range():
    assert compute_clif_c_aclf_score(6, 1, 0.01) == 0.0
    assert compute_clif_c_aclf_score(18, 120, 1000) == 100.0
    assert compute_clif_c_ad_score(1, 0.01, 0.01, 0.01, 200) == 0.0
    assert compute_clif_c_ad_score(120, 20, 10, 1000, 100) == 100.0


def test_original_meld_bounds_inputs_and_total():
    assert compute_meld(0.2, 0.3, 0.8) == 6
    assert compute_meld(50, 10, 5) == 40
    assert compute_meld(1, 1.1, 1, dialysis=True) == compute_meld(1, 4, 1)


def test_kim_2008_meld_na_sodium_and_total_bounds():
    # Sodium below 125 and above 137 are constrained before applying the equation.
    assert compute_meld_na(20, 120) == compute_meld_na(20, 125)
    assert compute_meld_na(20, 140) == compute_meld_na(20, 137) == 20
    assert compute_meld_na(40, 125) == 40


@pytest.mark.parametrize(
    ("bilirubin", "albumin", "inr", "ascites", "he", "expected"),
    [
        (1.9, 3.6, 1.6, "none", 0, 5),
        (2.0, 3.5, 1.7, "mild", 1, 10),
        (3.1, 2.7, 2.4, "moderate_severe", 3, 15),
    ],
)
def test_child_pugh_boundaries(bilirubin, albumin, inr, ascites, he, expected):
    assert compute_child_pugh(bilirubin, albumin, inr, ascites, he) == expected


def test_comparator_scores_are_null_when_required_input_is_missing():
    payload = valid_payload()
    payload["prognostic_inputs"]["serum_albumin"] = None
    payload["prognostic_inputs"]["albumin_datetime"] = None
    result = score_aclf(ACLFAssessment.model_validate(payload))
    assert result["meld_score"] is not None
    assert result["meld_na_score"] is not None
    assert result["child_pugh_score"] is None
