"""Read-only patient-scoped queries over a filtered OMOP DuckDB."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LAB_CONCEPTS: dict[str, tuple[int, ...]] = {
    # Verified against cirrhosis_regv20 v1 on Quartz, 2026-07-15.
    "bilirubin": (3024128,),
    "bilirubin total": (3024128,),
    "creatinine": (3016723, 3051825),
    "inr": (3022217, 3032080),
    "wbc": (3010813, 3000905),
    "white blood cell count": (3010813, 3000905),
    "sodium": (3019550, 3000285),
    # Verified in cirrhosis_regv20 v1 measurements on Quartz, 2026-07-15.
    "albumin": (2212186, 3024561),
    "ammonia": (3011958,),
    "pao2": (3027801, 3027315, 3013702),
    "fio2": (3024882,),
    "spo2": (40762499, 3016502, 3013502, 3011367),
}

CORE_LAB_ORDER = (
    "bilirubin",
    "creatinine",
    "inr",
    "wbc",
    "sodium",
    "albumin",
    "pao2",
    "fio2",
    "spo2",
)
CORE_LAB_IDS = tuple(
    dict.fromkeys(
        concept_id
        for name in CORE_LAB_ORDER
        for concept_id in LAB_CONCEPTS[name]
    )
)
CORE_ID_TO_NAME = {
    concept_id: name
    for name in CORE_LAB_ORDER
    for concept_id in LAB_CONCEPTS[name]
}


def _normalize_lab_key(value: str) -> str:
    key = " ".join(
        value.strip().lower().replace("_", " ").replace("-", " ").split()
    )
    return {
        "white blood cells": "wbc",
        "white blood cell": "wbc",
        "white blood cell count": "wbc",
        "total bilirubin": "bilirubin",
        "aclf core": "aclf_core",
    }.get(key, key)


def _reduce_core_labs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return compact deterministic representatives without inventing ratios."""
    grouped: dict[str, list[dict[str, Any]]] = {
        name: [] for name in CORE_LAB_ORDER
    }
    for record in records:
        name = CORE_ID_TO_NAME.get(record["concept_id"])
        if name and record["value"] is not None:
            grouped[name].append(record)
    selected = []
    for name in CORE_LAB_ORDER:
        candidates = grouped[name]
        if not candidates:
            continue
        if name in {"bilirubin", "creatinine", "inr"}:
            item = max(candidates, key=lambda row: float(row["value"]))
            rule = "maximum in requested acute window"
        elif name in {"pao2", "spo2"}:
            item = min(candidates, key=lambda row: float(row["value"]))
            rule = "minimum in requested acute window; do not infer FiO2 pairing"
        else:
            item = min(
                candidates,
                key=lambda row: (row["datetime"] or row["date"] or ""),
            )
            rule = "earliest value in requested acute window"
        item = dict(item)
        item["core_lab"] = name
        item["selection_rule"] = rule
        selected.append(item)
    return selected


class EHRBackend:
    """Lazy read-only DuckDB connection bound to one OMOP person ID."""

    def __init__(self, pid: int, db_path: Path):
        self.pid = int(pid)
        self.db_path = Path(db_path)
        self._db = None

    def _get_db(self):
        if self._db is None:
            if not self.db_path.exists():
                raise FileNotFoundError(f"EHR DuckDB not found: {self.db_path}")
            import duckdb

            self._db = duckdb.connect(str(self.db_path), read_only=True)
            # Quartz login/compute nodes expose many cores. DuckDB's default
            # per-connection thread count can reserve excessive memory when
            # several patient queries run concurrently.
            self._db.execute("SET threads = 1")
            self._db.execute("SET preserve_insertion_order = false")
        return self._db

    @staticmethod
    def _date_clause(
        column: str,
        date_start: str | None,
        date_end: str | None,
        params: list[Any],
    ) -> str:
        clause = ""
        if date_start:
            clause += f" AND {column} >= ?"
            params.append(date_start)
        if date_end:
            clause += f" AND {column} <= ?"
            params.append(date_end)
        return clause

    def query_labs(
        self,
        concept: str,
        date_start: str | None = None,
        date_end: str | None = None,
        datetime_start: str | None = None,
        datetime_end: str | None = None,
        visit_occurrence_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        db = self._get_db()
        key = _normalize_lab_key(concept)
        core_query = key == "aclf_core"
        ids = CORE_LAB_IDS if core_query else LAB_CONCEPTS.get(key)
        params: list[Any] = [self.pid]
        if ids:
            marks = ",".join("?" for _ in ids)
            where = f"person_id = ? AND measurement_concept_id IN ({marks})"
            params.extend(ids)
        else:
            where = (
                "person_id = ? AND (lower(coalesce(measurement_concept_name, '')) "
                "LIKE ? OR lower(coalesce(measurement_source_value, '')) LIKE ?)"
            )
            params.extend([f"%{key}%", f"%{key}%"])
        where += self._date_clause(
            "measurement_date", date_start, date_end, params
        )
        if datetime_start:
            where += " AND measurement_datetime >= ?"
            params.append(datetime_start)
        if datetime_end:
            where += " AND measurement_datetime < ?"
            params.append(datetime_end)
        if visit_occurrence_id is not None:
            where += " AND visit_occurrence_id = ?"
            params.append(int(visit_occurrence_id))
        limit = 2000 if core_query else max(1, min(int(limit), 200))
        rows = db.execute(
            f"""
            SELECT measurement_id, measurement_date, measurement_datetime, value_as_number,
                   unit_source_value, measurement_source_value,
                   measurement_concept_id, measurement_concept_name,
                   visit_occurrence_id
            FROM measurement
            WHERE {where}
            ORDER BY measurement_datetime NULLS LAST, measurement_date
            LIMIT {limit}
            """,
            params,
        ).fetchall()
        records = [
            {
                "measurement_id": row[0],
                "date": str(row[1]) if row[1] is not None else None,
                "datetime": str(row[2]) if row[2] is not None else None,
                "value": row[3],
                "unit": row[4],
                "source": row[5],
                "concept_id": row[6],
                "concept_name": row[7],
                "visit_occurrence_id": row[8],
            }
            for row in rows
        ]
        return _reduce_core_labs(records) if core_query else records

    def query_medications(
        self,
        concept: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        visit_occurrence_id: int | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [self.pid]
        where = "person_id = ?"
        if concept:
            key = concept.strip().lower()
            where += (
                " AND (lower(coalesce(drug_concept_name, '')) LIKE ? "
                "OR lower(coalesce(drug_source_value, '')) LIKE ?)"
            )
            params.extend([f"%{key}%", f"%{key}%"])
        where += self._date_clause(
            "drug_exposure_start_date", date_start, date_end, params
        )
        if visit_occurrence_id is not None:
            where += " AND visit_occurrence_id = ?"
            params.append(int(visit_occurrence_id))
        rows = self._get_db().execute(
            f"""
            SELECT drug_exposure_id, drug_exposure_start_date, drug_exposure_end_date,
                   drug_source_value, drug_concept_id, drug_concept_name,
                   route_source_value, quantity, visit_occurrence_id
            FROM drug_exposure WHERE {where}
            ORDER BY drug_exposure_start_date LIMIT 200
            """,
            params,
        ).fetchall()
        return [
            {
                "drug_exposure_id": row[0],
                "start": str(row[1]) if row[1] is not None else None,
                "end": str(row[2]) if row[2] is not None else None,
                "source": row[3],
                "concept_id": row[4],
                "concept_name": row[5],
                "route": row[6],
                "quantity": row[7],
                "visit_occurrence_id": row[8],
            }
            for row in rows
        ]

    def query_conditions(
        self,
        icd_prefix: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        visit_occurrence_id: int | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [self.pid]
        where = "person_id = ?"
        if icd_prefix:
            clean = icd_prefix.strip().replace(".", "").upper()
            where += " AND upper(condition_code) LIKE ?"
            params.append(f"{clean}%")
        where += self._date_clause(
            "condition_start_date", date_start, date_end, params
        )
        if visit_occurrence_id is not None:
            where += " AND visit_occurrence_id = ?"
            params.append(int(visit_occurrence_id))
        rows = self._get_db().execute(
            f"""
            SELECT condition_occurrence_id, condition_start_date, condition_end_date, condition_code,
                   condition_source_value, condition_concept_id,
                   condition_concept_name, visit_occurrence_id
            FROM condition_occurrence WHERE {where}
            ORDER BY condition_start_date LIMIT 300
            """,
            params,
        ).fetchall()
        return [
            {
                "condition_occurrence_id": row[0],
                "start": str(row[1]) if row[1] is not None else None,
                "end": str(row[2]) if row[2] is not None else None,
                "code": row[3],
                "source": row[4],
                "concept_id": row[5],
                "concept_name": row[6],
                "visit_occurrence_id": row[7],
            }
            for row in rows
        ]

    def query_procedures(
        self,
        code_prefix: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        visit_occurrence_id: int | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [self.pid]
        where = "person_id = ?"
        if code_prefix:
            key = code_prefix.strip().lower()
            where += (
                " AND (lower(coalesce(procedure_source_value, '')) LIKE ? "
                "OR lower(coalesce(procedure_concept_name, '')) LIKE ?)"
            )
            params.extend([f"{key}%", f"%{key}%"])
        where += self._date_clause("procedure_date", date_start, date_end, params)
        if visit_occurrence_id is not None:
            where += " AND visit_occurrence_id = ?"
            params.append(int(visit_occurrence_id))
        rows = self._get_db().execute(
            f"""
            SELECT procedure_occurrence_id, procedure_date, procedure_source_value, procedure_concept_id,
                   procedure_concept_name, visit_occurrence_id
            FROM procedure_occurrence WHERE {where}
            ORDER BY procedure_date LIMIT 200
            """,
            params,
        ).fetchall()
        return [
            {
                "procedure_occurrence_id": row[0],
                "date": str(row[1]) if row[1] is not None else None,
                "source": row[2],
                "concept_id": row[3],
                "concept_name": row[4],
                "visit_occurrence_id": row[5],
            }
            for row in rows
        ]

    def inpatient_episodes(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return inpatient visits chronologically for prospective index selection."""
        rows = self._get_db().execute(
            """
            SELECT v.visit_occurrence_id, v.visit_start_date, v.visit_end_date,
                   v.visit_start_datetime, v.visit_end_datetime, v.visit_source_value,
                   max(CASE WHEN m.measurement_concept_id = 3024128
                            THEN m.value_as_number END) AS peak_bilirubin,
                   max(CASE WHEN m.measurement_concept_id IN (3016723, 3051825)
                            THEN m.value_as_number END) AS peak_creatinine,
                   max(CASE WHEN m.measurement_concept_id IN (3022217, 3032080)
                            THEN m.value_as_number END) AS peak_inr
            FROM visit_occurrence v
            LEFT JOIN measurement m
              ON v.visit_occurrence_id = m.visit_occurrence_id
             AND v.person_id = m.person_id
            WHERE v.person_id = ? AND v.visit_concept_id = 9201
            GROUP BY 1,2,3,4,5,6
            ORDER BY v.visit_start_datetime, v.visit_occurrence_id
            LIMIT ?
            """,
            [self.pid, max(1, min(limit, 100))],
        ).fetchall()
        return [
            {
                "visit_occurrence_id": row[0],
                "start_date": str(row[1]) if row[1] is not None else None,
                "end_date": str(row[2]) if row[2] is not None else None,
                "start_datetime": str(row[3]) if row[3] is not None else None,
                "end_datetime": str(row[4]) if row[4] is not None else None,
                "source": row[5],
                "structured_severity_proxy": {
                    "peak_total_bilirubin_mg_dl": row[6],
                    "peak_creatinine_mg_dl": row[7],
                    "peak_inr": row[8],
                    "scope": "liver, kidney, and coagulation only; not a final ACLF grade",
                },
            }
            for row in rows
        ]

    def demographics(self) -> dict[str, Any]:
        row = self._get_db().execute(
            """
            SELECT year_of_birth, gender_source_value, race_source_value,
                   ethnicity_source_value
            FROM person WHERE person_id = ? LIMIT 1
            """,
            [self.pid],
        ).fetchone()
        if row is None:
            return {}
        return {
            "year_of_birth": row[0],
            "gender": row[1],
            "race": row[2],
            "ethnicity": row[3],
        }

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None


__all__ = ["EHRBackend", "LAB_CONCEPTS", "CORE_LAB_IDS"]
