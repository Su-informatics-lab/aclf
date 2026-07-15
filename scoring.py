"""Deterministic EASL-CLIF-C scoring; no LLM calls occur here."""

from __future__ import annotations

import math
from typing import Any

from schema import ACLFAssessment


def _positive(name: str, value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and > 0")
    return value


def compute_clif_c_aclf_score(of_score: int, age: float, wbc: float) -> float:
    """Compute the CLIF-C ACLF prognostic score and round to one decimal."""
    if not 6 <= of_score <= 18:
        raise ValueError("of_score must be between 6 and 18")
    _positive("age", age)
    _positive("wbc", wbc)
    return round(10 * (0.33 * of_score + 0.04 * age + 0.63 * math.log(wbc) - 2), 1)


def compute_clif_c_ad_score(
    age: float, cr: float, inr: float, wbc: float, na: float
) -> float:
    """Compute the CLIF-C AD prognostic score and round to one decimal."""
    _positive("age", age)
    _positive("creatinine", cr)
    _positive("INR", inr)
    _positive("WBC", wbc)
    _positive("sodium", na)
    return round(
        10
        * (
            0.03 * age
            + 0.66 * math.log(cr)
            + 1.71 * math.log(inr)
            + 0.88 * math.log(wbc)
            - 0.05 * na
            + 8
        ),
        1,
    )


def _organ_value(assessment: ACLFAssessment, name: str) -> float | None:
    for organ in assessment.organs:
        if organ.organ == name:
            return organ.peak_value
    return None


def _mortality_label(grade: str) -> str:
    return {
        "no_aclf": "approximately 5% 28-day mortality",
        "1a": "approximately 22% 28-day mortality",
        "1b": "approximately 22% 28-day mortality",
        "2": "approximately 32% 28-day mortality",
        "3a": "approximately 73-79% 28-day mortality",
        "3b": "approximately 73-79% 28-day mortality",
        "indeterminate": "indeterminate because one or more organ scores are missing",
    }[grade]


def score_aclf(assessment: ACLFAssessment) -> dict[str, Any]:
    """Grade ACLF from six organ assessments and compute applicable scores."""
    scores = {organ.organ: organ.clif_score for organ in assessment.organs}
    missing = [name for name, score in scores.items() if score is None]

    base: dict[str, Any] = {
        "scoring_status": "complete",
        "missing_organs": missing,
        "clif_of_score": None,
        "n_organ_failures": None,
        "n_organ_dysfunctions": None,
        "failed_organs": [],
        "dysfunctional_organs": [],
        "aclf_grade": "indeterminate",
        "clif_c_aclf_score": None,
        "clif_c_ad_score": None,
        "predicted_28d_mortality": _mortality_label("indeterminate"),
    }
    if not assessment.has_acute_decompensation:
        base.update(
            {
                "scoring_status": "not_eligible_no_acute_decompensation",
                "aclf_grade": "no_aclf",
                "predicted_28d_mortality": (
                    "not applicable: no qualifying acute decompensation"
                ),
            }
        )
        if not missing:
            typed_scores = {
                name: int(score) for name, score in scores.items() if score is not None
            }
            failed = [name for name, score in typed_scores.items() if score == 3]
            dysfunctional = [name for name, score in typed_scores.items() if score == 2]
            base.update(
                {
                    "clif_of_score": sum(typed_scores.values()),
                    "n_organ_failures": len(failed),
                    "n_organ_dysfunctions": len(dysfunctional),
                    "failed_organs": failed,
                    "dysfunctional_organs": dysfunctional,
                }
            )
        return base
    if missing:
        base["scoring_status"] = "indeterminate_missing_organ_data"
        return base

    typed_scores = {name: int(score) for name, score in scores.items() if score is not None}
    failed = [name for name, score in typed_scores.items() if score == 3]
    dysfunctional = [name for name, score in typed_scores.items() if score == 2]
    n_fail = len(failed)
    of_score = sum(typed_scores.values())

    if n_fail == 0:
        grade = "no_aclf"
        status = "complete"
    elif n_fail == 1:
        if failed[0] == "kidney":
            grade = "1a"
        elif typed_scores["kidney"] == 2 or typed_scores["brain"] == 2:
            grade = "1b"
        else:
            grade = "no_aclf"
        status = "complete"
    elif n_fail == 2:
        grade, status = "2", "complete"
    elif n_fail == 3:
        grade, status = "3a", "complete"
    else:
        grade, status = "3b", "complete"

    base.update(
        {
            "scoring_status": status,
            "clif_of_score": of_score,
            "n_organ_failures": n_fail,
            "n_organ_dysfunctions": len(dysfunctional),
            "failed_organs": failed,
            "dysfunctional_organs": dysfunctional,
            "aclf_grade": grade,
            "predicted_28d_mortality": _mortality_label(grade),
        }
    )

    if grade != "no_aclf":
        if assessment.age_years is not None and assessment.wbc_count is not None:
            base["clif_c_aclf_score"] = compute_clif_c_aclf_score(
                of_score, assessment.age_years, assessment.wbc_count
            )
    else:
        cr = _organ_value(assessment, "kidney")
        inr = _organ_value(assessment, "coagulation")
        if all(
            value is not None
            for value in (
                assessment.age_years,
                cr,
                inr,
                assessment.wbc_count,
                assessment.serum_sodium,
            )
        ):
            base["clif_c_ad_score"] = compute_clif_c_ad_score(
                float(assessment.age_years),
                float(cr),
                float(inr),
                float(assessment.wbc_count),
                float(assessment.serum_sodium),
            )
    return base


__all__ = ["score_aclf", "compute_clif_c_aclf_score", "compute_clif_c_ad_score"]
