#!/usr/bin/env python3
"""Build a roster-filtered, provenance-preserving DuckDB from OMOP v1 parquet."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _id_column(header: list[str]) -> str:
    for candidate in ("omop_person_id", "OMOP_PERSON_ID", "person_id"):
        if candidate in header:
            return candidate
    raise ValueError(f"Roster has no recognized OMOP ID column: {header}")


def build_database(data_dir: Path, roster: Path, output: Path, overwrite: bool) -> None:
    import csv
    import duckdb

    data_dir, roster, output = Path(data_dir), Path(roster), Path(output)
    if output.exists():
        if not overwrite:
            raise FileExistsError(f"Output exists; pass --overwrite: {output}")
        output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    with roster.open(encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle))
    id_col = _id_column(header)

    procedure_file = data_dir / "procedure_occurrence.parquet"
    if not procedure_file.exists():
        procedure_file = data_dir / "procedure_ocurrence.parquet"
    required = {
        "person": data_dir / "person.parquet",
        "visit_occurrence": data_dir / "visit_occurrence.parquet",
        "measurement": data_dir / "measurement.parquet",
        "drug_exposure": data_dir / "drug_exposure.parquet",
        "condition_occurrence": data_dir / "condition_occurrence.parquet",
        "procedure_occurrence": procedure_file,
        "concept": data_dir / "concept.parquet",
    }
    missing = [str(path) for path in required.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing OMOP files: " + ", ".join(missing))

    db = duckdb.connect(str(output))
    try:
        db.execute("PRAGMA threads=4")
        db.execute(
            f"""
            CREATE TABLE roster AS
            SELECT DISTINCT CAST({id_col} AS BIGINT) AS person_id
            FROM read_csv_auto(?)
            WHERE {id_col} IS NOT NULL
            """,
            [str(roster)],
        )
        logger.info("Roster: %d patients", db.execute("SELECT count(*) FROM roster").fetchone()[0])

        db.execute(
            """
            CREATE TABLE person AS
            SELECT p.person_id, p.year_of_birth, p.gender_source_value,
                   p.race_source_value, p.ethnicity_source_value
            FROM read_parquet(?) p JOIN roster r USING (person_id)
            """,
            [str(required["person"])],
        )
        db.execute(
            """
            CREATE TABLE visit_occurrence AS
            SELECT v.visit_occurrence_id, v.person_id, v.visit_concept_id,
                   v.visit_start_date, v.visit_start_datetime, v.visit_end_date,
                   v.visit_end_datetime, v.visit_source_value
            FROM read_parquet(?) v JOIN roster r USING (person_id)
            """,
            [str(required["visit_occurrence"])],
        )

        db.execute(
            """
            CREATE TEMP TABLE measurement_base AS
            SELECT m.measurement_id, m.person_id, m.measurement_concept_id,
                   m.measurement_date, m.measurement_datetime, m.value_as_number,
                   m.unit_source_value, m.measurement_source_value,
                   m.visit_occurrence_id
            FROM read_parquet(?) m JOIN roster r USING (person_id)
            """,
            [str(required["measurement"])],
        )
        db.execute(
            """
            CREATE TABLE measurement AS
            SELECT m.*, c.concept_name AS measurement_concept_name
            FROM measurement_base m LEFT JOIN read_parquet(?) c
              ON m.measurement_concept_id = c.concept_id
            """,
            [str(required["concept"])],
        )

        for table, id_name, date_columns, source_column in (
            (
                "drug_exposure",
                "drug_concept_id",
                "drug_exposure_id, person_id, drug_concept_id, drug_exposure_start_date, "
                "drug_exposure_end_date, drug_source_value, route_source_value, quantity, visit_occurrence_id",
                "drug_concept_name",
            ),
            (
                "condition_occurrence",
                "condition_concept_id",
                "condition_occurrence_id, person_id, condition_concept_id, condition_start_date, "
                "condition_end_date, condition_source_value, visit_occurrence_id",
                "condition_concept_name",
            ),
            (
                "procedure_occurrence",
                "procedure_concept_id",
                "procedure_occurrence_id, person_id, procedure_concept_id, procedure_date, "
                "procedure_source_value, visit_occurrence_id",
                "procedure_concept_name",
            ),
        ):
            source_path = required[table]
            db.execute(
                f"""
                CREATE TEMP TABLE {table}_base AS
                SELECT {date_columns}
                FROM read_parquet(?) x JOIN roster r USING (person_id)
                """,
                [str(source_path)],
            )
            db.execute(
                f"""
                CREATE TABLE {table} AS
                SELECT x.*, c.concept_name AS {source_column}
                FROM {table}_base x LEFT JOIN read_parquet(?) c
                  ON x.{id_name} = c.concept_id
                """,
                [str(required["concept"])],
            )

        db.execute(
            """
            ALTER TABLE condition_occurrence ADD COLUMN condition_code VARCHAR;
            UPDATE condition_occurrence
            SET condition_code = upper(replace(
                regexp_extract(condition_source_value, '\\^\\^([^\\^]+)', 1), '.', ''
            ));
            """
        )
        for table in (
            "person", "visit_occurrence", "measurement", "drug_exposure",
            "condition_occurrence", "procedure_occurrence",
        ):
            db.execute(f"CREATE INDEX idx_{table}_pid ON {table}(person_id)")
            count = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            logger.info("%s: %d rows", table, count)
    finally:
        db.close()
    logger.info("Wrote %s (%.1f MiB)", output, output.stat().st_size / 1024**2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/ehr.duckdb"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build_database(args.data_dir, args.roster, args.output, args.overwrite)


if __name__ == "__main__":
    main()
