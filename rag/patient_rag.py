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

    def search_notes(self, **kwargs):
        return self.notes.search(**kwargs)

    def query_labs(self, **kwargs):
        return self.ehr.query_labs(**kwargs)

    def query_medications(self, **kwargs):
        return self.ehr.query_medications(**kwargs)

    def query_conditions(self, **kwargs):
        return self.ehr.query_conditions(**kwargs)

    def query_procedures(self, **kwargs):
        return self.ehr.query_procedures(**kwargs)

    def get_extraction(self, block: str | None = None) -> dict[str, Any]:
        if not self.extraction_dir:
            return {}
        candidates = [
            self.extraction_dir / f"sample_{self.pid}.json",
            self.extraction_dir / f"{self.pid}.json",
        ]
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if block:
            return {block: data.get(block)} if block in data else {}
        return data

    def case_context(self) -> dict[str, Any]:
        return {
            "demographics": self.ehr.demographics(),
            "inpatient_episodes": self.ehr.inpatient_episodes(),
            "note_provenance": self.notes.provenance_summary(),
        }

    def close(self) -> None:
        self.ehr.close()


__all__ = ["PatientRAG"]
