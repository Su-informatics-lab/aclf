"""Composition root for patient-scoped structured and narrative retrieval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rag.ehr import EHRBackend
from rag.vectors import NoteStore


class PatientRAG:
    def __init__(
        self,
        pid: int,
        *,
        ehr_db_path: Path,
        mapping_path: Path,
        notes_dirs: list[Path],
        note_dates_path: Path | None = None,
        vectors_dir: Path | None = None,
        extraction_dir: Path | None = None,
    ):
        self.pid = int(pid)
        self.ehr = EHRBackend(self.pid, ehr_db_path)
        self.notes = NoteStore(
            self.pid,
            mapping_path,
            notes_dirs,
            note_dates_path=note_dates_path,
            vectors_dir=vectors_dir,
        )
        self.extraction_dir = Path(extraction_dir) if extraction_dir else None
        self.retrieval_trace: list[dict[str, Any]] = []
        self.llm_usage: list[dict[str, Any]] = []

    def record_llm_usage(self, record: dict[str, Any]) -> None:
        self.llm_usage.append(record)

    def _record(self, tool: str, arguments: dict[str, Any], result: Any) -> Any:
        id_fields = {
            "search_notes": "report_id",
            "query_labs": "measurement_id",
            "query_medications": "drug_exposure_id",
            "query_conditions": "condition_occurrence_id",
            "query_procedures": "procedure_occurrence_id",
        }
        rows = result if isinstance(result, list) else []
        id_field = id_fields.get(tool)
        source_ids = []
        if id_field:
            source_ids = [str(row[id_field]) for row in rows if row.get(id_field) is not None]
        self.retrieval_trace.append(
            {
                "tool": tool,
                "arguments": arguments,
                "n_records": len(rows) if isinstance(result, list) else None,
                "source_ids": source_ids,
            }
        )
        return result

    def search_notes(self, **kwargs):
        return self._record("search_notes", kwargs, self.notes.search(**kwargs))

    def query_labs(self, **kwargs):
        return self._record("query_labs", kwargs, self.ehr.query_labs(**kwargs))

    def query_medications(self, **kwargs):
        return self._record("query_medications", kwargs, self.ehr.query_medications(**kwargs))

    def query_conditions(self, **kwargs):
        return self._record("query_conditions", kwargs, self.ehr.query_conditions(**kwargs))

    def query_procedures(self, **kwargs):
        return self._record("query_procedures", kwargs, self.ehr.query_procedures(**kwargs))

    def get_extraction(self, block: str | None = None) -> dict[str, Any]:
        if not self.extraction_dir:
            return self._record("get_extraction", {"block": block}, {})
        candidates = [
            self.extraction_dir / f"sample_{self.pid}.json",
            self.extraction_dir / f"{self.pid}.json",
        ]
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            return self._record("get_extraction", {"block": block}, {})
        data = json.loads(path.read_text(encoding="utf-8"))
        if block:
            result = {block: data.get(block)} if block in data else {}
        else:
            result = data
        return self._record("get_extraction", {"block": block}, result)

    def case_context(self) -> dict[str, Any]:
        return {
            "demographics": self.ehr.demographics(),
            "inpatient_episodes": self.ehr.inpatient_episodes(),
            "note_provenance": self.notes.provenance_summary(),
        }

    def close(self) -> None:
        self.ehr.close()


__all__ = ["PatientRAG"]
