#!/usr/bin/env python3
"""Validate ACLF outputs, provenance completeness, and deterministic rescoring."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from schema import ACLFAssessment
from scoring import score_aclf


def _parse_datetime(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _validate_assessment(
    assessment_payload: dict[str, Any],
    saved_scores: dict[str, Any],
    episodes: list[dict[str, Any]],
    retrieved_ids: set[str],
) -> tuple[list[str], ACLFAssessment | None]:
    errors: list[str] = []
    try:
        assessment = ACLFAssessment.model_validate(assessment_payload)
    except Exception as exc:
        return [f"invalid assessment: {exc}"], None
    rescored = score_aclf(assessment)
    if saved_scores != rescored:
        errors.append("saved deterministic scores differ from fresh score_aclf output")
    episode_by_id = {
        int(item["visit_occurrence_id"]): item
        for item in episodes
        if item.get("visit_occurrence_id") is not None
    }
    episode = episode_by_id.get(assessment.visit_occurrence_id)
    if episode_by_id and episode is None:
        errors.append("assessment visit_occurrence_id is absent from provenance")
    elif episode is not None:
        expected = (
            _parse_datetime(episode.get("start_datetime")),
            _parse_datetime(episode.get("end_datetime")),
        )
        observed = (
            _parse_datetime(assessment.episode_start_datetime),
            _parse_datetime(assessment.episode_end_datetime),
        )
        if observed != expected:
            errors.append("assessment datetimes differ from provenance inpatient episode")
    references = list(assessment.decompensation_evidence_references)
    references.extend(
        reference for organ in assessment.organs for reference in organ.evidence_references
    )
    references.extend(
        reference
        for precipitant in assessment.precipitants
        for reference in precipitant.evidence_references
    )
    references.extend(assessment.prognostic_inputs.evidence_references)
    for criterion in type(assessment.eligibility).model_fields:
        references.extend(getattr(assessment.eligibility, criterion).evidence_references)
    unsupported = sorted(
        {
            str(reference.source_id)
            for reference in references
            if reference.source_id is not None
            and reference.source_type != "other"
            and str(reference.source_id) not in retrieved_ids
        }
    )
    if unsupported:
        errors.append("evidence IDs absent from retrieval_trace: " + ", ".join(unsupported))
    return errors, assessment


def validate_output(path: Path) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"invalid JSON: {exc}"], None
    if payload.get("schema_version") != "2.0":
        errors.append("schema_version is not 2.0")
    if payload.get("outcome_blinded") is not True:
        errors.append("outcome_blinded must be true")
    if payload.get("assessment") is None:
        if not payload.get("exclusion_reason"):
            errors.append("missing assessment requires exclusion_reason")
        return errors, payload
    assessment_payload = payload["assessment"]
    provenance = payload.get("provenance") or {}
    note_provenance = provenance.get("note_provenance") or {}
    episodes = provenance.get("inpatient_episodes") or []
    trace = payload.get("retrieval_trace")
    if not isinstance(trace, list) or not trace:
        errors.append("retrieval_trace is missing or empty")
    retrieved_ids = {
        str(source_id)
        for item in (trace or [])
        if isinstance(item, dict)
        for source_id in (item.get("source_ids") or [])
    }
    assessment_errors, assessment = _validate_assessment(
        assessment_payload, payload.get("scores") or {}, episodes, retrieved_ids
    )
    errors.extend(assessment_errors)
    if assessment is None:
        return errors, payload
    if str(payload.get("sample_id")) != assessment.sample_id:
        errors.append("top-level sample_id differs from assessment.sample_id")
    if note_provenance.get("omop_person_id") != assessment.sample_id:
        errors.append("note provenance OMOP ID differs from assessment sample_id")
    seen_visits = {assessment.visit_occurrence_id}
    for index, followup in enumerate(payload.get("follow_up_assessments") or []):
        follow_errors, follow_assessment = _validate_assessment(
            followup.get("assessment") or {},
            followup.get("scores") or {},
            episodes,
            retrieved_ids,
        )
        errors.extend(f"follow_up[{index}]: {error}" for error in follow_errors)
        if follow_assessment:
            if follow_assessment.assessment_timepoint != "follow_up":
                errors.append(f"follow_up[{index}]: assessment_timepoint must be follow_up")
            if follow_assessment.visit_occurrence_id in seen_visits:
                errors.append(f"follow_up[{index}]: duplicate visit_occurrence_id")
            seen_visits.add(follow_assessment.visit_occurrence_id)
    return errors, payload


def summarize(output_dir: Path) -> tuple[dict[str, Any], int]:
    files = sorted(
        path
        for path in Path(output_dir).glob("*.json")
        if not path.name.endswith(".error.json")
    )
    grades: Counter[str] = Counter()
    quality: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    presence: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    exclusions: Counter[str] = Counter()
    failures: dict[str, list[str]] = {}
    for path in files:
        errors, payload = validate_output(path)
        if errors:
            failures[path.name] = errors
            continue
        assert payload is not None
        if payload.get("assessment") is None:
            exclusions[payload.get("exclusion_reason") or "unknown"] += 1
            continue
        scores = payload["scores"]
        assessment = payload["assessment"]
        grades[scores["aclf_grade"]] += 1
        statuses[scores["scoring_status"]] += 1
        value = scores.get("aclf_present")
        presence["indeterminate" if value is None else str(value).lower()] += 1
        quality[assessment["data_quality"]] += 1
        missing.update(scores.get("missing_organs") or [])
    error_files = list(Path(output_dir).glob("*.error.json"))
    summary = {
        "output_dir": str(output_dir),
        "n_outputs": len(files),
        "n_valid": len(files) - len(failures),
        "n_invalid": len(failures),
        "n_runtime_errors": len(error_files),
        "aclf_grades": dict(grades),
        "scoring_status": dict(statuses),
        "aclf_presence": dict(presence),
        "data_quality": dict(quality),
        "missing_organs": dict(missing),
        "exclusions": dict(exclusions),
        "validation_failures": failures,
        "runtime_error_files": [path.name for path in error_files],
    }
    return summary, len(failures) + len(error_files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    summary, n_errors = summarize(args.output_dir)
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    print(text)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(text + "\n", encoding="utf-8")
    if n_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
