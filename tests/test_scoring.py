from __future__ import annotations

import math

import pytest

from schema import ACLFAssessment
from scoring import compute_clif_c_aclf_score, compute_clif_c_ad_score, score_aclf
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
