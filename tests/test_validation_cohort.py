from __future__ import annotations

import json
from datetime import date

from analysis.build_validation_cohort import (
    assign_split,
    load_frozen_assessments,
    merge_outcomes,
)
from tests.test_schema import valid_payload


def frozen_payload(pid: int, *, baseline_aclf: bool, followups: list[dict] | None = None) -> dict:
    assessment = valid_payload()
    assessment["sample_id"] = str(pid)
    scores = {
        "aclf_present": baseline_aclf,
        "aclf_grade": "1a" if baseline_aclf else "no_aclf",
        "clif_c_aclf_score": 52.0 if baseline_aclf else None,
        "clif_c_ad_score": None if baseline_aclf else 48.0,
        "meld_score": 18,
        "meld_na_score": 21,
        "child_pugh_score": 9,
    }
    return {
        "schema_version": "2.0",
        "sample_id": str(pid),
        "analysis_split": assign_split(pid),
        "assessment": assessment,
        "scores": scores,
        "screened_episodes": [
            {
                "visit_occurrence_id": 10,
                "episode_start_datetime": "2026-01-01 01:00:00",
                "exclusion_reason": None,
            }
        ],
        "retrieval_trace": [{"source_ids": ["1001", "1002"]}],
        "follow_up_assessments": followups or [],
    }


def incident_followup(day: str = "2026-03-31 01:00:00") -> dict:
    assessment = valid_payload()
    assessment["assessment_timepoint"] = "follow_up"
    assessment["visit_occurrence_id"] = 20
    assessment["episode_start_datetime"] = day
    assessment["episode_end_datetime"] = "2026-04-03 10:00:00"
    return {
        "assessment": assessment,
        "scores": {
            "aclf_present": True,
            "aclf_grade": "2",
            "clif_c_aclf_score": 61.0,
            "meld_score": 25,
            "meld_na_score": 28,
            "child_pugh_score": 12,
        },
    }


def test_split_is_stable_and_exhaustive():
    assert assign_split(101) == assign_split(101)
    assert {assign_split(pid) for pid in range(1, 100)} == {"development", "test"}


def test_frozen_loader_carries_first_incident_aclf_scores(tmp_path):
    payload = frozen_payload(101, baseline_aclf=False, followups=[incident_followup()])
    (tmp_path / "101.json").write_text(json.dumps(payload), encoding="utf-8")
    rows, flow = load_frozen_assessments(tmp_path)
    assert flow["phenotype_eligible"] == 1
    assert rows[0]["incident_aclf_date"] == "2026-03-31"
    assert rows[0]["incident_clif_c_aclf_score"] == 61.0


def test_ineligible_followup_does_not_trigger_incident_aclf(tmp_path):
    followup = incident_followup()
    followup["assessment"]["eligibility"]["prior_liver_transplant"] = {
        "status": "yes",
        "reasoning": "Prior liver transplant is documented.",
        "evidence_references": [
            {
                "source_type": "clinical_note",
                "source_id": "1002",
                "event_date": "2026-03-31",
                "description": "Prior transplant documented",
                "quote": "status post liver transplant",
            }
        ],
    }
    payload = frozen_payload(102, baseline_aclf=False, followups=[followup])
    (tmp_path / "102.json").write_text(json.dumps(payload), encoding="utf-8")
    rows, _ = load_frozen_assessments(tmp_path)
    assert rows[0]["n_followup_readmissions_90d"] == 1
    assert rows[0]["incident_aclf_date"] is None


def test_predict_trajectories_and_day90_boundary():
    rows = [
        {**load_row(201), "n_followup_readmissions_90d": 0},
        {**load_row(202), "n_followup_readmissions_90d": 1},
        {
            **load_row(203),
            "n_followup_readmissions_90d": 1,
            "incident_aclf_date": "2026-04-01",  # exactly day 90
        },
    ]
    outcomes = {
        201: {"death_date": None, "transplant_date": None},
        202: {"death_date": None, "transplant_date": None},
        203: {"death_date": None, "transplant_date": None},
    }
    merge_outcomes(rows, outcomes, date(2027, 1, 1))
    assert [row["six_group"] for row in rows] == ["SDC", "UDC", "pre-ACLF"]


def test_outcome_qc_and_transplant_competing_trajectory():
    rows = [load_row(301), load_row(302)]
    outcomes = {
        301: {"death_date": date(2025, 12, 31), "transplant_date": None},
        302: {"death_date": None, "transplant_date": date(2026, 1, 20)},
    }
    qc = merge_outcomes(rows, outcomes, date(2027, 1, 1))
    assert qc["death_before_index"] == 1
    assert rows[301 - 301]["complete_90d"] is False
    assert rows[1]["six_group"] == "trajectory_competing_transplant"


def load_row(pid: int) -> dict:
    return {
        "person_id": pid,
        "index_date": "2026-01-01",
        "baseline_group": None,
        "baseline_aclf_present": False,
        "n_followup_readmissions_90d": 0,
        "incident_aclf_date": None,
    }
