from __future__ import annotations

import csv
from pathlib import Path

import duckdb

from rag.ehr import EHRBackend
from rag.tools import TOOL_DEFS, dispatch_tool
from rag.vectors import NoteStore


def build_test_db(path: Path) -> None:
    db = duckdb.connect(str(path))
    db.execute(
        """
        CREATE TABLE measurement(
            measurement_id BIGINT, person_id BIGINT, measurement_concept_id BIGINT,
            measurement_date DATE, measurement_datetime TIMESTAMP,
            value_as_number DOUBLE, unit_source_value VARCHAR,
            measurement_source_value VARCHAR, measurement_concept_name VARCHAR,
            visit_occurrence_id BIGINT
        );
        INSERT INTO measurement VALUES
          (100, 1, 3016723, '2026-01-02', '2026-01-02 08:00:00', 2.1,
           'mg/dL', '1^^256', 'Creatinine in serum', 10),
          (101, 1, 3010813, '2026-01-02', '2026-01-02 09:00:00', 8.0,
           'k/cumm', '1^^62', 'Leukocytes in blood', 10),
          (102, 1, 3010813, '2026-01-03', '2026-01-03 09:00:00', 12.0,
           'k/cumm', '1^^62', 'Leukocytes in blood', 10),
          (103, 1, 3024561, '2026-01-01', '2026-01-01 04:00:00', 3.1,
           'g/dL', '1751-7', 'Albumin in Serum or Plasma', 10),
          (104, 1, 3016723, '2026-01-02', '2026-01-02 01:00:00', 4.9,
           'mg/dL', '1^^256', 'Creatinine in serum', 10);
        CREATE TABLE drug_exposure(
            drug_exposure_id BIGINT, person_id BIGINT, drug_exposure_start_date DATE,
            drug_exposure_end_date DATE, drug_source_value VARCHAR,
            drug_concept_id BIGINT, drug_concept_name VARCHAR,
            route_source_value VARCHAR, quantity DOUBLE, visit_occurrence_id BIGINT
        );
        CREATE TABLE condition_occurrence(
            condition_occurrence_id BIGINT, person_id BIGINT, condition_start_date DATE, condition_end_date DATE,
            condition_code VARCHAR, condition_source_value VARCHAR,
            condition_concept_id BIGINT, condition_concept_name VARCHAR,
            visit_occurrence_id BIGINT
        );
        CREATE TABLE procedure_occurrence(
            procedure_occurrence_id BIGINT, person_id BIGINT, procedure_date DATE, procedure_source_value VARCHAR,
            procedure_concept_id BIGINT, procedure_concept_name VARCHAR,
            visit_occurrence_id BIGINT
        );
        CREATE TABLE visit_occurrence(
            visit_occurrence_id BIGINT, person_id BIGINT, visit_concept_id BIGINT,
            visit_start_date DATE, visit_end_date DATE,
            visit_start_datetime TIMESTAMP, visit_end_datetime TIMESTAMP,
            visit_source_value VARCHAR
        );
        INSERT INTO visit_occurrence VALUES
          (10, 1, 9201, '2026-01-01', '2026-01-05',
           '2026-01-01 01:00:00', '2026-01-05 10:00:00', 'IP');
        CREATE TABLE person(
            person_id BIGINT, year_of_birth INTEGER, gender_source_value VARCHAR,
            race_source_value VARCHAR, ethnicity_source_value VARCHAR
        );
        INSERT INTO person VALUES (1, 1960, 'F', 'Unknown', 'Unknown');
        """
    )
    db.close()


def test_verified_lab_mapping_and_episode_query(tmp_path):
    path = tmp_path / "ehr.duckdb"
    build_test_db(path)
    ehr = EHRBackend(1, path)
    try:
        labs = ehr.query_labs("creatinine")
        assert {row["value"] for row in labs} == {2.1, 4.9}
        assert {row["visit_occurrence_id"] for row in labs} == {10}
        assert ehr.inpatient_episodes()[0]["start_date"] == "2026-01-01"
        assert ehr.query_labs("creatinine", visit_occurrence_id=999) == []
        assert len(ehr.query_labs("white_blood_cells")) == 2
        core = ehr.query_labs("aclf_core", visit_occurrence_id=10)
        assert {row["core_lab"] for row in core} == {"albumin", "creatinine", "wbc"}
        assert next(row for row in core if row["core_lab"] == "wbc")["value"] == 8.0
        baseline = ehr.query_labs(
            "aclf_core",
            visit_occurrence_id=10,
            datetime_start="2026-01-01 01:00:00",
            datetime_end="2026-01-02 01:00:00",
        )
        assert {row["measurement_id"] for row in baseline} == {103}
    finally:
        ehr.close()


def test_keyword_note_fallback_preserves_id_provenance(tmp_path):
    mapping = tmp_path / "mapping.csv"
    with mapping.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["GLOBAL_PATIENT_ID", "OMOP_PERSON_ID", "HAS_AUD", "REPORT_ID"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "GLOBAL_PATIENT_ID": "2001",
                "OMOP_PERSON_ID": "1",
                "HAS_AUD": "0",
                "REPORT_ID": "3001",
            }
        )
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "3001.txt").write_text(
        "The patient had asterixis and disorientation consistent with hepatic encephalopathy.",
        encoding="utf-8",
    )
    dates = tmp_path / "note_dates.csv"
    dates.write_text("report_id,note_date,source\n3001,2026-01-02,note_text\n")
    store = NoteStore(1, mapping, [notes], note_dates_path=dates)
    result = store.search("asterixis hepatic encephalopathy", date_start="2026-01-01")
    assert result[0]["report_id"] == "3001"
    assert result[0]["global_patient_id"] == "2001"
    assert result[0]["omop_person_id"] == "1"
    assert result[0]["retrieval_method"] == "keyword"


def test_tool_contract_has_six_internal_tools_only():
    names = [item["function"]["name"] for item in TOOL_DEFS]
    assert names == [
        "search_notes",
        "query_labs",
        "query_medications",
        "query_conditions",
        "query_procedures",
        "get_extraction",
    ]
    assert "search_literature" not in names


def test_unknown_tool_returns_json_error():
    assert "Unknown tool" in dispatch_tool(object(), "not_a_tool", {})
