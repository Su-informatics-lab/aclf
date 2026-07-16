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
    """Compute the published CLIF-C ACLF score, trimmed to 0-100."""
    if not 6 <= of_score <= 18:
        raise ValueError("of_score must be between 6 and 18")
    _positive("age", age)
    _positive("wbc", wbc)
    raw = 10 * (0.33 * of_score + 0.04 * age + 0.63 * math.log(wbc) - 2)
    return round(min(100.0, max(0.0, raw)), 1)


def compute_clif_c_ad_score(
    age: float, cr: float, inr: float, wbc: float, na: float
) -> float:
    """Compute the published CLIF-C AD score, trimmed to 0-100."""
    _positive("age", age)
    _positive("creatinine", cr)
    _positive("INR", inr)
    _positive("WBC", wbc)
    _positive("sodium", na)
    raw = (
        10
        * (
            0.03 * age
            + 0.66 * math.log(cr)
            + 1.71 * math.log(inr)
            + 0.88 * math.log(wbc)
            - 0.05 * na
            + 8
        )
    )
    return round(min(100.0, max(0.0, raw)), 1)


def compute_meld(
    bilirubin: float,
    creatinine: float,
    inr: float,
    *,
    dialysis: bool = False,
) -> int:
    """Compute the original UNOS MELD used by the CANONIC-era studies."""
    for name, value in (("bilirubin", bilirubin), ("creatinine", creatinine), ("INR", inr)):
        _positive(name, value)
    bilirubin = max(1.0, float(bilirubin))
    inr = max(1.0, float(inr))
    creatinine = 4.0 if dialysis else min(4.0, max(1.0, float(creatinine)))
    raw = (
        3.78 * math.log(bilirubin)
        + 11.2 * math.log(inr)
        + 9.57 * math.log(creatinine)
        + 6.43
    )
    return min(40, max(6, int(math.floor(raw + 0.5))))


def compute_meld_na(meld: int, sodium: float) -> int:
    """Compute Kim et al. 2008 MELD-Na used by the CLIF comparator studies.

    This is the study-era equation cited by the CLIF-C AD paper, not the
    later OPTN allocation policy label. Sodium is constrained to 125-137
    mmol/L and the final score to 6-40.
    """
    if not 6 <= int(meld) <= 40:
        raise ValueError("MELD must be between 6 and 40")
    _positive("sodium", sodium)
    sodium = min(137.0, max(125.0, float(sodium)))
    raw = meld + 1.32 * (137 - sodium) - 0.033 * meld * (137 - sodium)
    return min(40, max(6, int(math.floor(raw + 0.5))))


def compute_child_pugh(
    bilirubin: float,
    albumin: float,
    inr: float,
    ascites_severity: str,
    hepatic_encephalopathy_grade: int,
) -> int:
    """Compute conventional Child-Pugh (5-15); do not impute missing inputs."""
    for name, value in (("bilirubin", bilirubin), ("albumin", albumin), ("INR", inr)):
        _positive(name, value)
    if ascites_severity not in {"none", "mild", "moderate_severe"}:
        raise ValueError("ascites_severity must be none, mild, or moderate_severe")
    if not 0 <= hepatic_encephalopathy_grade <= 4:
        raise ValueError("hepatic_encephalopathy_grade must be between 0 and 4")
    bilirubin_points = 1 if bilirubin < 2 else (2 if bilirubin <= 3 else 3)
    albumin_points = 1 if albumin > 3.5 else (2 if albumin >= 2.8 else 3)
    inr_points = 1 if inr < 1.7 else (2 if inr <= 2.3 else 3)
    ascites_points = {"none": 1, "mild": 2, "moderate_severe": 3}[ascites_severity]
    he_points = 1 if hepatic_encephalopathy_grade == 0 else (
        2 if hepatic_encephalopathy_grade <= 2 else 3
    )
    return bilirubin_points + albumin_points + inr_points + ascites_points + he_points


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


def _grade_from_complete_scores(scores: dict[str, int]) -> str:
    failed = [name for name, score in scores.items() if score == 3]
    n_fail = len(failed)
    if n_fail == 0:
        return "no_aclf"
    if n_fail == 1:
        if failed[0] == "kidney":
            return "1a"
        if scores["kidney"] == 2 or scores["brain"] == 2:
            return "1b"
        return "no_aclf"
    if n_fail == 2:
        return "2"
    if n_fail == 3:
        return "3a"
    return "3b"


def _add_comparator_scores(base: dict[str, Any], assessment: ACLFAssessment) -> None:
    bilirubin = _organ_value(assessment, "liver")
    creatinine = _organ_value(assessment, "kidney")
    inr = _organ_value(assessment, "coagulation")
    inputs = assessment.prognostic_inputs
    if bilirubin is not None and creatinine is not None and inr is not None:
        meld = compute_meld(
            float(bilirubin),
            float(creatinine),
            float(inr),
            dialysis=inputs.renal_replacement_therapy is True,
        )
        base["meld_score"] = meld
        if assessment.serum_sodium is not None:
            base["meld_na_score"] = compute_meld_na(meld, assessment.serum_sodium)
    if all(
        value is not None
        for value in (
            bilirubin,
            inr,
            inputs.serum_albumin,
            inputs.hepatic_encephalopathy_grade,
        )
    ) and inputs.ascites_severity != "unknown":
        base["child_pugh_score"] = compute_child_pugh(
            float(bilirubin),
            float(inputs.serum_albumin),
            float(inr),
            inputs.ascites_severity,
            int(inputs.hepatic_encephalopathy_grade),
        )


def score_aclf(assessment: ACLFAssessment) -> dict[str, Any]:
    """Grade ACLF from six organ assessments and compute applicable scores."""
    scores = {organ.organ: organ.clif_score for organ in assessment.organs}
    missing = [name for name, score in scores.items() if score is None]

    base: dict[str, Any] = {
        "scoring_status": "complete",
        "missing_organs": missing,
        "clif_of_score": None,
        "clif_of_score_min": None,
        "clif_of_score_max": None,
        "n_organ_failures": None,
        "n_organ_failures_min": None,
        "n_organ_failures_max": None,
        "n_organ_dysfunctions": None,
        "failed_organs": [],
        "dysfunctional_organs": [],
        "aclf_grade": "indeterminate",
        "aclf_grade_min": None,
        "aclf_grade_max": None,
        "aclf_present": None,
        "clif_c_aclf_score": None,
        "clif_c_ad_score": None,
        "meld_score": None,
        "meld_na_score": None,
        "child_pugh_score": None,
        "predicted_28d_mortality": _mortality_label("indeterminate"),
    }
    if not assessment.has_acute_decompensation:
        base.update(
            {
                "scoring_status": "not_eligible_no_acute_decompensation",
                "aclf_grade": "no_aclf",
                "aclf_grade_min": "no_aclf",
                "aclf_grade_max": "no_aclf",
                "aclf_present": False,
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
                    "clif_of_score_min": sum(typed_scores.values()),
                    "clif_of_score_max": sum(typed_scores.values()),
                    "n_organ_failures": len(failed),
                    "n_organ_failures_min": len(failed),
                    "n_organ_failures_max": len(failed),
                    "n_organ_dysfunctions": len(dysfunctional),
                    "failed_organs": failed,
                    "dysfunctional_organs": dysfunctional,
                }
            )
        _add_comparator_scores(base, assessment)
        return base
    if missing:
        base["scoring_status"] = "indeterminate_missing_organ_data"
        known = {
            name: int(score) for name, score in scores.items() if score is not None
        }
        minimum_scores = {name: int(score or 1) for name, score in scores.items()}
        maximum_scores = {name: int(score or 3) for name, score in scores.items()}
        minimum_grade = _grade_from_complete_scores(minimum_scores)
        maximum_grade = _grade_from_complete_scores(maximum_scores)
        known_failed = [name for name, score in known.items() if score == 3]
        known_dysfunctional = [name for name, score in known.items() if score == 2]
        definitely_present = minimum_grade != "no_aclf"
        possibly_present = maximum_grade != "no_aclf"
        base.update(
            {
                "clif_of_score_min": sum(minimum_scores.values()),
                "clif_of_score_max": sum(maximum_scores.values()),
                "n_organ_failures_min": len(known_failed),
                "n_organ_failures_max": len(known_failed) + len(missing),
                "failed_organs": known_failed,
                "dysfunctional_organs": known_dysfunctional,
                "aclf_grade_min": minimum_grade,
                "aclf_grade_max": maximum_grade,
                "aclf_present": True if definitely_present else (None if possibly_present else False),
                "predicted_28d_mortality": (
                    f"ACLF is definite; exact grade ranges from {minimum_grade} "
                    f"to {maximum_grade} because organ data are missing"
                    if definitely_present
                    else "ACLF presence is indeterminate because organ data are missing"
                ),
            }
        )
        _add_comparator_scores(base, assessment)
        return base

    typed_scores = {name: int(score) for name, score in scores.items() if score is not None}
    failed = [name for name, score in typed_scores.items() if score == 3]
    dysfunctional = [name for name, score in typed_scores.items() if score == 2]
    n_fail = len(failed)
    of_score = sum(typed_scores.values())

    grade = _grade_from_complete_scores(typed_scores)
    status = "complete"

    base.update(
        {
            "scoring_status": status,
            "clif_of_score": of_score,
            "clif_of_score_min": of_score,
            "clif_of_score_max": of_score,
            "n_organ_failures": n_fail,
            "n_organ_failures_min": n_fail,
            "n_organ_failures_max": n_fail,
            "n_organ_dysfunctions": len(dysfunctional),
            "failed_organs": failed,
            "dysfunctional_organs": dysfunctional,
            "aclf_grade": grade,
            "aclf_grade_min": grade,
            "aclf_grade_max": grade,
            "aclf_present": grade != "no_aclf",
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
    _add_comparator_scores(base, assessment)
    return base


__all__ = [
    "score_aclf",
    "compute_clif_c_aclf_score",
    "compute_clif_c_ad_score",
    "compute_meld",
    "compute_meld_na",
    "compute_child_pugh",
]
