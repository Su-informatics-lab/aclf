#!/usr/bin/env python3
"""Validate ACLF outputs, provenance completeness, and deterministic rescoring."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from schema import ACLFAssessment
from scoring import score_aclf


def validate_output(path: Path) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"invalid JSON: {exc}"], None
    try:
        assessment = ACLFAssessment.model_validate(payload.get("assessment"))
    except Exception as exc:
        return [f"invalid assessment: {exc}"], payload
    if str(payload.get("sample_id")) != assessment.sample_id:
        errors.append("top-level sample_id differs from assessment.sample_id")
    rescored = score_aclf(assessment)
    if payload.get("scores") != rescored:
        errors.append("saved deterministic scores differ from fresh score_aclf output")
    provenance = payload.get("provenance") or {}
    note_provenance = provenance.get("note_provenance") or {}
    if note_provenance.get("omop_person_id") != assessment.sample_id:
        errors.append("note provenance OMOP ID differs from assessment sample_id")
    episodes = provenance.get("inpatient_episodes") or []
    episode_pairs = {
        (str(item.get("start_date"))[:10], str(item.get("end_date"))[:10])
        for item in episodes
        if item.get("start_date") and item.get("end_date")
    }
    if episode_pairs and (
        assessment.episode_start_date,
        assessment.episode_end_date,
    ) not in episode_pairs:
        errors.append("assessment episode does not match a provenance inpatient episode")
    trace = payload.get("retrieval_trace")
    if not isinstance(trace, list) or not trace:
        errors.append("retrieval_trace is missing or empty")
    for organ in assessment.organs:
        if organ.clif_score is not None and not organ.evidence_references:
            errors.append(f"{organ.organ}: scored without evidence references")
        for reference in organ.evidence_references:
            if reference.source_type == "clinical_note" and not reference.source_id:
                errors.append(f"{organ.organ}: note evidence lacks report_id")
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
    missing: Counter[str] = Counter()
    failures: dict[str, list[str]] = {}
    for path in files:
        errors, payload = validate_output(path)
        if errors:
            failures[path.name] = errors
            continue
        assert payload is not None
        scores = payload["scores"]
        assessment = payload["assessment"]
        grades[scores["aclf_grade"]] += 1
        statuses[scores["scoring_status"]] += 1
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
        "data_quality": dict(quality),
        "missing_organs": dict(missing),
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
