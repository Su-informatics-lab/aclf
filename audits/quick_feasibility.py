#!/usr/bin/env python3
"""Fast, aggregate-only feasibility checks for notes and ACLF structured inputs."""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path


NOTE_PATTERNS = {
    "discharge_summary": (r"\bdischarge summary\b", r"\bdischarge diagnoses?\b"),
    "history_and_physical": (r"\bhistory and physical\b", r"\badmission history\b"),
    "progress_note": (r"\bprogress note\b", r"\bdaily progress\b"),
    "consult_note": (r"\bconsult(?:ation)? note\b",),
    "operative_or_procedure_note": (r"\boperative note\b", r"\bprocedure note\b"),
    "radiology_report": (r"\bradiology report\b",),
    "pathology_report": (r"\bpathology report\b",),
}


def note_check(mapping: Path, note_dates: Path, note_dirs: list[Path], seed: int) -> dict:
    dated = set()
    with note_dates.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("note_date") or "").strip():
                dated.add((row.get("report_id") or "").strip())

    by_person: dict[str, list[str]] = defaultdict(list)
    with mapping.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            pid = (row.get("OMOP_PERSON_ID") or "").strip()
            report_id = (row.get("REPORT_ID") or "").strip()
            if pid and report_id:
                by_person[pid].append(report_id)

    chosen = random.Random(seed).sample(sorted(by_person), 3)
    patients = []
    overall = Counter()
    for alias, pid in zip(("A", "B", "C"), chosen, strict=True):
        found = 0
        labels = Counter()
        for report_id in by_person[pid]:
            path = next(
                (directory / f"{report_id}.txt" for directory in note_dirs
                 if (directory / f"{report_id}.txt").exists()),
                None,
            )
            if path is None:
                continue
            found += 1
            # This is intentionally a quick title/header check, not NLP classification.
            header = path.read_text(encoding="utf-8", errors="replace")[:6000].lower()
            for label, patterns in NOTE_PATTERNS.items():
                if any(re.search(pattern, header) for pattern in patterns):
                    labels[label] += 1
                    overall[label] += 1
        patients.append(
            {
                "alias": alias,
                "mapped_notes": len(by_person[pid]),
                "files_found": found,
                "dated_notes": sum(rid in dated for rid in by_person[pid]),
                "explicit_header_matches": dict(sorted(labels.items())),
            }
        )
    return {
        "design": "fixed-seed random three-patient sanity check; not a coverage estimate",
        "seed": seed,
        "patients": patients,
        "overall_explicit_header_matches": dict(sorted(overall.items())),
    }


def load_targets(output_dir: Path) -> list[tuple[int, int, str, str]]:
    targets = []
    for path in output_dir.glob("*.json"):
        if path.name.endswith(".error.json"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        assessment = payload.get("assessment")
        if not assessment:
            continue
        start = assessment["baseline_window_start"]
        end = assessment["baseline_window_end"]
        targets.append(
            (int(payload["sample_id"]), int(assessment["visit_occurrence_id"]), start, end)
        )
    return targets


def structured_check(ehr_db: Path, raw_dir: Path, output_dir: Path) -> dict:
    import duckdb

    targets = load_targets(output_dir)
    db = duckdb.connect()
    db.execute("SET threads=1")
    db.execute("SET preserve_insertion_order=false")
    db.execute(f"ATTACH '{ehr_db}' AS ehr (READ_ONLY)")
    db.execute(
        "CREATE TEMP TABLE targets(person_id BIGINT, visit_occurrence_id BIGINT, "
        "window_start TIMESTAMP, window_end TIMESTAMP)"
    )
    db.executemany("INSERT INTO targets VALUES (?, ?, ?, ?)", targets)

    def scalar(sql: str, params: list[str] | None = None) -> int:
        return int(db.execute(sql, params or []).fetchone()[0])

    concept_groups = {
        "bilirubin": (3024128,),
        "creatinine": (3016723, 3051825),
        "inr": (3022217, 3032080),
        "pao2": (3027801, 3027315, 3013702),
        "fio2": (3024882,),
        "spo2": (40762499, 3016502, 3013502, 3011367),
    }
    coverage: dict[str, int] = {}
    for label, concept_ids in concept_groups.items():
        marks = ",".join("?" for _ in concept_ids)
        coverage[label] = scalar(
            f"""
            SELECT count(DISTINCT t.visit_occurrence_id)
            FROM targets t JOIN ehr.measurement m
              ON m.person_id=t.person_id
             AND m.visit_occurrence_id=t.visit_occurrence_id
             AND m.measurement_datetime>=t.window_start
             AND m.measurement_datetime<t.window_end
            WHERE m.measurement_concept_id IN ({marks})
              AND m.value_as_number IS NOT NULL
            """,
            list(concept_ids),
        )

    concept_file = str(raw_dir / "concept.parquet")
    visit_detail_file = str(raw_dir / "visit_detail.parquet")
    drug_file = str(raw_dir / "drug_exposure.parquet")
    procedure_file = str(raw_dir / "procedure_ocurrence.parquet")
    device_file = str(raw_dir / "device_exposure.parquet")
    observation_file = str(raw_dir / "observation.parquet")
    cost_file = str(raw_dir / "cost.parquet")

    coverage["any_visit_detail"] = scalar(
        """
        SELECT count(DISTINCT t.visit_occurrence_id)
        FROM targets t JOIN read_parquet(?) v
          ON v.person_id=t.person_id AND v.visit_occurrence_id=t.visit_occurrence_id
        """,
        [visit_detail_file],
    )

    def named_event(table_file: str, concept_column: str, source_column: str,
                    datetime_column: str, pattern: str) -> int:
        return scalar(
            f"""
            SELECT count(DISTINCT t.visit_occurrence_id)
            FROM targets t JOIN read_parquet(?) x
              ON x.person_id=t.person_id AND x.visit_occurrence_id=t.visit_occurrence_id
             AND x.{datetime_column}>=t.window_start AND x.{datetime_column}<t.window_end
            LEFT JOIN read_parquet(?) c ON x.{concept_column}=c.concept_id
            WHERE regexp_matches(lower(coalesce(x.{source_column}, '') || ' ' ||
                  coalesce(c.concept_name, '')), ?)
            """,
            [table_file, concept_file, pattern],
        )

    coverage["vasopressor_datetime"] = named_event(
        drug_file, "drug_concept_id", "drug_source_value", "drug_exposure_start_datetime",
        "norepinephrine|noradrenaline|vasopressin|epinephrine|phenylephrine|dopamine|terlipressin",
    )
    coverage["dialysis_or_crrt_procedure_datetime"] = named_event(
        procedure_file, "procedure_concept_id", "procedure_source_value", "procedure_datetime",
        "dialysis|hemodialysis|haemodialysis|crrt|continuous renal replacement|hemofiltration",
    )
    coverage["ventilation_procedure_datetime"] = named_event(
        procedure_file, "procedure_concept_id", "procedure_source_value", "procedure_datetime",
        "mechanical ventilation|ventilator|intubation|endotracheal",
    )
    coverage["ventilation_device_datetime"] = named_event(
        device_file, "device_concept_id", "device_source_value", "device_exposure_start_datetime",
        "ventilator|mechanical ventilation|endotracheal",
    )
    coverage["gcs_or_consciousness_observation_datetime"] = named_event(
        observation_file, "observation_concept_id", "observation_source_value", "observation_datetime",
        "glasgow|gcs|consciousness|mental status|encephalopathy",
    )
    coverage["revenue_code_present"] = scalar(
        """
        SELECT count(DISTINCT t.visit_occurrence_id)
        FROM targets t JOIN read_parquet(?) c ON c.cost_event_id=t.visit_occurrence_id
        WHERE c.revenue_code_concept_id IS NOT NULL
           OR nullif(trim(c.revenue_code_source_value), '') IS NOT NULL
        """,
        [cost_file],
    )
    return {
        "design": "fast feasibility scan over the current successful 100-patient pilot assessments",
        "target_assessments": len(targets),
        "visits_with_signal_in_first_24h": coverage,
        "important_current_builder_omissions": [
            "visit_detail", "device_exposure", "observation", "cost/revenue_code",
            "drug_exposure_start_datetime", "procedure_datetime", "visit_detail_id",
        ],
        "warning": "Regex concept probes are feasibility signals, not validated phenotype definitions.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--note-dates", type=Path, required=True)
    parser.add_argument("--notes-dir", type=Path, action="append", required=True)
    parser.add_argument("--ehr-db", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260716)
    args = parser.parse_args()
    result = {
        "notes": note_check(args.mapping, args.note_dates, args.notes_dir, args.seed),
        "structured": structured_check(args.ehr_db, args.raw_dir, args.output_dir),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
