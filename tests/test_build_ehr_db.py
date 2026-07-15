from __future__ import annotations

from pathlib import Path

import duckdb

from rag.build_ehr_db import build_database
from rag.ehr import EHRBackend


def write_parquet(db, directory: Path, table: str, filename: str | None = None):
    path = directory / (filename or f"{table}.parquet")
    db.execute(f"COPY {table} TO '{path}' (FORMAT PARQUET)")


def test_build_filtered_ehr_database_with_v1_procedure_typo(tmp_path):
    raw = tmp_path / "parquet"
    raw.mkdir()
    source = duckdb.connect()
    source.execute(
        """
        CREATE TABLE person AS SELECT 1::BIGINT person_id, 1960 year_of_birth,
          'F'::VARCHAR gender_source_value, 'Unknown'::VARCHAR race_source_value,
          'Unknown'::VARCHAR ethnicity_source_value;
        CREATE TABLE visit_occurrence AS SELECT 10::BIGINT visit_occurrence_id,
          1::BIGINT person_id, 9201::BIGINT visit_concept_id,
          DATE '2026-01-01' visit_start_date, TIMESTAMP '2026-01-01' visit_start_datetime,
          DATE '2026-01-05' visit_end_date, TIMESTAMP '2026-01-05' visit_end_datetime,
          'IP'::VARCHAR visit_source_value;
        CREATE TABLE measurement AS SELECT 100::BIGINT measurement_id,
          1::BIGINT person_id, 3016723::BIGINT measurement_concept_id,
          DATE '2026-01-02' measurement_date, TIMESTAMP '2026-01-02 08:00' measurement_datetime,
          2.1::DOUBLE value_as_number, 'mg/dL'::VARCHAR unit_source_value,
          '1^^256'::VARCHAR measurement_source_value, 10::BIGINT visit_occurrence_id;
        CREATE TABLE drug_exposure AS SELECT 200::BIGINT drug_exposure_id,
          1::BIGINT person_id, 111::BIGINT drug_concept_id,
          DATE '2026-01-02' drug_exposure_start_date,
          DATE '2026-01-03' drug_exposure_end_date, 'norepinephrine'::VARCHAR drug_source_value,
          'IV'::VARCHAR route_source_value, 1::DOUBLE quantity,
          10::BIGINT visit_occurrence_id;
        CREATE TABLE condition_occurrence AS SELECT 300::BIGINT condition_occurrence_id,
          1::BIGINT person_id, 222::BIGINT condition_concept_id,
          DATE '2026-01-01' condition_start_date, DATE '2026-01-05' condition_end_date,
          'SITE^^K7460^'::VARCHAR condition_source_value, 10::BIGINT visit_occurrence_id;
        CREATE TABLE procedure_ocurrence AS SELECT 400::BIGINT procedure_occurrence_id,
          1::BIGINT person_id, 333::BIGINT procedure_concept_id,
          DATE '2026-01-02' procedure_date, '90935'::VARCHAR procedure_source_value,
          10::BIGINT visit_occurrence_id;
        CREATE TABLE concept(concept_id BIGINT, concept_name VARCHAR);
        INSERT INTO concept VALUES
          (3016723, 'Creatinine in serum'), (111, 'Norepinephrine'),
          (222, 'Cirrhosis'), (333, 'Hemodialysis');
        """
    )
    for table in (
        "person", "visit_occurrence", "measurement", "drug_exposure",
        "condition_occurrence", "concept",
    ):
        write_parquet(source, raw, table)
    write_parquet(source, raw, "procedure_ocurrence")
    source.close()

    roster = tmp_path / "roster.csv"
    roster.write_text("omop_person_id\n1\n", encoding="utf-8")
    output = tmp_path / "ehr.duckdb"
    build_database(raw, roster, output, overwrite=False)

    ehr = EHRBackend(1, output)
    try:
        assert ehr.query_labs("creatinine")[0]["measurement_id"] == 100
        assert ehr.query_conditions("K74")[0]["code"] == "K7460"
        assert ehr.query_procedures("hemodialysis")[0]["procedure_occurrence_id"] == 400
    finally:
        ehr.close()
