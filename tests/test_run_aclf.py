from __future__ import annotations

from schema import ACLFAssessment
from run_aclf import assign_split, index_exclusion_reason, summarize_llm_usage
from tests.test_schema import valid_payload


def assessment_with_status(criterion: str, status: str) -> ACLFAssessment:
    payload = valid_payload()
    payload["eligibility"][criterion]["status"] = status
    if status == "unknown":
        payload["eligibility"][criterion]["evidence_references"] = []
    elif not payload["eligibility"][criterion]["evidence_references"]:
        payload["eligibility"][criterion]["evidence_references"] = payload[
            "eligibility"
        ]["canonical_acute_decompensation"]["evidence_references"]
    return ACLFAssessment.model_validate(payload)


def test_outcome_blind_split_is_stable():
    assert assign_split(12345) == assign_split(12345)


def test_unknown_exclusion_is_retained_but_confirmed_is_excluded():
    assert index_exclusion_reason(assessment_with_status("hiv", "unknown")) is None
    assert index_exclusion_reason(assessment_with_status("hiv", "yes")) == "confirmed_hiv"


def test_non_elective_no_is_excluded():
    assert (
        index_exclusion_reason(assessment_with_status("non_elective_admission", "no"))
        == "not_non_elective"
    )


def test_llm_usage_summary_contains_counts_not_prompts():
    summary = summarize_llm_usage(
        [
            {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        ]
    )
    assert summary == {
        "api_calls_with_usage": 2,
        "prompt_tokens": 150,
        "completion_tokens": 30,
        "total_tokens": 180,
    }
