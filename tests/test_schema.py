from __future__ import annotations

import pytest
from pydantic import ValidationError

from schema import ACLFAssessment


def valid_payload(scores: dict[str, int | None] | None = None) -> dict:
    scores = scores or {}
    organs = []
    for name in ("liver", "kidney", "brain", "coagulation", "circulation", "respiration"):
        score = scores.get(name, 1)
        numeric = name in {"liver", "kidney", "coagulation"}
        organs.append(
            {
                "organ": name,
                "peak_value": 1.0 if numeric and score is not None else None,
                "peak_value_unit": "mg/dL" if numeric and score is not None else None,
                "peak_value_date": "2026-01-02" if numeric and score is not None else None,
                "clinical_finding": "No failure documented" if not numeric else None,
                "clif_score": score,
                "evidence_source": "structured_ehr" if numeric else "clinical_notes",
                "evidence_text": "Documented evidence" if score is not None else "No result",
                "evidence_references": (
                    [
                        {
                            "source_type": "measurement" if numeric else "clinical_note",
                            "source_id": "1001",
                            "event_date": "2026-01-02",
                            "description": "Documented evidence",
                            "quote": None if numeric else "No failure documented",
                        }
                    ]
                    if score is not None
                    else []
                ),
                "reasoning": "Meets the specified CLIF-C OF threshold.",
                "confidence": "high" if score is not None else "low",
                "missing_data_reason": None if score is not None else "No evidence available",
            }
        )
    return {
        "sample_id": "1030000000000001",
        "assessment_date": "2026-01-03",
        "has_acute_decompensation": True,
        "decompensation_type": ["ascites"],
        "organs": organs,
        "precipitants": [
            {
                "type": "none_identified",
                "subtype": None,
                "evidence_text": "Systematic review found none.",
                "evidence_references": [],
                "confidence": "moderate",
            }
        ],
        "age_years": 60,
        "wbc_count": 10.0,
        "wbc_date": "2026-01-02",
        "serum_sodium": 135.0,
        "sodium_date": "2026-01-02",
        "clinical_summary": "The patient had an acute hospitalization. Evidence was reviewed for all organs.",
        "data_quality": "sufficient",
        "episode_start_date": "2026-01-01",
        "episode_end_date": "2026-01-05",
    }


def test_valid_assessment_has_six_ordered_organs():
    assessment = ACLFAssessment.model_validate(valid_payload())
    assert [item.organ for item in assessment.organs] == [
        "liver",
        "kidney",
        "brain",
        "coagulation",
        "circulation",
        "respiration",
    ]


def test_duplicate_organ_is_rejected():
    payload = valid_payload()
    payload["organs"][-1]["organ"] = "liver"
    with pytest.raises(ValidationError):
        ACLFAssessment.model_validate(payload)


def test_empty_sample_id_is_rejected():
    payload = valid_payload()
    payload["sample_id"] = "   "
    with pytest.raises(ValidationError):
        ACLFAssessment.model_validate(payload)


def test_numeric_score_requires_value():
    payload = valid_payload()
    payload["organs"][0]["peak_value"] = None
    with pytest.raises(ValidationError):
        ACLFAssessment.model_validate(payload)


def test_missing_data_is_explicit_not_assumed_normal():
    assessment = ACLFAssessment.model_validate(valid_payload({"liver": None}))
    assert assessment.organs[0].clif_score is None
    assert assessment.organs[0].missing_data_reason


def test_none_identified_cannot_mix_with_precipitants():
    payload = valid_payload()
    payload["precipitants"].append(
        {
            "type": "bacterial_infection",
            "subtype": "SBP",
            "evidence_text": "Ascitic neutrophils 400/mm3.",
            "evidence_references": [
                {
                    "source_type": "measurement",
                    "source_id": "2001",
                    "event_date": "2026-01-02",
                    "description": "Ascitic neutrophils 400/mm3",
                    "quote": None,
                }
            ],
            "confidence": "high",
        }
    )
    with pytest.raises(ValidationError):
        ACLFAssessment.model_validate(payload)
