from __future__ import annotations

import copy

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
                "peak_value_datetime": "2026-01-01 08:00:00" if numeric and score is not None else None,
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
    eligibility_evidence = {
        "source_type": "clinical_note",
        "source_id": "1002",
        "event_date": "2026-01-01",
        "description": "Admission documentation",
        "quote": "new tense ascites",
    }
    known_yes = {
        "status": "yes",
        "reasoning": "Documented at admission.",
        "evidence_references": [eligibility_evidence],
    }
    known_no = {
        "status": "no",
        "reasoning": "Admission documentation argues against this criterion.",
        "evidence_references": [eligibility_evidence],
    }
    unknown = {
        "status": "unknown",
        "reasoning": "Available evidence cannot determine this criterion.",
        "evidence_references": [],
    }
    return {
        "sample_id": "1030000000000001",
        "assessment_timepoint": "admission_baseline",
        "visit_occurrence_id": 10,
        "episode_start_datetime": "2026-01-01 01:00:00",
        "episode_end_datetime": "2026-01-05 10:00:00",
        "baseline_window_start": "2026-01-01 01:00:00",
        "baseline_window_end": "2026-01-02 01:00:00",
        "eligibility": {
            "canonical_acute_decompensation": copy.deepcopy(known_yes),
            "non_elective_admission": copy.deepcopy(known_yes),
            "scheduled_procedure_or_treatment": copy.deepcopy(known_no),
            "prior_liver_transplant": copy.deepcopy(known_no),
            "hcc_outside_milan": copy.deepcopy(unknown),
            "hiv": copy.deepcopy(unknown),
            "immunosuppression": copy.deepcopy(unknown),
            "severe_extrahepatic_disease": copy.deepcopy(unknown),
        },
        "assessment_date": "2026-01-03",
        "has_acute_decompensation": True,
        "decompensation_type": ["ascites"],
        "decompensation_evidence_references": [
            {
                "source_type": "clinical_note",
                "source_id": "1002",
                "event_date": "2026-01-01",
                "description": "New tense ascites requiring hospitalization",
                "quote": "new tense ascites",
            }
        ],
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
        "wbc_datetime": "2026-01-01 09:00:00",
        "serum_sodium": 135.0,
        "sodium_date": "2026-01-02",
        "sodium_datetime": "2026-01-01 09:30:00",
        "prognostic_inputs": {
            "serum_albumin": 3.0,
            "albumin_datetime": "2026-01-01 04:00:00",
            "ascites_severity": "mild",
            "hepatic_encephalopathy_grade": 0,
            "renal_replacement_therapy": False,
            "evidence_references": [eligibility_evidence],
        },
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
    assessment = ACLFAssessment.model_validate(payload)
    assert assessment.organs[0].clif_score is None


def test_numeric_score_requires_peak_date():
    payload = valid_payload()
    payload["organs"][0]["peak_value_date"] = None
    assessment = ACLFAssessment.model_validate(payload)
    assert assessment.organs[0].clif_score is None


def test_numeric_score_requires_peak_datetime():
    payload = valid_payload()
    payload["organs"][0]["peak_value_datetime"] = None
    assessment = ACLFAssessment.model_validate(payload)
    assert assessment.organs[0].clif_score is None
    assert assessment.organs[0].peak_value is None
    assert assessment.normalization_warnings


def test_record_evidence_requires_source_id():
    payload = valid_payload()
    payload["organs"][0]["evidence_references"][0]["source_id"] = None
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


def test_acute_decompensation_requires_traceable_evidence():
    payload = valid_payload()
    payload["decompensation_evidence_references"] = []
    with pytest.raises(ValidationError):
        ACLFAssessment.model_validate(payload)


def test_infection_is_a_canonical_acute_decompensation():
    payload = valid_payload()
    payload["decompensation_type"] = ["infection"]
    assert ACLFAssessment.model_validate(payload).decompensation_type == ["infection"]


def test_noncanonical_decompensation_alone_is_rejected():
    payload = valid_payload()
    payload["decompensation_type"] = ["jaundice"]
    with pytest.raises(ValidationError):
        ACLFAssessment.model_validate(payload)


def test_known_eligibility_status_requires_evidence():
    payload = valid_payload()
    payload["eligibility"]["hiv"] = {
        "status": "no",
        "reasoning": "No HIV documented.",
        "evidence_references": [],
    }
    assessment = ACLFAssessment.model_validate(payload)
    assert assessment.eligibility.hiv.status == "unknown"
    assert "unsupported no -> unknown" in assessment.normalization_warnings[-1]


def test_albumin_requires_datetime():
    payload = valid_payload()
    payload["prognostic_inputs"]["albumin_datetime"] = None
    assessment = ACLFAssessment.model_validate(payload)
    assert assessment.prognostic_inputs.serum_albumin is None
    assert assessment.prognostic_inputs.albumin_datetime is None


def test_wbc_and_sodium_without_datetime_are_null_not_imputed():
    payload = valid_payload()
    payload["wbc_datetime"] = None
    payload["sodium_datetime"] = "2026-01-02 01:00:00"  # exclusive boundary
    assessment = ACLFAssessment.model_validate(payload)
    assert assessment.wbc_count is None
    assert assessment.serum_sodium is None
