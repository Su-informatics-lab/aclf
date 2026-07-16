#!/usr/bin/env python3
"""Build a study-aligned mortality cohort after ACLF phenotypes are frozen."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "2.0"
LIVER_TRANSPLANT_CONCEPT_IDS = (2750764, 2109321)
CONFIRMED_EXCLUSIONS = (
    "scheduled_procedure_or_treatment",
    "prior_liver_transplant",
    "hcc_outside_milan",
    "hiv",
    "immunosuppression",
    "severe_extrahepatic_disease",
)


def assign_split(pid: int) -> str:
    digest = hashlib.sha256(f"aclf-v1:{int(pid)}".encode()).digest()
    return "development" if int.from_bytes(digest[:8], "big") % 10 < 7 else "test"


def _datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _days(start: date, end: date | None) -> int | None:
    return None if end is None else (end - start).days


def _collapse_grade(grade: str | None) -> str | None:
    if grade in {"1a", "1b"}:
        return "ACLF-1"
    if grade == "2":
        return "ACLF-2"
    if grade in {"3a", "3b"}:
        return "ACLF-3"
    return None


def _status(eligibility: dict[str, Any], name: str) -> str:
    return str((eligibility.get(name) or {}).get("status") or "unknown")


def _exclusion_reason(assessment: dict[str, Any]) -> str | None:
    eligibility = assessment.get("eligibility") or {}
    if _status(eligibility, "canonical_acute_decompensation") != "yes":
        return "no_confirmed_canonical_acute_decompensation"
    if _status(eligibility, "non_elective_admission") == "no":
        return "not_non_elective"
    for criterion in CONFIRMED_EXCLUSIONS:
        if _status(eligibility, criterion) == "yes":
            return f"confirmed_{criterion}"
    return None


def _baseline_contract_error(assessment: dict[str, Any]) -> str | None:
    try:
        start = _datetime(assessment.get("episode_start_datetime"))
        window_start = _datetime(assessment.get("baseline_window_start"))
        window_end = _datetime(assessment.get("baseline_window_end"))
    except ValueError:
        return "invalid_baseline_datetime"
    if not start or window_start != start or window_end != start + timedelta(hours=24):
        return "invalid_baseline_window"
    value_datetimes = [
        organ.get("peak_value_datetime")
        for organ in assessment.get("organs") or []
        if organ.get("peak_value") is not None
    ]
    value_datetimes.extend(
        [
            assessment.get("wbc_datetime") if assessment.get("wbc_count") is not None else None,
            assessment.get("sodium_datetime") if assessment.get("serum_sodium") is not None else None,
            (assessment.get("prognostic_inputs") or {}).get("albumin_datetime")
            if (assessment.get("prognostic_inputs") or {}).get("serum_albumin") is not None
            else None,
        ]
    )
    for value in value_datetimes:
        if not value:
            return "missing_baseline_value_datetime"
        try:
            parsed = _datetime(value)
        except ValueError:
            return "invalid_baseline_value_datetime"
        if parsed is None or not window_start <= parsed < window_end:
            return "baseline_value_outside_24h"
    return None


def _retrieval_contract_error(payload: dict[str, Any], assessment: dict[str, Any]) -> bool:
    allowed = {
        str(source_id)
        for trace in payload.get("retrieval_trace") or []
        for source_id in trace.get("source_ids") or []
    }
    references: list[dict[str, Any]] = list(
        assessment.get("decompensation_evidence_references") or []
    )
    for organ in assessment.get("organs") or []:
        references.extend(organ.get("evidence_references") or [])
    for precipitant in assessment.get("precipitants") or []:
        references.extend(precipitant.get("evidence_references") or [])
    references.extend(
        (assessment.get("prognostic_inputs") or {}).get("evidence_references") or []
    )
    for criterion in (assessment.get("eligibility") or {}).values():
        references.extend(criterion.get("evidence_references") or [])
    return any(
        reference.get("source_type") != "other"
        and reference.get("source_id") is not None
        and str(reference["source_id"]) not in allowed
        for reference in references
    )


def load_frozen_assessments(directory: Path) -> tuple[list[dict[str, Any]], Counter]:
    rows: list[dict[str, Any]] = []
    flow: Counter = Counter()
    seen: set[int] = set()
    for path in sorted(Path(directory).glob("*.json")):
        if path.name.endswith(".error.json"):
            continue
        flow["json_files"] += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            flow["invalid_json"] += 1
            continue
        if payload.get("schema_version") != SCHEMA_VERSION:
            flow["wrong_schema_version"] += 1
            continue
        pid = int(payload["sample_id"])
        if pid in seen:
            flow["duplicate_patient"] += 1
            continue
        seen.add(pid)
        assessment = payload.get("assessment")
        scores = payload.get("scores") or {}
        if not assessment:
            flow[payload.get("exclusion_reason") or "missing_assessment"] += 1
            continue
        screened = payload.get("screened_episodes") or []
        matching_screen = [
            item
            for item in screened
            if item.get("visit_occurrence_id") == assessment.get("visit_occurrence_id")
        ]
        if not matching_screen or matching_screen[-1].get("exclusion_reason") is not None:
            flow["first_eligible_contract_violation"] += 1
            continue
        if any(item.get("exclusion_reason") is None for item in screened[:-1]):
            flow["earlier_eligible_episode_violation"] += 1
            continue
        if baseline_error := _baseline_contract_error(assessment):
            flow[baseline_error] += 1
            continue
        if _retrieval_contract_error(payload, assessment):
            flow["unretrieved_evidence_reference"] += 1
            continue
        exclusion = _exclusion_reason(assessment)
        if exclusion:
            flow[exclusion] += 1
            continue
        index_dt = _datetime(assessment.get("episode_start_datetime"))
        if index_dt is None:
            flow["invalid_index_datetime"] += 1
            continue
        followups = payload.get("follow_up_assessments") or []
        incident_aclf: list[tuple[date, dict[str, Any]]] = []
        for item in followups:
            follow_assessment = item.get("assessment") or {}
            follow_scores = item.get("scores") or {}
            follow_dt = _datetime(follow_assessment.get("episode_start_datetime"))
            if (
                follow_dt
                and follow_scores.get("aclf_present") is True
                and _exclusion_reason(follow_assessment) is None
            ):
                incident_aclf.append((follow_dt.date(), follow_scores))
        first_incident = min(incident_aclf, key=lambda item: item[0]) if incident_aclf else None
        row = {
            "person_id": pid,
            "analysis_split": payload.get("analysis_split") or assign_split(pid),
            "visit_occurrence_id": assessment.get("visit_occurrence_id"),
            "index_datetime": index_dt.isoformat(),
            "index_date": index_dt.date().isoformat(),
            "baseline_aclf_present": scores.get("aclf_present"),
            "baseline_aclf_grade": scores.get("aclf_grade"),
            "baseline_group": _collapse_grade(scores.get("aclf_grade")),
            "clif_c_aclf_score": scores.get("clif_c_aclf_score"),
            "clif_c_ad_score": scores.get("clif_c_ad_score"),
            "meld_score": scores.get("meld_score"),
            "meld_na_score": scores.get("meld_na_score"),
            "child_pugh_score": scores.get("child_pugh_score"),
            "data_quality": assessment.get("data_quality"),
            "n_followup_readmissions_90d": len(
                payload.get("follow_up_visits_90d") or followups
            ),
            "incident_aclf_date": first_incident[0].isoformat() if first_incident else None,
            "incident_clif_c_aclf_score": (
                first_incident[1].get("clif_c_aclf_score") if first_incident else None
            ),
            "incident_meld_score": first_incident[1].get("meld_score") if first_incident else None,
            "incident_meld_na_score": (
                first_incident[1].get("meld_na_score") if first_incident else None
            ),
            "incident_child_pugh_score": (
                first_incident[1].get("child_pugh_score") if first_incident else None
            ),
            "eligibility_unknown_count": sum(
                _status(assessment.get("eligibility") or {}, criterion) == "unknown"
                for criterion in (
                    "non_elective_admission",
                    *CONFIRMED_EXCLUSIONS,
                )
            ),
        }
        rows.append(row)
        flow["phenotype_eligible"] += 1
    return rows, flow


def load_outcomes(
    ehr_db: Path, death_parquet: Path, patient_ids: list[int]
) -> dict[int, dict[str, date | None]]:
    import duckdb

    db = duckdb.connect(str(ehr_db), read_only=True)
    try:
        db.execute("SET threads=1")
        db.execute("CREATE TEMP TABLE validation_ids(person_id BIGINT)")
        db.executemany("INSERT INTO validation_ids VALUES (?)", [(pid,) for pid in patient_ids])
        deaths = dict(
            db.execute(
                """
                SELECT d.person_id, min(d.death_date)::DATE
                FROM read_parquet(?) d JOIN validation_ids v USING(person_id)
                GROUP BY d.person_id
                """,
                [str(death_parquet)],
            ).fetchall()
        )
        marks = ",".join("?" for _ in LIVER_TRANSPLANT_CONCEPT_IDS)
        transplants = dict(
            db.execute(
                f"""
                SELECT p.person_id, min(p.procedure_date)::DATE
                FROM procedure_occurrence p JOIN validation_ids v USING(person_id)
                WHERE p.procedure_concept_id IN ({marks})
                GROUP BY p.person_id
                """,
                list(LIVER_TRANSPLANT_CONCEPT_IDS),
            ).fetchall()
        )
    finally:
        db.close()
    return {
        pid: {"death_date": _date(deaths.get(pid)), "transplant_date": _date(transplants.get(pid))}
        for pid in patient_ids
    }


def merge_outcomes(
    rows: list[dict[str, Any]], outcomes: dict[int, dict[str, date | None]], cutoff: date
) -> Counter:
    qc: Counter = Counter()
    for row in rows:
        index = _date(row["index_date"])
        assert index is not None
        outcome = outcomes[row["person_id"]]
        death = outcome["death_date"]
        transplant = outcome["transplant_date"]
        row["death_date"] = death.isoformat() if death else None
        row["transplant_date"] = transplant.isoformat() if transplant else None
        row["death_before_index"] = bool(death and death < index)
        row["transplant_before_index"] = bool(transplant and transplant < index)
        row["same_day_death_transplant"] = bool(death and transplant and death == transplant)
        if row["death_before_index"]:
            qc["death_before_index"] += 1
        if row["transplant_before_index"]:
            qc["transplant_before_index"] += 1
        if row["same_day_death_transplant"]:
            qc["same_day_death_transplant"] += 1
        valid_order = not row["death_before_index"] and not row["transplant_before_index"]
        for horizon in (28, 90, 360):
            death_in_window = bool(
                valid_order and death and 0 <= (death - index).days <= horizon
            )
            transplant_in_window = bool(
                valid_order and transplant and 0 <= (transplant - index).days <= horizon
            )
            row[f"complete_{horizon}d"] = bool(
                valid_order
                and (
                    index + timedelta(days=horizon) <= cutoff
                    or death_in_window
                    or transplant_in_window
                )
            )
            row[f"death_{horizon}d"] = death_in_window
            row[f"transplant_{horizon}d"] = transplant_in_window
        incident = _date(row.get("incident_aclf_date"))
        row["incident_aclf_90d"] = bool(
            incident and valid_order and 0 <= (incident - index).days <= 90
        )
        incident_complete = bool(
            row["incident_aclf_90d"]
            and incident
            and incident + timedelta(days=28) <= cutoff
        )
        row["incident_complete_28d"] = incident_complete
        row["incident_death_28d"] = bool(
            incident_complete and death and 0 <= (death - incident).days <= 28
        )
        row["incident_transplant_28d"] = bool(
            incident_complete and transplant and 0 <= (transplant - incident).days <= 28
        )
        if row["baseline_group"]:
            row["six_group"] = row["baseline_group"]
        elif row["baseline_aclf_present"] is False:
            if not row["complete_90d"]:
                row["six_group"] = "trajectory_incomplete"
            elif row["transplant_90d"] and not row["incident_aclf_90d"]:
                row["six_group"] = "trajectory_competing_transplant"
            elif row["incident_aclf_90d"]:
                row["six_group"] = "pre-ACLF"
            elif row["n_followup_readmissions_90d"] > 0 or row["death_90d"]:
                row["six_group"] = "UDC"
            else:
                row["six_group"] = "SDC"
        else:
            row["six_group"] = "ACLF-indeterminate"
        event_dates = [(death, 1), (transplant, 2), (cutoff, 0)]
        eligible_events = [(when, code) for when, code in event_dates if when and when >= index]
        first_date, status = min(eligible_events, key=lambda item: (item[0], item[1]))
        if death and transplant and death == transplant:
            status = 0
        row["followup_days"] = min(360, max(0, (first_date - index).days))
        row["event_status_360"] = status if row["followup_days"] <= 360 else 0
        if (first_date - index).days > 360:
            row["followup_days"] = 360
            row["event_status_360"] = 0
        if row["six_group"] in {"SDC", "UDC", "pre-ACLF"} and valid_order:
            landmark = index + timedelta(days=90)
            if death and death <= landmark or transplant and transplant <= landmark:
                row["landmark_eligible"] = False
                row["landmark_followup_days"] = None
                row["landmark_event_status"] = None
            else:
                row["landmark_eligible"] = cutoff >= landmark
                row["landmark_followup_days"] = min(270, max(0, (first_date - landmark).days))
                row["landmark_event_status"] = status if first_date <= index + timedelta(days=360) else 0
        else:
            row["landmark_eligible"] = False
            row["landmark_followup_days"] = None
            row["landmark_event_status"] = None
    return qc


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(args: argparse.Namespace) -> None:
    rows, flow = load_frozen_assessments(args.assessments)
    outcomes = load_outcomes(args.ehr_db, args.death_parquet, [row["person_id"] for row in rows])
    cutoff = date.fromisoformat(args.admin_censor_date)
    qc = merge_outcomes(rows, outcomes, cutoff)
    for key in ("death_before_index", "transplant_before_index", "same_day_death_transplant"):
        qc.setdefault(key, 0)
    qc["incomplete_90d_followup"] = sum(not row["complete_90d"] for row in rows)
    qc["incomplete_360d_followup"] = sum(not row["complete_360d"] for row in rows)
    qc["trajectory_incomplete_or_competing"] = sum(
        str(row.get("six_group", "")).startswith("trajectory_") for row in rows
    )
    qc["eligibility_with_unknown_criteria"] = sum(
        row.get("eligibility_unknown_count", 0) > 0 for row in rows
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "patient_level.csv", rows)
    write_csv(
        args.output_dir / "cohort_flow.csv",
        [{"reason": key, "n": value} for key, value in sorted(flow.items())],
        ["reason", "n"],
    )
    write_csv(
        args.output_dir / "qc_counts.csv",
        [{"check": key, "n": value} for key, value in sorted(qc.items())],
        ["check", "n"],
    )
    score_names = (
        "clif_c_aclf_score",
        "clif_c_ad_score",
        "meld_score",
        "meld_na_score",
        "child_pugh_score",
    )
    write_csv(
        args.output_dir / "score_completeness.csv",
        [
            {
                "score": score,
                "available": sum(row.get(score) not in (None, "") for row in rows),
                "missing": sum(row.get(score) in (None, "") for row in rows),
                "eligible_total": len(rows),
            }
            for score in score_names
        ],
        ["score", "available", "missing", "eligible_total"],
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "admin_censor_date": cutoff.isoformat(),
        "death_source": 'OMOP death_type 38003569: EHR record patient status "Deceased"',
        "death_was_hidden_from_phenotyping": True,
        "liver_transplant_concept_ids": list(LIVER_TRANSPLANT_CONCEPT_IDS),
        "n_rows": len(rows),
        "analysis_split": "sha256(aclf-v1:person_id), modulo 10; 0-6 development, 7-9 test",
        "meld_na_formula": "Kim WR et al., NEJM 2008; sodium constrained 125-137; score 6-40",
        "baseline_window": "[visit_start_datetime, visit_start_datetime + 24 hours)",
        "index_selection": "first chronological phenotype-eligible inpatient episode",
    }
    (args.output_dir / "analysis_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assessments", type=Path, required=True)
    parser.add_argument("--ehr-db", type=Path, required=True)
    parser.add_argument("--death-parquet", type=Path, required=True)
    parser.add_argument("--admin-censor-date", default="2023-07-10")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    build(parse_args(argv))


if __name__ == "__main__":
    main()
